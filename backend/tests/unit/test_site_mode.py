# Unit tests for the site switch (screening_core.site_mode).
from __future__ import annotations

import json
from pathlib import Path

import pytest

from screening_core import site_mode

REPO_ROOT = Path(__file__).resolve().parents[3]


# Write a site_profiles.json with the given default/profiles and return its folder.
def _write_profiles(tmp_path: Path, *, default: str | None = None, profiles: dict | None = None) -> Path:
    payload: dict = {}
    if default is not None:
        payload["default"] = default
    if profiles is not None:
        payload["profiles"] = profiles
    (tmp_path / site_mode.SITE_PROFILES_NAME).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


# prod spellings: 1 and prod, case-insensitive and trimmed.
@pytest.mark.parametrize("value", ["1", "prod", "PROD", " prod "])
def test_resolve_site_mode_prod_values(monkeypatch, value) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, value)
    assert site_mode.resolve_site_mode() == site_mode.MODE_PROD


# demo spellings: empty, 0, demo.
@pytest.mark.parametrize("value", ["", "0", "demo", "DEMO"])
def test_resolve_site_mode_demo_values(monkeypatch, value) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, value)
    assert site_mode.resolve_site_mode() == site_mode.MODE_DEMO


# An unset switch falls back to the demo profile.
def test_resolve_site_mode_unset_defaults_to_demo(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_DEMO


# An unrecognised value is refused: a typo must never silently screen on the demo site.
@pytest.mark.parametrize("value", ["production", "true", "yes", "2", "staging"])
def test_resolve_site_mode_refuses_unknown(monkeypatch, value) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, value)
    with pytest.raises(site_mode.SiteModeError):
        site_mode.resolve_site_mode()


# An explicit argument beats the env var.
def test_resolve_site_mode_explicit_wins(monkeypatch) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    assert site_mode.resolve_site_mode(site_mode.MODE_DEMO) == site_mode.MODE_DEMO


# The env var beats the profile file's default.
def test_resolve_site_mode_env_beats_file(monkeypatch, tmp_path) -> None:
    _write_profiles(tmp_path, default="demo")
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_PROD


# The file's default is used when the env var is unset.
def test_resolve_site_mode_file_default(monkeypatch, tmp_path) -> None:
    _write_profiles(tmp_path, default="prod")
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_PROD


# A bad value in the file is refused too.
def test_resolve_site_mode_refuses_bad_file_default(monkeypatch, tmp_path) -> None:
    _write_profiles(tmp_path, default="production")
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    with pytest.raises(site_mode.SiteModeError):
        site_mode.resolve_site_mode(repo_root=tmp_path)


# A JES_SITE_MODE line in the repo .env is honoured when the environment does not carry it:
# the CLIs resolve the mode before any settings object copies .env into the environment.
def test_resolve_site_mode_reads_env_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    (tmp_path / ".env").write_text("ZAI_API_KEY=x\nJES_SITE_MODE=1\n", encoding="utf-8")
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_PROD


# The real environment beats .env, so a one-off run can override the saved choice.
def test_resolve_site_mode_environment_beats_env_file(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("JES_SITE_MODE=1\n", encoding="utf-8")
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "demo")
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_DEMO


# A commented-out switch is not a switch: the file default still applies.
def test_resolve_site_mode_ignores_commented_env_file(monkeypatch, tmp_path) -> None:
    _write_profiles(tmp_path, default="prod")
    (tmp_path / ".env").write_text("# JES_SITE_MODE=1\n", encoding="utf-8")
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_PROD


# The quoted form common in hand-edited .env files is accepted.
def test_resolve_site_mode_env_file_quoted(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    (tmp_path / ".env").write_text('JES_SITE_MODE="1"\n', encoding="utf-8")
    assert site_mode.resolve_site_mode(repo_root=tmp_path) == site_mode.MODE_PROD


# A typo in .env is refused exactly like a typo in the environment.
def test_resolve_site_mode_refuses_bad_env_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(site_mode.SITE_MODE_ENV, raising=False)
    (tmp_path / ".env").write_text("JES_SITE_MODE=production\n", encoding="utf-8")
    with pytest.raises(site_mode.SiteModeError):
        site_mode.resolve_site_mode(repo_root=tmp_path)


# A file override replaces only the keys it names.
def test_site_profile_override(monkeypatch, tmp_path) -> None:
    _write_profiles(tmp_path, profiles={"prod": {"base_url": "https://jas.example.test"}})
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    profile = site_mode.site_profile(repo_root=tmp_path)
    assert profile["base_url"] == "https://jas.example.test"
    assert profile["records_url_template"] == site_mode.BUILTIN_PROFILES["prod"]["records_url_template"]


# The prod profile points at the internal records page and expects a login.
def test_site_profile_prod_shape(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    profile = site_mode.site_profile(repo_root=tmp_path)
    assert profile["mode"] == "prod"
    assert profile["list_url"] == "https://jobs.polyu.edu.hk/internal/records.php"
    assert profile["expects_login"] is True
    assert profile["allow_hosts"] == ["jobs.polyu.edu.hk"]


# The demo profile needs no login and lists from the site root.
def test_site_profile_demo_shape(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "0")
    profile = site_mode.site_profile(repo_root=tmp_path)
    assert profile["mode"] == "demo"
    assert profile["expects_login"] is False
    assert profile["list_url"] == "https://jes-web-demo.vercel.app/"


# The shipped site_profiles.json must agree with the built-ins, or reading the file would
# silently repoint a site.
def test_shipped_profiles_match_builtins() -> None:
    shipped = json.loads((REPO_ROOT / site_mode.SITE_PROFILES_NAME).read_text(encoding="utf-8"))
    assert shipped["default"] in (site_mode.MODE_DEMO, site_mode.MODE_PROD)
    for mode, builtin in site_mode.BUILTIN_PROFILES.items():
        for key, value in (shipped["profiles"].get(mode) or {}).items():
            assert builtin[key] == value, f"{mode}.{key} differs between the file and the built-in profile"


# The records URL is built from the active profile, and the mode argument wins over the env var.
def test_records_url_per_mode(monkeypatch) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    assert (
        site_mode.records_url_for_refno("2600827001")
        == "https://jobs.polyu.edu.hk/internal/records.php?refno=2600827001"
    )
    assert (
        site_mode.records_url_for_refno("2600827001", site_mode.MODE_DEMO)
        == "https://jes-web-demo.vercel.app/records.html?refno=2600827001"
    )


class _Args:
    # Stands in for a parsed argparse Namespace with the site-related flags.
    def __init__(self, **kwargs) -> None:
        self.site = None
        self.allow_host: list[str] = []
        self.no_cookie = False
        self.cookie_file = None
        self.__dict__.update(kwargs)


# The resolved mode is recorded on the namespace and the active host is allowlisted.
# The internal site expects a login, so the run is NOT declared cookie-free: the CLI must
# still be able to ask HR for JAS access when no cookie jar was given.
def test_apply_site_defaults_prod(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    args = _Args()
    profile = site_mode.apply_site_defaults(args, repo_root=tmp_path)
    assert args.site == "prod"
    assert args.allow_host == ["jobs.polyu.edu.hk"]
    assert args.no_cookie is False
    assert profile["mode"] == "prod"


# The demo site expects no login at all, so it runs cookie-free without HR being asked.
def test_apply_site_defaults_demo_is_cookie_free(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "0")
    args = _Args()
    site_mode.apply_site_defaults(args, repo_root=tmp_path)
    assert args.site == "demo"
    assert args.no_cookie is True


# An existing allow-host entry is kept, not replaced.
def test_apply_site_defaults_keeps_existing_hosts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "0")
    args = _Args(allow_host=["example.test"])
    site_mode.apply_site_defaults(args, repo_root=tmp_path)
    assert args.allow_host == ["example.test", "jes-web-demo.vercel.app"]


# An explicit cookie file means the run is not cookie-free.
def test_apply_site_defaults_respects_cookie_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "0")
    args = _Args(cookie_file="cookies.txt")
    site_mode.apply_site_defaults(args, repo_root=tmp_path)
    assert args.no_cookie is False


# The default state dir carries the site, so the two sites never share a baseline.
def test_default_state_dir_is_site_scoped(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "1")
    assert site_mode.default_state_dir(tmp_path) == tmp_path / "data" / "jas_state" / "prod"
    monkeypatch.setenv(site_mode.SITE_MODE_ENV, "0")
    assert site_mode.default_state_dir(tmp_path) == tmp_path / "data" / "jas_state" / "demo"


# A fresh pack is claimed and is safe to resume.
def test_claim_pack_site_first_run(tmp_path) -> None:
    work = tmp_path / "_pipeline"
    assert site_mode.claim_pack_site(work, "prod") is True
    marker = json.loads((work / site_mode.PACK_SITE_MARKER).read_text(encoding="utf-8"))
    assert marker["site"] == "prod"


# The same site keeps the pack resumable.
def test_claim_pack_site_same_site(tmp_path) -> None:
    work = tmp_path / "_pipeline"
    site_mode.claim_pack_site(work, "demo")
    (work / "detail-1.json").write_text("{}", encoding="utf-8")
    assert site_mode.claim_pack_site(work, "demo") is True
    assert (work / "detail-1.json").is_file()


# A pack from the other site is archived and must not be resumed.
def test_claim_pack_site_other_site_archives(tmp_path) -> None:
    work = tmp_path / "_pipeline"
    site_mode.claim_pack_site(work, "demo")
    (work / "detail-1.json").write_text("{}", encoding="utf-8")
    (work / "rows.json").write_text("{}", encoding="utf-8")
    assert site_mode.claim_pack_site(work, "prod") is False
    assert not (work / "detail-1.json").exists()
    backups = list(work.glob("_backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "detail-1.json").is_file()
    assert (backups[0] / "rows.json").is_file()


# HR's own answers survive the archive: they are authored, not derived from a run.
def test_claim_pack_site_keeps_hr_answers(tmp_path) -> None:
    work = tmp_path / "_pipeline"
    site_mode.claim_pack_site(work, "demo")
    (work / "jd-overrides.yaml").write_text("must_skills: []\n", encoding="utf-8")
    assert site_mode.claim_pack_site(work, "prod", keep=("jd-overrides.yaml",)) is False
    assert (work / "jd-overrides.yaml").is_file()
