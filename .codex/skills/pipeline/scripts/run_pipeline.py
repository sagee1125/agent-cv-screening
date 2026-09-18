"""CLI entry point for the pipeline skill (agent-facing).

Runs the full candidate screening pipeline in one command by chaining the
other skill CLIs: (optional PolyU import) -> jd-parser -> scorer build-config
-> cv-parser -> scorer score -> report-gen (PDF per candidate + Excel).

L1 phase 1: per-candidate isolation, retries, resume from output-dir, and a
need_input envelope when JD/CVs/position are missing.

Two scoring engines are supported:
- legacy (default): the deterministic ScorerService (dimension_scores + interview_suggestions).
- matching: the five-dimension candidate_matching engine, which emits the same
  radar/interview-question detail payload the frontend modal shows, and renders
  that content in the PDF reports.

Example (from repository root):
    python .codex/skills/pipeline/scripts/run_pipeline.py \
      --jd-file jd.txt --cv cv1.pdf --cv cv2.pdf \
      --position "Backend Engineer" --output-dir data/pipeline_out
    python .codex/skills/pipeline/scripts/run_pipeline.py \
      --jd-file jd.txt --cv cv1.pdf --engine matching \
      --position "Backend Engineer" --output-dir data/pipeline_out
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import _bootstrap  # noqa: F401  (sets sys.path + cwd before app imports)
from jd_parser.post_split import PostSplit, split_advertisement
from screening_core.candidate_id import appno_from_filename, format_candidate_label, refno_from_url
from screening_core.board_tooltip import public_radar_dimensions
from screening_core.hr_output import RANKING_OVERVIEW_HTML, RESUME_LINKS_JSON, candidate_match_stem, safe_http_url
from screening_core.input_policy import (
    ALLOWED_URL_HOSTS,
    extra_allowed_hosts_from_env,
    merge_allowed_hosts,
    validate_extracted_reference,
    validate_path,
    validate_reference,
)
from screening_core.jd_overrides import (
    FINAL_JD_FILENAME,
    OVERRIDES_FILENAME,
    OverridesUnreadableError,
    describe_overrides,
    load_overrides,
    pending_post_grill,
    write_final_jd,
)
from screening_core.job_state import load_job_state, save_job_state
from screening_core.post_jds import (
    BASE_JD_TEXT_NAME,
    POST_JDS_NAME,
    base_names_of,
    post_artifacts,
    post_jd_payload,
    post_slug,
)
from screening_core.posts import base_name, group_by_post, post_key, post_of
from screening_core.report_fingerprint import (
    board_report_fingerprint,
    candidate_report_fingerprint,
    input_run_payload,
    jd_inputs_changed,
    load_fingerprints,
    overrides_changed,
    post_changed_slugs,
    save_fingerprints,
    sha256_file,
    sha256_text,
    stale_cv_slugs,
)
from jas_import.fetch import cv_filename_for_url, download_to_if_changed, fetch_jd_text

REPO_ROOT = _bootstrap.REPO_ROOT
SKILLS_DIR = REPO_ROOT / ".codex" / "skills"
PYTHON = sys.executable

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEED_INPUT = 2


# Raised when the run cannot start until the caller supplies missing inputs.
class NeedInputError(Exception):
    def __init__(
        self,
        missing: list[str],
        questions: list[str],
        *,
        status: str = "need_input",
        details: dict | None = None,
    ) -> None:
        """Record which inputs are missing and the questions to ask the caller."""
        self.missing = missing
        self.questions = questions
        self.status = status
        self.details = details or {}
        super().__init__(", ".join(missing))


# One per-candidate (or comparison-report) failure recorded in the manifest.
class Failure:
    def __init__(self, source: str, stage: str, attempts: int, error_message: str) -> None:
        """Store the failed source, pipeline stage, attempt count, and error text."""
        self.source = source
        self.stage = stage
        self.attempts = attempts
        self.error_message = error_message

    def to_dict(self) -> dict:
        """Return a JSON-serializable failure record."""
        return {
            "source": self.source,
            "stage": self.stage,
            "attempts": self.attempts,
            "error_message": self.error_message,
        }


def _skill_script(skill: str, script: str) -> Path:
    """Return the absolute path of a skill CLI script."""
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise RuntimeError(f"skill script not found: {path}")
    return path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run a skill CLI subprocess and raise its JSON error envelope on failure."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(message)
    return proc


def _run_with_retries(cmd: list[str], max_retries: int) -> tuple[int, str | None]:
    """Run a skill CLI up to 1 + max_retries times. Returns (attempts, error or None)."""
    attempts = 0
    last_error: str | None = None
    total = 1 + max(0, max_retries)
    for _ in range(total):
        attempts += 1
        try:
            _run(cmd)
            return attempts, None
        except RuntimeError as exc:
            last_error = str(exc)
    return attempts, last_error


def _load_json(path: Path) -> dict:
    """Load a JSON file tolerating a UTF-8 BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _is_usable_json(path: Path) -> bool:
    """Return True when path exists and contains a JSON object."""
    if not path.is_file():
        return False
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict)


def _safe_name(name: str) -> str:
    """Return a filesystem-safe token derived from a candidate name."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_")
    return cleaned or "candidate"


# Deletes cached parse/score JSON for one candidate slug so it is rebuilt.
def _clear_candidate_artifacts(out_dir: Path, slug: str) -> None:
    """Remove extracted/score/detail JSON for a slug that must be parsed again."""
    for prefix in ("extracted-", "score-", "detail-"):
        (out_dir / f"{prefix}{slug}.json").unlink(missing_ok=True)


# Deletes every cached score so a conditions change is re-scored without re-parsing.
def _clear_score_artifacts(out_dir: Path) -> None:
    """Remove per-candidate scores, rows and board rows; keep the parsed JD and CVs."""
    for prefix in ("detail-", "score-"):
        for path in out_dir.glob(f"{prefix}*.json"):
            path.unlink(missing_ok=True)
    (out_dir / "rows.json").unlink(missing_ok=True)
    for path in out_dir.glob("board-row-*.json"):
        path.unlink(missing_ok=True)
    (out_dir / "jd-final.json").unlink(missing_ok=True)


# Deletes one candidate's cached score so it is recomputed against their post's JD, keeping their
# parsed CV: a re-assignment changes which JD applies to them, not the CV itself (FR-10).
def _clear_score_for_slug(out_dir: Path, slug: str) -> None:
    """Remove score/detail JSON for one slug, leaving extracted JSON and every other slug alone."""
    for prefix in ("score-", "detail-"):
        (out_dir / f"{prefix}{slug}.json").unlink(missing_ok=True)


# Delete the per-post effective JDs and their scoring configs so a changed post is rebuilt.
# Only a multi-post run writes these, so this is a no-op on a single-post job.
def _clear_post_jd_artifacts(out_dir: Path) -> None:
    """Remove every per-post JD artifact and per-post scoring config."""
    for pattern in ("jd-post-*.json", "jd-post-*.txt", "config-*.json"):
        for path in out_dir.glob(pattern):
            path.unlink(missing_ok=True)
    (out_dir / POST_JDS_NAME).unlink(missing_ok=True)
    (out_dir / BASE_JD_TEXT_NAME).unlink(missing_ok=True)


# Snapshot JD + CV bytes so --resume does not reuse stale parse/score JSON.
def _input_payload(args: argparse.Namespace, out_dir: Path) -> dict:
    """Hash the JD files, HR conditions and CV/extracted files for resume invalidation."""
    jd_paths: list[Path | str | None] = [getattr(args, "jd_file", None), getattr(args, "jd_json", None)]
    used: set[str] = set()
    cv_hashes: dict[str, str] = {}
    # --cv-post is keyed by appno, but every cached artifact is keyed by slug. Staged CVs are named
    # <appno>.pdf, so the file stem is the appno and the two key spaces are aligned here. Without
    # that, a re-assignment could not be traced to the one artifact it invalidates (FR-10).
    post_by_appno = _post_map(args)
    posts: dict[str, str] = {}
    for source in list(args.cv or []) + list(args.extracted or []):
        slug = _unique_slug(str(source), used)
        cv_hashes[slug] = sha256_file(source)
        label = post_by_appno.get(_safe_name(Path(source).stem))
        if label:
            posts[slug] = label
    return input_run_payload(
        engine=getattr(args, "engine", None),
        position=getattr(args, "position", None),
        refno=getattr(args, "refno", None),
        jd_paths=jd_paths,
        cv_hashes=cv_hashes,
        overrides_path=out_dir / OVERRIDES_FILENAME,
        apply_overrides=bool(getattr(args, "_conditions_confirmed", False)),
        posts=posts,
    )


# Turn off --resume or drop cached work when the JD, the engine, the conditions, a CV or a post
# assignment changed. Each input change invalidates the smallest set of artifacts that covers it,
# so a re-run that touches one post group does not rebuild the others (FR-10).
def _sync_resume_with_inputs(args: argparse.Namespace, out_dir: Path) -> None:
    """Keep --resume only when JD/engine match; rebuild only what the changed inputs stale."""
    payload = _input_payload(args, out_dir)
    args._input_payload = payload
    previous = load_fingerprints(out_dir).get("input")
    prior = previous if isinstance(previous, dict) else {}
    args._inputs_unchanged = bool(prior) and prior == payload
    if not args.resume:
        return
    if jd_inputs_changed(prior, payload):
        # The advertisement or the engine changed: no cached parse, score or post JD can be
        # trusted, so the whole run is rebuilt. FR-10's "only one group changed" does not cover
        # this case, because a changed advertisement can move requirements between posts.
        args.resume = False
        args._inputs_unchanged = False
        (out_dir / "jd-parse.json").unlink(missing_ok=True)
        (out_dir / "config.json").unlink(missing_ok=True)
        _clear_post_jd_artifacts(out_dir)
        return
    if overrides_changed(prior, payload):
        # HR edited the conditions: the parsed JD still stands, only the scores are stale.
        # --resume stays on so the JD is not re-parsed and must/nice assignment stays stable.
        _clear_score_artifacts(out_dir)
        args._inputs_unchanged = False
        return
    stale_cvs = stale_cv_slugs(prior, payload)
    for slug in stale_cvs:
        _clear_candidate_artifacts(out_dir, slug)
    # An applicant moved to another post is scored against another post's JD, so their score is
    # stale even though their CV bytes are not: rebuild the score, reuse the parsed CV (FR-10).
    moved = [slug for slug in post_changed_slugs(prior, payload) if slug not in set(stale_cvs)]
    for slug in moved:
        _clear_score_for_slug(out_dir, slug)
    if stale_cvs or moved:
        args._inputs_unchanged = False


# Merge report + input fingerprints and write report-fingerprints.json.
def _persist_fingerprints(out_dir: Path, args: argparse.Namespace, extra: dict | None = None) -> None:
    """Write input and optional report fingerprints next to pipeline JSON."""
    data = load_fingerprints(out_dir)
    if extra:
        data.update(extra)
    payload = getattr(args, "_input_payload", None)
    if isinstance(payload, dict):
        data["input"] = payload
    save_fingerprints(out_dir, data)


def _unique_slug(source: str, used: set[str]) -> str:
    """Return a stable artifact slug from the source filename, unique within the run."""
    stem = _safe_name(Path(source).stem)
    slug = stem
    n = 2
    while slug in used:
        slug = f"{stem}_{n}"
        n += 1
    used.add(slug)
    return slug


# Parse the repeatable --cv-post "<appno>=<post label>" flags into an appno -> post map.
# The application number never contains "=", so the first "=" always splits the pair and a
# post label may contain spaces, parentheses and slashes.
def _post_map(args: argparse.Namespace) -> dict[str, str]:
    """Return the appno -> post label map supplied by the caller, empty for a single-post job."""
    posts: dict[str, str] = {}
    for entry in getattr(args, "cv_post", None) or []:
        appno, separator, label = str(entry).partition("=")
        if not separator:
            raise RuntimeError(f"--cv-post expects <appno>=<post label>, got {entry!r}")
        appno = appno.strip()
        label = label.strip()
        if appno and label:
            posts[appno] = label
    return posts


# Read one candidate's post from the map, or None when the job is single-post.
def _post_for_appno(args: argparse.Namespace, appno: str | None) -> str | None:
    if not appno:
        return None
    return _post_map(args).get(str(appno)) or None


# The post universe of this run: the distinct post labels in first-appearance order (FR-3).
# Empty for a single-post job, which is how every caller detects "no post dimension".
def _post_labels(args: argparse.Namespace) -> list[str]:
    """Return the distinct post labels supplied by the caller, in first-appearance order."""
    labels: list[str] = []
    for label in _post_map(args).values():
        if label and not any(post_key(label) == post_key(seen) for seen in labels):
            labels.append(label)
    return labels


# The JD each post group is scored against, plus the advertisement the run started from.
# A plain class rather than a dataclass: these CLI modules are loaded by the test suite with
# importlib without registering them in sys.modules, which makes dataclasses fail to resolve
# their own string annotations. Every other skill CLI here uses a plain class for the same reason.
class JdSources:
    """Resolve which parsed JD one applicant is scored against (FR-5).

    For a single-post job `by_post` is empty and `for_post` always returns `default`, which is
    exactly the one JD this pipeline has always used. A multi-post job fills `by_post` with one
    effective JD per base name, so full-time and part-time variants of one post share a JD.
    """

    def __init__(
        self,
        default: Path,
        text: str | None = None,
        split: PostSplit | None = None,
        base_names: list[str] | None = None,
        by_post: dict[str, Path] | None = None,
        multi_post: bool = False,
    ) -> None:
        """Record the run's JD text, the shared base JD and one effective JD per post."""
        self.default = default
        self.text = text
        self.split = split
        self.base_names = list(base_names or [])
        self.by_post = dict(by_post or {})
        # Driven by the post universe, never by whether any post turned out to have its own
        # delta: an advertisement whose requirements are all shared still has a post dimension,
        # so it still ranks per post and still renders one section per post (FR-5, FR-6).
        self._multi_post = bool(multi_post)

    @property
    def multi_post(self) -> bool:
        """True when this run has a post dimension."""
        return self._multi_post

    def for_post(self, label: str | None) -> Path:
        """The JD one applicant is scored against: their own post's, else the run default."""
        if not label:
            return self.default
        return self.by_post.get(base_name(label), self.default)

    def config_name(self, label: str | None) -> str:
        """The legacy scoring config file name for one applicant's post."""
        if not label:
            return "config.json"
        return f"config-{post_slug(base_name(label))}.json"

    @property
    def jd_paths(self) -> list[Path]:
        """Every JD this run scores against, base first, then one per post."""
        ordered = [self.default, *self.by_post.values()]
        seen: list[Path] = []
        for path in ordered:
            if path not in seen:
                seen.append(path)
        return seen


def _radar_dim_score(dims: dict, dimension_id: str) -> float:
    """Return a numeric radar dimension score, treating inactive (None) dimensions as 0."""
    value = dims.get(dimension_id)
    return float(value) if value is not None else 0.0


def _record_failure(args: argparse.Namespace, failures: list[Failure], failure: Failure) -> None:
    """Append a failure; abort the batch immediately when --fail-fast is set."""
    failures.append(failure)
    if args.fail_fast:
        raise RuntimeError(failure.error_message)


# Rejects inline content and non-allowlisted references at the entry point.
def _enforce_input_policy(args: argparse.Namespace, out_dir: Path) -> None:
    for flag, value in (("--jd-file", args.jd_file), ("--jd-json", args.jd_json)):
        if value:
            validate_reference(value, flag=flag)
    for value in args.cv:
        validate_reference(value, flag="--cv")
    for value in args.extracted:
        validate_extracted_reference(value, out_dir=out_dir, trusted=args.trust_extracted, flag="--extracted")
    if args.polyu_detail_url:
        validate_reference(args.polyu_detail_url, flag="--polyu-detail-url")
    allowed_hosts = _effective_allowed_hosts(args)
    if args.jd_url:
        validate_reference(args.jd_url, flag="--jd-url", allowed_hosts=allowed_hosts)
    for value in args.cv_url:
        validate_reference(value, flag="--cv-url", allowed_hosts=allowed_hosts)
    if args.cookie_file:
        validate_path(args.cookie_file, flag="--cookie-file")


def _collect_need_input(args: argparse.Namespace) -> None:
    """Raise NeedInputError when JD, candidates, or report position are missing."""
    missing: list[str] = []
    questions: list[str] = []
    if not args.jd_file and not args.jd_json and not args.polyu_ref and not args.jd_url:
        missing.append("jd")
        questions.append("Provide a JD via --jd-file, --jd-json, --polyu-ref, or --jd-url.")
    if not args.cv and not args.extracted and not args.cv_url:
        missing.append("candidates")
        questions.append("Provide at least one CV (--cv), CV URL (--cv-url), or extracted profile (--extracted).")
    if not args.skip_reports and not args.position:
        missing.append("position")
        questions.append("Provide --position for reports, or pass --skip-reports.")
    if missing:
        raise NeedInputError(missing, questions)


def _resolve_jd_sources(args: argparse.Namespace, out_dir: Path) -> JdSources:
    """Return the parsed JD each post is scored against, plus the JD text for CV context.

    A single-post job returns exactly one JD, so every downstream stage behaves as it always
    has. A multi-post job splits the advertisement once (FR-4) and parses the shared base plus
    one effective JD per post, so each post group can be scored against its own JD (FR-5).
    """
    labels = _post_labels(args)
    if not labels:
        jd_path, jd_text = _resolve_raw_jd_source(args, out_dir)
        return JdSources(default=_apply_jd_overrides(args, out_dir, jd_path), text=jd_text)

    jd_text, _existing = _raw_jd_text(args, out_dir)
    if not jd_text:
        raise RuntimeError(
            "a multi-post run needs the advertisement as text to split it by post; "
            "provide --jd-file or --jd-url"
        )
    split = split_advertisement(jd_text, labels)
    names = base_names_of(labels)
    # Splitting the advertisement needs only its text, so HR's decision about the derived
    # per-post requirements is taken before anything is parsed or scored (FR-9).
    _require_conditions_decision(
        args, out_dir, post_deltas=_post_deltas(split, names), post_labels=labels
    )
    # jd-parse.json becomes the base JD: the advertisement with every post-specific unit removed,
    # so the shared JD panel and the shared parsed tags are shared by construction (FR-6).
    base_path = _parse_jd_text(
        args, split.base_text, out_dir / "jd-parse.json", out_dir / BASE_JD_TEXT_NAME
    )
    by_post = _build_post_jds(args, out_dir, split, names)
    return JdSources(
        default=_apply_jd_overrides(args, out_dir, base_path),
        text=jd_text,
        split=split,
        base_names=names,
        by_post=by_post,
        multi_post=True,
    )


# Build one effective JD per post and record each delta's provenance in post-jds.json (FR-4).
# A post whose requirements are all shared has no delta, so its effective JD is the base JD
# itself and no second parse is written for it.
def _build_post_jds(
    args: argparse.Namespace, out_dir: Path, split: PostSplit, names: list[str]
) -> dict[str, Path]:
    """Return {post base name: effective JD JSON path} and write post-jds.json."""
    entries: list[dict] = []
    by_post: dict[str, Path] = {}
    for name in names:
        delta = split.delta_for(name)
        if not delta:
            entries.append({"post": name, "slug": post_slug(name), "jd_json": None, "delta": []})
            continue
        text_path, json_path = post_artifacts(out_dir, name)
        _parse_jd_text(args, split.effective_text(name), json_path, text_path)
        by_post[name] = json_path
        entries.append(
            {
                "post": name,
                "slug": post_slug(name),
                "jd_json": str(json_path),
                "jd_text": str(text_path),
                # The exact advertisement sentences this post's JD adds over the base (FR-4).
                "delta": delta,
            }
        )
    payload = post_jd_payload(
        base_jd_json=str(out_dir / "jd-parse.json"),
        base_text=split.base_text,
        posts=entries,
        mentioned=split.mentioned,
        unclaimed=split.unclaimed,
    )
    (out_dir / POST_JDS_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return by_post


# Parse JD text with the jd-parser skill into a JSON file, reusing it under --resume.
# The text is always written next to the JSON so a split decision can be audited afterwards.
def _parse_jd_text(
    args: argparse.Namespace, jd_text: str, out_path: Path, text_path: Path
) -> Path:
    """Return the parsed JD JSON path, running the jd-parser only when it is not cached."""
    text_path.write_text(jd_text, encoding="utf-8")
    if args.resume and _is_usable_json(out_path):
        return out_path
    _run(
        [
            PYTHON,
            str(_skill_script("jd-parser", "run_jd_parse.py")),
            "--jd-file",
            str(text_path),
            "--output",
            str(out_path),
        ]
    )
    return out_path


# Fold HR-supplied conditions onto the parsed JD so scores use the agreed conditions.
# Stored conditions are only merged once the current conversation confirms them; the
# file lives in the shared per-refno output directory and outlives the conversation
# that wrote it, so merging on sight would leak one conversation's edits into the next.
def _apply_jd_overrides(args: argparse.Namespace, out_dir: Path, jd_parse_path: Path) -> Path:
    """Return the JD JSON to score against: the merged one when HR conditions apply."""
    if getattr(args, "_conditions_confirmed", False):
        return _merge_jd_overrides(args, out_dir, jd_parse_path)
    if getattr(args, "_discard_conditions", False):
        # HR chose to screen against the job ad alone: an answer, so nothing to ask.
        args._jd_overrides = {"applied": False, "reason": "discarded by HR"}
        return jd_parse_path
    _require_conditions_decision(args, out_dir)
    args._jd_overrides = {"applied": False, "reason": "no conditions file"}
    return jd_parse_path


# The derived delta of every post that has one, keyed by base name in post-universe order (FR-9).
# A post whose requirements are all shared has no delta, so it is no item: there is nothing about
# it for HR to confirm.
def _post_deltas(split: PostSplit, names: list[str]) -> dict[str, list[str]]:
    """Return {post base name: derived sentences} for the posts with a derivation of their own."""
    return {name: delta for name in names if (delta := split.delta_for(name))}


# Stop the run while HR still has a decision to make, before anything is parsed or scored (FR-9).
#
# Two things can be pending, and both are answered questions rather than something to inherit
# silently: conditions saved by an earlier conversation, and the base/delta derivation of a
# multi-post advertisement. `--conditions confirmed|discard` answers either. A post HR already
# confirmed is not asked again, so a partially confirmed run asks only about what is left.
def _require_conditions_decision(
    args: argparse.Namespace,
    out_dir: Path,
    *,
    post_deltas: dict[str, list[str]] | None = None,
    post_labels: list[str] | None = None,
) -> None:
    """Raise NeedInputError(status='conditions_pending') while HR has a decision to make."""
    if getattr(args, "_conditions_confirmed", False) or getattr(args, "_discard_conditions", False):
        return
    pending_posts = pending_post_grill(
        load_overrides(out_dir), post_deltas or {}, post_labels or []
    )
    pending_conditions = describe_overrides(out_dir)
    if pending_conditions is None and not pending_posts:
        return
    questions: list[str] = []
    details: dict = {}
    if pending_conditions is not None:
        details["conditions"] = pending_conditions
        questions.append(
            "This job has conditions saved by an earlier conversation: read them back and ask HR "
            "to reuse, change or drop them."
        )
    if pending_posts:
        # Each item carries its post and the advertisement sentences that post's requirements
        # were read from, so HR confirms the attribution against the source, not a summary.
        details["post_deltas"] = pending_posts
        # Kept short on purpose: the host envelope truncates every question at 120 characters.
        questions.append(
            "Show HR each post's own requirements with the source sentence and confirm the attribution."
        )
    questions.append(
        "Then re-run with --conditions confirmed (keep them) or --conditions discard "
        "(screen against the job ad alone)."
    )
    raise NeedInputError(
        ["conditions"],
        questions,
        status="conditions_pending",
        details=details,
    )


# Merge confirmed HR conditions onto the parsed JD, falling back on any merge error.
def _merge_jd_overrides(args: argparse.Namespace, out_dir: Path, jd_parse_path: Path) -> Path:
    """Return the merged JD path when HR conditions changed something, else the parsed JD."""
    try:
        final_path, summary = write_final_jd(out_dir, jd_parse_path, confirmed=True)
    except OverridesUnreadableError:
        # Not a merge failure to fall back from: scoring without HR's conditions while she believes
        # they are in force is the one outcome the gate exists to prevent, so this one propagates.
        raise
    except Exception as exc:  # never block a screening because the merge failed
        args._jd_overrides = {"applied": False, "reason": f"merge failed: {exc}"}
        return jd_parse_path
    args._jd_overrides = summary
    return final_path or jd_parse_path


# Read the advertisement text of the configured JD source without parsing it.
# A multi-post run must split the advertisement before it parses anything (FR-4), so text
# extraction is separated from parsing. `existing` is the already-parsed JD path when the
# source arrives pre-parsed (--polyu-ref / --jd-json), else None.
def _raw_jd_text(args: argparse.Namespace, out_dir: Path) -> tuple[str | None, Path | None]:
    """Return (advertisement text, already-parsed JD path or None) for the configured source."""
    if args.polyu_ref:
        polyu_out = out_dir / "polyu-parsed.json"
        if not (args.resume and _is_usable_json(polyu_out)):
            cmd = [
                PYTHON,
                str(_skill_script("polyu-import", "run_polyu_import.py")),
                "fetch-and-parse",
                "--output",
                str(polyu_out),
                "--external-ref",
                args.polyu_ref,
            ]
            if args.polyu_detail_url:
                cmd += ["--detail-url", args.polyu_detail_url]
            _run(cmd)
        return _load_json(polyu_out).get("jd_text"), polyu_out
    if args.jd_json:
        jd_path = Path(args.jd_json)
        return _load_json(jd_path).get("jd_text"), jd_path
    if args.jd_file:
        return Path(args.jd_file).read_text(encoding="utf-8-sig"), None
    raise RuntimeError("no JD source: provide --jd-file, --jd-json, or --polyu-ref/--polyu-detail-url")


def _resolve_raw_jd_source(args: argparse.Namespace, out_dir: Path) -> tuple[Path, str | None]:
    """Return (parsed JD JSON path, optional JD text) before HR conditions are merged."""
    jd_text, existing = _raw_jd_text(args, out_dir)
    if existing is not None:
        return existing, jd_text
    jd_parse_out = out_dir / "jd-parse.json"
    if not (args.resume and _is_usable_json(jd_parse_out)):
        _run(
            [
                PYTHON,
                str(_skill_script("jd-parser", "run_jd_parse.py")),
                "--jd-file",
                str(Path(args.jd_file)),
                "--output",
                str(jd_parse_out),
            ]
        )
    return jd_parse_out, jd_text


def _parse_candidates(
    args: argparse.Namespace, out_dir: Path, jd_text: str | None, failures: list[Failure]
) -> list[dict]:
    """Parse each CV (cv-parser) or reuse provided extracted profiles."""
    jd_context = None
    if jd_text:
        jd_context = out_dir / "jd-context.txt"
        jd_context.write_text(jd_text, encoding="utf-8")
    used_slugs: set[str] = set()
    candidates: list[dict] = []
    for cv in args.cv:
        source = str(cv)
        slug = _unique_slug(source, used_slugs)
        extracted_out = out_dir / f"extracted-{slug}.json"
        if args.resume and _is_usable_json(extracted_out):
            candidates.append(_with_identity(args, extracted_out, source, slug))
            continue
        cmd = [
            PYTHON,
            str(_skill_script("cv-parser", "run_cv_parse.py")),
            "--file",
            source,
            "--output",
            str(extracted_out),
        ]
        if jd_context:
            cmd += ["--jd-file", str(jd_context)]
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=source, stage="cv-parse", attempts=attempts, error_message=error),
            )
            continue
        candidates.append(_with_identity(args, extracted_out, source, slug))
    for ext in args.extracted:
        source = str(ext)
        slug = _unique_slug(source, used_slugs)
        candidates.append(_with_identity(args, Path(ext), source, slug))
    return candidates


# Attach the composite JAS key (refno, appno) used for ranking and reports.
def _with_identity(args: argparse.Namespace, extracted: Path, source: str, slug: str) -> dict:
    refno = getattr(args, "refno", None) or None
    appno = appno_from_filename(Path(source).stem, refno)
    return {
        "extracted": extracted,
        "source": source,
        "slug": slug,
        "refno": refno,
        "appno": appno,
        "display_label": format_candidate_label(refno, appno),
        # None on a single-post job, which has no post column to read (FR-2).
        "post": _post_for_appno(args, appno),
    }


def _score_legacy_candidate(
    args: argparse.Namespace, cand: dict, config_out: Path, out_dir: Path, failures: list[Failure]
) -> bool:
    """Score one candidate with the legacy engine. Returns True on success."""
    score_out = out_dir / f"score-{cand['slug']}.json"
    if args.resume and _is_usable_json(score_out):
        cand["score"] = score_out
        return True
    cmd = [
        PYTHON,
        str(_skill_script("scorer", "run_score.py")),
        "score",
        "--extracted",
        str(cand["extracted"]),
        "--config",
        str(config_out),
        "--output",
        str(score_out),
    ]
    attempts, error = _run_with_retries(cmd, args.max_retries)
    if error:
        _record_failure(
            args,
            failures,
            Failure(source=cand["source"], stage="score", attempts=attempts, error_message=error),
        )
        return False
    cand["score"] = score_out
    return True


def _legacy_row(cand: dict) -> dict:
    """Build a comparison/ranking row from a successfully scored legacy candidate."""
    score = _load_json(cand["score"])
    dims = score.get("dimension_scores") or {}
    snapshot = score.get("full_snapshot") or {}
    suggestions = snapshot.get("interview_suggestions") or score.get("interview_suggestions") or []
    return {
        "refno": cand.get("refno"),
        "appno": cand.get("appno"),
        "display_label": cand.get("display_label") or format_candidate_label(cand.get("refno"), cand.get("appno")),
        # None on a single-post job, which has no post column to read (FR-2).
        "post": cand.get("post"),
        "total_score": score.get("total_score", 0),
        "tier": score.get("tier", ""),
        "skill_match": dims.get("skill_match", 0),
        "experience_match": dims.get("experience_match", 0),
        "education_match": dims.get("education_match", 0),
        "research_quality": dims.get("research_quality", 0),
        "suggestion_summary": " | ".join(s.get("text", "") for s in suggestions[:3]),
        "_extracted": cand["extracted"],
        "_score": cand["score"],
        "_source": cand["source"],
        "_slug": cand["slug"],
    }


# Rank the run's rows without ever merging post groups into one ordered list (FR-5).
# A single-post job keeps one ranking over every row, which is what it has always done.
# Returns the rows that belong to no post so the caller can ask HR instead of guessing (FR-7).
def _rank_rows(rows: list[dict], *, multi_post: bool) -> list[dict]:
    """Rank within each post group in place and return the rows that belong to no post."""
    if not multi_post:
        rows.sort(key=lambda r: r["total_score"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return []
    grouping = group_by_post(rows, multi_post=True)
    ranked: list[dict] = []
    for group in grouping.groups:
        group.rows.sort(key=lambda r: r["total_score"], reverse=True)
        for rank, row in enumerate(group.rows, start=1):
            row["rank"] = rank
        ranked.extend(group.rows)
    rows[:] = ranked
    return grouping.unassigned


# Build (or reuse) the legacy scoring config for one JD. A multi-post run gets one per post.
def _legacy_config(args: argparse.Namespace, out_dir: Path, jd_path: Path, name: str) -> Path:
    """Return the scoring config for one JD, building it with the scorer when not cached."""
    config_out = out_dir / name
    if not (args.resume and _is_usable_json(config_out)):
        _run(
            [
                PYTHON,
                str(_skill_script("scorer", "run_score.py")),
                "build-config",
                "--jd-structured",
                str(jd_path),
                "--output",
                str(config_out),
            ]
        )
    return config_out


def _run_legacy_engine(
    args: argparse.Namespace,
    out_dir: Path,
    jd_sources: JdSources,
    candidates: list[dict],
    failures: list[Failure],
) -> int:
    """Run build-config + score + rank + reports with the legacy ScorerService."""
    # One config per JD: the single JD of a single-post job, or one per post (FR-5).
    configs: dict[str, Path] = {}
    rows: list[dict] = []
    for cand in candidates:
        label = post_of(cand) if jd_sources.multi_post else None
        name = jd_sources.config_name(label)
        config_out = configs.get(name)
        if config_out is None:
            config_out = _legacy_config(args, out_dir, jd_sources.for_post(label), name)
            configs[name] = config_out
        if _score_legacy_candidate(args, cand, config_out, out_dir, failures):
            rows.append(_legacy_row(cand))
    unassigned = _rank_rows(rows, multi_post=jd_sources.multi_post)
    reports = _generate_reports(
        args, out_dir, rows, failures, jd_sources=jd_sources, unassigned=unassigned
    )
    return _build_manifest(
        args,
        out_dir,
        jd_sources,
        configs.get("config.json"),
        rows,
        reports,
        failures,
        engine="legacy",
        unassigned=unassigned,
    )


def _match_candidate(
    args: argparse.Namespace,
    cand: dict,
    jd_source: Path,
    reference_date: str,
    out_dir: Path,
    failures: list[Failure],
) -> dict | None:
    """Match one candidate. Returns a ranking row or None on failure."""
    detail_out = out_dir / f"detail-{cand['slug']}.json"
    if not (args.resume and _is_usable_json(detail_out)):
        cmd = [
            PYTHON,
            str(_skill_script("scorer", "run_score.py")),
            "match",
            "--jd-structured",
            str(jd_source),
            "--cv-extracted",
            str(cand["extracted"]),
            "--reference-date",
            reference_date,
            "--output",
            str(detail_out),
        ]
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=cand["source"], stage="match", attempts=attempts, error_message=error),
            )
            return None
    detail = _load_json(detail_out)
    dims = {
        (d.get("dimension_id") or ""): d.get("score")
        for d in (detail.get("radar_dimensions") or [])
        if isinstance(d, dict)
    }
    questions = detail.get("interview_questions") or []
    suggestion_summary = "; ".join(
        f"{q.get('priority', '')}:{q.get('template_id', '')}" for q in questions[:3]
    )
    return {
        "refno": cand.get("refno"),
        "appno": cand.get("appno"),
        "display_label": cand.get("display_label") or format_candidate_label(cand.get("refno"), cand.get("appno")),
        # None on a single-post job, which has no post column to read (FR-2).
        "post": cand.get("post"),
        "total_score": float(detail.get("match_score", 0)),
        "tier": detail.get("fit_band") or "",
        "skill_match": _radar_dim_score(dims, "core_skill_match"),
        "experience_match": _radar_dim_score(dims, "relevant_experience"),
        "education_match": _radar_dim_score(dims, "education_certification"),
        "suggestion_summary": suggestion_summary,
        "_extracted": cand["extracted"],
        "_detail": detail_out,
        "_source": cand["source"],
        "_slug": cand["slug"],
    }


def _run_matching_engine(
    args: argparse.Namespace,
    out_dir: Path,
    jd_sources: JdSources,
    candidates: list[dict],
    failures: list[Failure],
) -> int:
    """Run the matching engine per candidate and render modal-style radar/interview PDFs."""
    reference_date = args.reference_date or date.today().isoformat()
    rows: list[dict] = []
    for cand in candidates:
        # Each applicant is matched against their own post's effective JD (FR-5).
        label = post_of(cand) if jd_sources.multi_post else None
        row = _match_candidate(
            args, cand, jd_sources.for_post(label), reference_date, out_dir, failures
        )
        if row is not None:
            rows.append(row)
    unassigned = _rank_rows(rows, multi_post=jd_sources.multi_post)
    reports = _generate_reports(
        args, out_dir, rows, failures, jd_sources=jd_sources, unassigned=unassigned
    )
    return _build_manifest(
        args,
        out_dir,
        jd_sources,
        None,
        rows,
        reports,
        failures,
        engine="matching",
        unassigned=unassigned,
    )


# Loads the optional appno -> online resume URL map written by the collector.
def _load_resume_links(out_dir: Path) -> dict[str, str]:
    path = out_dir / RESUME_LINKS_JSON
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value}


# Variable keys from matching interview questions that may be published to HR reports.
# CV text must never reach reports, so only requirement/skill/context names are allowed.
PUBLIC_QUESTION_VARIABLE_KEYS = frozenset({"requirement", "skill", "context"})


# Public ranking fields plus radar tooltip/interview numbers from matching detail (allow-listed reasoning only, no raw CV text).
def _board_row(row: dict, resume_links: dict[str, str] | None = None) -> dict:
    public = {key: value for key, value in row.items() if not str(key).startswith("_")}
    if resume_links and row.get("appno"):
        resume_url = safe_http_url(resume_links.get(str(row.get("appno"))))
        if resume_url:
            public["resume_url"] = resume_url
    detail_path = row.get("_detail")
    if not detail_path:
        return public
    path = Path(detail_path)
    if not path.is_file():
        return public
    try:
        detail = _load_json(path)
    except (OSError, json.JSONDecodeError, TypeError):
        return public
    axes = public_radar_dimensions(detail)
    if axes:
        public["radar_dimensions"] = axes

    questions = []
    for item in detail.get("interview_questions") or []:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        entry = {
            "priority": item.get("priority"),
            "question": str(item.get("question"))[:240],
        }
        raw_variables = item.get("variables")
        if isinstance(raw_variables, dict):
            variables = {
                key: value for key, value in raw_variables.items() if key in PUBLIC_QUESTION_VARIABLE_KEYS
            }
        else:
            variables = {}
        template_id = item.get("template_id")
        if isinstance(template_id, str) and template_id and variables:
            entry["template_id"] = template_id
            entry["variables"] = variables
        questions.append(entry)
    if questions:
        public["interview_questions"] = questions[:8]
    return public


# HR-facing report folder (ranking HTML/XLSX and <appno>.html/.pdf).
def _report_dir(args: argparse.Namespace, out_dir: Path) -> Path:
    raw = getattr(args, "report_dir", None)
    if not raw:
        return out_dir
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Stable fingerprint for one candidate's PDF/HTML inputs (score JSON + rank + post).
def _row_report_fingerprint(args: argparse.Namespace, row: dict) -> str:
    return candidate_report_fingerprint(
        engine=getattr(args, "engine", None),
        position=args.position,
        refno=row.get("refno") or getattr(args, "refno", None),
        appno=row.get("appno"),
        rank=row.get("rank"),
        total_score=row.get("total_score"),
        tier=row.get("tier"),
        # An applicant moved to another post is scored against another JD, so their page
        # must be rebuilt even when the score happens to be identical (PRD Section 6).
        post=row.get("post"),
        artifact_paths=[row.get("_detail"), row.get("_score"), row.get("_extracted")],
    )


# Resolve report-gen JD inputs and a digest that invalidates the board when JD content changes.
def _report_jd_inputs(
    out_dir: Path, jd_sources: JdSources | None, jd_text: str | None
) -> tuple[str | None, str | None, str | None]:
    """Return (jd digest, raw JD text path arg, parsed JD JSON path arg)."""
    text_path: Path | None = None
    if jd_text:
        candidate = out_dir / "jd.txt"
        if not candidate.is_file():
            candidate = out_dir / "jd-context.txt"
        if not candidate.is_file():
            candidate = out_dir / "jd.txt"
            candidate.write_text(jd_text, encoding="utf-8")
        text_path = candidate
    # The board carries every post's JD panel, so its digest must cover every post's JD, not a
    # single one (PRD Section 6). A single-post run has exactly one path here, which reproduces
    # the digest this function has always produced.
    json_paths = [path for path in jd_sources.jd_paths if path.is_file()] if jd_sources else []
    json_path = jd_sources.default if jd_sources and jd_sources.default.is_file() else None
    digest_parts: list[str] = []
    if text_path is not None:
        digest_parts.append(f"text:{sha256_file(text_path)}")
    for path in sorted(json_paths, key=str):
        digest_parts.append(f"json:{sha256_file(path)}")
    jd_digest = sha256_text("|".join(digest_parts)) if digest_parts else None
    return jd_digest, str(text_path) if text_path else None, str(json_path) if json_path else None


def _generate_reports(
    args: argparse.Namespace,
    out_dir: Path,
    rows: list[dict],
    failures: list[Failure],
    *,
    jd_sources: JdSources | None = None,
    jd_text: str | None = None,
    unassigned: list[dict] | None = None,
) -> dict:
    """Generate per-candidate HTML/PDF and ranking overview (unless skipped)."""
    reports: dict = {}
    if args.skip_reports:
        return reports
    jd_text = jd_sources.text if jd_sources is not None else jd_text
    report_dir = _report_dir(args, out_dir)
    previous = load_fingerprints(out_dir)
    previous_candidates = previous.get("candidates") if isinstance(previous.get("candidates"), dict) else {}
    candidate_fps: dict[str, str] = {}
    for row in rows:
        stem = candidate_match_stem(row.get("appno") or row.get("display_label") or row["rank"])
        pdf_out = report_dir / f"{stem}.pdf"
        match_html = report_dir / f"{stem}.html"
        fingerprint = _row_report_fingerprint(args, row)
        candidate_fps[stem] = fingerprint
        reusable = (
            previous_candidates.get(stem) == fingerprint
            and pdf_out.is_file()
            and match_html.is_file()
        )
        if reusable:
            row["_pdf"] = pdf_out
            row["_report_reused"] = True
            continue
        cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "candidate",
            "--extracted",
            str(row["_extracted"]),
            "--position",
            args.position,
            "--rank",
            str(row["rank"]),
            "--output",
            str(pdf_out),
        ]
        if row.get("refno"):
            cmd += ["--refno", str(row["refno"])]
        if row.get("appno"):
            cmd += ["--appno", str(row["appno"])]
        if row.get("_detail"):
            cmd += ["--detail", str(row["_detail"])]
        else:
            cmd += ["--score", str(row["_score"])]
        attempts, error = _run_with_retries(cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=row["_source"], stage="report-gen", attempts=attempts, error_message=error),
            )
            continue
        row["_pdf"] = pdf_out
    if not rows:
        return reports
    resume_links = _load_resume_links(out_dir)
    comparison_rows = [_board_row(row, resume_links) for row in rows]
    # An applicant whose post could not be read is ranked nowhere, so the board must carry it in
    # its needs-confirmation block instead of dropping it (FR-7). They are appended after the
    # ranked rows, so every ranked row keeps its position and its matching board-row file.
    comparison_rows += [_board_row(row, resume_links) for row in (unassigned or [])]
    html_out = report_dir / RANKING_OVERVIEW_HTML
    # JD content feeds the board panel, so its digest must invalidate the cached board.
    jd_digest, jd_text_arg, jd_json_arg = _report_jd_inputs(out_dir, jd_sources, jd_text)
    # The board's sections follow the order their posts first appear in the ranked rows, which is
    # the order the CVs were handed to the run — the records page's own order (FR-6.3). The digest
    # has to carry it, or a reordered board would reuse the cached one rendered in the old order.
    post_order = (
        [group.label for group in group_by_post(rows, multi_post=True).groups]
        if jd_sources is not None and jd_sources.multi_post
        else []
    )
    board_fp = board_report_fingerprint(
        position=args.position,
        refno=getattr(args, "refno", None),
        candidate_fingerprints=candidate_fps,
        resume_links_digest=sha256_text(json.dumps(resume_links, sort_keys=True, ensure_ascii=False)),
        jd_digest=jd_digest,
        post_order=post_order,
    )
    reuse_board = previous.get("board") == board_fp and html_out.is_file()
    # A multi-post board is told about every post through post-jds.json. Rendering without it
    # would publish one ordered list across posts, which FR-5 forbids, so the run stops instead
    # of quietly shipping a merged ranking.
    post_jds_path = out_dir / POST_JDS_NAME
    board_blocked = jd_sources is not None and jd_sources.multi_post and not post_jds_path.is_file()
    if board_blocked:
        _record_failure(
            args,
            failures,
            Failure(
                source=str(html_out),
                stage="report-gen",
                attempts=0,
                error_message=(
                    "multi-post run has no post-jds.json, so the per-post board cannot be built; "
                    "refusing to merge every post's ranking into one list"
                ),
            ),
        )
    elif reuse_board:
        reports["ranking_overview_html"] = str(html_out)
        reports["screening_board_html"] = str(html_out)
    else:
        rows_out = out_dir / "rows.json"
        rows_out.write_text(json.dumps(comparison_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        html_cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "board",
            "--position",
            args.position,
            "--rows",
            str(rows_out),
            "--output",
            str(html_out),
        ]
        if getattr(args, "refno", None):
            html_cmd += ["--refno", str(args.refno)]
        if jd_text_arg:
            html_cmd += ["--jd-file", jd_text_arg]
        if jd_json_arg:
            html_cmd += ["--jd-json", jd_json_arg]
        # A multi-post board carries one section per post, so it needs each post's own effective
        # JD and delta, not just the shared base the panel above shows (FR-6.3).
        if jd_sources is not None and jd_sources.multi_post:
            html_cmd += ["--post-jds", str(post_jds_path)]
        attempts, error = _run_with_retries(html_cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=str(html_out), stage="report-gen", attempts=attempts, error_message=error),
            )
        else:
            reports["ranking_overview_html"] = str(html_out)
            reports["screening_board_html"] = str(html_out)
    for row, public in zip(rows, comparison_rows):
        if row.get("_report_reused"):
            continue
        stem = candidate_match_stem(row.get("appno") or public.get("appno") or row.get("rank"))
        match_html = report_dir / f"{stem}.html"
        row_path = out_dir / f"board-row-{stem}.json"
        row_path.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
        match_cmd = [
            PYTHON,
            str(_skill_script("report-gen", "run_report.py")),
            "match-html",
            "--position",
            args.position,
            "--row",
            str(row_path),
            "--output",
            str(match_html),
        ]
        # Each candidate page shows that applicant's own effective JD, not the shared base (FR-8).
        own_jd = None
        if jd_sources is not None and jd_sources.multi_post:
            own_jd = jd_sources.for_post(row.get("post"))
        own_jd_arg = str(own_jd) if own_jd is not None and own_jd.is_file() else jd_json_arg
        if own_jd_arg:
            match_cmd += ["--jd-json", own_jd_arg]
        attempts, error = _run_with_retries(match_cmd, args.max_retries)
        if error:
            _record_failure(
                args,
                failures,
                Failure(source=str(match_html), stage="report-gen", attempts=attempts, error_message=error),
            )
    reused = sum(1 for row in rows if row.get("_report_reused"))
    reports["reused_pdf_count"] = reused
    reports["generated_pdf_count"] = max(0, len(rows) - reused)
    reports["inputs_unchanged"] = bool(getattr(args, "_inputs_unchanged", False) and reuse_board and reused == len(rows))
    _persist_fingerprints(
        out_dir,
        args,
        {"candidates": candidate_fps, "board": board_fp},
    )
    return reports


# Summarise the post dimension for the manifest: one entry per post with its applicant count,
# its top applicant and score, plus the rows that could not be placed (FR-7, FR-11).
def _post_summary(rows: list[dict], unassigned: list[dict]) -> dict:
    """Return the manifest's post dimension: per-post counts plus needs-confirmation rows."""
    grouping = group_by_post(rows, multi_post=True)
    posts = []
    for group in grouping.groups:
        scores = [r.get("total_score") for r in group.rows if isinstance(r.get("total_score"), (int, float))]
        # The top of the post, never the top of the run: a rank is only meaningful inside its own
        # post, so the reply names each post's best applicant without comparing posts (FR-5).
        ranked = sorted(
            group.rows,
            key=lambda r: r.get("rank") if isinstance(r.get("rank"), int) else len(group.rows) + 1,
        )
        best = next((r for r in ranked if isinstance(r.get("total_score"), (int, float))), None)
        posts.append(
            {
                "post": group.label,
                "applicants": len(group.rows),
                "top_appno": best.get("appno") if best else None,
                "top_score": max(scores) if scores else None,
            }
        )
    needs_confirmation = [
        {
            "appno": row.get("appno"),
            # The raw value is carried through so HR can see exactly what the page said.
            "post": post_of(row),
        }
        for row in unassigned
    ]
    return {"posts": posts, "needs_confirmation": needs_confirmation}


def _build_manifest(
    args: argparse.Namespace,
    out_dir: Path,
    jd_sources: JdSources,
    config_out: Path | None,
    rows: list[dict],
    reports: dict,
    failures: list[Failure],
    engine: str,
    unassigned: list[dict] | None = None,
) -> int:
    """Print the pipeline result manifest to stdout and write manifest.json."""
    if rows and not failures:
        status = "success"
        exit_code = EXIT_OK
    elif rows and failures:
        status = "partial_success"
        exit_code = EXIT_OK
    else:
        status = "error"
        exit_code = EXIT_ERROR
    manifest_rows = []
    for row in rows:
        manifest_rows.append(
            {
                "rank": row["rank"],
                "refno": row.get("refno"),
                "appno": row.get("appno"),
                "display_label": row.get("display_label"),
                # None on a single-post job (FR-2).
                "post": row.get("post"),
                "source": row["_source"],
                "total_score": row["total_score"],
                "tier": row["tier"],
                "extracted_json": str(row["_extracted"]),
                "score_json": str(row["_score"]) if "_score" in row else None,
                "detail_json": str(row["_detail"]) if "_detail" in row else None,
                "report_pdf": str(row["_pdf"]) if "_pdf" in row else None,
            }
        )
    manifest = {
        "status": status,
        "engine": engine,
        "refno": args.refno,
        "output_dir": str(out_dir),
        "jd_source": str(jd_sources.default),
        "jd_overrides": getattr(args, "_jd_overrides", None),
        "config_json": str(config_out) if config_out else None,
        "multi_post": jd_sources.multi_post,
        "candidates": manifest_rows,
        "failures": [item.to_dict() for item in failures],
        "ask": None,
        "reports": reports,
        "inputs_unchanged": bool((reports or {}).get("inputs_unchanged")),
    }
    if jd_sources.multi_post:
        manifest.update(_post_summary(rows, unassigned or []))
    _persist_fingerprints(out_dir, args)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (out_dir / "manifest.json").write_text(text + "\n", encoding="utf-8")
    stream = sys.stdout if exit_code == EXIT_OK else sys.stderr
    print(text, file=stream)
    return exit_code


# Resolves a private scratch directory for downloaded files.
def _resolve_scratch_dir(scratch_dir: str) -> Path:
    path = Path(scratch_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


# Fetches URL inputs into local files and returns downloaded CV paths.
# Build the effective URL host allowlist: defaults + env + --allow-host flags.
def _effective_allowed_hosts(args: argparse.Namespace) -> tuple[str, ...]:
    extra = tuple(getattr(args, "allow_host", []) or [])
    return merge_allowed_hosts(ALLOWED_URL_HOSTS, extra_allowed_hosts_from_env(), extra)


# Resolve the job-state directory (default repo data/jas_state).
def _resolve_state_dir(args: argparse.Namespace) -> Path:
    raw = getattr(args, "state_dir", None) or "data/jas_state"
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _resolve_url_inputs(args: argparse.Namespace, out_dir: Path) -> list[Path]:
    downloaded_cvs: list[Path] = []
    allowed_hosts = _effective_allowed_hosts(args)
    base_url = getattr(args, "base_url", None)
    if args.jd_url:
        jd_text = asyncio.run(
            fetch_jd_text(args.jd_url, cookie_file=args.cookie_file, base_url=base_url, allowed_hosts=allowed_hosts)
        )
        dest = out_dir / "jd-from-url.txt"
        dest.write_text(jd_text, encoding="utf-8")
        args.jd_file = str(dest)
    if args.cv_url:
        scratch = _resolve_scratch_dir(args.scratch_dir)
        refno = getattr(args, "refno", None) or "job"
        state_dir = _resolve_state_dir(args)
        prev_cv_meta = load_job_state(state_dir, refno).get("cv_meta") or {}
        cv_meta: dict[str, dict[str, str]] = {}
        for url in args.cv_url:
            dest = scratch / cv_filename_for_url(url)
            prev_meta = prev_cv_meta.get(url) or {}
            downloaded, new_meta = asyncio.run(
                download_to_if_changed(
                    url,
                    dest,
                    cookie_file=args.cookie_file,
                    allowed_hosts=allowed_hosts,
                    etag=prev_meta.get("etag") if dest.is_file() else None,
                    last_modified=prev_meta.get("last_modified") if dest.is_file() else None,
                )
            )
            cv_meta[url] = new_meta if downloaded else prev_meta
            args.cv.append(str(dest))
            downloaded_cvs.append(dest)
        state = load_job_state(state_dir, refno)
        state["cv_meta"] = cv_meta
        save_job_state(state_dir, refno, state)
    return downloaded_cvs


def _run_pipeline(args: argparse.Namespace) -> int:
    """Execute every pipeline step and print a result manifest to stdout."""
    if args.polyu_detail_url and not args.polyu_ref:
        raise RuntimeError("--polyu-detail-url is only valid together with --polyu-ref")

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # HR's answer about previously saved conditions decides whether they are merged.
    args._conditions_confirmed = args.conditions == "confirmed"
    args._discard_conditions = args.conditions == "discard"
    if args._discard_conditions:
        # Screen against the job ad alone: drop the merged JD so nothing can pick it up.
        (out_dir / FINAL_JD_FILENAME).unlink(missing_ok=True)

    _enforce_input_policy(args, out_dir)
    if not args.refno:
        args.refno = refno_from_url(getattr(args, "jd_url", None)) or getattr(args, "polyu_ref", None)
    _collect_need_input(args)
    downloaded_cvs = _resolve_url_inputs(args, out_dir)
    _sync_resume_with_inputs(args, out_dir)
    try:
        failures: list[Failure] = []
        jd_sources = _resolve_jd_sources(args, out_dir)
        candidates = _parse_candidates(args, out_dir, jd_sources.text, failures)
        if args.engine == "matching":
            return _run_matching_engine(args, out_dir, jd_sources, candidates, failures)
        return _run_legacy_engine(args, out_dir, jd_sources, candidates, failures)
    finally:
        if getattr(args, "cleanup_cvs", False):
            for path in downloaded_cvs:
                path.unlink(missing_ok=True)


def _print_need_input(exc: NeedInputError) -> int:
    """Print a need_input (or conditions_pending) envelope and return exit code 2."""
    payload = {
        "status": exc.status,
        "missing": exc.missing,
        "questions": exc.questions,
        "ask": {"missing": exc.missing, "questions": exc.questions, **exc.details},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_NEED_INPUT


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full candidate screening pipeline end-to-end.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--jd-file", default=None, help="JD text file; parsed with the jd-parser skill.")
    source.add_argument("--jd-json", default=None, help="Existing parsed JD JSON (jd-parser output, polyu-parsed output, or pure structured_data).")
    source.add_argument("--polyu-ref", default=None, help="PolyU external ref; fetched and parsed with the polyu-import skill.")
    source.add_argument("--jd-url", default=None, help="JAS records page URL to fetch and parse as JD text.")
    parser.add_argument("--polyu-detail-url", default=None, help="PolyU detail URL fallback used with --polyu-ref.")
    parser.add_argument("--engine", choices=("legacy", "matching"), default="legacy", help="Scoring engine: legacy scorer (default) or matching engine with radar/interview detail.")
    parser.add_argument("--reference-date", default=None, help="Reference date YYYY-MM-DD used by the matching engine (default: today).")
    parser.add_argument("--cv", action="append", default=[], metavar="FILE", help="CV PDF to parse and score; repeatable.")
    parser.add_argument(
        "--cv-post",
        action="append",
        default=[],
        metavar="APPNO=POST",
        help="Post one applicant applied for, as <appno>=<post label>; repeatable. Supplying these makes "
        "the run multi-post: applicants are grouped by post and each group is scored against the JD of "
        "its own post. Omit entirely for a single-post job, which is unchanged.",
    )
    parser.add_argument("--cv-url", action="append", default=[], metavar="URL", help="JAS CV file URL to download (repeatable).")
    parser.add_argument("--extracted", action="append", default=[], metavar="FILE", help="Existing extracted candidate JSON; skips cv-parser; repeatable.")
    parser.add_argument("--trust-extracted", action="store_true", help="Allow --extracted profiles from outside --output-dir (trusted, pre-masked data only).")
    parser.add_argument("--cookie-file", default=None, help="Local Netscape cookies.txt used for authenticated JAS fetches.")
    parser.add_argument("--no-cookie", action="store_true", help="Allow unauthenticated JAS fetches for public demo hosts.")
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Extra allowlisted URL host (repeatable; public demo hosts).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for CV link resolution in fetched pages (public demo).",
    )
    parser.add_argument(
        "--conditions",
        choices=("confirmed", "discard"),
        default=None,
        help=(
            "What to do with conditions saved by an earlier conversation for this job. "
            "Omit to be asked (status conditions_pending); 'confirmed' applies them, "
            "'discard' screens against the job ad alone."
        ),
    )
    parser.add_argument("--scratch-dir", default="data/jas_scratch", help="Directory for downloaded CV files.")
    parser.add_argument(
        "--cleanup-cvs",
        action="store_true",
        help="Delete CVs downloaded from --cv-url after the run (default keeps them for reuse).",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Directory for per-refno job state (CV hashes/metadata; default repo data/jas_state).",
    )
    parser.add_argument("--position", default=None, help="Job title shown on reports (required unless --skip-reports).")
    parser.add_argument("--refno", default=None, help="Job reference number; together with application no. identifies a candidate (names are never shown).")
    parser.add_argument("--output-dir", default="data/pipeline_out", help="Directory for intermediate JSONs (default data/pipeline_out).")
    parser.add_argument("--report-dir", default=None, help="HR-facing report folder for ranking-overview.html and <appno>.html/.pdf (default: same as --output-dir).")
    parser.add_argument("--skip-reports", action="store_true", help="Score/rank only; skip HTML/PDF/Excel (do not use for HR runs).")
    parser.add_argument("--max-retries", type=int, default=2, metavar="N", help="Retries per candidate step after the first attempt (default 2).")
    parser.add_argument("--resume", action="store_true", help="Skip JD/CV/score steps when usable artifacts already exist in --output-dir.")
    parser.add_argument("--fail-fast", action="store_true", help="Abort the batch on the first per-candidate failure (legacy behavior).")
    args = parser.parse_args()

    try:
        return _run_pipeline(args)
    except NeedInputError as exc:
        return _print_need_input(exc)
    except Exception as exc:  # surface errors to the agent instead of a traceback
        print(json.dumps({"status": "error", "error_message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
