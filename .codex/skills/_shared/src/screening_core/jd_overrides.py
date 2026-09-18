# Merge HR-supplied job conditions (collected in conversation) onto the parsed JD.
"""Deterministic merge of the JD-grill output onto a parsed JD.

The JD grill collects corrections and additions from HR in the conversation. Those
conditions are written to `_pipeline/jd-overrides.yaml`. This module folds them onto
`jd-parse.json` and produces `jd-final.json`, which is what every downstream consumer
(sorer, report-gen) should read.

The merge is deterministic on purpose. Re-parsing a JD that HR has edited would make
must-have / nice-to-have assignment probabilistic again, and that assignment is both
the field HR edits most and the least stable output of the parser.

A multi-post advertisement adds a second thing the grill must settle: the derivation that
attributed each requirement bullet to a post. That derivation decides what each post is
scored against, so HR confirms it before any score is produced (FR-9). The confirmation is
recorded in the same file under `posts`, one entry per base name, and carries the delta HR
actually saw. A delta that no longer matches its recorded copy is unconfirmed again, because
an answer about different text is not an answer about this one.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from screening_core.paths import taxonomy_yaml_path
from screening_core.posts import base_name
from screening_core.taxonomy import SkillTaxonomyLoader

# HR conditions file written by the conversation grill inside the output directory.
OVERRIDES_FILENAME = "jd-overrides.yaml"
# Merged JD every downstream consumer should score and report against.
FINAL_JD_FILENAME = "jd-final.json"
# Per-post confirmation of the base/delta split, one entry per post base name (FR-9).
POSTS_KEY = "posts"


# Raised when a conditions file exists but cannot be honoured. A run must never treat that as
# "no conditions": HR would be shown a ranking scored against the job ad alone while believing her
# conditions were in force.
class OverridesUnreadableError(RuntimeError):
    """A jd-overrides.yaml exists but could not be read as conditions."""

# Provenance origins marking a requirement as coming from the conversation, not the ad.
ORIGIN_SUPPLEMENT = "hr_supplement"
ORIGIN_MOVED = "hr_moved"

# Seniority keywords the scorer recognises when deciding whether to activate its axis.
_SENIORITY_LEVELS = ("executive", "director", "manager", "lead", "senior", "junior", "intern", "mid")

# Relative weights HR may put on individual must-have skills.
_MIN_MUST_SKILL_WEIGHT = 0.5
_MAX_MUST_SKILL_WEIGHT = 3.0


# Return the path of the HR conditions file for one pipeline output directory.
def overrides_path(out_dir: Path | str) -> Path:
    return Path(out_dir) / OVERRIDES_FILENAME


# Load HR-supplied conditions, returning None only when there is no file to read.
#
# A file that exists but cannot be honoured is an error, never a silent None. Returning None would
# screen against the job ad alone while HR believes her conditions are in force, which is exactly
# the failure this whole gate exists to prevent. The way to screen without them is --conditions
# discard, which is an answer HR gives, not something inferred from a file we failed to read.
def load_overrides(out_dir: Path | str) -> dict[str, Any] | None:
    path = overrides_path(out_dir)
    if not path.is_file():
        return None
    try:
        import yaml
    except ImportError as exc:
        raise OverridesUnreadableError(
            f"{OVERRIDES_FILENAME} exists but PyYAML is not installed, so HR's conditions cannot be "
            "read. Install the dependencies (backend/requirements.txt), or re-run with "
            "--conditions discard to screen against the job ad alone."
        ) from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise OverridesUnreadableError(
            f"{OVERRIDES_FILENAME} could not be parsed ({exc}). Fix the file, or re-run with "
            "--conditions discard to screen against the job ad alone."
        ) from exc
    if data is None:
        # An empty file holds no conditions, which is a valid state rather than a failure.
        return None
    if not isinstance(data, dict):
        raise OverridesUnreadableError(
            f"{OVERRIDES_FILENAME} must be a YAML mapping, not {type(data).__name__}."
        )
    return data


# Normalize a skill or requirement name into the canonical underscore token form.
def _token(value: Any) -> str:
    return "_".join(str(value or "").strip().casefold().replace("-", " ").split())


# Return name and raw-weight pairs from either supported HR skill-list shape.
def _skill_entries(raw: Any) -> list[tuple[str, Any]]:
    if not isinstance(raw, list):
        return []
    entries: list[tuple[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            raw_weight = item.get("weight") if "weight" in item else None
        else:
            name = str(item or "").strip()
            if not name:
                continue
            raw_weight = None
        entries.append((name, raw_weight))
    return entries


# Keep rejected YAML values JSON-friendly when they appear in summaries.
def _reported_weight(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


# Validate HR weights without blocking unrelated conditions from being merged.
def _normalize_skill_entries(
    raw: Any, *, allow_weight: bool
) -> tuple[list[tuple[str, float | None]], list[dict[str, Any]]]:
    entries: list[tuple[str, float | None]] = []
    rejected: list[dict[str, Any]] = []
    for name, raw_weight in _skill_entries(raw):
        weight: float | None = None
        if raw_weight is not None:
            reason: str | None = None
            if not allow_weight:
                reason = "weights are only allowed on must-have skills"
            elif isinstance(raw_weight, bool):
                reason = "must-have weight must be numeric"
            else:
                try:
                    candidate = float(raw_weight)
                except (TypeError, ValueError):
                    reason = "must-have weight must be numeric"
                else:
                    if not math.isfinite(candidate):
                        reason = (
                            "must-have weight must be a finite number between "
                            f"{_MIN_MUST_SKILL_WEIGHT:g} and {_MAX_MUST_SKILL_WEIGHT:g}"
                        )
                    elif not _MIN_MUST_SKILL_WEIGHT <= candidate <= _MAX_MUST_SKILL_WEIGHT:
                        reason = (
                            "must-have weight must be between "
                            f"{_MIN_MUST_SKILL_WEIGHT:g} and {_MAX_MUST_SKILL_WEIGHT:g}"
                        )
                    else:
                        weight = candidate
            if reason:
                rejected.append(
                    {"name": name, "weight": _reported_weight(raw_weight), "reason": reason}
                )
        entries.append((name, weight))
    return entries, rejected


# Deduplicate skills by token, keeping an explicit weight over an absent one.
def _dedupe_skill_entries(
    entries: list[tuple[str, float | None]],
) -> list[tuple[str, float | None]]:
    deduped: list[tuple[str, float | None]] = []
    positions: dict[str, int] = {}
    for name, weight in entries:
        token = _token(name)
        if not token:
            continue
        index = positions.get(token)
        if index is None:
            positions[token] = len(deduped)
            deduped.append((name, weight))
            continue
        current_name, current_weight = deduped[index]
        if weight is not None and (current_weight is None or weight > current_weight):
            deduped[index] = (current_name, weight)
    return deduped


# Render a relative weight compactly for the conversation to read back.
def _format_skill_weight(weight: float) -> str:
    return f"{weight:g}"


# Return the structured_data block, unwrapping a jd-parse envelope when present.
def _structured(jd_parsed: Any) -> dict[str, Any]:
    nested = jd_parsed.get("structured_data") if isinstance(jd_parsed, dict) else None
    return nested if isinstance(nested, dict) else (jd_parsed if isinstance(jd_parsed, dict) else {})


# Load the shared skill taxonomy once, or None when it cannot be read.
def _taxonomy() -> SkillTaxonomyLoader | None:
    try:
        return SkillTaxonomyLoader(str(taxonomy_yaml_path()))
    except Exception:
        return None


# Attach an origin marker to a record, tolerating a plain-string provenance.
def _stamp_origin(record: dict[str, Any], origin: str) -> None:
    provenance = record.get("provenance")
    if isinstance(provenance, dict):
        provenance["origin"] = origin
        return
    record["provenance"] = {
        "origin": origin,
        "source_sentence": str(provenance) if provenance else None,
    }


# Build one skill record for a name HR supplied that the job ad never mentioned.
def _new_skill(
    name: str,
    taxonomy: SkillTaxonomyLoader | None,
    order: int,
    weight: float | None = None,
) -> dict[str, Any]:
    canonical = None
    if taxonomy is not None:
        try:
            canonical = taxonomy.normalize_skill(str(name))
        except Exception:
            canonical = None
    token = _token(canonical or name)
    record: dict[str, Any] = {
        "skill_id": f"{token}_{order}",
        "display_name": str(name).strip(),
        "canonical_skill": token,
        "priority_order": order,
        "weight": weight if weight is not None else 1.0,
        "provenance": {"origin": ORIGIN_SUPPLEMENT, "source_sentence": None, "confidence": 1.0},
    }
    if canonical is None:
        # Not in the taxonomy: keep it visible but flag it so HR is told it will not match.
        record["provenance"]["unmatched"] = True
    return record


# Reclassify parsed skills against HR's final must/preferred lists and stamp provenance.
# Returns how many requirements changed plus any rejected skill weights.
def _merge_skill_lists(
    data: dict[str, Any], overrides: dict[str, Any], taxonomy
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    final_must = overrides.get("must_skills")
    final_preferred = overrides.get("preferred_skills")
    if not isinstance(final_must, list) and not isinstance(final_preferred, list):
        return 0, [], []

    must_entries, must_rejected = _normalize_skill_entries(final_must, allow_weight=True)
    preferred_entries, preferred_rejected = _normalize_skill_entries(
        final_preferred, allow_weight=False
    )
    must_entries = _dedupe_skill_entries(must_entries)
    preferred_entries = _dedupe_skill_entries(preferred_entries)
    rejected = [*must_rejected, *preferred_rejected]

    # HR's lists are authoritative: a parsed skill in neither list was dropped by HR.
    must_tokens = {_token(name) for name, _ in must_entries}
    preferred_tokens = {_token(name) for name, _ in preferred_entries}
    must_weights = {_token(name): weight for name, weight in must_entries if weight is not None}
    applied_weights = [
        {"name": name, "weight": weight}
        for name, weight in must_entries
        if weight is not None
    ]

    claimed: set[str] = set()
    must: list[dict[str, Any]] = []
    preferred: list[dict[str, Any]] = []
    changed = 0

    for original, items in (
        ("must_skills", data.get("must_skills")),
        ("preferred_skills", data.get("preferred_skills")),
    ):
        for item in items or []:
            if not isinstance(item, dict):
                continue
            record = copy.deepcopy(item)
            token = _token(record.get("canonical_skill") or record.get("display_name"))
            if not token:
                continue
            if token in must_tokens:
                target = "must_skills"
            elif token in preferred_tokens:
                target = "preferred_skills"
            else:
                changed += 1
                continue
            if target != original:
                # Moved must-haves normally reset to 1.0; an explicit HR weight overrides that reset.
                if target == "must_skills":
                    record["weight"] = must_weights.get(token, 1.0)
                _stamp_origin(record, ORIGIN_MOVED)
                changed += 1
            elif target == "must_skills":
                explicit_weight = must_weights.get(token)
                if explicit_weight is not None:
                    try:
                        weight_changed = float(record.get("weight", 1.0)) != explicit_weight
                    except (TypeError, ValueError):
                        weight_changed = True
                    record["weight"] = explicit_weight
                    if weight_changed:
                        changed += 1
            claimed.add(token)
            (must if target == "must_skills" else preferred).append(record)

    # Names HR supplied that the ad never mentioned become new requirements.
    for entries, bucket in ((must_entries, must), (preferred_entries, preferred)):
        for order, (name, weight) in enumerate(entries, start=1):
            token = _token(name)
            if not token or token in claimed:
                continue
            bucket.append(_new_skill(name, taxonomy, order, weight))
            claimed.add(token)
            changed += 1

    if not changed:
        return 0, rejected, applied_weights
    for order, record in enumerate(must, start=1):
        record["priority_order"] = order
    for order, record in enumerate(preferred, start=1):
        record["priority_order"] = order
    data["must_skills"] = must
    data["preferred_skills"] = preferred
    return changed, rejected, applied_weights


# Replace parsed language requirements when HR supplied their own list.
# Returns how many language entries HR changed or added.
def _merge_languages(data: dict[str, Any], overrides: dict[str, Any]) -> int:
    supplied = overrides.get("language_requirements")
    if not isinstance(supplied, list) or not supplied:
        return 0
    existing = {
        _token(item.get("language")): item
        for item in data.get("language_requirements") or []
        if isinstance(item, dict)
    }
    merged: list[dict[str, Any]] = []
    changed = 0
    for item in supplied:
        if not isinstance(item, dict):
            continue
        language = str(item.get("language") or "").strip()
        if not language:
            continue
        source = existing.get(_token(language))
        record = copy.deepcopy(source) if isinstance(source, dict) else {}
        record["language"] = language
        for key in ("level", "is_mandatory"):
            if key in item and record.get(key) != item[key]:
                record[key] = item[key]
                changed += 1
        if not isinstance(source, dict):
            record["provenance"] = {"origin": ORIGIN_SUPPLEMENT}
            changed += 1
        merged.append(record)
    if not merged or not changed:
        return 0
    data["language_requirements"] = merged
    return changed


# Apply HR's degree and field-of-study gates onto the parsed education requirement.
# Returns 1 when HR changed the gate, 0 otherwise.
def _merge_education(data: dict[str, Any], overrides: dict[str, Any]) -> int:
    rules = overrides.get("eligibility_rules")
    if not isinstance(rules, list) or not rules:
        return 0
    degree_rule = next(
        (rule for rule in rules if isinstance(rule, dict) and rule.get("rule") == "minimum_degree"),
        None,
    )
    if not isinstance(degree_rule, dict):
        return 0
    record = copy.deepcopy(data.get("education_requirement") or {})
    if not isinstance(record, dict):
        record = {}
    before = json.dumps(record, sort_keys=True, ensure_ascii=False)
    if degree_rule.get("value"):
        record["minimum_degree"] = degree_rule["value"]
    if degree_rule.get("field_of_study"):
        record["field_of_study"] = degree_rule["field_of_study"]
    if "is_mandatory" in degree_rule:
        record["is_mandatory"] = bool(degree_rule["is_mandatory"])
    if json.dumps(record, sort_keys=True, ensure_ascii=False) == before:
        return 0
    _stamp_origin(record, ORIGIN_SUPPLEMENT)
    data["education_requirement"] = record
    return 1


# Apply HR's minimum-years gate onto the parsed experience requirement.
# Returns 1 when HR set or changed the gate, 0 otherwise.
def _merge_experience(data: dict[str, Any], overrides: dict[str, Any]) -> int:
    years = overrides.get("min_relevant_years")
    if years is None:
        return 0
    try:
        value = float(years)
    except (TypeError, ValueError):
        return 0
    record = copy.deepcopy(data.get("experience_requirement") or {})
    if not isinstance(record, dict):
        record = {}
    if record.get("minimum_years") == value:
        return 0
    record["minimum_years"] = value
    _stamp_origin(record, ORIGIN_SUPPLEMENT)
    data["experience_requirement"] = record
    return 1


# Apply HR's target seniority so the seniority dimension becomes scoreable.
# Returns 1 when HR set a seniority the ad did not state, 0 otherwise.
def _merge_seniority(data: dict[str, Any], overrides: dict[str, Any]) -> int:
    level = str(overrides.get("target_seniority") or "").strip().casefold()
    if level not in _SENIORITY_LEVELS:
        return 0
    overview = copy.deepcopy(data.get("jd_overview") or {})
    if not isinstance(overview, dict):
        overview = {}
    if str(overview.get("seniority") or "").strip().casefold() == level:
        return 0
    overview["seniority"] = level
    data["jd_overview"] = overview
    data["seniority"] = level
    return 1


# Merge HR conditions onto parsed JD data and return the structured block plus a summary.
def merge_structured(jd_parsed: Any, overrides: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    data = copy.deepcopy(_structured(jd_parsed))
    if not isinstance(data, dict):
        data = {}
    if not isinstance(overrides, dict):
        return data, {"applied": False, "reason": "no conditions"}
    taxonomy = _taxonomy()
    counts: dict[str, int] = {}
    skills_changed, rejected_weights, applied_weights = _merge_skill_lists(
        data, overrides, taxonomy
    )
    for section, changed in (
        ("skills", skills_changed),
        ("languages", _merge_languages(data, overrides)),
        ("education", _merge_education(data, overrides)),
        ("experience", _merge_experience(data, overrides)),
        ("seniority", _merge_seniority(data, overrides)),
    ):
        if changed:
            counts[section] = changed
    summary = {
        "applied": bool(counts),
        "collected_at": overrides.get("collected_at"),
        "sections": sorted(counts),
        "counts": counts,
        # Total requirements HR changed, used for the report's conditions label.
        "changed": sum(counts.values()),
    }
    if applied_weights:
        summary["must_skill_weights"] = applied_weights
    if rejected_weights:
        summary["rejected_weights"] = rejected_weights
    data["hr_conditions"] = summary
    return data, summary


# Collapse a delta into the comparable strings HR confirms and the file stores.
def _delta_sentences(sentences: Any) -> list[str]:
    if not isinstance(sentences, list):
        return []
    return [" ".join(str(item).split()) for item in sentences if str(item or "").strip()]


# Read the per-post confirmation state, keyed by case-folded base name so the full-time and
# part-time variants of one post resolve to the single entry HR answered about (FR-9).
def _recorded_posts(overrides: Any) -> dict[str, dict[str, Any]]:
    entries = overrides.get(POSTS_KEY) if isinstance(overrides, dict) else None
    if not isinstance(entries, list):
        return {}
    recorded: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = base_name(str(entry.get("post") or ""))
        if not name:
            continue
        recorded[name.casefold()] = {
            "confirmed": entry.get("confirmed") is True,
            "delta": _delta_sentences(entry.get("delta")),
        }
    return recorded


# The raw post labels each base name covers, in universe order, so one item can name every
# variant it stands for: HR recognises "Research Assistant (Full-time)", not "Research Assistant".
def _labels_by_base(labels: Iterable[str] | None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for label in labels or []:
        name = base_name(str(label or ""))
        if not name:
            continue
        variants = grouped.setdefault(name.casefold(), [])
        if label not in variants:
            variants.append(label)
    return grouped


# One grill item per post that has a derivation of its own (FR-9). Grouped by base name, so the
# full-time and part-time variants of one post share one item and therefore one answer.
#
# A post counts as confirmed only while the delta HR was shown still matches the delta derived
# now: a changed advertisement re-opens the question instead of reusing an answer about other
# text. A post with no delta of its own is not an item at all - there is nothing to confirm.
def post_grill_items(
    overrides: Any,
    deltas: Mapping[str, Any] | None,
    labels: Iterable[str] | None = (),
) -> list[dict[str, Any]]:
    """Return one grill item per post base name that has a delta, tagged with its post."""
    recorded = _recorded_posts(overrides)
    grouped = _labels_by_base(labels)
    items: list[dict[str, Any]] = []
    for name, sentences in (deltas or {}).items():
        base = base_name(str(name or ""))
        delta = _delta_sentences(sentences)
        if not base or not delta:
            continue
        state = recorded.get(base.casefold()) or {}
        items.append(
            {
                "post": base,
                "labels": grouped.get(base.casefold()) or [base],
                "confirmed": bool(state.get("confirmed")) and state.get("delta") == delta,
                # The exact advertisement sentences this post's requirements were read from, so
                # HR confirms the attribution against the source and not against a summary.
                "delta": delta,
            }
        )
    return items


# The posts whose derivation HR has not yet settled, which is what the grill must ask about.
# Empty means every derivation is confirmed, so the run has nothing left to stop for (FR-9).
def pending_post_grill(
    overrides: Any,
    deltas: Mapping[str, Any] | None,
    labels: Iterable[str] | None = (),
) -> list[dict[str, Any]]:
    """Return only the posts whose derivation is still unconfirmed."""
    return [item for item in post_grill_items(overrides, deltas, labels) if not item["confirmed"]]


# True when the file carries a condition the merge would actually consume, so HR is asked about
# it. The per-post confirmation state is not a condition: a file holding only `posts` has nothing
# for HR to read back, and asking about it would be a question with no content (FR-9).
def _has_conditions(overrides: Any) -> bool:
    if not isinstance(overrides, dict):
        return False
    for key in ("must_skills", "preferred_skills", "language_requirements", "eligibility_rules"):
        if overrides.get(key):
            return True
    for key in ("target_seniority", "min_relevant_years", "extra_notes"):
        value = overrides.get(key)
        if value is not None and str(value).strip():
            return True
    return False


# Describe stored conditions so the conversation can read them back to HR before reuse.
def describe_overrides(out_dir: Path | str) -> dict[str, Any] | None:
    """Return a summary of the stored conditions, or None when there are none."""
    overrides = load_overrides(out_dir)
    if overrides is None or not _has_conditions(overrides):
        return None
    must_entries, must_rejected = _normalize_skill_entries(
        overrides.get("must_skills"), allow_weight=True
    )
    preferred_entries, preferred_rejected = _normalize_skill_entries(
        overrides.get("preferred_skills"), allow_weight=False
    )
    must_entries = _dedupe_skill_entries(must_entries)
    preferred_entries = _dedupe_skill_entries(preferred_entries)
    weighted_must = [
        {"name": name, "weight": weight}
        for name, weight in must_entries
        if weight is not None
    ]
    summary = {
        "collected_at": overrides.get("collected_at"),
        "must_skills": [
            f"{name} ×{_format_skill_weight(weight)}" if weight is not None else name
            for name, weight in must_entries
        ],
        "preferred_skills": [name for name, _ in preferred_entries],
        "target_seniority": overrides.get("target_seniority"),
        "min_relevant_years": overrides.get("min_relevant_years"),
        "languages": [
            str(item.get("language"))
            for item in overrides.get("language_requirements") or []
            if isinstance(item, dict) and item.get("language")
        ],
        "notes": str(overrides.get("extra_notes") or "").strip() or None,
    }
    if weighted_must:
        summary["must_skill_weights"] = weighted_must
    rejected = [*must_rejected, *preferred_rejected]
    if rejected:
        summary["rejected_weights"] = rejected
    return summary


# Write jd-final.json for one output directory; returns (path or None, summary).
# `confirmed` is the conversation's answer to "reuse the stored conditions?": the file
# alone is never enough, because it outlives the conversation that produced it.
def write_final_jd(
    out_dir: Path | str,
    jd_parsed_path: Path | str,
    *,
    confirmed: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    overrides = load_overrides(out_dir)
    if overrides is None:
        return None, {"applied": False, "reason": "no conditions file"}
    if not confirmed:
        # Refusing here is what stops a fresh conversation from silently inheriting
        # another conversation's conditions. The caller must ask HR first.
        return None, {
            "applied": False,
            "reason": "awaiting confirmation",
            "counts": None,
        }
    try:
        raw = json.loads(Path(jd_parsed_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None, {"applied": False, "reason": "unreadable parsed JD"}
    structured, summary = merge_structured(raw, overrides)
    if not summary.get("applied"):
        return None, summary
    envelope = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    envelope["structured_data"] = structured
    envelope["jd_overrides"] = summary
    final_path = Path(out_dir) / FINAL_JD_FILENAME
    final_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_path, summary
