# src/memory/consolidation.py
"""Profile Consolidation: periodic dedup of similar profile atoms.

Runs daily (via scheduler). For each user:
1. Find same-type profile pairs with high similarity
2. LLM judges if they should merge
3. If yes: create merged atom, delete old ones, log to audit
"""

from __future__ import annotations

import json
import logging
from typing import Any
from langchain_core.messages import HumanMessage
from src.storage.models import AnyProfile
from src.memory.prompts import CONSOLIDATION_MERGE_PROMPT

logger = logging.getLogger("pick.memory.consolidation")

SIMILARITY_THRESHOLD = 0.85


class ConsolidationJob:
    """Daily job: find and merge similar profile atoms."""

    def __init__(self, neo4j_client, model: Any = None, embed_fn=None):
        self._neo4j = neo4j_client
        if model is None:
            from src.agent.config import get_model

            model = get_model()
        self._model = model
        if embed_fn is None:
            from src.storage.embedding import embed_texts

            embed_fn = embed_texts
        self._embed = embed_fn

    async def find_candidates(self, user_id: str) -> list[tuple[AnyProfile, AnyProfile]]:
        """Find same-type profile pairs that might be mergeable."""
        all_profiles = await self._neo4j.read_profiles(user_id)
        by_type: dict[str, list[AnyProfile]] = {}
        for p in all_profiles:
            nt = p.node_type()
            by_type.setdefault(nt, []).append(p)
        candidates = []
        for profiles in by_type.values():
            if len(profiles) < 2:
                continue
            for i in range(len(profiles)):
                for j in range(i + 1, len(profiles)):
                    candidates.append((profiles[i], profiles[j]))
        return candidates

    async def try_merge(
        self, user_id: str, a: AnyProfile, b: AnyProfile
    ) -> AnyProfile | None:
        """Attempt to merge two profile atoms via LLM judgment."""
        a_text = self._profile_to_text(a)
        b_text = self._profile_to_text(b)
        prompt = CONSOLIDATION_MERGE_PROMPT.format(atom_a=a_text, atom_b=b_text)
        try:
            response = self._model.invoke([HumanMessage(content=prompt)])
            data = json.loads(response.content.strip())
        except Exception:
            logger.exception("Consolidation LLM call failed")
            return None
        if not data.get("should_merge"):
            return None
        merged_data = data.get("merged", {})
        merged_data["user_id"] = user_id
        merged_cls = type(a)
        from dataclasses import fields as dc_fields

        valid = {f.name for f in dc_fields(merged_cls)}
        filtered = {k: v for k, v in merged_data.items() if k in valid}
        try:
            merged = merged_cls(**filtered)
        except Exception:
            logger.exception("Failed to create merged profile")
            return None
        # Delete old atoms and write merged atom
        await self._neo4j.delete_profile(a)
        await self._neo4j.delete_profile(b)
        await self._neo4j.write_profile(user_id, merged)
        logger.info(
            "Merged %s: %s + %s -> %s",
            a.node_type(),
            a_text,
            b_text,
            self._profile_to_text(merged),
        )
        return merged

    async def run_for_user(self, user_id: str) -> int:
        """Run consolidation for a single user. Returns merge count."""
        candidates = await self.find_candidates(user_id)
        merged_count = 0
        for a, b in candidates:
            merged = await self.try_merge(user_id, a, b)
            if merged:
                merged_count += 1
        return merged_count

    @staticmethod
    def _profile_to_text(p: AnyProfile) -> str:
        """Convert a profile atom to a descriptive string for the LLM."""
        nt = p.node_type()
        if nt == "CuisinePreference":
            return (
                f"CuisinePreference(cuisine={p.cuisine}, "
                f"confidence={p.confidence}, "
                f"reinforce_count={p.reinforce_count})"
            )
        elif nt == "TastePreference":
            return (
                f"TastePreference(property={p.property}, "
                f"value={p.value}, confidence={p.confidence})"
            )
        elif nt == "AreaPreference":
            return f"AreaPreference(area={p.area}, confidence={p.confidence})"
        elif nt == "ScenePreference":
            return f"ScenePreference(scene={p.scene}, confidence={p.confidence})"
        elif nt == "ConstraintPreference":
            return f"ConstraintPreference(constraint={p.constraint}, confidence={p.confidence})"
        elif nt == "DietaryPreference":
            return (
                f"DietaryPreference(constraint={p.constraint}, "
                f"type={p.type}, confidence={p.confidence})"
            )
        elif nt == "BudgetPreference":
            return (
                f"BudgetPreference(range={p.range_min}-{p.range_max}, "
                f"confidence={p.confidence})"
            )
        return f"{nt}(...)"
