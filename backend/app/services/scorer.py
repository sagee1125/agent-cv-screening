# Compatibility shim: ScorerService lives in the scorer skill.
from scorer.service import ScorerService

__all__ = ["ScorerService"]
