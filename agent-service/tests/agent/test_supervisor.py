"""Tests for the Supervisor node, routing, and memory trim helpers."""
import pytest
from langgraph.types import Send

from src.agent.supervisor import (
    HARD_CONSTRAINT_TYPES,
    WORKER_MEMORY_FIELDS,
    WORKER_NODE_MAP,
    _classify_complexity,
    _rule_based_routing,
    route_to_workers,
    trim_memory_for_worker,
)


# ---------------------------------------------------------------------------
# TestRuleBasedRouting
# ---------------------------------------------------------------------------


class TestRuleBasedRouting:
    def test_routes_purchase_keywords(self):
        """Purchase-like keywords route to worker_voucher."""
        result = _rule_based_routing("I want to buy a voucher")
        assert len(result) == 1
        assert result[0]["worker_id"] == "worker_voucher"

    def test_routes_recommend_keywords(self):
        """Recommend/find/search/hotpot keywords route to worker_restaurant."""
        result = _rule_based_routing("recommend hotpot nearby")
        assert len(result) == 1
        assert result[0]["worker_id"] == "worker_restaurant"

    def test_routes_chat_default(self):
        """Unknown / conversational queries fall back to worker_chat."""
        result = _rule_based_routing("hello there")
        assert len(result) == 1
        assert result[0]["worker_id"] == "worker_chat"


# ---------------------------------------------------------------------------
# TestComplexityClassification
# ---------------------------------------------------------------------------


class TestComplexityClassification:
    def test_single_intent_is_simple(self):
        """A query with only recommend signals is simple."""
        assert _classify_complexity("recommend hotpot in Chunxi Road") == "simple"

    def test_multi_intent_is_complex(self):
        """A query with both recommend and purchase signals is complex."""
        assert (
            _classify_complexity("recommend hotpot and check vouchers") == "complex"
        )

    def test_purchase_only_is_simple(self):
        """A pure purchase query without recommend signals is simple."""
        assert _classify_complexity("I want to buy a voucher") == "simple"

    def test_chat_greeting_is_simple(self):
        """A simple greeting has no signals and is simple."""
        assert _classify_complexity("hello") == "simple"


# ---------------------------------------------------------------------------
# TestMemoryTrim
# ---------------------------------------------------------------------------


class TestMemoryTrim:
    def test_restaurant_worker_gets_cuisine_and_hard_constraints(self):
        """Restaurant worker receives CuisinePreference (soft) + hard constraints."""
        profiles = [
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.9,
            },
            {
                "type_name": "DietaryPreference",
                "value": {"diet": "halal"},
                "confidence": 1.0,
            },
        ]
        result = trim_memory_for_worker(profiles, "worker_restaurant")
        assert "hotpot" in result
        assert "halal" in result

    def test_voucher_worker_excludes_cuisine(self):
        """Voucher worker excludes CuisinePreference (not in its field list)."""
        profiles = [
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.9,
            },
            {
                "type_name": "BudgetPreference",
                "value": {"budget": "50-100"},
                "confidence": 0.8,
            },
        ]
        result = trim_memory_for_worker(profiles, "worker_voucher")
        assert "hotpot" not in result
        assert "50-100" in result

    def test_hard_constraints_always_in_all_workers(self):
        """Hard constraints are always included regardless of worker."""
        profiles = [
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.9,
            },
            {
                "type_name": "DietaryPreference",
                "value": {"diet": "halal"},
                "confidence": 1.0,
            },
            {
                "type_name": "ConstraintPreference",
                "value": {"constraint": "no alcohol"},
                "confidence": 1.0,
            },
        ]
        # Voucher worker should get hard constraints even though Cuisine is excluded.
        result = trim_memory_for_worker(profiles, "worker_voucher")
        assert "hotpot" not in result   # soft constraint excluded for voucher
        assert "halal" in result        # hard constraint always included
        assert "no alcohol" in result   # hard constraint always included

    def test_empty_profiles_returns_empty_string(self):
        """Empty profile list returns an empty string."""
        result = trim_memory_for_worker([], "worker_restaurant")
        assert result == ""

    def test_unknown_worker_defaults_to_empty_soft_fields(self):
        """An unknown worker gets only hard constraints."""
        profiles = [
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.9,
            },
            {
                "type_name": "DietaryPreference",
                "value": {"diet": "halal"},
                "confidence": 1.0,
            },
        ]
        result = trim_memory_for_worker(profiles, "unknown_worker")
        # Hard constraint included, soft excluded (no matching field list).
        assert "halal" in result
        assert "hotpot" not in result

    def test_chat_worker_gets_all_profiles(self):
        """Chat worker with __ALL__ gets every profile."""
        profiles = [
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.9,
            },
            {
                "type_name": "BudgetPreference",
                "value": {"budget": "50-100"},
                "confidence": 0.8,
            },
            {
                "type_name": "DietaryPreference",
                "value": {"diet": "halal"},
                "confidence": 1.0,
            },
        ]
        result = trim_memory_for_worker(profiles, "worker_chat")
        # All three should appear (Dietary as hard, the rest via __ALL__).
        assert "hotpot" in result
        assert "50-100" in result
        assert "halal" in result

    def test_output_includes_hard_and_pref_prefixes(self):
        """Verify the formatted output uses [HARD] and [PREF] prefixes."""
        profiles = [
            {
                "type_name": "DietaryPreference",
                "value": {"diet": "vegan"},
                "confidence": 1.0,
            },
            {
                "type_name": "CuisinePreference",
                "value": {"cuisine": "sushi"},
                "confidence": 0.7,
            },
        ]
        result = trim_memory_for_worker(profiles, "worker_restaurant")
        assert "[HARD]" in result
        assert "[PREF]" in result


# ---------------------------------------------------------------------------
# TestRouteToWorkers
# ---------------------------------------------------------------------------


class TestRouteToWorkers:
    def test_parallel_routing_returns_multiple_sends(self):
        """Parallel strategy dispatches one Send per subtask."""
        state = {
            "sub_tasks": [
                {
                    "worker_id": "worker_restaurant",
                    "task": "find hotpot",
                    "priority": 1,
                    "memory_ctx": "",
                },
                {
                    "worker_id": "worker_voucher",
                    "task": "check vouchers",
                    "priority": 2,
                    "memory_ctx": "",
                },
            ],
            "strategy": "parallel",
        }
        sends = route_to_workers(state)
        assert len(sends) == 2
        assert all(isinstance(s, Send) for s in sends)
        assert sends[0].node == "worker_restaurant"
        assert sends[1].node == "worker_voucher"

    def test_sequential_routing_returns_one_send(self):
        """Sequential strategy dispatches only the current_step subtask."""
        state = {
            "sub_tasks": [
                {
                    "worker_id": "worker_restaurant",
                    "task": "step 1",
                    "priority": 1,
                    "memory_ctx": "",
                },
                {
                    "worker_id": "worker_voucher",
                    "task": "step 2",
                    "priority": 2,
                    "memory_ctx": "",
                },
            ],
            "strategy": "sequential",
            "current_step": 0,
        }
        sends = route_to_workers(state)
        assert len(sends) == 1
        assert sends[0].node == "worker_restaurant"
        assert isinstance(sends[0], Send)

    def test_empty_sub_tasks_falls_back_to_chat(self):
        """Empty sub_tasks list triggers a fallback Send to worker_chat."""
        sends = route_to_workers({"sub_tasks": [], "strategy": "parallel"})
        assert len(sends) == 1
        assert sends[0].node == "worker_chat"
        assert isinstance(sends[0], Send)

    def test_sequential_past_end_returns_empty(self):
        """When current_step is beyond the sub_tasks list, return empty."""
        state = {
            "sub_tasks": [
                {
                    "worker_id": "worker_restaurant",
                    "task": "only step",
                    "priority": 1,
                    "memory_ctx": "",
                },
            ],
            "strategy": "sequential",
            "current_step": 5,
        }
        sends = route_to_workers(state)
        assert sends == []

    def test_unknown_worker_id_falls_back_to_chat(self):
        """A subtask with an unrecognised worker_id maps to worker_chat."""
        state = {
            "sub_tasks": [
                {
                    "worker_id": "worker_nonexistent",
                    "task": "do something unknown",
                    "priority": 1,
                    "memory_ctx": "",
                },
            ],
            "strategy": "parallel",
        }
        sends = route_to_workers(state)
        assert len(sends) == 1
        assert sends[0].node == "worker_chat"


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_worker_node_map_has_expected_entries(self):
        assert "worker_restaurant" in WORKER_NODE_MAP
        assert "worker_voucher" in WORKER_NODE_MAP
        assert "worker_chat" in WORKER_NODE_MAP
        assert len(WORKER_NODE_MAP) == 3

    def test_hard_constraint_types_are_expected(self):
        assert "DietaryPreference" in HARD_CONSTRAINT_TYPES
        assert "ConstraintPreference" in HARD_CONSTRAINT_TYPES

    def test_worker_memory_fields_coverage(self):
        """Every worker in WORKER_NODE_MAP has a corresponding memory field entry."""
        for worker_id in WORKER_NODE_MAP:
            assert worker_id in WORKER_MEMORY_FIELDS, (
                f"Missing memory fields for {worker_id}"
            )
