# Fingerprints HR reports so unchanged candidate PDFs and ranking HTML are skipped.
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# v3: board radar axes carry native-tooltip reasoning payload (Option A, PRD-REPORT-GEN-001).
# v4: radar axes print full dimension names plus on-chart scores, tooltip cards auto-size,
#     and the candidate match page shows an always-visible dimension breakdown (F1.3-F1.6).
REPORT_FINGERPRINT_VERSION = "hr-report-v4"
INPUT_FINGERPRINT_VERSION = "hr-input-v1"
FINGERPRINTS_NAME = "report-fingerprints.json"


# Returns the SHA-256 hex digest of a file, or empty string if it is missing.
def sha256_file(path: Path | str | None) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Returns the SHA-256 hex digest of a UTF-8 string.
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Builds a stable fingerprint for one candidate HTML/PDF pair.
def candidate_report_fingerprint(
    *,
    engine: str | None,
    position: str | None,
    refno: str | None,
    appno: str | None,
    rank: object,
    total_score: object,
    tier: str | None,
    artifact_paths: list[Path | str | None],
) -> str:
    chunks = [
        REPORT_FINGERPRINT_VERSION,
        str(engine or ""),
        str(position or ""),
        str(refno or ""),
        str(appno or ""),
        str(rank or ""),
        str(total_score or ""),
        str(tier or ""),
    ]
    for path in artifact_paths:
        chunks.append(sha256_file(path))
    return sha256_text("|".join(chunks))


# Builds a comparable snapshot of JD + CV bytes so --resume can be invalidated.
def input_run_payload(
    *,
    engine: str | None,
    position: str | None,
    refno: str | None,
    jd_paths: list[Path | str | None],
    cv_hashes: dict[str, str],
) -> dict[str, Any]:
    jd_chunks = [sha256_file(path) for path in jd_paths if path]
    return {
        "version": INPUT_FINGERPRINT_VERSION,
        "engine": str(engine or ""),
        "position": str(position or ""),
        "refno": str(refno or ""),
        "jd": sha256_text("|".join(jd_chunks)),
        "cvs": dict(sorted(cv_hashes.items())),
    }


# True when JD text or scoring engine changed and cached parse/score JSON must not be reused.
def jd_inputs_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    prior = previous or {}
    if not prior.get("jd"):
        return False
    return prior.get("jd") != current.get("jd") or prior.get("engine") != current.get("engine")


# Slugs whose CV bytes changed (or are new) and must be re-parsed.
def stale_cv_slugs(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    prior_cvs = (previous or {}).get("cvs")
    if not isinstance(prior_cvs, dict):
        return []
    current_cvs = current.get("cvs") if isinstance(current.get("cvs"), dict) else {}
    stale: list[str] = []
    for slug, digest in current_cvs.items():
        if prior_cvs.get(slug) != digest:
            stale.append(str(slug))
    return stale


# Builds a fingerprint for ranking-overview.html from the current candidate set.
def board_report_fingerprint(
    *,
    position: str | None,
    refno: str | None,
    candidate_fingerprints: dict[str, str],
    resume_links_digest: str | None = None,
) -> str:
    ordered = [candidate_fingerprints[key] for key in sorted(candidate_fingerprints)]
    return sha256_text(
        "|".join(
            [
                REPORT_FINGERPRINT_VERSION,
                str(position or ""),
                str(refno or ""),
                *ordered,
                f"links:{resume_links_digest or ''}",
            ]
        )
    )


# Loads previously stored report fingerprints from the pipeline work directory.
def load_fingerprints(out_dir: Path) -> dict[str, Any]:
    path = out_dir / FINGERPRINTS_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


# Writes the current report fingerprints next to other pipeline JSON.
def save_fingerprints(out_dir: Path, payload: dict[str, Any]) -> None:
    path = out_dir / FINGERPRINTS_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "FINGERPRINTS_NAME",
    "INPUT_FINGERPRINT_VERSION",
    "REPORT_FINGERPRINT_VERSION",
    "board_report_fingerprint",
    "candidate_report_fingerprint",
    "input_run_payload",
    "jd_inputs_changed",
    "load_fingerprints",
    "save_fingerprints",
    "sha256_file",
    "sha256_text",
    "stale_cv_slugs",
]
