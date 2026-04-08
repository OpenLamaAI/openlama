"""Tool: web_search – DuckDuckGo web search."""

import asyncio
from functools import partial

from openlama.tools.registry import register_tool
from openlama.config import get_config_int


def _search_sync(query: str, max_results: int) -> str:
    """Run DuckDuckGo search synchronously."""
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))

    if not results:
        return f"No search results found for '{query}'."

    lines = [f"Search results: '{query}'\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. {title}\n   {body}\n   URL: {href}\n")
    return "\n".join(lines)


async def _execute(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Please provide a search query."

    max_results = args.get("max_results", get_config_int("duckduckgo_max_results", 5))

    try:
        # DDGS v8+ is sync-only, run in thread pool
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, partial(_search_sync, query, max_results)
        )
        return result
    except Exception as e:
        return f"Search error: {e}"


register_tool(
    name="web_search",
    description="Search the web using DuckDuckGo. Use for up-to-date information, news, and fact-checking.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    execute=_execute,
)
