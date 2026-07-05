"""Supervisor node: classifies + decomposes user requests into SubTasks,
fans out to specialized Workers via LangGraph Send API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import Send

from src.agent.config import LLM_MODEL, get_sync_llm_client
from src.agent.state import PickAgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKER_NODE_MAP: dict[str, str] = {
    "worker_restaurant": "worker_restaurant",
    "worker_voucher": "worker_voucher",
    "worker_chat": "worker_chat",
}

WORKER_MEMORY_FIELDS: dict[str, list[str]] = {
    "worker_restaurant": [
        "CuisinePreference",
        "TastePreference",
        "BudgetPreference",
        "DietaryPreference",
        "AreaPreference",
        "ScenePreference",
    ],
    "worker_voucher": ["BudgetPreference", "ConstraintPreference"],
    "worker_chat": ["__ALL__"],
}

HARD_CONSTRAINT_TYPES: set[str] = {"DietaryPreference", "ConstraintPreference"}

# ---------------------------------------------------------------------------
# Memory trimming
# ---------------------------------------------------------------------------


def trim_memory_for_worker(profiles: list[dict], worker_id: str) -> str:
    """Filter and format user preference profiles for a specific worker.

    Hard constraints (DietaryPreference, ConstraintPreference) are always
    included regardless of the worker.  Soft preferences are filtered by
    ``WORKER_MEMORY_FIELDS``.

    Parameters
    ----------
    profiles:
        List of profile dicts, each with keys ``type_name``, ``value``,
        ``confidence``.
    worker_id:
        The worker node name (e.g. ``"worker_restaurant"``).

    Returns
    -------
    A formatted markdown string suitable for injection into the worker's
    memory context, or an empty string if no profiles match.
    """
    if not profiles:
        return ""

    # Separate hard constraints (always included) from soft preferences.
    hards = [p for p in profiles if p.get("type_name") in HARD_CONSTRAINT_TYPES]

    allowed = WORKER_MEMORY_FIELDS.get(worker_id, [])
    if "__ALL__" in allowed:
        softs = [p for p in profiles if p.get("type_name") not in HARD_CONSTRAINT_TYPES]
    else:
        softs = [p for p in profiles if p.get("type_name") in allowed]

    selected = hards + softs
    if not selected:
        return ""

    lines = ["### User Preference Memory"]
    for p in selected:
        tn = p.get("type_name", "Unknown")
        v = p.get("value", {})
        conf = p.get("confidence", 0.0)
        is_hard = p.get("type_name") in HARD_CONSTRAINT_TYPES
        prefix = "[HARD]" if is_hard else "[PREF]"
        lines.append(
            f"- {prefix} [{tn}] {json.dumps(v, ensure_ascii=False)} "
            f"(conf:{conf:.2f})"
        )

    return "\n".join(lines)


def _format_profiles_for_llm(profiles: list[dict]) -> str:
    """Format profile list into a compact string for the decomposition LLM prompt."""
    if not profiles:
        return "(No stored user preferences)"
    formatted = []
    for p in profiles[:20]:
        tn = p.get("type_name", "?")
        v = p.get("value", {})
        formatted.append(
            f"  [{tn}] {json.dumps(v, ensure_ascii=False)}"
        )
    return "\n".join(formatted)


# ---------------------------------------------------------------------------
# Complexity classification
# ---------------------------------------------------------------------------


def _classify_complexity(query: str) -> str:
    """Classify a user query as ``"simple"`` or ``"complex"``.

    A query is considered *complex* when it contains signals from multiple
    intent categories (recommend + purchase), indicating the need for
    LLM-based decomposition.  Otherwise it is *simple*.
    """
    query_lower = query.lower()

    signals = {
        "recommend": any(
            kw in query_lower
            for kw in ["recommend", "find", "search", "nearby", "delicious",
                        "hotpot", "restaurant", "shop", "eat", "food", "cuisine"]
        ),
        "purchase": any(
            kw in query_lower
            for kw in ["buy", "order", "voucher", "refund", "purchase", "coupon"]
        ),
    }

    active_count = sum(1 for v in signals.values() if v)
    return "complex" if active_count >= 2 else "simple"


# ---------------------------------------------------------------------------
# Rule-based routing
# ---------------------------------------------------------------------------


def _rule_based_routing(query: str) -> list[dict]:
    """Fast keyword-based routing that returns a single SubTask.

    Used for simple queries and as a fallback when LLM decomposition fails.

    Returns
    -------
    A list containing a single SubTask dict with keys ``worker_id``,
    ``task``, ``priority``, ``memory_ctx``, and ``context``.
    """
    query_lower = query.lower()

    if any(
        kw in query_lower
        for kw in ["buy", "order", "voucher", "refund", "purchase", "coupon"]
    ):
        worker = "worker_voucher"
    elif any(
        kw in query_lower
        for kw in [
            "recommend", "find", "search", "nearby", "delicious",
            "hotpot", "restaurant", "shop", "eat", "food", "cuisine",
        ]
    ):
        worker = "worker_restaurant"
    else:
        worker = "worker_chat"

    return [
        {
            "worker_id": worker,
            "task": query,
            "priority": 1,
            "memory_ctx": "",
            "context": {},
        }
    ]


# ---------------------------------------------------------------------------
# LLM decomposition
# ---------------------------------------------------------------------------

DECOMPOSITION_PROMPT = """You are a task decomposer for a shopping guide assistant.

Available Workers:
- worker_restaurant: search shops, recommend restaurants, bookmarks, reservations
- worker_voucher: query vouchers, place orders, order management, refunds, alerts
- worker_chat: chat, greetings, general questions

Break the user request into subtasks. Output JSON with this structure:
{
  "strategy": "parallel" | "sequential",
  "decomposition": [
    {"worker_id": "...", "task": "...", "priority": 1}
  ],
  "reasoning": "..."
}

Rules:
- Independent subtasks use "parallel"
- Dependent subtasks (where one needs the other's output) use "sequential"
- priority: 1=core (must complete), 2=auxiliary (nice to have), 3=supplementary
- The "task" field should be a clear, self-contained instruction for the worker

User request: {query}
Available preferences: {memory_context}"""


def _decompose_via_llm(query: str, memory_context: str = "") -> dict | None:
    """Use the sync OpenAI client to decompose a compound request into subtasks.

    Parameters
    ----------
    query:
        The raw user query text.
    memory_context:
        Formatted string of available user preferences (may be empty).

    Returns
    -------
    A dict with ``strategy`` and ``sub_tasks`` keys, or ``None`` on failure
    (caller should fall back to rule-based routing).
    """
    client = get_sync_llm_client()
    prompt = DECOMPOSITION_PROMPT.format(
        query=query, memory_context=memory_context or "(None)"
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            logger.warning("LLM decomposition returned empty content")
            return None
        result = json.loads(content)
    except Exception:
        logger.exception("LLM decomposition failed, falling back to rule-based routing")
        return None

    # Validate and normalise strategy.
    strategy = result.get("strategy", "parallel")
    if strategy not in ("parallel", "sequential"):
        strategy = "parallel"

    # Build sanitised sub_tasks list.
    sub_tasks: list[dict] = []
    for d in result.get("decomposition", []):
        wid = d.get("worker_id", "worker_chat")
        if wid not in WORKER_NODE_MAP:
            wid = "worker_chat"
        sub_tasks.append(
            {
                "worker_id": wid,
                "task": d.get("task", query),
                "priority": d.get("priority", 1),
                "memory_ctx": "",
                "context": d.get("context", {}),
            }
        )

    return {"strategy": strategy, "sub_tasks": sub_tasks}


# ---------------------------------------------------------------------------
# Supervisor node
# ---------------------------------------------------------------------------


def supervisor_node(
    state: PickAgentState,
    *,
    profiles=None,
    retrieval_gateway=None,
    prompt_builder=None,
    user_id: str | None = None,
) -> dict:
    """Classify the last user message, decompose into SubTasks, and trim memory.

    Parameters
    ----------
    state:
        The shared ``PickAgentState``.
    profiles:
        Pre-fetched user profiles (list of dicts).  If not provided and
        *retrieval_gateway* + *user_id* are available, profiles are fetched
        on-demand.
    retrieval_gateway:
        Optional memory retrieval gateway with an async ``retrieve()`` method.
    prompt_builder:
        Reserved for future use (dynamic prompt construction).
    user_id:
        The current user's ID, used for profile retrieval.

    Returns
    -------
    A state update dict with keys ``sub_tasks``, ``strategy``, and
    ``current_step``.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"sub_tasks": [], "strategy": "parallel", "current_step": 0}

    # Extract the last user message as the query.
    last_msg = messages[-1]
    if isinstance(last_msg, dict):
        query = last_msg.get("content", "")
    else:
        query = str(last_msg)

    profiles_list = list(profiles) if profiles else []

    # Optionally retrieve profiles from the memory gateway.
    if retrieval_gateway is not None and user_id is not None and not profiles_list:
        import asyncio

        try:
            retrieval_result = asyncio.run(
                retrieval_gateway.retrieve(
                    user_id=user_id, query=query, is_new_session=True
                )
            )
            profiles_list = retrieval_result.get("profiles", [])
        except Exception:
            logger.exception(
                "Memory retrieval failed, continuing without profiles"
            )

    # Classify complexity and decompose.
    complexity = _classify_complexity(query)
    logger.info("Supervisor: complexity=%s query=%.80s", complexity, query)

    if complexity == "simple":
        sub_tasks = _rule_based_routing(query)
        strategy = "parallel"
    else:
        decomposition = _decompose_via_llm(
            query, _format_profiles_for_llm(profiles_list)
        )
        if decomposition is None:
            sub_tasks = _rule_based_routing(query)
            strategy = "parallel"
        else:
            sub_tasks = decomposition["sub_tasks"]
            strategy = decomposition["strategy"]

    # Trim memory context per worker.
    for st in sub_tasks:
        if profiles_list:
            st["memory_ctx"] = trim_memory_for_worker(
                profiles_list, st["worker_id"]
            )

    # Force sequential when multiple HITL workers are present (voucher worker
    # uses human-in-the-loop for place_order / request_refund).
    hitl_workers = [
        st for st in sub_tasks if st["worker_id"] == "worker_voucher"
    ]
    if len(hitl_workers) > 1 and strategy == "parallel":
        logger.info("Supervisor: multiple HITL workers present, forcing sequential")
        strategy = "sequential"

    logger.info(
        "Supervisor: strategy=%s sub_tasks=%d", strategy, len(sub_tasks)
    )
    return {"sub_tasks": sub_tasks, "strategy": strategy, "current_step": 0}


# ---------------------------------------------------------------------------
# Routing to workers
# ---------------------------------------------------------------------------


def route_to_workers(state: PickAgentState) -> list[Send]:
    """Build LangGraph ``Send`` commands to fan out SubTasks to Workers.

    - **Parallel strategy**: one ``Send`` per SubTask, all dispatched at once.
    - **Sequential strategy**: one ``Send`` for the ``current_step`` SubTask.
    - **Empty sub_tasks**: fallback ``Send`` to ``worker_chat``.

    Returns
    -------
    A list of ``langgraph.types.Send`` objects.
    """
    sub_tasks: list[dict] = state.get("sub_tasks", [])
    if not sub_tasks:
        return [
            Send(
                "worker_chat",
                {
                    "worker_task": {
                        "worker_id": "worker_chat",
                        "task": "chat",
                        "priority": 1,
                        "memory_ctx": "",
                    },
                    "memory_context": "",
                },
            )
        ]

    strategy = state.get("strategy", "parallel")

    if strategy == "sequential":
        current_step = state.get("current_step", 0)
        if current_step >= len(sub_tasks):
            return []
        task = sub_tasks[current_step]
        node_name = WORKER_NODE_MAP.get(task["worker_id"], "worker_chat")
        return [
            Send(
                node_name,
                {
                    "worker_task": task,
                    "memory_context": task.get("memory_ctx", ""),
                },
            )
        ]

    # Parallel: one Send per subtask.
    sends: list[Send] = []
    for t in sub_tasks:
        node_name = WORKER_NODE_MAP.get(t["worker_id"], "worker_chat")
        sends.append(
            Send(
                node_name,
                {
                    "worker_task": t,
                    "memory_context": t.get("memory_ctx", ""),
                },
            )
        )

    return sends
