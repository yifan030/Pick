import json
import pytest
from pathlib import Path


class TestEvalScenarios:
    @pytest.fixture
    def scenarios(self):
        data_path = Path(__file__).parent.parent.parent / "eval" / "data" / "scenarios.json"
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_scenarios_have_required_fields(self, scenarios):
        for s in scenarios:
            assert "scenario_id" in s
            assert "user_query" in s
            assert "expected_retrieval" in s
            assert "should_include" in s["expected_retrieval"]
            assert "should_exclude" in s["expected_retrieval"]

    def test_at_least_3_scenarios(self, scenarios):
        assert len(scenarios) >= 3


class TestEvalMetrics:
    def test_recall_calculation(self):
        from eval.run_eval import calculate_recall
        retrieved = {"a", "b", "c"}
        should_include = {"a", "b", "d"}
        recall = calculate_recall(retrieved, should_include)
        assert recall == 2 / 3

    def test_precision_calculation(self):
        from eval.run_eval import calculate_precision
        retrieved = {"a", "b", "c"}
        should_include = {"a", "b"}
        precision = calculate_precision(retrieved, should_include)
        assert precision == 2 / 3

    def test_hallucination_rate(self):
        from eval.run_eval import calculate_hallucination_rate
        recommendations = ["蜀大侠火锅", "小龙坎火锅"]
        excluded = {"蜀大侠火锅"}
        rate = calculate_hallucination_rate(recommendations, excluded)
        assert rate == 1 / 2
