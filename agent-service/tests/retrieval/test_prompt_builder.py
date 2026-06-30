from __future__ import annotations

import pytest
from src.retrieval.prompt_builder import PromptBuilder
from src.storage.models import (
    TastePreference,
    DietaryPreference,
    CuisinePreference,
    BudgetPreference,
)


@pytest.fixture
def builder():
    return PromptBuilder()


def test_build_profiles_section(builder):
    """Profile atoms should be formatted into a readable section."""
    profiles = [
        TastePreference(
            user_id="u1", property="spicy", value="avoid",
            confidence=0.9, reinforce_count=5,
        ),
        DietaryPreference(
            user_id="u1", constraint="清真", type="religious", confidence=1.0,
        ),
        BudgetPreference(
            user_id="u1", range_min=50, range_max=100, confidence=0.7,
        ),
        CuisinePreference(
            user_id="u1", cuisine="川渝火锅", confidence=0.85, weight=0.9,
        ),
    ]
    section = builder.build_profiles_section(profiles)
    # TastePreference(value="avoid") renders as "避免"
    assert "避免" in section
    assert "清真" in section
    assert "50-100" in section
    assert "川渝火锅" in section


def test_build_hard_constraints_section(builder):
    """Hard constraints should be clearly marked."""
    hard = [
        DietaryPreference(
            user_id="u1", constraint="清真", type="religious",
        ),
    ]
    section = builder.build_hard_constraints_section(hard)
    assert "硬约束" in section or "必须遵守" in section
    assert "清真" in section


def test_build_memories_section(builder):
    """Fused memory results should be summarized."""
    memories = [
        {
            "id": "evt_1",
            "final_score": 0.85,
            "description": "在春熙路搜索火锅",
        },
        {
            "id": "sess_1",
            "final_score": 0.72,
            "description": "之前在春熙路搜索火锅和粤菜",
        },
    ]
    section = builder.build_memories_section(memories)
    assert "春熙路" in section
    assert "火锅" in section


def test_build_full_system_context(builder):
    """Full system context should include all sections."""
    context = builder.build(
        profiles=[
            TastePreference(
                user_id="u1", property="spicy", value="avoid", confidence=0.9,
            ),
        ],
        hard_constraints=[
            DietaryPreference(
                user_id="u1", constraint="清真", type="religious",
            ),
        ],
        memories=[
            {"id": "evt_1", "final_score": 0.85, "description": "搜索火锅"},
        ],
    )
    assert "## 用户记忆" in context
    assert "### 偏好" in context
    assert "### 近期行为" in context
    # Agent cases section should not appear when empty
    assert "Agent 经验" not in context


def test_empty_context_is_graceful(builder):
    """Empty inputs should produce a minimal placeholder."""
    context = builder.build([], [], [])
    assert "暂无" in context or "记忆" in context
