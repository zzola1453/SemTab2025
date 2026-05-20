from .preprocessing import CellContext
from .retrieval import Candidate
from .llm_client import call_llm


_DEBATE_SYSTEM = (
    "You are a Wikidata entity disambiguation expert. "
    "Given a table cell and a list of Wikidata candidates, select the best matching entity. "
    "Respond ONLY with the entity QID (e.g. Q12345) or NIL if none match. No explanation."
)

_DEBATE_PROMPT = """\
Table context (first rows):
{table_sample}

Target cell: row={row_id}, col={col_id}, value="{cell_value}"
Same row values: {row_values}
Same column values (sample): {col_values}
{confirmed_context}
Candidates:
{candidates_text}

Select the best matching Wikidata entity QID for the cell value "{cell_value}".
Consider: (1) label match, (2) column context, (3) table context.
If no candidate is a plausible match, output NIL.
Output only the QID or NIL."""


def _format_confirmed(confirmed: dict) -> str:
    if not confirmed:
        return ""
    lines = [f"  row={r}, col={c} → {qid}" for (r, c), qid in list(confirmed.items())[:8]]
    return "Already confirmed in this table:\n" + "\n".join(lines)


def _format_candidates(candidates: list[Candidate]) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        desc = c.description[:100] if c.description else "(no description)"
        lines.append(f"{i}. {c.qid} | {c.label} | {desc}")
    return "\n".join(lines)


def _format_table_sample(rows: list[list[str]]) -> str:
    lines = []
    for row in rows[:5]:
        lines.append(" | ".join(row))
    return "\n".join(lines)


def debate(
    ctx: CellContext,
    candidates: list[Candidate],
    client,
    model: str = "qwen2.5:14b",
) -> str:
    if not candidates:
        return "NIL"

    if len(candidates) == 1:
        return candidates[0].qid

    prompt = _DEBATE_PROMPT.format(
        table_sample=_format_table_sample(ctx.table_sample),
        row_id=ctx.row_id,
        col_id=ctx.col_id,
        cell_value=ctx.cell_value,
        row_values=", ".join(ctx.row_values),
        col_values=", ".join(ctx.col_values),
        confirmed_context=_format_confirmed(ctx.confirmed_annotations),
        candidates_text=_format_candidates(candidates),
    )

    result = call_llm(client, model, _DEBATE_SYSTEM, prompt, max_tokens=20)
    if result.upper() == "NIL":
        return "NIL"
    if result.startswith("Q") and result[1:].isdigit():
        return result
    return candidates[0].qid
