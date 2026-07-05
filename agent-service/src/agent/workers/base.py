"""Hand-written ReAct Worker subgraph factory.

Each Worker is a compiled LangGraph StateGraph with the loop:

    START -> agent_node -> check_continue --> "tools" -> tools_node -> agent_node (loop)
                              |
                              +--> "extract_deltas" -> extract_deltas_node -> END

No langchain create_agent() or middleware.  All LLM calls use the **sync**
OpenAI client from ``src.agent.config``.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agent.config import LLM_MODEL, get_sync_llm_client
from src.agent.state import WorkerState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum allowed tool-calling rounds per Worker (guard against infinite loops).
MAX_TOOL_ROUNDS: int = 8

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_worker_system_prompt(
    worker_task: str,
    memory_context: str,
    base_prompt: str,
) -> str:
    """Combine the base system prompt, task description and memory context.

    Parameters
    ----------
    worker_task:
        Human-readable description of what this worker should accomplish.
    memory_context:
        User memory / preference context injected from the shared state.
    base_prompt:
        Static base system prompt (role, tone, constraints, etc.).
    """
    parts: list[str] = [base_prompt]
    if worker_task:
        parts.append(f"\n## Your Task\n{worker_task}")
    if memory_context:
        parts.append(f"\n## User Context\n{memory_context}")
    return "\n".join(parts)


def _langchain_msgs_to_openai(msgs: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of LangChain messages to the OpenAI API dict format."""
    openai_msgs: list[dict[str, Any]] = []
    for msg in msgs:
        if isinstance(msg, HumanMessage):
            openai_msgs.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            d: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                d["tool_calls"] = []
                for tc in msg.tool_calls:
                    name = tc.get("name") or tc.get("function", {}).get("name", "")
                    args = tc.get("args") or tc.get("function", {}).get("arguments", "{}")
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    d["tool_calls"].append(
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": name, "arguments": args},
                        }
                    )
            openai_msgs.append(d)
        elif isinstance(msg, ToolMessage):
            openai_msgs.append(
                {
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                }
            )
        elif isinstance(msg, SystemMessage):
            openai_msgs.append({"role": "system", "content": msg.content})
        elif isinstance(msg, dict):
            # Pass-through raw dicts (best-effort).
            openai_msgs.append(msg)
    return openai_msgs


def _openai_tool_calls_to_langchain(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """Convert OpenAI SDK tool_calls to AIMessage-compatible dicts."""
    result: list[dict[str, Any]] = []
    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, TypeError):
            args = {}
        result.append(
            {
                "name": tc.function.name,
                "args": args,
                "id": tc.id,
            }
        )
    return result


def _get_tool_call_info(tc: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """Extract (name, args, id) from a tool-call dict in either format."""
    # LangChain AIMessage format: {"name": ..., "args": ..., "id": ...}
    # OpenAI raw dict format:  {"id": ..., "function": {"name": ..., "arguments": ...}}
    name = tc.get("name") or tc.get("function", {}).get("name", "")
    raw_args = tc.get("args") or tc.get("function", {}).get("arguments", "{}")
    call_id = tc.get("id", "")

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}

    return name, args, call_id


# ---------------------------------------------------------------------------
# ReAct graph nodes
# ---------------------------------------------------------------------------


def _agent_node(
    state: WorkerState,
    *,
    system_prompt: str,
    tool_schemas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call the sync OpenAI client with the conversation + available tools.

    Parameters
    ----------
    system_prompt:
        Base system prompt (static).  Memory context from *state* is appended
        automatically inside the node.
    tool_schemas:
        OpenAI function-calling tool definitions to expose to the LLM.
    """
    client = get_sync_llm_client()

    # Build the final system prompt (static base + dynamic memory context).
    worker_task = state.get("worker_task", {})
    task_desc = ""
    if isinstance(worker_task, dict):
        task_desc = worker_task.get("task", "")
    elif isinstance(worker_task, str):
        task_desc = worker_task
    memory_context = state.get("memory_context", "")
    full_system = _build_worker_system_prompt(task_desc, memory_context, system_prompt)

    # Convert LangChain messages → OpenAI dicts, prepend system prompt.
    api_messages: list[dict[str, Any]] = [{"role": "system", "content": full_system}]
    api_messages.extend(_langchain_msgs_to_openai(state.get("messages", [])))

    tools_param: list[dict[str, Any]] | None = tool_schemas if tool_schemas else None

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=api_messages,
            tools=tools_param,  # type: ignore[arg-type]
        )
        choice = response.choices[0]
        msg = choice.message
    except Exception:
        logger.exception("LLM call failed in worker agent_node")
        ai_msg = AIMessage(
            content="I apologize, but I encountered an error processing your "
            "request. Please try again."
        )
        return {
            "messages": [ai_msg],
            "tool_rounds": state.get("tool_rounds", 0) + 1,
        }

    # Convert OpenAI tool_calls back to LangChain AIMessage format.
    lc_tool_calls = _openai_tool_calls_to_langchain(msg.tool_calls or [])

    ai_msg = AIMessage(
        content=msg.content or "",
        tool_calls=lc_tool_calls if lc_tool_calls else [],
    )

    return {
        "messages": [ai_msg],
        "tool_rounds": state.get("tool_rounds", 0) + 1,
    }


def _check_continue(
    state: WorkerState,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    """Decide whether to execute tools or extract deltas.

    Returns
    -------
    ``"tools"``
        Last assistant message contains tool-calls and we are still under the
        round limit.
    ``"extract_deltas"``
        No tool-calls, max rounds exhausted, or no messages yet.
    """
    messages = state.get("messages", [])
    if not messages:
        return "extract_deltas"

    last_msg = messages[-1]

    # AIMessage with tool_calls present?
    tool_calls: list[Any] = []
    if isinstance(last_msg, AIMessage):
        tool_calls = last_msg.tool_calls or []
    elif isinstance(last_msg, dict):
        tool_calls = last_msg.get("tool_calls", [])

    if tool_calls:
        current_round = state.get("tool_rounds", 0)
        if current_round < max_rounds:
            return "tools"

    return "extract_deltas"


def _tools_node(
    state: WorkerState,
    *,
    tool_executors: dict[str, Callable[..., str]],
    hitl_tools: frozenset[str],
) -> dict[str, Any]:
    """Execute tool-calls from the last assistant message.

    Human-in-the-loop tools (listed in *hitl_tools*) trigger ``interrupt()``
    before execution, pausing the graph until the user confirms.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    last_msg = messages[-1]

    # Extract tool-calls in a format-agnostic way.
    raw_tool_calls: list[dict[str, Any]] = []
    if isinstance(last_msg, AIMessage):
        raw_tool_calls = last_msg.tool_calls or []
    elif isinstance(last_msg, dict):
        raw_tool_calls = last_msg.get("tool_calls", [])

    tool_msgs: list[ToolMessage] = []

    for tc in raw_tool_calls:
        fn_name, fn_args, call_id = _get_tool_call_info(tc)

        # Unknown tool → error message.
        if fn_name not in tool_executors:
            tool_msgs.append(
                ToolMessage(
                    content=f"Error: unknown tool '{fn_name}'",
                    tool_call_id=call_id,
                )
            )
            continue

        # HITL guard — pause for user confirmation.
        if fn_name in hitl_tools:
            interrupt(
                {
                    "type": "confirm",
                    "tool": fn_name,
                    "params": fn_args,
                    "message": f"Confirm execution of '{fn_name}' with "
                    f"parameters: {json.dumps(fn_args, ensure_ascii=False)}",
                }
            )

        # Execute the tool.
        try:
            result = tool_executors[fn_name](**fn_args)
            tool_msgs.append(
                ToolMessage(content=str(result), tool_call_id=call_id)
            )
        except Exception:
            logger.exception("Tool '%s' execution failed", fn_name)
            tool_msgs.append(
                ToolMessage(
                    content=f"Error: execution of '{fn_name}' failed",
                    tool_call_id=call_id,
                )
            )

    return {"messages": tool_msgs}


def _build_empty_output(state: WorkerState) -> dict[str, Any]:
    """Build a ``WorkerResult`` from the last assistant message content.

    Used when preference extraction is disabled or fails.
    """
    messages = state.get("messages", [])
    summary = ""
    if messages:
        last_msg = messages[-1]
        content = getattr(last_msg, "content", "") or ""
        summary = str(content)[:500]

    worker_id = "unknown_worker"
    worker_task = state.get("worker_task", {})
    if isinstance(worker_task, dict):
        worker_id = worker_task.get("worker_id", "unknown_worker")

    return {
        "worker_result": {
            "worker_id": worker_id,
            "status": "success",
            "summary": summary,
            "artifacts": [],
            "error": None,
        },
        "candidate_deltas": [],
    }


def _extract_deltas_node(
    state: WorkerState,
    *,
    extract_deltas: bool,
    extractor_client: Any = None,
) -> dict[str, Any]:
    """Optional preference-delta extraction from the conversation.

    When *extract_deltas* is ``False`` this node is a no-op that just
    packages the last assistant message into a ``WorkerResult``.

    When ``True`` it calls a lightweight model (default: ``gpt-4o-mini``) with
    ``response_format={"type": "json_object"}`` to extract structured
    ``CandidateDelta`` objects.
    """
    if not extract_deltas:
        return _build_empty_output(state)

    client = extractor_client or get_sync_llm_client()

    # Build a compact conversation transcript.
    messages = state.get("messages", [])
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"User: {msg.content}")
        elif isinstance(msg, AIMessage):
            content = msg.content or ""
            if msg.tool_calls:
                content += f"\n[Used tools: {[tc.get('name', '') for tc in msg.tool_calls]}]"
            lines.append(f"Assistant: {content}")
        elif isinstance(msg, ToolMessage):
            lines.append(f"Tool result: {msg.content[:300]}")

    transcript = "\n".join(lines)

    extract_prompt = (
        "You are a preference extraction agent for a shopping guide assistant.\n"
        "Analyze the conversation below and extract any user preference changes.\n\n"
        "Return a JSON object with these keys:\n"
        '  - "summary": A concise 1-2 sentence summary of what the assistant accomplished.\n'
        '  - "deltas": A list of preference changes. Each delta has:\n'
        '      "op": "ADD" | "REVISE" | "DELETE" | "REINFORCE"\n'
        '      "target_type": e.g. "CuisinePreference", "PriceRange", "Ambiance"\n'
        '      "new_value": {{}}  (the preference value as a JSON object)\n'
        '      "evidence": A short quote from the conversation\n'
        '      "confidence": 0.0 – 1.0\n'
        "If no clear preference changes are found, return an empty deltas list.\n\n"
        f"Conversation:\n{transcript}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": extract_prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            return _build_empty_output(state)

        result = json.loads(content)

        worker_id = "unknown_worker"
        worker_task = state.get("worker_task", {})
        if isinstance(worker_task, dict):
            worker_id = worker_task.get("worker_id", "unknown_worker")

        deltas: list[dict[str, Any]] = result.get("deltas", [])
        for d in deltas:
            d.setdefault("source_worker", worker_id)

        return {
            "worker_result": {
                "worker_id": worker_id,
                "status": "success",
                "summary": result.get("summary", "Task completed"),
                "artifacts": [],
                "error": None,
            },
            "candidate_deltas": deltas,
        }
    except Exception:
        logger.exception("Preference extraction failed, falling back to empty output")
        return _build_empty_output(state)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_worker(
    name: str,
    system_prompt: str,
    tool_schemas: list[dict[str, Any]],
    tool_executors: dict[str, Callable[..., str]],
    *,
    hitl_tools: frozenset[str] | None = None,
    max_rounds: int = 8,
    extract_deltas: bool = True,
) -> Any:
    """Build and compile a hand-written ReAct Worker subgraph.

    Parameters
    ----------
    name:
        Human-readable worker name (e.g. ``"worker_restaurant"``).
    system_prompt:
        Static base system prompt (role, tone, constraints).
    tool_schemas:
        OpenAI function-calling tool definitions to expose to the LLM.
    tool_executors:
        Mapping of ``tool_name`` → callable.  Each callable receives keyword
        arguments matching its schema and must return a ``str``.
    hitl_tools:
        Set of tool names that require human-in-the-loop confirmation via
        ``interrupt()`` before execution.
    max_rounds:
        Maximum number of agent→tool→agent rounds (default ``8``).
    extract_deltas:
        When ``True`` the terminal node calls a lightweight extractor model to
        produce ``CandidateDelta`` objects.  When ``False`` it simply packages
        the last assistant message into a ``WorkerResult``.

    Returns
    -------
    Compiled LangGraph ``StateGraph`` with ``ainvoke`` and ``astream_events``.
    """
    if hitl_tools is None:
        hitl_tools = frozenset()

    # Include the worker name in the static system prompt so the LLM knows its
    # role.  Dynamic fields (task, memory_context) are read from state at
    # runtime inside _agent_node.
    full_system_prompt = _build_worker_system_prompt(
        worker_task=f"You are the {name} worker.",
        memory_context="",
        base_prompt=system_prompt,
    )

    # -- Build the graph ---------------------------------------------------
    graph = StateGraph(WorkerState)

    graph.add_node(
        "agent",
        partial(
            _agent_node,
            system_prompt=full_system_prompt,
            tool_schemas=tool_schemas,
        ),
    )
    graph.add_node(
        "tools",
        partial(
            _tools_node,
            tool_executors=tool_executors,
            hitl_tools=hitl_tools,
        ),
    )
    graph.add_node(
        "extract_deltas",
        partial(_extract_deltas_node, extract_deltas=extract_deltas),
    )

    # Routing.
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        partial(_check_continue, max_rounds=max_rounds),
        {
            "tools": "tools",
            "extract_deltas": "extract_deltas",
        },
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("extract_deltas", END)

    return graph.compile()
