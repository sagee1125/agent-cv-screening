# Exposes a reusable orchestration API for the pure candidate matching engine.
from __future__ import annotations

from datetime import date
from typing import Any

from .config_builder import build_matching_config
from .contracts import EffectiveConfig, SkillRelationResolver
from .engine import match_candidate
from .ranker import rank_candidates


class CandidateMatchingService:
    """Builds effective configs and evaluates candidates without persistence."""

    # Stores an optional taxonomy-backed related-skill resolver.
    def __init__(self, relation_resolver: SkillRelationResolver | None = None) -> None:
        self.relation_resolver = relation_resolver

    # Builds the immutable effective configuration used by a score version.
    def build_config(
        self,
        jd_structured_data: dict[str, Any],
        explicit_config: dict[str, Any] | None = None,
        legacy_weight_config: dict[str, Any] | None = None,
    ) -> EffectiveConfig:
        return build_matching_config(jd_structured_data, explicit_config, legacy_weight_config)

    # Evaluates one candidate using a prebuilt score-version configuration.
    def match(
        self,
        cv_structured_data: dict[str, Any],
        effective_config: EffectiveConfig,
        reference_date: date | str,
    ) -> dict[str, Any]:
        return match_candidate(
            cv_structured_data,
            effective_config,
            reference_date,
            relation_resolver=self.relation_resolver,
        )

    # Builds a configuration and evaluates one candidate in a convenience call.
    def build_and_match(
        self,
        cv_structured_data: dict[str, Any],
        jd_structured_data: dict[str, Any],
        reference_date: date | str,
        explicit_config: dict[str, Any] | None = None,
        legacy_weight_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_config = self.build_config(jd_structured_data, explicit_config, legacy_weight_config)
        return self.match(cv_structured_data, effective_config, reference_date)

    # Orders a complete score batch and assigns dense recommendation ranks.
    def rank(self, scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rank_candidates(scored_items)
