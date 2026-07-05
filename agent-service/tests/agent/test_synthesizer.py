"""Tests for the Synthesizer node — dedup_and_resolve and _concat_results.

These tests cover the pure functions only (no LLM or Neo4j mocking needed).
"""

import pytest

from src.agent.synthesizer import (
    _canonicalize,
    _is_contradict,
    _concat_results,
    dedup_and_resolve,
)


# ---------------------------------------------------------------------------
# TestCanonicalize
# ---------------------------------------------------------------------------


class TestCanonicalize:
    def test_sorted_keys_produce_deterministic_output(self):
        """Same content with different key order → same canonical string."""
        a = _canonicalize({"b": 1, "a": 2})
        b = _canonicalize({"a": 2, "b": 1})
        assert a == b

    def test_different_values_differ(self):
        """Different values produce different canonical strings."""
        a = _canonicalize({"cuisine": "hotpot"})
        b = _canonicalize({"cuisine": "sushi"})
        assert a != b

    def test_nested_dict_sorted(self):
        """Nested dict keys are also sorted."""
        a = _canonicalize({"outer": {"z": 3, "a": 1}})
        b = _canonicalize({"outer": {"a": 1, "z": 3}})
        assert a == b


# ---------------------------------------------------------------------------
# TestIsContradict
# ---------------------------------------------------------------------------


class TestIsContradict:
    def test_same_values_not_contradict(self):
        """Same new_value and existing value → not a contradiction."""
        assert not _is_contradict(
            {"new_value": {"cuisine": "hotpot"}},
            {"value": {"cuisine": "hotpot"}},
        )

    def test_different_values_contradict(self):
        """Different values for the same key → contradiction."""
        assert _is_contradict(
            {"new_value": {"cuisine": "hotpot"}},
            {"value": {"cuisine": "sushi"}},
        )

    def test_disjoint_keys_not_contradict(self):
        """No shared keys → not a contradiction."""
        assert not _is_contradict(
            {"new_value": {"cuisine": "hotpot"}},
            {"value": {"area": "chunxi"}},
        )

    def test_partial_overlap_only_contradicts_on_mismatch(self):
        """Only the keys that differ cause contradiction."""
        assert _is_contradict(
            {"new_value": {"cuisine": "hotpot", "spice": "mild"}},
            {"value": {"cuisine": "sushi", "spice": "mild"}},
        )

    def test_partial_overlap_no_mismatch(self):
        """Overlapping keys with same values → not a contradiction."""
        assert not _is_contradict(
            {"new_value": {"cuisine": "hotpot", "spice": "mild"}},
            {"value": {"cuisine": "hotpot"}},
        )

    def test_non_dict_values_are_safe(self):
        """Non-dict values don't crash."""
        assert not _is_contradict(
            {"new_value": "not_a_dict"},
            {"value": {"cuisine": "hotpot"}},
        )
        assert not _is_contradict(
            {"new_value": {"cuisine": "hotpot"}},
            {"value": "not_a_dict"},
        )


# ---------------------------------------------------------------------------
# TestDedupAndResolve
# ---------------------------------------------------------------------------


class TestDedupAndResolve:
    def test_duplicate_same_value_keeps_highest_confidence(self):
        """Two deltas with same (target_type, new_value) → keeps highest confidence."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "hotpot"},
                "evidence": "user likes hotpot",
                "confidence": 0.6,
                "source_worker": "worker_restaurant",
            },
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "hotpot"},
                "evidence": "user mentioned hotpot again",
                "confidence": 0.85,
                "source_worker": "worker_chat",
            },
        ]
        result = dedup_and_resolve(deltas, {})
        assert len(result) == 1
        assert result[0]["confidence"] == 0.85
        assert result[0]["source_worker"] == "worker_chat"

    def test_different_target_types_both_kept(self):
        """Deltas for different target types are both kept."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "hotpot"},
                "evidence": "likes hotpot",
                "confidence": 0.8,
                "source_worker": "worker_restaurant",
            },
            {
                "op": "ADD",
                "target_type": "BudgetPreference",
                "new_value": {"range_min": 50, "range_max": 100},
                "evidence": "budget mentioned",
                "confidence": 0.7,
                "source_worker": "worker_voucher",
            },
        ]
        result = dedup_and_resolve(deltas, {})
        assert len(result) == 2

    def test_contradict_dropped_when_confidence_too_low(self):
        """Contradiction with existing → dropped when confidence margin insufficient."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "sushi"},
                "evidence": "user said they like sushi now",
                "confidence": 0.8,
                "source_worker": "worker_restaurant",
            },
        ]
        existing = {
            "profile_1": {
                "id": "profile_1",
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.75,
            },
        }
        # new=0.8, existing=0.75 → margin=0.05 < 0.2 → dropped
        result = dedup_and_resolve(deltas, existing)
        assert len(result) == 0

    def test_contradict_accepted_when_confidence_high_enough(self):
        """Contradiction accepted when new_confidence > existing_confidence + 0.2."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "sushi"},
                "evidence": "user strongly prefers sushi now",
                "confidence": 0.9,
                "source_worker": "worker_restaurant",
            },
        ]
        existing = {
            "profile_1": {
                "id": "profile_1",
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.55,
            },
        }
        # new=0.90, existing=0.55 → margin=0.35 >= 0.2 → accepted as REVISE
        result = dedup_and_resolve(deltas, existing)
        assert len(result) == 1
        assert result[0]["op"] == "REVISE"
        assert result[0]["target_id"] == "profile_1"
        assert result[0]["confidence"] == 0.9

    def test_non_contradict_always_accepted(self):
        """A delta that does not contradict any existing profile is always kept."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "BudgetPreference",
                "new_value": {"range_min": 50, "range_max": 100},
                "evidence": "budget ~50-100",
                "confidence": 0.7,
                "source_worker": "worker_voucher",
            },
        ]
        existing = {
            "profile_1": {
                "id": "profile_1",
                "type_name": "CuisinePreference",
                "value": {"cuisine": "hotpot"},
                "confidence": 0.8,
            },
        }
        result = dedup_and_resolve(deltas, existing)
        assert len(result) == 1
        assert result[0]["op"] == "ADD"

    def test_empty_deltas_returns_empty(self):
        """Empty deltas list returns empty list."""
        assert dedup_and_resolve([], {}) == []

    def test_existing_profiles_empty_dict_is_safe(self):
        """Empty existing_profiles dict allows all deltas through."""
        deltas = [
            {
                "op": "ADD",
                "target_type": "CuisinePreference",
                "new_value": {"cuisine": "hotpot"},
                "evidence": "test",
                "confidence": 0.8,
                "source_worker": "worker_restaurant",
            },
        ]
        result = dedup_and_resolve(deltas, {})
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestConcatResults
# ---------------------------------------------------------------------------


class TestConcatResults:
    def test_concatenates_success_summaries(self):
        """Successful worker summaries are joined with double newlines."""
        worker_results = [
            {
                "worker_id": "worker_restaurant",
                "status": "success",
                "summary": "Found 3 hotpot restaurants near Chunxi Road.",
            },
            {
                "worker_id": "worker_voucher",
                "status": "success",
                "summary": "2 vouchers available for hotpot.",
            },
        ]
        result = _concat_results(worker_results)
        assert "Found 3 hotpot restaurants" in result
        assert "2 vouchers available" in result
        assert "\n\n" in result

    def test_all_failures_returns_apology(self):
        """When every worker failed, return a polite apology message."""
        worker_results = [
            {
                "worker_id": "worker_restaurant",
                "status": "failed",
                "summary": "",
                "error": {"message": "timeout"},
            },
            {
                "worker_id": "worker_voucher",
                "status": "failed",
                "summary": "",
                "error": {"message": "connection error"},
            },
        ]
        result = _concat_results(worker_results)
        assert "抱歉" in result
        assert "无法处理" in result

    def test_mixed_success_and_failure_only_concatenates_success(self):
        """Only successful summaries are included; failures are skipped."""
        worker_results = [
            {
                "worker_id": "worker_restaurant",
                "status": "success",
                "summary": "Shop results here.",
            },
            {
                "worker_id": "worker_voucher",
                "status": "failed",
                "summary": "",
                "error": {"message": "timeout"},
            },
        ]
        result = _concat_results(worker_results)
        assert "Shop results here" in result
        assert "timeout" not in result

    def test_empty_worker_results_returns_apology(self):
        """Empty worker_results returns the apology message."""
        result = _concat_results([])
        assert "抱歉" in result

    def test_success_without_summary_is_skipped(self):
        """A successful worker result without a summary is treated as empty."""
        worker_results = [
            {
                "worker_id": "worker_chat",
                "status": "success",
                "summary": "",
            },
        ]
        result = _concat_results(worker_results)
        assert "抱歉" in result
