from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillNode:
    skill: str
    category: str
    synonyms: list[str]
    parent: str | None


class SkillTaxonomyLoader:
    """Loads and normalizes taxonomy skills from YAML."""

    def __init__(self, yaml_path: str) -> None:
        self.yaml_path = Path(yaml_path)
        self.nodes: dict[str, SkillNode] = {}
        self.synonym_to_skill: dict[str, str] = {}
        self.children_map: dict[str, set[str]] = {}
        self._nodes_by_lower: dict[str, SkillNode] = {}

    def load(self) -> None:
        payload = yaml.safe_load(self.yaml_path.read_text(encoding="utf-8")) or []
        self.nodes.clear()
        self.synonym_to_skill.clear()
        self.children_map.clear()
        self._nodes_by_lower.clear()

        for item in payload:
            skill_name = str(item["skill"]).strip()
            node = SkillNode(
                skill=skill_name,
                category=str(item.get("category", "")).strip(),
                synonyms=[str(s).strip() for s in item.get("synonyms", [])],
                parent=item.get("parent"),
            )
            self.nodes[skill_name] = node
            self._nodes_by_lower[skill_name.casefold()] = node
            self._index_synonym(skill_name, skill_name)
            for synonym in node.synonyms:
                self._index_synonym(synonym, skill_name)

            if node.parent:
                self.children_map.setdefault(node.parent, set()).add(skill_name)

    def _index_synonym(self, value: str, canonical: str) -> None:
        key = value.casefold().strip()
        if key:
            self.synonym_to_skill[key] = canonical

    def normalize_skill(self, skill_name: str) -> str | None:
        return self.synonym_to_skill.get(skill_name.casefold().strip())

    def ancestors(self, skill_name: str) -> set[str]:
        ancestors: set[str] = set()
        current = self._node_for(skill_name)
        while current and current.parent:
            ancestors.add(current.parent)
            current = self._node_for(current.parent)
        return ancestors

    def descendants(self, skill_name: str) -> set[str]:
        collected: set[str] = set()
        node = self._node_for(skill_name)
        if not node:
            return collected
        pending = list(self.children_map.get(node.skill, set()))
        while pending:
            child = pending.pop()
            if child in collected:
                continue
            collected.add(child)
            pending.extend(self.children_map.get(child, set()))
        return collected

    def related(self, left: str, right: str) -> bool:
        if left == right:
            return True
        return right in self.ancestors(left) or right in self.descendants(left)

    # Case-insensitive node lookup so lowercased canonical ids still resolve.
    def _node_for(self, skill_name: str) -> SkillNode | None:
        if not skill_name:
            return None
        key = skill_name.casefold()
        return self._nodes_by_lower.get(key)
