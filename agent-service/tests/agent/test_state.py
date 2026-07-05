"""Tests for agent state schemas and reducers."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.state import (
    add_messages, merge_lists, PickAgentState, WorkerState,
    SubTask, WorkerResult, CandidateDelta,
)


class TestMergeListsReducer:
    def test_merge_two_non_empty_lists(self):
        assert merge_lists([1, 2], [3, 4]) == [1, 2, 3, 4]

    def test_merge_left_empty(self):
        assert merge_lists([], [3, 4]) == [3, 4]

    def test_merge_right_empty(self):
        assert merge_lists([1, 2], []) == [1, 2]

    def test_merge_left_none(self):
        assert merge_lists(None, [3, 4]) == [3, 4]

    def test_merge_both_empty(self):
        assert merge_lists([], []) == []


class TestAddMessagesReducer:
    def test_concat_no_ids(self):
        """Items without id attribute just get appended."""
        result = add_messages(
            [HumanMessage(content="hello")],
            [AIMessage(content="hi")]
        )
        assert len(result) == 2
        assert result[0].content == "hello"
        assert result[1].content == "hi"

    def test_dedup_by_id_replaces(self):
        """Same id replaces existing message."""
        m1 = HumanMessage(content="old", id="1")
        m2 = HumanMessage(content="new", id="1")
        result = add_messages([m1], [m2])
        assert len(result) == 1
        assert result[0].content == "new"
        assert result[0].id == "1"
        assert result[0] is m2  # the new message replaces the old

    def test_left_none_right_non_empty(self):
        """Both left and right must be non-null for add_messages;
        use merge_lists for bare list merging."""
        # LangGraph's add_messages requires both left and right to be non-null.
        # For cases where one side may be None, pre-coalesce with an empty list.
        left = None
        right = [HumanMessage(content="hello")]
        result = add_messages(left or [], right or [])
        assert len(result) == 1
        assert result[0].content == "hello"

    def test_mixed_items_with_and_without_ids(self):
        """Mixed items (with and without explicit id) work correctly.
        Messages without explicit id get a UUID assigned."""
        m1 = HumanMessage(content="first")  # id auto-assigned by add_messages
        m2 = AIMessage(content="second", id="abc")
        result = add_messages([m1], [m2])
        assert len(result) == 2
        assert result[0].content == "first"
        assert result[1].content == "second"
        assert result[1].id == "abc"

    def test_none_id_skips_dedup(self):
        """Messages with id=None get a UUID assigned before merging,
        so two messages with id=None are both kept (they get distinct UUIDs)."""
        m1 = HumanMessage(content="no-id-1")
        m2 = AIMessage(content="no-id-2")
        result = add_messages([m1], [m2])
        assert len(result) == 2
        assert result[0].content == "no-id-1"
        assert result[1].content == "no-id-2"


class TestStateTypes:
    def test_sub_task_minimal(self):
        st = SubTask(worker_id="worker_restaurant", task="find hotpot near Chunxi Road", priority=1)
        assert st["worker_id"] == "worker_restaurant"
        assert st["task"] == "find hotpot near Chunxi Road"

    def test_worker_result_success(self):
        wr = WorkerResult(worker_id="worker_restaurant", status="success",
                          summary="Found 3 hotpot restaurants",
                          artifacts=[{"shop_id": 1, "name": "Shu Daxia"}], error=None)
        assert wr["status"] == "success"
        assert len(wr["artifacts"]) == 1

    def test_candidate_delta_add(self):
        cd = CandidateDelta(op="ADD", target_type="CuisinePreference",
                            new_value={"cuisine": "hotpot"},
                            evidence="user said 'I love Chongqing hotpot'",
                            confidence=0.85, source_worker="worker_restaurant")
        assert cd["op"] == "ADD"
        assert cd["confidence"] == 0.85

    def test_worker_state_construction(self):
        ws = WorkerState(
            worker_task={"task": "search shops", "priority": 1},
            memory_context="User prefers Sichuan cuisine",
            messages=[],
            tool_rounds=0,
            worker_result={},
            candidate_deltas=[],
        )
        assert ws["worker_task"]["task"] == "search shops"
        assert ws["memory_context"] == "User prefers Sichuan cuisine"
        assert ws["tool_rounds"] == 0
