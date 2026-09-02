# Loads skill taxonomy YAML and resolves synonyms, parents, and related skills.
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Taxonomy category whose nodes are spoken languages, not job skills.
_LANGUAGE_CATEGORY = "languages"


# Frozen taxonomy node: canonical name, category, synonyms, and optional parent.
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
        self._skill_token_re: re.Pattern[str] = re.compile(r"(?!)")

    # Parses the YAML file into nodes, synonym indexes, and parent/child maps.
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

        self._skill_token_re = self._compile_skill_token_regex()

    # Indexes one synonym (or the canonical name) for case-insensitive lookup.
    def _index_synonym(self, value: str, canonical: str) -> None:
        key = value.casefold().strip()
        if key:
            self.synonym_to_skill[key] = canonical

    # Builds a longest-first token regex over canonical names and synonyms.
    def _compile_skill_token_regex(self) -> re.Pattern[str]:
        tokens = sorted((key for key in self.synonym_to_skill if key), key=len, reverse=True)
        if not tokens:
            return re.compile(r"(?!)")
        pattern = r"(?<![a-z0-9])(?:" + "|".join(re.escape(token) for token in tokens) + r")(?![a-z0-9])"
        return re.compile(pattern)

    # Returns unique non-language canonical skills found in free text.
    def skills_in_text(self, text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for match in self._skill_token_re.finditer((text or "").casefold()):
            token = match.group(0).casefold()
            # Very short tokens such as R, CV, ML, Go are too ambiguous in free text.
            if len(token) <= 2:
                continue
            canonical = self.synonym_to_skill.get(token)
            if not canonical or canonical in seen:
                continue
            node = self.nodes.get(canonical)
            if node and node.category.strip().casefold() == _LANGUAGE_CATEGORY:
                continue
            seen.add(canonical)
            found.append(canonical)
        return found

    # Maps a raw skill/synonym string to the canonical taxonomy skill name.
    def normalize_skill(self, skill_name: str) -> str | None:
        return self.synonym_to_skill.get(skill_name.casefold().strip())

    # Returns all parent skills walking up from the given node.
    def ancestors(self, skill_name: str) -> set[str]:
        ancestors: set[str] = set()
        current = self._node_for(skill_name)
        while current and current.parent:
            ancestors.add(current.parent)
            current = self._node_for(current.parent)
        return ancestors

    # Returns all child skills walking down from the given node.
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

    # True when two skills are the same node or in a parent/child relationship.
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
