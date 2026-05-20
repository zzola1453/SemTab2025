from .preprocessing import CellContext
from .llm_client import call_llm

_SYSTEM = (
    "You are a Wikidata search expert. "
    "Output only search query strings, one per line. No numbering, no explanation."
)

_PROMPT = """\
Cell value: "{cell_value}"
Column header: {col_header}
Other values in the same row: {row_context}

Generate 3 Wikidata search queries for this cell.
Consider: full name, common alias, abbreviation, alternate spelling.
Output exactly 3 queries, one per line."""


def rewrite_query(
    ctx: CellContext,
    client,
    model: str = "qwen2.5:14b",
) -> list[str]:
    row_context = ", ".join(v for v in ctx.row_values if v and v != ctx.cell_value)[:120]
    prompt = _PROMPT.format(
        cell_value=ctx.cell_value,
        col_header=ctx.col_header,
        row_context=row_context or "(none)",
    )
    text = call_llm(client, model, _SYSTEM, prompt, max_tokens=150)
    lines = text.strip().splitlines()
    queries = [l.strip().lstrip("123.-) ") for l in lines if l.strip()]
    return [q for q in queries if q and q != ctx.cell_value][:3]
