from __future__ import annotations

import numpy as np
from .preprocessing import CellContext
from .retrieval import Candidate


class CrossEncoderReranker:
    """Local cross-encoder reranker — replaces LLM Debate with no API key."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        nil_threshold: float | None = None,
    ):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)
        self.nil_threshold = nil_threshold

    def score(self, ctx: CellContext, candidates: list[Candidate]) -> list[float]:
        if not candidates:
            return []
        query = self._build_query(ctx)
        pairs = [(query, self._format_doc(c)) for c in candidates]
        return self.model.predict(pairs).tolist()

    def rerank(self, ctx: CellContext, candidates: list[Candidate]) -> str:
        if not candidates:
            return "NIL"
        if len(candidates) == 1:
            return candidates[0].qid

        scores = self.score(ctx, candidates)
        best_idx = int(np.argmax(scores))
        if self.nil_threshold is not None and scores[best_idx] < self.nil_threshold:
            return "NIL"
        return candidates[best_idx].qid

    def _build_query(self, ctx: CellContext) -> str:
        row_ctx = " | ".join(v for v in ctx.row_values if v and v != ctx.cell_value)[:100]
        parts = [ctx.cell_value]
        if ctx.col_header:
            parts.append(f"column: {ctx.col_header}")
        if row_ctx:
            parts.append(f"row: {row_ctx}")
        return " [SEP] ".join(parts)

    def _format_doc(self, c: Candidate) -> str:
        desc = c.description[:150] if c.description else ""
        return f"{c.label}: {desc}" if desc else c.label


class BiEncoderReranker:
    """Bi-encoder dense reranker using E5/BGE sentence-transformers.

    Combines normalized BM25 score with dense cosine similarity for final ranking.
    No vector index needed — encodes BM25 candidates on-the-fly.
    """

    def __init__(
        self,
        model_name: str = "intfloat/e5-large-v2",
        bm25_weight: float = 0.3,
        nil_threshold: float | None = None,
    ):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self.bm25_weight = bm25_weight
        self.nil_threshold = nil_threshold
        # E5 models require task-specific prefixes
        self._q_prefix = "query: " if "e5" in model_name.lower() else ""
        self._d_prefix = "passage: " if "e5" in model_name.lower() else ""

    def score(self, ctx: CellContext, candidates: list[Candidate]) -> list[float]:
        """Return hybrid (BM25 + dense) scores, one per candidate."""
        if not candidates:
            return []

        query_text = self._q_prefix + self._build_query(ctx)
        doc_texts = [self._d_prefix + self._format_doc(c) for c in candidates]

        query_emb = self.model.encode(query_text, normalize_embeddings=True)
        doc_embs = self.model.encode(doc_texts, normalize_embeddings=True, batch_size=64)
        dense_scores = (doc_embs @ query_emb).tolist()

        bm25_raw = [c.score for c in candidates]
        max_bm25 = max(bm25_raw) if max(bm25_raw) > 0 else 1.0
        bm25_norm = [s / max_bm25 for s in bm25_raw]

        return [
            self.bm25_weight * b + (1.0 - self.bm25_weight) * d
            for b, d in zip(bm25_norm, dense_scores)
        ]

    def rerank(self, ctx: CellContext, candidates: list[Candidate]) -> str:
        if not candidates:
            return "NIL"
        if len(candidates) == 1:
            return candidates[0].qid

        scores = self.score(ctx, candidates)
        best_idx = int(np.argmax(scores))
        if self.nil_threshold is not None and scores[best_idx] < self.nil_threshold:
            return "NIL"
        return candidates[best_idx].qid

    def _build_query(self, ctx: CellContext) -> str:
        parts = [ctx.cell_value]
        if ctx.col_header:
            parts.append(f"column: {ctx.col_header}")
        row_ctx = " | ".join(v for v in ctx.row_values if v and v != ctx.cell_value)[:100]
        if row_ctx:
            parts.append(f"row: {row_ctx}")
        return " ".join(parts)

    def _format_doc(self, c: Candidate) -> str:
        desc = c.description[:150] if c.description else ""
        return f"{c.label}: {desc}" if desc else c.label


class EnsembleReranker:
    """Combines cross-encoder and bi-encoder scores via weighted average.

    cross_weight controls how much the cross-encoder contributes (0–1).
    """

    def __init__(
        self,
        cross_encoder: CrossEncoderReranker,
        bi_encoder: BiEncoderReranker,
        cross_weight: float = 0.6,
        nil_threshold: float | None = None,
    ):
        self.cross = cross_encoder
        self.bi = bi_encoder
        self.cross_weight = cross_weight
        self.nil_threshold = nil_threshold

    def rerank(self, ctx: CellContext, candidates: list[Candidate]) -> str:
        if not candidates:
            return "NIL"
        if len(candidates) == 1:
            return candidates[0].qid

        cross_scores = np.array(self.cross.score(ctx, candidates))
        bi_scores = np.array(self.bi.score(ctx, candidates))

        # Normalize each score set to [0, 1] before combining
        def _norm(arr: np.ndarray) -> np.ndarray:
            lo, hi = arr.min(), arr.max()
            return (arr - lo) / (hi - lo + 1e-9)

        ensemble = self.cross_weight * _norm(cross_scores) + (1.0 - self.cross_weight) * _norm(bi_scores)

        best_idx = int(np.argmax(ensemble))
        if self.nil_threshold is not None and float(ensemble[best_idx]) < self.nil_threshold:
            return "NIL"
        return candidates[best_idx].qid
