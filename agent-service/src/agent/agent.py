"""Core agent for the Pick AI Shopping Guide.

Builds a Supervisor + Worker fan-out LangGraph StateGraph:
    START -> supervisor_node -> route_to_workers (Send[] fan-out)
           -> worker_restaurant / worker_voucher / worker_chat
           -> synthesizer_node -> END
"""

import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from src.agent.state import PickAgentState
from src.agent.supervisor import supervisor_node, route_to_workers
from src.agent.synthesizer import synthesizer_node
from src.agent.workers.restaurant import create_worker_restaurant
from src.agent.workers.voucher import create_worker_voucher
from src.agent.workers.chat import create_worker_chat
from src.memory.control.handler import MemoryControlHandler

logger = logging.getLogger("pick.agent")


def create_pick_agent(
    checkpointer=None,
    memory_control_handler: MemoryControlHandler | None = None,
    neo4j_client=None,
    retrieval_gateway=None,
    prompt_builder=None,
    memory_pipeline=None,
):
    """Build and compile the Supervisor + Worker agent graph.

    Topology:
        START → supervisor → route_to_workers (Send[] fan-out)
              → worker_restaurant / worker_voucher / worker_chat
              → synthesizer → END

    Args:
        checkpointer: A LangGraph checkpointer instance.
            Falls back to InMemorySaver when None.
        memory_control_handler: Kept for backward compatibility;
            unused in the new graph.
        neo4j_client: Optional Neo4j client for profile updates in
            the synthesizer.
        retrieval_gateway: Optional memory retrieval gateway for the
            supervisor to fetch user profiles.
        prompt_builder: Reserved for future use (dynamic prompt
            construction in the supervisor).
        memory_pipeline: Optional MemoryPipeline for the synthesizer's
            ProfileUpdater.

    Returns:
        A compiled LangGraph StateGraph exposing .astream(),
        .ainvoke(), and .get_state().
    """
    if checkpointer is None:
        checkpointer = InMemorySaver()
        logger.warning("checkpointer not provided, using InMemorySaver (non-persistent)")

    worker_restaurant = create_worker_restaurant()
    worker_voucher = create_worker_voucher()
    worker_chat = create_worker_chat()
    logger.info("Workers created: restaurant=%s voucher=%s chat=%s",
                type(worker_restaurant).__name__,
                type(worker_voucher).__name__,
                type(worker_chat).__name__)

    def _supervisor(state):
        return supervisor_node(
            state,
            retrieval_gateway=retrieval_gateway,
            prompt_builder=prompt_builder,
        )

    def _synthesizer(state):
        return synthesizer_node(
            state,
            neo4j_client=neo4j_client,
            memory_pipeline=memory_pipeline,
        )

    builder = StateGraph(PickAgentState)
    builder.add_node("supervisor", _supervisor)
    builder.add_node("synthesizer", _synthesizer)
    builder.add_node("worker_restaurant", worker_restaurant)
    builder.add_node("worker_voucher", worker_voucher)
    builder.add_node("worker_chat", worker_chat)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_to_workers,
        ["worker_restaurant", "worker_voucher", "worker_chat"])
    for name in ("worker_restaurant", "worker_voucher", "worker_chat"):
        builder.add_edge(name, "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile(checkpointer=checkpointer)
