"""State schemas for the Pick Agent Team architecture.

Defines the shared PickAgentState, WorkerState, and all sub-schemas
(SubTask, WorkerResult, CandidateDelta). Reducers handle list merging
for parallel Worker fan-out.
"""

from typing import Annotated, TypedDict

from langgraph.graph import add_messages


# ── Reducers ──────────────────────────────────────────────────────────


def merge_lists(left: list, right: list) -> list:
    """Generic list-concatenation reducer for parallel Worker aggregation."""
    return (left or []) + (right or [])


# ── Sub-Schemas ───────────────────────────────────────────────────────


class SubTask(TypedDict, total=False):
    """A single unit of work dispatched to a Worker subgraph."""
    worker_id: str
    task: str
    priority: int
    memory_ctx: str
    context: dict


class WorkerResult(TypedDict, total=False):
    """Structured output returned by each Worker subgraph."""
    worker_id: str
    status: str              # "success" | "failed" | "cancelled"
    summary: str
    artifacts: list[dict]
    error: dict | None


class CandidateDelta(TypedDict, total=False):
    """A candidate memory change proposed by a Worker for Synthesizer review."""
    op: str                  # ADD | REVISE | DELETE | REINFORCE
    target_type: str
    new_value: dict
    evidence: str
    confidence: float
    source_worker: str


# ── State Schemas ─────────────────────────────────────────────────────


class PickAgentState(TypedDict, total=False):
    """Shared state across the Supervisor + Worker(s) + Synthesizer graph."""
    messages: Annotated[list, add_messages]
    sub_tasks: list[dict]
    strategy: str            # "parallel" | "sequential"
    current_step: int
    worker_results: Annotated[list[dict], merge_lists]
    candidate_deltas: Annotated[list[dict], merge_lists]
    final_response: str


class WorkerState(TypedDict, total=False):
    """Isolated state inside a single Worker subgraph."""
    worker_task: dict
    memory_context: str
    messages: Annotated[list, add_messages]
    tool_rounds: int
    worker_result: dict
    worker_results: Annotated[list[dict], merge_lists]
    candidate_deltas: list[dict]
