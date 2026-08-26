# Compatibility shim: SkillMatcherService lives in the scorer skill.
from scorer.skill_matcher import ROLE_SCORES, SCALE_SCORES, SkillMatcherService

__all__ = ["ROLE_SCORES", "SCALE_SCORES", "SkillMatcherService"]
