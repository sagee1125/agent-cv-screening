"""Unit tests for the release updater's dependency-failure handling.

`apply_update()` must not advance the installed version stamp when the
dependency re-install fails (PyPI unreachable is the usual cause): the engine
files are already refreshed, and keeping the old stamp makes the next
conversation retry the whole update instead of a half-applied one being
reported as done.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATE_ENGINE = REPO_ROOT / "release" / "payload" / "scripts" / "update_engine.py"


def load_module():
    spec = importlib.util.spec_from_file_location("update_engine_under_test", UPDATE_ENGINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_installed_engine(root: Path, version: str = "1.1.8", requirements: str = "reportlab==4.0\n") -> None:
    """A minimal installed engine: stamp, requirements, and a fake venv interpreter."""
    (root / "scripts").mkdir(parents=True)
    # Bytes, not write_text: real installs carry the zip's LF endings, and the
    # digest comparison below must not be defeated by Windows newline
    # translation in the fixture.
    (root / "requirements.txt").write_bytes(requirements.encode("utf-8"))
    (root / "version.json").write_text(
        json.dumps({"version": version, "requirements_sha256": "old-digest"}), encoding="utf-8"
    )
    venv_exe = root / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    venv_exe.parent.mkdir(parents=True, exist_ok=True)
    venv_exe.write_text("", encoding="utf-8")


def make_payload(tmp_path: Path, version: str = "1.1.9", requirements: str = "reportlab==4.1\n") -> Path:
    """A minimal release package: new stamp, changed requirements, one marker file."""
    payload = tmp_path / f"payload-{version}.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "engine/version.json",
            json.dumps({"version": version, "requirements_sha256": "new-digest"}),
        )
        archive.writestr("engine/requirements.txt", requirements)
        archive.writestr("engine/.codex/marker.py", "# new engine code\n")
    return payload


def run_apply(monkeypatch, root: Path, payload: Path, pip_rc: int, quiet: bool = True):
    module = load_module()
    pip_calls: list[list[str]] = []
    busted: list[bool] = []

    monkeypatch.setattr(module, "engine_root", lambda: root)
    monkeypatch.setitem(
        sys.modules,
        "setup_engine",
        types.SimpleNamespace(
            install_expert=lambda *args, **kwargs: None,
            install_launcher_files=lambda *args, **kwargs: None,
            sha256_of=lambda path: "new-digest",
            workbuddy_config_dir=lambda: Path("/unused"),
        ),
    )
    monkeypatch.setattr(module, "bust_score_caches", lambda quiet_flag: busted.append(quiet_flag) or 0)
    fake_subprocess = SimpleNamespace(
        run=lambda cmd, check=False: pip_calls.append(cmd) or SimpleNamespace(returncode=pip_rc)
    )
    monkeypatch.setattr(module, "subprocess", fake_subprocess)

    module.apply_update(payload, quiet=quiet)
    return pip_calls, busted


def read_stamp(root: Path) -> dict:
    return json.loads((root / "version.json").read_text(encoding="utf-8"))


def test_failed_dependency_install_keeps_the_old_stamp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "engine"
    make_installed_engine(root)
    payload = make_payload(tmp_path)

    pip_calls, busted = run_apply(monkeypatch, root, payload, pip_rc=1)

    # The dependency step ran and failed, so the stamp was kept at the old
    # version: the next conversation retries the whole update.
    assert len(pip_calls) == 1
    assert read_stamp(root)["version"] == "1.1.8"
    # Cache invalidation only accompanies a completed update.
    assert busted == []
    # The engine files themselves were still refreshed (the retry is a no-op copy).
    assert (root / ".codex" / "marker.py").read_text(encoding="utf-8").startswith("# new")


def test_successful_dependency_install_advances_the_stamp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "engine"
    make_installed_engine(root)
    payload = make_payload(tmp_path)

    pip_calls, busted = run_apply(monkeypatch, root, payload, pip_rc=0)

    assert len(pip_calls) == 1
    stamp = read_stamp(root)
    assert stamp["version"] == "1.1.9"
    assert stamp["requirements_sha256"] == "new-digest"
    assert busted == [True]


def test_unchanged_requirements_skip_pip_but_still_advance(tmp_path, monkeypatch) -> None:
    root = tmp_path / "engine"
    make_installed_engine(root, requirements="reportlab==4.1\n")
    payload = make_payload(tmp_path, requirements="reportlab==4.1\n")

    pip_calls, busted = run_apply(monkeypatch, root, payload, pip_rc=0)

    assert pip_calls == []
    assert read_stamp(root)["version"] == "1.1.9"
    assert busted == [True]
