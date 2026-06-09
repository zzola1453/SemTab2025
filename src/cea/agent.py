"""ReAct-style Agentic CEA using Ollama tool calling (OpenAI-compatible API)."""
from __future__ import annotations

import asyncio
import functools
import json
import re

import aiohttp

from .preprocessing import CellContext
from .retrieval import BaseRetriever
from .tools import TOOLS, format_candidates

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"

_PROMPT_TEMPLATE = """\
You are a Wikidata entity annotation expert. Find the correct Wikidata QID for the target table cell.

Table ID: {table_id}
Target cell: row={row_id}, col={col_id}, value="{cell_value}"
Column header: {col_header}
Same row: {row_context}
Same column (sample): {col_context}
{confirmed_block}
Table preview (first rows):
{table_preview}

IMPORTANT RULES:
- Almost every named entity (person, film, place, organization) exists in Wikidata. Always search before concluding.
- If the first search finds no results, try a shorter or rephrased query (e.g. drop articles like "The", "A").
- Submit "NIL" ONLY when you are certain the entity does not exist in Wikidata at all.
- When in doubt between candidates, pick the one whose description best matches the table context. Do NOT submit NIL just because you are uncertain.
- Always call submit_answer as your final action.
"""


def _build_prompt(ctx: CellContext) -> str:
    confirmed_block = ""
    if ctx.confirmed_annotations:
        lines = [
            f"  ({r},{c}) → {qid}"
            for (r, c), qid in list(ctx.confirmed_annotations.items())[:8]
        ]
        confirmed_block = "Already confirmed in this table:\n" + "\n".join(lines) + "\n"

    table_preview = "\n".join(" | ".join(row) for row in ctx.table_sample[:5])
    row_ctx = ", ".join(v for v in ctx.row_values if v and v != ctx.cell_value)[:200]
    col_ctx = ", ".join(ctx.col_values[:8])[:200]

    return _PROMPT_TEMPLATE.format(
        table_id=ctx.table_id,
        row_id=ctx.row_id,
        col_id=ctx.col_id,
        cell_value=ctx.cell_value,
        col_header=ctx.col_header,
        row_context=row_ctx or "(none)",
        col_context=col_ctx or "(none)",
        confirmed_block=confirmed_block,
        table_preview=table_preview,
    )


def _extract_qid(text: str) -> str | None:
    m = re.search(r"\b(Q\d+)\b", text or "")
    return m.group(1) if m else None


async def _fetch_entity_details(qid: str) -> str:
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "labels|descriptions|aliases",
        "languages": "en",
        "format": "json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _WIKIDATA_API, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
        entity = data.get("entities", {}).get(qid, {})
        label = entity.get("labels", {}).get("en", {}).get("value", "")
        desc = entity.get("descriptions", {}).get("en", {}).get("value", "")
        aliases = [a["value"] for a in entity.get("aliases", {}).get("en", [])[:5]]
        parts = [f"QID: {qid}", f"Label: {label}", f"Description: {desc}"]
        if aliases:
            parts.append(f"Aliases: {', '.join(aliases)}")
        return "\n".join(parts)
    except Exception as e:
        return f"Failed to fetch {qid}: {e}"


class CeaAgent:
    def __init__(
        self,
        retriever: BaseRetriever,
        client,
        model: str = "llama3.1:8b",
        max_steps: int = 5,
    ):
        self.retriever = retriever
        self.client = client
        self.model = model
        self.max_steps = max_steps

    async def annotate(self, ctx: CellContext) -> str:
        prompt = _build_prompt(ctx)
        messages: list[dict] = [{"role": "user", "content": prompt}]
        fallback_qid: str | None = None

        loop = asyncio.get_event_loop()
        for _ in range(self.max_steps):
            try:
                resp = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        functools.partial(
                            self.client.chat.completions.create,
                            model=self.model,
                            messages=messages,
                            tools=TOOLS,
                            tool_choice="auto",
                        ),
                    ),
                    timeout=120.0,
                )
            except (asyncio.TimeoutError, Exception):
                break

            msg = resp.choices[0].message

            if not msg.tool_calls:
                # Model returned plain text — try to extract a QID
                qid = _extract_qid(msg.content)
                if qid:
                    return qid
                break

            # Append assistant turn (convert SDK objects → plain dicts)
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                fn = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}

                if fn == "submit_answer":
                    qid = args.get("qid", "NIL")
                    return qid if qid else "NIL"

                result_str = await self._execute(fn, args)

                # Cache first search hit as emergency fallback
                if fallback_qid is None and fn in ("search_entities", "search_fuzzy"):
                    m = re.search(r"\b(Q\d+)\b", result_str)
                    if m:
                        fallback_qid = m.group(1)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Fallback: use first search result seen during the loop
        if fallback_qid:
            return fallback_qid

        # Last resort: bare BM25 top-1
        candidates = await self.retriever.search(ctx.cell_value, limit=1)
        return candidates[0].qid if candidates else "NIL"

    async def _execute(self, fn: str, args: dict) -> str:
        if fn == "search_entities":
            query = str(args.get("query", ""))
            try:
                limit = min(int(args.get("limit", 5)), 10)
            except (ValueError, TypeError):
                limit = 5
            candidates = await self.retriever.search(query, limit)
            return format_candidates(candidates)

        if fn == "search_fuzzy":
            query = str(args.get("query", ""))
            try:
                limit = min(int(args.get("limit", 5)), 10)
            except (ValueError, TypeError):
                limit = 5
            candidates = await self.retriever.search_fuzzy(query, limit)
            return format_candidates(candidates)

        if fn == "get_entity_details":
            qid = str(args.get("qid", ""))
            return await _fetch_entity_details(qid)

        return f"Unknown tool: {fn}"
