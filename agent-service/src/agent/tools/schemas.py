"""OpenAI-compatible tool schemas and executor registry for hand-written ReAct.

Converts LangChain ``@tool``-decorated functions into OpenAI function-calling
schemas so they can be driven by the native OpenAI SDK (without LangChain agent
infrastructure).
"""

from typing import Any, Callable

from src.agent.tools import (
    bookmark_shop,
    check_order_status,
    list_bookmarks,
    list_my_orders,
    make_reservation,
    place_order,
    query_vouchers,
    queue_reservation,
    remove_bookmark,
    request_refund,
    search_shops,
    set_voucher_alert,
)


# ---------------------------------------------------------------------------
# Schema conversion helpers
# ---------------------------------------------------------------------------


def _pydantic_to_json_schema(model: type) -> dict[str, Any]:
    """Convert a Pydantic v2 model to an OpenAI-compatible JSON Schema dict.

    OpenAI function-calling requires ``"type": "object"`` at the top level of
    ``parameters``.  We remove the Pydantic-generated ``"title"`` key but
    preserve everything else (``properties``, ``required``, ``$defs``, etc.).
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


def _wrap_content_and_artifact(fn: Callable[..., Any]) -> Callable[..., str]:
    """Wrap a ``content_and_artifact`` tool to return only the text portion.

    LangChain tools decorated with ``@tool(response_format="content_and_artifact")``
    return ``tuple[str, list[dict]]``.  The OpenAI executor should only return
    the text (first element) so the caller always gets a clean string.
    """

    def wrapper(*args: Any, **kwargs: Any) -> str:
        result = fn(*args, **kwargs)
        if isinstance(result, tuple):
            return str(result[0])
        return str(result)

    return wrapper


# ---------------------------------------------------------------------------
# All 12 tools
# ---------------------------------------------------------------------------

_TOOLS = [
    search_shops,
    query_vouchers,
    place_order,
    check_order_status,
    list_my_orders,
    request_refund,
    bookmark_shop,
    list_bookmarks,
    remove_bookmark,
    set_voucher_alert,
    queue_reservation,
    make_reservation,
]

# ---------------------------------------------------------------------------
# TOOL_SCHEMAS — list of OpenAI function-calling objects
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = []
for tool in _TOOLS:
    schema = _pydantic_to_json_schema(tool.args_schema)
    TOOL_SCHEMAS.append(
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            },
        }
    )

# ---------------------------------------------------------------------------
# TOOL_EXECUTORS — maps tool name -> callable
# ---------------------------------------------------------------------------

_CONTENT_AND_ARTIFACT_TOOLS: frozenset[str] = frozenset(
    {
        "search_shops",
        "query_vouchers",
    }
)

TOOL_EXECUTORS: dict[str, Callable[..., str]] = {}
for tool in _TOOLS:
    if tool.name in _CONTENT_AND_ARTIFACT_TOOLS:
        TOOL_EXECUTORS[tool.name] = _wrap_content_and_artifact(tool.func)
    else:
        TOOL_EXECUTORS[tool.name] = tool.func

# ---------------------------------------------------------------------------
# Per-worker tool name sets
# ---------------------------------------------------------------------------

RESTAURANT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_shops",
        "bookmark_shop",
        "list_bookmarks",
        "remove_bookmark",
        "queue_reservation",
        "make_reservation",
    }
)

VOUCHER_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "query_vouchers",
        "place_order",
        "check_order_status",
        "list_my_orders",
        "request_refund",
        "set_voucher_alert",
    }
)

CHAT_TOOL_NAMES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Worker lookup helpers
# ---------------------------------------------------------------------------


def get_tool_schemas_for_worker(
    tool_names: frozenset[str],
) -> list[dict[str, Any]]:
    """Return the subset of ``TOOL_SCHEMAS`` whose names are in *tool_names*."""
    name_set = set(tool_names)
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in name_set]


def get_tool_executors_for_worker(
    tool_names: frozenset[str],
) -> dict[str, Callable[..., str]]:
    """Return the subset of ``TOOL_EXECUTORS`` whose names are in *tool_names*."""
    return {name: fn for name, fn in TOOL_EXECUTORS.items() if name in tool_names}


# ---------------------------------------------------------------------------
# Human-in-the-loop tools by worker
# ---------------------------------------------------------------------------

HITL_TOOLS_BY_WORKER: dict[str, frozenset[str]] = {
    "worker_restaurant": frozenset({"make_reservation"}),
    "worker_voucher": frozenset({"place_order", "request_refund"}),
    "worker_chat": frozenset(),
}
