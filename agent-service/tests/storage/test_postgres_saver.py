# tests/storage/test_postgres_saver.py
"""Integration tests for PostgresSaver. Requires Postgres running."""
import pytest
from src.storage.postgres_saver import PostgresSaverManager

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_setup_creates_tables():
    """setup() should not raise — tables created idempotently."""
    manager = PostgresSaverManager()
    await manager.setup()
    saver = manager.create_saver()
    assert saver is not None
    await manager.close()


@pytest.mark.asyncio
async def test_saver_can_checkpoint():
    """PostgresSaver should store and retrieve state."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.base import empty_checkpoint

    manager = PostgresSaverManager()
    await manager.setup()
    saver = manager.create_saver()

    # Build a minimal graph to test checkpoint
    builder = StateGraph(dict)
    builder.add_node("echo", lambda s: s)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "test_thread_1"}}
    result = await graph.ainvoke({"msg": "hello"}, config)
    assert result["msg"] == "hello"

    # Verify state persists
    state = graph.get_state(config)
    assert state is not None
    assert state.values["msg"] == "hello"

    await manager.close()
