from __future__ import annotations

"""System Prompt Builder: augments the agent's system prompt with memories.

Injects retrieved memories into the system prompt in a structured format:
- ## 用户记忆 section with subsections for profiles, events, sessions, agent cases
- Hard constraints always included
- Memories sorted by relevance (final_score)
"""

import logging
from src.storage.models import AnyProfile, DietaryPreference

logger = logging.getLogger("pick.retrieval.prompt_builder")


class PromptBuilder:
    """Builds the memory-augmented section of the system prompt."""

    def build(
        self,
        profiles: list[AnyProfile],
        hard_constraints: list[AnyProfile],
        memories: list[dict],
        agent_cases: list[dict] | None = None,
    ) -> str:
        """Build the full memory context string.

        Args:
            profiles: All active (confidence >= 0.3, not expired) profile atoms.
            hard_constraints: Hard constraint atoms (is_hard=true).
            memories: Fused memory results from RetrievalGateway.
            agent_cases: Optional agent case results.

        Returns:
            A markdown-formatted string for injection into the system prompt.
        """
        sections = []

        # -- 1. Profiles section -------------------------------------------
        profiles_text = self.build_profiles_section(profiles)
        if profiles_text:
            sections.append(profiles_text)

        # -- 2. Hard constraints section -----------------------------------
        hard_text = self.build_hard_constraints_section(hard_constraints)
        if hard_text:
            sections.append(hard_text)

        # -- 3. Recent events / behavior -----------------------------------
        events_text = self.build_memories_section(memories)
        if events_text:
            sections.append(events_text)

        # -- 4. Agent cases (internal, not shown to user in prompt) --------
        if agent_cases:
            cases_text = self.build_agent_cases_section(agent_cases)
            if cases_text:
                sections.append(cases_text)

        if not sections:
            return "## 用户记忆\n\n暂无该用户的记忆数据。\n"

        return "## 用户记忆\n\n" + "\n\n".join(sections)

    def build_profiles_section(self, profiles: list[AnyProfile]) -> str:
        """Build the preferences section."""
        if not profiles:
            return ""

        lines = ["### 偏好"]
        for p in profiles:
            nt = p.node_type()
            if nt == "TastePreference":
                emoji = "✅" if p.value == "like" else "❌"
                lines.append(
                    f"- {emoji} [口味] {p.property}:"
                    f"{'喜欢' if p.value == 'like' else '避免'} "
                    f"(置信度:{p.confidence:.1f}, 提及{p.reinforce_count}次)"
                )
            elif nt == "DietaryPreference":
                lines.append(
                    f"- 🔒 [饮食约束] {p.constraint} "
                    f"(硬约束, 类型:{p.type}, 置信度:{p.confidence:.1f})"
                )
            elif nt == "BudgetPreference":
                lines.append(
                    f"- 💰 [预算] 人均{p.range_min}-{p.range_max}元 "
                    f"(置信度:{p.confidence:.1f})"
                )
            elif nt == "CuisinePreference":
                lines.append(
                    f"- 🍳 [菜系] {p.cuisine} "
                    f"(权重:{p.weight:.1f}, 置信度:{p.confidence:.1f})"
                )
            elif nt == "AreaPreference":
                lines.append(
                    f"- 📍 [商圈] {p.area} "
                    f"(权重:{p.weight:.1f}, 置信度:{p.confidence:.1f})"
                )
            elif nt == "ScenePreference":
                lines.append(
                    f"- 🎯 [场景] {p.scene} "
                    f"(权重:{p.weight:.1f}, 置信度:{p.confidence:.1f})"
                )
            elif nt == "ConstraintPreference":
                lines.append(
                    f"- ⚠️ [约束] {p.constraint} "
                    f"(置信度:{p.confidence:.1f})"
                )
        return "\n".join(lines)

    def build_hard_constraints_section(
        self, hard_constraints: list[AnyProfile]
    ) -> str:
        """Build the hard constraints section. Always injected."""
        if not hard_constraints:
            return ""

        lines = ["### 🔒 硬约束（必须遵守）"]
        for p in hard_constraints:
            if isinstance(p, DietaryPreference):
                lines.append(f"- 饮食: {p.constraint}（{p.type}）")
            else:
                nt = p.node_type()
                if nt == "TastePreference":
                    lines.append(
                        f"- 口味: "
                        f"{'避免' if p.value == 'avoid' else '偏好'}{p.property}"
                    )
                elif nt == "ConstraintPreference":
                    lines.append(f"- 约束: {p.constraint}")
        return "\n".join(lines)

    def build_memories_section(self, memories: list[dict]) -> str:
        """Build the recent behavior section from fused memory results."""
        if not memories:
            return ""

        lines = ["### 近期行为"]
        # Show top 5 memories
        for m in memories[:5]:
            desc = m.get("description", "")
            if desc:
                score = m.get("final_score", 0)
                lines.append(f"- {desc} (相关度:{score:.2f})")
        return "\n".join(lines)

    def build_agent_cases_section(self, agent_cases: list[dict]) -> str:
        """Build the agent cases section (internal patterns).

        This section is for agent reasoning, not shown to users.
        """
        if not agent_cases:
            return ""

        lines = ["### Agent 经验（内部参考）"]
        for c in agent_cases[:3]:
            entity = c.get("entity", c)
            lesson = entity.get("lesson", "") or entity.get("description", "")
            outcome = entity.get("outcome", "")
            outcome_emoji = {
                "success": "✅",
                "partial": "⚠️",
                "failure": "❌",
            }.get(outcome, "")
            if lesson:
                lines.append(f"- {outcome_emoji} {lesson}")
        return "\n".join(lines)
