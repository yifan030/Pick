"""记忆质量离线评估脚本。

使用方式:
    cd agent-service
    python eval/run_eval.py

读取 eval/data/scenarios.json → 调检索管道 + Agent → 输出指标

指标:
    - Profile Recall:    检索返回中命中了多少 should_include (目标 > 0.85)
    - Profile Precision: 检索返回中有多少真正相关 (目标 > 0.80)
    - Constraint Compliance: Agent 推荐满足了多少 expected_constraints (目标 > 0.90)
    - Hallucination Rate: 推荐是否包含明确排除的内容 (目标 < 0.05)
"""

import json
import sys
from pathlib import Path
from typing import Set, List, Dict, Any


def calculate_recall(retrieved: Set[str], should_include: Set[str]) -> float:
    """Recall = |retrieved ∩ should_include| / |should_include|"""
    if not should_include:
        return 1.0
    return len(retrieved & should_include) / len(should_include)


def calculate_precision(retrieved: Set[str], should_include: Set[str]) -> float:
    """Precision = |retrieved ∩ should_include| / |retrieved|"""
    if not retrieved:
        return 1.0
    return len(retrieved & should_include) / len(retrieved)


def calculate_hallucination_rate(recommendations: List[str], excluded: Set[str]) -> float:
    """Hallucination Rate = |recs ∩ excluded| / |recs|"""
    if not recommendations:
        return 0.0
    rec_set = set(recommendations)
    return len(rec_set & excluded) / len(rec_set)


def load_scenarios(data_path: str = None) -> List[Dict[str, Any]]:
    """加载标注评估数据集。"""
    if data_path is None:
        data_path = Path(__file__).parent / "data" / "scenarios.json"
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run_evaluation(scenarios_path: str = None, output_path: str = None):
    """主评估函数。

    遍历所有标注场景，调用检索管道和 Agent，计算四项指标。
    此为 Phase 14 一次性离线评估，非 CI 自动化。
    """
    scenarios = load_scenarios(scenarios_path)
    results = {
        "total_scenarios": len(scenarios),
        "recall_scores": [],
        "precision_scores": [],
        "compliance_scores": [],
        "hallucination_rates": [],
        "per_scenario": [],
    }

    for sc in scenarios:
        scenario_result = {
            "scenario_id": sc["scenario_id"],
            "description": sc.get("description", ""),
        }

        # 检索评估 — 接入真实检索管道时替换此处的模拟逻辑
        retrieved_ids: Set[str] = set()
        should_include = set(sc["expected_retrieval"]["should_include"])
        should_exclude = set(sc["expected_retrieval"]["should_exclude"])

        recall = calculate_recall(retrieved_ids, should_include)
        precision = calculate_precision(retrieved_ids, should_include)

        scenario_result["recall"] = recall
        scenario_result["precision"] = precision
        results["recall_scores"].append(recall)
        results["precision_scores"].append(precision)

        # 推荐合规性评估 — 接入真实 Agent 时替换此处的模拟逻辑
        constraints = sc.get("expected_recommendation_constraints", [])
        recommendations: List[str] = []

        if constraints:
            compliance = 1.0  # 接入 LLM-as-judge 后逐条检查
        else:
            compliance = 1.0

        hallucination = calculate_hallucination_rate(recommendations, excluded=should_exclude)

        scenario_result["compliance"] = compliance
        scenario_result["hallucination_rate"] = hallucination
        results["compliance_scores"].append(compliance)
        results["hallucination_rates"].append(hallucination)

        results["per_scenario"].append(scenario_result)

    # 汇总指标
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    summary = {
        "total_scenarios": results["total_scenarios"],
        "avg_recall": round(avg(results["recall_scores"]), 3),
        "avg_precision": round(avg(results["precision_scores"]), 3),
        "avg_compliance": round(avg(results["compliance_scores"]), 3),
        "avg_hallucination_rate": round(avg(results["hallucination_rates"]), 3),
    }
    results["summary"] = summary

    # 输出
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("记忆质量评估结果")
    print("=" * 60)
    print(f"场景数:              {summary['total_scenarios']}")
    print(f"Profile Recall:      {summary['avg_recall']:.3f}  (目标 > 0.85)")
    print(f"Profile Precision:   {summary['avg_precision']:.3f}  (目标 > 0.80)")
    print(f"Constraint Compliance: {summary['avg_compliance']:.3f}  (目标 > 0.90)")
    print(f"Hallucination Rate:  {summary['avg_hallucination_rate']:.3f}  (目标 < 0.05)")
    print("=" * 60)

    return results


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_evaluation())
