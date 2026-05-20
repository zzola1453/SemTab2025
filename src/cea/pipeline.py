import asyncio
import os
import csv
import time
from dataclasses import dataclass

from tqdm import tqdm

from .preprocessing import (
    CellContext,
    get_cell_context,
    is_numeric_column,
    is_date_column,
    load_table,
    normalize_cell,
)
from .retrieval import BaseRetriever, Candidate, WikidataAPIRetriever, get_retriever
from .debate import debate
from .verification import verify
from .query_rewriter import rewrite_query
from .reranker import CrossEncoderReranker
from .llm_client import create_client


@dataclass
class AnnotationResult:
    table_id: str
    row_id: int
    col_id: int
    entity_id: str
    skipped: bool = False


class CeaPipeline:
    def __init__(
        self,
        tables_dir: str,
        retrieval_backend: str = "wikidata_api",
        max_candidates: int = 10,
        use_debate: bool = True,
        use_verification: bool = False,
        use_query_rewriting: bool = False,
        use_collective: bool = False,
        use_reranker: bool = False,
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        nil_threshold: float | None = None,
        llm_backend: str = "ollama",
        llm_api_key: str | None = None,
        llm_model: str = "qwen2.5:14b",
        **retriever_kwargs,
    ):
        self.tables_dir = tables_dir
        self.retriever: BaseRetriever = get_retriever(retrieval_backend, **retriever_kwargs)
        self.max_candidates = max_candidates
        self.use_debate = use_debate
        self.use_verification = use_verification
        self.use_query_rewriting = use_query_rewriting
        self.use_collective = use_collective
        self.llm_model = llm_model

        needs_llm = use_debate or use_verification or use_query_rewriting
        if needs_llm:
            api_key = llm_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GROQ_API_KEY")
            self.client = create_client(llm_backend, api_key)
        else:
            self.client = None

        self.reranker = CrossEncoderReranker(reranker_model, nil_threshold) if use_reranker else None

    # ------------------------------------------------------------------ #
    # Single-cell annotation                                               #
    # ------------------------------------------------------------------ #

    async def _annotate_cell_async(self, ctx: CellContext) -> AnnotationResult:
        if not ctx.cell_value:
            return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, "NIL", skipped=True)

        # Skip numeric/date-only cells (not entity mentions)
        col_sample = ctx.col_values + [ctx.cell_value]
        if is_numeric_column(col_sample) or is_date_column(col_sample):
            return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, "NIL", skipped=True)

        candidates = await self.retriever.search(ctx.cell_value, limit=self.max_candidates)

        if not candidates:
            row_hint = " ".join(v for v in ctx.row_values if v and v != ctx.cell_value)
            if row_hint:
                candidates = await self.retriever.search(
                    f"{ctx.cell_value} {row_hint[:60]}", limit=self.max_candidates
                )

        # LLM query rewriting fallback when candidates are scarce
        if len(candidates) < 3 and self.use_query_rewriting and self.client:
            seen_qids = {c.qid for c in candidates}
            for alt_query in rewrite_query(ctx, self.client, self.llm_model):
                alt = await self.retriever.search(alt_query, limit=self.max_candidates)
                for c in alt:
                    if c.qid not in seen_qids:
                        candidates.append(c)
                        seen_qids.add(c.qid)
                if len(candidates) >= self.max_candidates:
                    break

        if not candidates:
            return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, "NIL", skipped=True)

        if self.use_debate and self.client:
            entity_id = debate(ctx, candidates[:5], self.client, self.llm_model)
        elif self.reranker:
            entity_id = await asyncio.to_thread(self.reranker.rerank, ctx, candidates[:10])
        else:
            entity_id = candidates[0].qid

        if entity_id == "NIL":
            return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, "NIL", skipped=True)

        if self.use_verification and self.client and entity_id != "NIL":
            matched = next((c for c in candidates if c.qid == entity_id), candidates[0])
            accepted, entity_id = verify(ctx, matched, self.client, self.llm_model)
            if not accepted:
                return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, "NIL", skipped=True)

        return AnnotationResult(ctx.table_id, ctx.row_id, ctx.col_id, entity_id)

    # ------------------------------------------------------------------ #
    # Table-level batch annotation                                         #
    # ------------------------------------------------------------------ #

    async def _annotate_table_async(
        self, table_id: str, targets: list[tuple[int, int]]
    ) -> list[AnnotationResult]:
        try:
            rows = load_table(table_id, self.tables_dir)
        except FileNotFoundError:
            return []

        if self.use_collective:
            # Sequential processing: confirmed annotations feed into subsequent cells
            confirmed: dict[tuple[int, int], str] = {}
            results = []
            for row_id, col_id in sorted(targets):
                ctx = get_cell_context(rows, row_id, col_id, table_id)
                ctx.confirmed_annotations = dict(confirmed)
                result = await self._annotate_cell_async(ctx)
                if not result.skipped and result.entity_id != "NIL":
                    confirmed[(row_id, col_id)] = result.entity_id
                results.append(result)
            return results

        # Parallel processing (default)
        contexts = [get_cell_context(rows, row_id, col_id, table_id) for row_id, col_id in targets]
        sem = asyncio.Semaphore(3)

        async def bounded(ctx):
            async with sem:
                return await self._annotate_cell_async(ctx)

        return await asyncio.gather(*[bounded(ctx) for ctx in contexts])

    def annotate_table(self, table_id: str, targets: list[tuple[int, int]]) -> list[AnnotationResult]:
        return asyncio.run(self._annotate_table_async(table_id, targets))

    # ------------------------------------------------------------------ #
    # Dataset-level run                                                    #
    # ------------------------------------------------------------------ #

    def run_on_target_file(
        self,
        target_file: str,
        output_file: str,
        max_tables: int | None = None,
    ) -> list[AnnotationResult]:
        from collections import defaultdict

        table_targets: dict[str, list[tuple[int, int]]] = defaultdict(list)
        with open(target_file) as f:
            for row in csv.reader(f):
                if len(row) >= 3:
                    table_targets[row[0]].append((int(row[1]), int(row[2])))

        table_ids = list(table_targets.keys())
        if max_tables:
            table_ids = table_ids[:max_tables]

        # Resume: skip tables already written in the output file
        done_tables: set[str] = set()
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else ".", exist_ok=True)
        if os.path.exists(output_file):
            with open(output_file) as f:
                for row in csv.reader(f):
                    if row:
                        done_tables.add(row[0])
            if done_tables:
                print(f"Resuming: {len(done_tables)} tables already done, skipping.")

        remaining = [t for t in table_ids if t not in done_tables]
        all_results: list[AnnotationResult] = []

        out_f = open(output_file, "a", newline="")
        writer = csv.writer(out_f)

        async def _run_all():
            with tqdm(total=len(table_ids), desc="Tables",
                      initial=len(done_tables)) as pbar:
                for table_id in remaining:
                    results = await self._annotate_table_async(table_id, table_targets[table_id])
                    all_results.extend(results)
                    # Write completed table immediately
                    for r in results:
                        if not r.skipped and r.entity_id != "NIL":
                            writer.writerow([r.table_id, r.row_id, r.col_id, r.entity_id])
                    out_f.flush()
                    pbar.update(1)
            if hasattr(self.retriever, "close"):
                await self.retriever.close()

        try:
            asyncio.run(_run_all())
        finally:
            out_f.close()

        total_written = sum(1 for r in all_results if not r.skipped and r.entity_id != "NIL")
        print(f"Wrote {len(done_tables)} (resumed) + {total_written} (new) annotations to {output_file}")
        return all_results
