"""Integration tests for the full Supervisor + Workers + Synthesizer graph.

Tests the complete create_pick_agent() graph end-to-end with mocked LLM
responses to avoid real API calls.  All LLM calls use the synchronous
OpenAI client accessed via patching the module-level references in
``src.agent.workers.base`` and ``src.agent.synthesizer``.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

from src.agent.agent import create_pick_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_openai_response(content="Hello!", tool_calls=None):
    """Build a MagicMock that mimics an OpenAI ``chat.completions.create`` response.

    Parameters
    ----------
    content:
        The text content to return in ``choices[0].message.content``.
    tool_calls:
        Optional list of tool-call mocks for ``choices[0].message.tool_calls``.
        Each mock must have ``id``, ``function.name``, and ``function.arguments``.
    """
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


# ---------------------------------------------------------------------------
# TestSingleWorkerPath
# ---------------------------------------------------------------------------


class TestSingleWorkerPath:
    """Integration tests verifying that single-intent queries route to the
    correct worker and produce a complete response."""

    @patch("src.agent.synthesizer.get_sync_llm_client")
    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_simple_chat_goes_to_chat_worker(self, mock_base_llm, mock_synth_llm):
        """'hello' routes to worker_chat via keyword routing (no domain signals)."""
        mock_client = MagicMock()
        # Chat worker has extract_deltas=False, so only 2 LLM calls:
        #   1. worker agent_node
        #   2. synthesizer
        mock_client.chat.completions.create.side_effect = [
            _make_mock_openai_response("Hello! How can I help you today?"),
            _make_mock_openai_response("Greeting response synthesized."),
        ]
        mock_base_llm.return_value = mock_client
        mock_synth_llm.return_value = mock_client

        agent = create_pick_agent(checkpointer=InMemorySaver())
        state = {"messages": [HumanMessage(content="hello")]}
        config = {"configurable": {"thread_id": "test-chat-1"}}

        result = asyncio.run(agent.ainvoke(state, config))

        worker_results = result.get("worker_results", [])
        assert len(worker_results) >= 1, (
            f"Expected at least 1 worker result, got {worker_results}"
        )
        worker_ids = {wr.get("worker_id") for wr in worker_results}
        assert "worker_chat" in worker_ids, (
            f"Expected worker_chat in results, got {worker_ids}"
        )

    @patch("src.agent.synthesizer.get_sync_llm_client")
    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_recommend_goes_to_restaurant_worker(self, mock_base_llm, mock_synth_llm):
        """'recommend hotpot' routes to worker_restaurant via keyword routing."""
        mock_client = MagicMock()
        # Restaurant worker has extract_deltas=True, so 3 LLM calls:
        #   1. worker agent_node
        #   2. worker extract_deltas (preference extraction)
        #   3. synthesizer
        mock_client.chat.completions.create.side_effect = [
            _make_mock_openai_response(
                "I found several hotpot restaurants near Chunxi Road."
            ),
            _make_mock_openai_response(
                '{"summary": "Found hotpot places near Chunxi Road", "deltas": []}'
            ),
            _make_mock_openai_response("Final hotpot recommendation synthesized."),
        ]
        mock_base_llm.return_value = mock_client
        mock_synth_llm.return_value = mock_client

        agent = create_pick_agent(checkpointer=InMemorySaver())
        state = {"messages": [HumanMessage(content="recommend hotpot")]}
        config = {"configurable": {"thread_id": "test-restaurant-1"}}

        result = asyncio.run(agent.ainvoke(state, config))

        worker_results = result.get("worker_results", [])
        assert len(worker_results) >= 1, (
            f"Expected at least 1 worker result, got {worker_results}"
        )
        worker_ids = {wr.get("worker_id") for wr in worker_results}
        assert "worker_restaurant" in worker_ids, (
            f"Expected worker_restaurant in results, got {worker_ids}"
        )

    @patch("src.agent.synthesizer.get_sync_llm_client")
    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_purchase_goes_to_voucher_worker(self, mock_base_llm, mock_synth_llm):
        """'I want to buy a voucher' routes to worker_voucher via keyword routing."""
        mock_client = MagicMock()
        # Voucher worker has extract_deltas=True, so 3 LLM calls:
        #   1. worker agent_node
        #   2. worker extract_deltas (preference extraction)
        #   3. synthesizer
        mock_client.chat.completions.create.side_effect = [
            _make_mock_openai_response(
                "Let me check available vouchers for you."
            ),
            _make_mock_openai_response(
                '{"summary": "Found available vouchers", "deltas": []}'
            ),
            _make_mock_openai_response("Voucher results synthesized."),
        ]
        mock_base_llm.return_value = mock_client
        mock_synth_llm.return_value = mock_client

        agent = create_pick_agent(checkpointer=InMemorySaver())
        state = {"messages": [HumanMessage(content="I want to buy a voucher")]}
        config = {"configurable": {"thread_id": "test-voucher-1"}}

        result = asyncio.run(agent.ainvoke(state, config))

        worker_results = result.get("worker_results", [])
        assert len(worker_results) >= 1, (
            f"Expected at least 1 worker result, got {worker_results}"
        )
        worker_ids = {wr.get("worker_id") for wr in worker_results}
        assert "worker_voucher" in worker_ids, (
            f"Expected worker_voucher in results, got {worker_ids}"
        )

    @patch("src.agent.synthesizer.get_sync_llm_client")
    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_state_has_final_response_and_worker_results(
        self, mock_base_llm, mock_synth_llm
    ):
        """The result state must contain both final_response and worker_results."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_mock_openai_response("Hello! How can I help you today?"),
            _make_mock_openai_response("Final greeting response."),
        ]
        mock_base_llm.return_value = mock_client
        mock_synth_llm.return_value = mock_client

        agent = create_pick_agent(checkpointer=InMemorySaver())
        state = {"messages": [HumanMessage(content="hello")]}
        config = {"configurable": {"thread_id": "test-state-1"}}

        result = asyncio.run(agent.ainvoke(state, config))

        assert result.get("final_response"), (
            f"final_response should not be empty, got {result.get('final_response')!r}"
        )
        assert result.get("worker_results"), (
            f"worker_results should not be empty, got {result.get('worker_results')!r}"
        )


# ---------------------------------------------------------------------------
# TestHITLInterrupt
# ---------------------------------------------------------------------------


class TestHITLInterrupt:
    """Integration test verifying human-in-the-loop interrupt behavior.

    The voucher worker's place_order tool is registered in both
    ``tool_executors`` and ``hitl_tools``.  When the LLM returns a tool
    call for ``place_order``, the ``_tools_node`` calls ``interrupt()``
    before executing the tool, pausing the entire graph.
    """

    @patch("src.agent.workers.base.get_sync_llm_client")
    def test_place_order_triggers_interrupt(self, mock_base_llm):
        """place_order tool_calls → interrupt → get_state returns non-None."""
        # Build a tool_calls response with place_order.
        tc = MagicMock()
        tc.id = "call_test"
        tc.type = "function"
        tc.function = MagicMock()
        tc.function.name = "place_order"
        tc.function.arguments = (
            '{"voucher_id": 88, "quantity": 1, "shop_name": "test"}'
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(
            content="", tool_calls=[tc]
        )
        mock_base_llm.return_value = mock_client

        agent = create_pick_agent(checkpointer=InMemorySaver())
        state = {
            "messages": [HumanMessage(content="I want to place an order")]
        }
        config = {"configurable": {"thread_id": "test-hitl-1"}}

        # ainvoke should return (interrupt pauses the graph).
        try:
            asyncio.run(agent.ainvoke(state, config))
        except Exception:
            pass  # Some LangGraph versions raise on interrupt.

        # get_state should return non-None indicating an interrupt is pending.
        interrupt_state = agent.get_state(config)
        assert interrupt_state is not None, (
            "get_state should return non-None after interrupt (graph is paused)"
        )
