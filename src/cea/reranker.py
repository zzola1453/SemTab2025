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
        self.nil_threshold = nil_threshold  # None = never return NIL via threshold

    def rerank(self, ctx: CellContext, candidates: list[Candidate]) -> str:
        if not candidates:
            return "NIL"
        if len(candidates) == 1:
            return candidates[0].qid

        query = self._format_query(ctx)
        pairs = [(query, self._format_doc(c)) for c in candidates]
        scores = self.model.predict(pairs)

        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if self.nil_threshold is not None and best_score < self.nil_threshold:
            return "NIL"

        return candidates[best_idx].qid

    def _format_query(self, ctx: CellContext) -> str:
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
