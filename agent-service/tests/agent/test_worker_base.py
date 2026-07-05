"""Unit tests for the Worker base factory (hand-written ReAct loop)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.state import WorkerState
from src.agent.workers.base import (
    _build_empty_output,
    _check_continue,
    _tools_node,
    create_worker,
)


# ============================================================================
# TestCheckContinue
# ============================================================================


class TestCheckContinue:
    """Tests for the _check_continue routing function."""

    def test_tool_calls_present_returns_tools(self):
        """When last message has tool_calls and under max_rounds → 'tools'."""
        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search_shops", "args": {}, "id": "call_1"}],
                ),
            ],
            "tool_rounds": 2,
        }
        assert _check_continue(state, max_rounds=8) == "tools"

    def test_no_tool_calls_returns_extract_deltas(self):
        """When last message has no tool_calls → 'extract_deltas'."""
        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="Here are your results."),
            ],
            "tool_rounds": 1,
        }
        assert _check_continue(state) == "extract_deltas"

    def test_max_rounds_exceeded_returns_extract_deltas(self):
        """When tool_rounds >= max_rounds → 'extract_deltas' even with tools."""
        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "search_shops", "args": {}, "id": "call_1"}],
                ),
            ],
            "tool_rounds": 8,
        }
        assert _check_continue(state, max_rounds=8) == "extract_deltas"

    def test_empty_messages_returns_extract_deltas(self):
        """When messages list is empty → 'extract_deltas'."""
        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [],
            "tool_rounds": 0,
        }
        assert _check_continue(state) == "extract_deltas"


# ============================================================================
# TestToolsNode
# ============================================================================


class TestToolsNode:
    """Tests for the _tools_node tool-execution function."""

    def test_executes_tool_and_returns_tool_message(self):
        """A known tool is called and its result is returned as a ToolMessage."""
        tool_executors = {
            "echo": lambda **kwargs: f"echoed: {kwargs.get('text', '')}",
        }

        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [
                HumanMessage(content="echo 'hello'"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "echo", "args": {"text": "hello"}, "id": "call_1"}
                    ],
                ),
            ],
            "tool_rounds": 1,
        }

        result = _tools_node(state, tool_executors=tool_executors, hitl_tools=frozenset())
        tool_msgs = result["messages"]
        assert len(tool_msgs) == 1
        assert isinstance(tool_msgs[0], ToolMessage)
        assert tool_msgs[0].content == "echoed: hello"
        assert tool_msgs[0].tool_call_id == "call_1"

    def test_unknown_tool_returns_error_message(self):
        """An unknown tool produces an error ToolMessage."""
        tool_executors: dict = {}

        state: WorkerState = {
            "worker_task": {"task": "test"},
            "memory_context": "",
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "nonexistent_tool", "args": {}, "id": "call_2"}
                    ],
                ),
            ],
            "tool_rounds": 1,
        }

        result = _tools_node(state, tool_executors=tool_executors, hitl_tools=frozenset())
        tool_msgs = result["messages"]
        assert len(tool_msgs) == 1
        assert "unknown tool" in tool_msgs[0].content.lower()
        assert tool_msgs[0].tool_call_id == "call_2"


# ============================================================================
# TestBuildEmptyOutput
# ============================================================================


class TestBuildEmptyOutput:
    """Tests for _build_empty_output."""

    def test_builds_output_with_correct_worker_id_and_status(self):
        """Output dict has worker_result with worker_id, success status, and empty deltas."""
        state: WorkerState = {
            "worker_task": {"worker_id": "worker_test", "task": "do something"},
            "memory_context": "",
            "messages": [
                HumanMessage(content="help"),
                AIMessage(content="I found 3 restaurants near you."),
            ],
            "tool_rounds": 1,
        }

        output = _build_empty_output(state)

        assert "worker_result" in output
        wr = output["worker_result"]
        assert wr["worker_id"] == "worker_test"
        assert wr["status"] == "success"
        assert "restaurants" in wr["summary"]
        assert wr["artifacts"] == []
        assert wr["error"] is None
        assert output["candidate_deltas"] == []

    def test_fallback_worker_id_when_task_is_string(self):
        """When worker_task is a plain string, worker_id falls back to 'unknown_worker'."""
        state: WorkerState = {
            "worker_task": "just a string task",  # type: ignore[typeddict-item]
            "memory_context": "",
            "messages": [AIMessage(content="Done.")],
            "tool_rounds": 0,
        }

        output = _build_empty_output(state)
        assert output["worker_result"]["worker_id"] == "unknown_worker"


# ============================================================================
# TestCreateWorker
# ============================================================================


class TestCreateWorker:
    """Tests for the create_worker factory function."""

    def test_returns_compiled_graph_with_ainvoke_and_astream_events(self):
        """The returned graph is a compiled LangGraph with expected methods."""
        worker = create_worker(
            name="test_worker",
            system_prompt="You are a helpful test assistant.",
            tool_schemas=[],
            tool_executors={},
        )

        assert hasattr(worker, "ainvoke")
        assert hasattr(worker, "astream_events")
        # Basic check that it's a compiled graph (not None or a raw builder).
        assert worker is not None

    def test_graph_has_expected_nodes(self):
        """The compiled graph includes agent, tools, and extract_deltas nodes."""
        worker = create_worker(
            name="test_worker",
            system_prompt="You are a helpful test assistant.",
            tool_schemas=[],
            tool_executors={},
        )

        # LangGraph compiled graphs store node info in a dictionary.
        nodes = worker.get_graph().nodes
        assert "agent" in nodes
        assert "tools" in nodes
        assert "extract_deltas" in nodes

    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_ainvoke_runs_through_agent_and_extract(self, mock_get_client):
        """A minimal ainvoke call goes agent → extract_deltas → END (no tools)."""
        # Mock the LLM to return a plain text response (no tool calls).
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Here are 3 restaurants near you."
        mock_choice.message.tool_calls = None
        mock_client.chat.completions.create.return_value.choices = [mock_choice]
        mock_get_client.return_value = mock_client

        worker = create_worker(
            name="test_worker",
            system_prompt="You are a helpful test assistant.",
            tool_schemas=[],
            tool_executors={},
            extract_deltas=False,
        )

        import asyncio

        async def _run():
            return await worker.ainvoke(
                {
                    "worker_task": {"worker_id": "test_worker", "task": "find shops"},
                    "memory_context": "",
                    "messages": [HumanMessage(content="Find me a hotpot place.")],
                    "tool_rounds": 0,
                }
            )

        result = asyncio.run(_run())

        # Should have produced a worker_result via _build_empty_output.
        assert "worker_result" in result
        assert result["worker_result"]["worker_id"] == "test_worker"
        assert result["worker_result"]["status"] == "success"
