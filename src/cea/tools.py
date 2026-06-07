"""Tool definitions for ReAct-style Agentic CEA (OpenAI function-calling format)."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_entities",
            "description": (
                "Search Wikidata for entities matching a query string using BM25. "
                "Returns QID, label, and description for each candidate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Can include the cell value, aliases, or alternate spellings.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (1-10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_fuzzy",
            "description": (
                "Fuzzy search for Wikidata entities. "
                "Use when the cell value may contain typos, abbreviations, or variant spellings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query with approximate spelling.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (1-10, default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_details",
            "description": (
                "Get detailed information about a specific Wikidata entity by QID. "
                "Use to confirm whether a candidate is the right entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "qid": {
                        "type": "string",
                        "description": "Wikidata entity ID (e.g. Q42, Q155).",
                    }
                },
                "required": ["qid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": (
                "Submit the final answer and end the search loop. "
                "Call this when you are confident about the correct entity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "qid": {
                        "type": "string",
                        "description": "Wikidata QID of the best match (e.g. Q42), or 'NIL' if no match exists.",
                    }
                },
                "required": ["qid"],
            },
        },
    },
]


def format_candidates(candidates) -> str:
    if not candidates:
        return "No results found."
    lines = []
    for i, c in enumerate(candidates, 1):
        desc = (c.description or "(no description)")[:120]
        lines.append(f"{i}. {c.qid} | {c.label} | {desc}")
    return "\n".join(lines)
