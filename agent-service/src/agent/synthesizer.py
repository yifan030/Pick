"""Synthesizer node: aggregates Worker results, deduplicates candidate deltas,
resolves conflicts with existing profiles, and generates the final natural-language
response.

Flow:
1. Collect worker_results and candidate_deltas from shared state.
2. Deduplicate deltas: same (target_type, canonicalized new_value) → keep highest confidence.
3. Resolve conflicts against existing profiles (contradiction → confidence threshold).
4. Synthesize final response via LLM (or concat fallback on failure).
5. Write resolved deltas to Neo4j via ProfileUpdater (best-effort, exceptions logged).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.config import LLM_MODEL, get_sync_llm_client
from src.agent.state import PickAgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum confidence margin required to accept a contradicting delta.
CONFIDENCE_MARGIN: float = 0.2

# ---------------------------------------------------------------------------
# Pure helpers (suitable for testing without LLM / Neo4j)
# ---------------------------------------------------------------------------


def _canonicalize(value: dict) -> str:
    """JSON-serialize *value* with sorted keys for consistent comparison.

    Parameters
    ----------
    value:
        A dict-like ``new_value`` from a ``CandidateDelta``.

    Returns
    -------
    A deterministic JSON string with sorted keys.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _is_contradict(new_delta: dict, existing_profile: dict) -> bool:
    """Check whether *new_delta* contradicts *existing_profile*.

    Two profiles contradict when they share any key whose value differs.

    Parameters
    ----------
    new_delta:
        A ``CandidateDelta`` dict with at least ``new_value``.
    existing_profile:
        An existing profile dict with at least ``value``.

    Returns
    -------
    ``True`` if at least one shared key has a mismatched value.
    """
    new_val = new_delta.get("new_value", {})
    existing_val = existing_profile.get("value", {})
    if not isinstance(new_val, dict) or not isinstance(existing_val, dict):
        return False
    for key in new_val:
        if key in existing_val and new_val[key] != existing_val[key]:
            return True
    return False


def dedup_and_resolve(
    deltas: list[dict],
    existing_profiles: dict[str, dict],
) -> list[dict]:
    """Deduplicate and resolve *deltas* against *existing_profiles*.

    Rules
    -----
    1. Same ``(target_type, canonicalized new_value)`` → keep highest confidence.
    2. Contradiction with an existing profile → accepted **only** if
       ``new_confidence > existing_confidence + CONFIDENCE_MARGIN``, and the
       ``op`` is changed to ``"REVISE"`` with ``target_id`` set.
    3. Non-contradicting deltas → always accepted.

    Parameters
    ----------
    deltas:
        Candidate deltas produced by workers.  Each dict has at least
        ``target_type``, ``new_value``, ``confidence``, and ``op``.
    existing_profiles:
        Mapping of ``profile_id`` → profile dict (must contain ``type_name`` and
        ``value`` keys).  Pass an empty dict when no profiles are available.

    Returns
    -------
    A deduplicated, conflict-resolved list of delta dicts.
    """
    # -- Step 1: Deduplicate by (target_type, canonical new_value) ----------
    seen: dict[tuple[str, str], dict] = {}
    for delta in deltas:
        tt = delta.get("target_type", "")
        nv = delta.get("new_value", {})
        canon = _canonicalize(nv) if isinstance(nv, dict) else json.dumps(nv)
        key = (tt, canon)

        existing_delta = seen.get(key)
        if existing_delta is None:
            seen[key] = delta
        else:
            # Keep the delta with higher confidence.
            new_conf = delta.get("confidence", 0.0)
            old_conf = existing_delta.get("confidence", 0.0)
            if new_conf > old_conf:
                seen[key] = delta

    # -- Step 2: Resolve contradictions with existing profiles --------------
    resolved: list[dict] = []
    for delta in seen.values():
        new_conf = delta.get("confidence", 0.0)
        tt = delta.get("target_type", "")

        # Find any existing profile of the same type with a contradicting value.
        contradicting_profile: dict | None = None
        for pid, prof in existing_profiles.items():
            if prof.get("type_name") != tt:
                continue
            if _is_contradict(delta, prof):
                contradicting_profile = prof
                break

        if contradicting_profile is not None:
            existing_conf = contradicting_profile.get("confidence", 0.0)
            if new_conf > existing_conf + CONFIDENCE_MARGIN:
                # Accept as REVISE — set target_id so the updater can replace it.
                resolved_delta = dict(delta)
                resolved_delta["op"] = "REVISE"
                resolved_delta["target_id"] = contradicting_profile.get("id")
                resolved.append(resolved_delta)
            else:
                # Confidence too low — drop the delta.
                logger.debug(
                    "Dropped contradicting delta: target_type=%s new_conf=%.2f "
                    "existing_conf=%.2f",
                    tt,
                    new_conf,
                    existing_conf,
                )
            continue

        # Non-contradicting → always accepted.
        resolved.append(delta)

    return resolved


# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------

SYNTHESIS_PROMPT = """You are a helpful shopping guide assistant synthesizing results
from multiple sub-agents into a single coherent response for the user.

User query: {query}

Below are summaries from the specialist workers that answered this query.
Combine them into a natural, helpful Chinese-language response.
Prioritize the most relevant information, remove redundancies, and present
results in a clear order.

Worker summaries:
{worker_summaries}

Respond in Chinese. Keep your response concise and actionable."""


def _synthesize_via_llm(query: str, worker_results: list[dict]) -> str | None:
    """Generate a unified natural-language response via LLM.

    Parameters
    ----------
    query:
        The original user query text.
    worker_results:
        List of ``WorkerResult`` dicts, each with at least a ``summary``.

    Returns
    -------
    A Chinese synthesis string, or ``None`` on failure.
    """
    # Extract successful summaries.
    summaries = [wr.get("summary", "") for wr in worker_results if wr.get("summary")]
    if not summaries:
        return None

    worker_summaries = "\n\n---\n\n".join(
        f"Worker {wr.get('worker_id', '?')}: {wr.get('summary', '')}"
        for wr in worker_results
        if wr.get("summary")
    )

    client = get_sync_llm_client()
    prompt = SYNTHESIS_PROMPT.format(query=query, worker_summaries=worker_summaries)

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if content:
            return content.strip()
        logger.warning("Synthesis LLM returned empty content, falling back to concat")
        return None
    except Exception:
        logger.exception("Synthesis LLM call failed, falling back to concat")
        return None


def _concat_results(worker_results: list[dict]) -> str:
    """Fallback: concatenate successful worker summaries into a single response.

    Parameters
    ----------
    worker_results:
        List of ``WorkerResult`` dicts.

    Returns
    -------
    A concatenated string, or an apology message if all workers failed.
    """
    success_parts: list[str] = []
    for wr in worker_results:
        status = wr.get("status", "failed")
        summary = wr.get("summary", "")
        if status == "success" and summary:
            success_parts.append(summary)

    if success_parts:
        return "\n\n".join(success_parts)

    # All workers failed — return a polite apology.
    return "抱歉，我暂时无法处理您的请求，请稍后再试。"


# ---------------------------------------------------------------------------
# Synthesizer node
# ---------------------------------------------------------------------------


def synthesizer_node(
    state: PickAgentState,
    *,
    neo4j_client: Any = None,
    memory_pipeline: Any = None,
) -> dict:
    """Aggregate Worker results, resolve deltas, and generate the final response.

    Parameters
    ----------
    state:
        The shared ``PickAgentState``.  Expected keys: ``worker_results``,
        ``candidate_deltas``, ``messages``.
    neo4j_client:
        Optional Neo4j storage client.  If provided, resolved deltas are written
        to the graph via ``ProfileUpdater``.
    memory_pipeline:
        Optional ``MemoryPipeline`` instance.  If provided along with
        *neo4j_client*, ``ProfileUpdater`` is constructed from the pipeline's
        model and the neo4j client.

    Returns
    -------
    A state update dict with keys ``final_response`` and ``candidate_deltas``.
    """
    # -- Collect inputs ------------------------------------------------------
    worker_results: list[dict] = state.get("worker_results", [])
    candidate_deltas: list[dict] = state.get("candidate_deltas", [])

    # Extract the user query from the last human message.
    messages = state.get("messages", [])
    query = ""
    for m in reversed(messages):
        if isinstance(m, dict):
            if m.get("role") == "user" or m.get("type") == "human":
                query = m.get("content", "")
                break
        else:
            from langchain_core.messages import HumanMessage

            if isinstance(m, HumanMessage):
                query = str(m.content)
                break
    if not query and worker_results:
        # Fallback: use the first worker's task description.
        query = "用户请求"

    # -- Deduplicate and resolve deltas -------------------------------------
    # Build an existing_profiles map.  For now this is passed as an empty dict;
    # in the future the memory_pipeline can supply the user's current profiles.
    existing_profiles: dict[str, dict] = {}
    resolved_deltas = dedup_and_resolve(candidate_deltas, existing_profiles)

    # -- Write resolved deltas to Neo4j (best-effort) -----------------------
    if neo4j_client is not None:
        try:
            from src.memory.profile.updater import ProfileUpdater

            # Always pass neo4j_client, plus the pipeline's model if available.
            model_kwargs = {}
            if memory_pipeline is not None and hasattr(memory_pipeline, "_model"):
                model_kwargs["model"] = memory_pipeline._model

            updater = ProfileUpdater(
                neo4j_client=neo4j_client,
                **model_kwargs,
            )
            # Convert resolved dicts to DeltaOperation objects and apply.
            delta_objects = _deltas_to_operations(resolved_deltas)
            updater.apply_delta(
                user_id=state.get("user_id", "unknown"),
                deltas=delta_objects,
            )
            logger.info(
                "Wrote %d resolved deltas to Neo4j", len(delta_objects)
            )
        except Exception:
            logger.exception(
                "Failed to write resolved deltas to Neo4j (continuing)"
            )

    # -- Synthesize final response ------------------------------------------
    # Try LLM synthesis first, then fall back to concatenation.
    final = _synthesize_via_llm(query, worker_results)
    if final is None:
        final = _concat_results(worker_results)

    return {
        "final_response": final,
        "candidate_deltas": resolved_deltas,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deltas_to_operations(resolved_deltas: list[dict]) -> list[Any]:
    """Convert resolved delta dicts to ``DeltaOperation`` objects.

    Uses the same type-class mapping as ``ProfileUpdater``.

    Parameters
    ----------
    resolved_deltas:
        List of resolved delta dicts with keys ``op``, ``target_type``,
        ``new_value``, ``confidence``, ``evidence``, ``source_worker``,
        and optionally ``target_id``.

    Returns
    -------
    A list of ``DeltaOperation`` instances.
    """
    from src.storage.models import DeltaOperation

    operations: list[DeltaOperation] = []
    for delta in resolved_deltas:
        op = delta.get("op", "ADD")
        target_type = delta.get("target_type", "")
        new_value = delta.get("new_value", {})
        target_id = delta.get("target_id")

        # Try to construct the appropriate profile atom.
        from src.memory.profile.updater import ProfileUpdater

        profile_atom = None
        if new_value and target_type:
            profile_atom = ProfileUpdater._dict_to_profile(
                target_type, new_value, user_id=""
            )

        operations.append(
            DeltaOperation(
                op=op,
                target_type=target_type,
                target_id=target_id,
                new_value=profile_atom,
                reason=delta.get("evidence", ""),
            )
        )

    return operations
