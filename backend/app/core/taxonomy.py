# Compatibility shim: skill taxonomy loader lives in screening_core.
from screening_core.taxonomy import SkillNode, SkillTaxonomyLoader

__all__ = ["SkillNode", "SkillTaxonomyLoader"]
