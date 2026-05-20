from .preprocessing import CellContext
from .retrieval import Candidate
from .llm_client import call_llm


_VERIFY_SYSTEM = (
    "You are a Wikidata entity annotation verifier. "
    "Respond ONLY with: ACCEPT <QID> or REJECT NIL."
)

_VERIFY_PROMPT = """\
Cell: row={row_id}, col={col_id}, value="{cell_value}"
Column sample values: {col_values}
Table context (first rows):
{table_sample}

Proposed entity: {qid} | {label} | {description}

Verify the proposed entity is the correct Wikidata match for "{cell_value}":
1. Does the label/description match the cell value?
2. Is it consistent with other column values?
3. Is it consistent with the table context?
4. Should it be NIL instead?

Output: ACCEPT {qid} or REJECT NIL"""


def verify(
    ctx: CellContext,
    candidate: Candidate,
    client,
    model: str = "qwen2.5:14b",
) -> tuple[bool, str]:
    table_sample = "\n".join(" | ".join(row) for row in ctx.table_sample[:5])

    prompt = _VERIFY_PROMPT.format(
        row_id=ctx.row_id,
        col_id=ctx.col_id,
        cell_value=ctx.cell_value,
        col_values=", ".join(ctx.col_values),
        table_sample=table_sample,
        qid=candidate.qid,
        label=candidate.label,
        description=candidate.description[:120] if candidate.description else "",
    )

    text = call_llm(client, model, _VERIFY_SYSTEM, prompt, max_tokens=30).upper()
    if text.startswith("ACCEPT"):
        parts = text.split()
        qid = parts[1] if len(parts) > 1 else candidate.qid
        return True, qid
    return False, "NIL"
