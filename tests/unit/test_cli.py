"""``linwp`` end to end (M1 §2.9). The M1 subcommands do real work against a temporary catalogue under a
tmp ``$XDG`` home; the later-milestone subcommands still report the milestone that will implement them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import __version__
from src.cli.linwp import COMMANDS, ExitCode, main
from tests.helpers import imagegen

# subcommands that are implemented in M1 (P5b) versus those that still report a milestone
_M1 = {"scan", "list", "show", "displays", "exclude"}
_LATER = sorted(set(COMMANDS) - _M1)

ARGS = {
    "scan": ["--display", "3840x2160"],
    "list": ["--ideal", "--min-width", "1920", "--sort", "name", "--limit", "20"],
    "show": ["image.jpg"],
    "displays": [],
    "exclude": ["add", "**/thumbs/**", "--group", "Work documents"],
    "preview": ["image.jpg", "--surface", "splash", "--out", "/tmp/splash.png"],
    "plan": ["image.jpg", "--surface", "all"],
    "apply": ["image.jpg", "--surface", "desktop,lock", "--mode", "fill"],
    "undo": [],
    "history": [],
    "sync": ["--enable"],
    "doctor": [],
}


@pytest.fixture(autouse=True)
def _no_real_displays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the CLI suite off this machine's ``/sys/class/drm`` and ``xrandr``: the scan's display probe
    chain is empty, so detection is deterministic (declared displays still work)."""
    from src.cli import context

    monkeypatch.setattr(context, "service_probes", lambda root, env: [])


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp ``$XDG`` home plus a folder of two catalogue-visible (long-edge ≥ 1280) images."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    lib = tmp_path / "lib"
    lib.mkdir()
    imagegen.make_jpeg(lib, "alpha.jpg", size=(1600, 1000), seed=1)
    imagegen.make_jpeg(lib, "beta.jpg", size=(1600, 1000), seed=2)
    return lib


def _last_json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    return json.loads(lines[-1])


# ── argument surface (unchanged from M0) ─────────────────────────────────────────────────────────────────


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_every_readme_command_is_covered() -> None:
    assert set(ARGS) == set(COMMANDS)


def test_no_command_is_a_usage_error() -> None:
    assert main([]) == ExitCode.USAGE


def test_cli_does_not_import_gtk() -> None:
    import subprocess
    import sys

    code = "import sys, src.cli.linwp; sys.exit(1 if 'gi' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


# ── later-milestone commands still report their milestone ────────────────────────────────────────────────


@pytest.mark.parametrize("command", _LATER)
def test_later_commands_exit_3_and_name_their_milestone(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command, *ARGS[command]]) == ExitCode.NOT_IMPLEMENTED == 3
    assert COMMANDS[command][0] in capsys.readouterr().err


def test_json_output_of_a_later_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--json"]) == 3
    payload = _last_json(capsys)
    assert payload == {"ok": False, "error": "not_implemented", "command": "doctor", "milestone": "M3"}


# ── scan / list / show ───────────────────────────────────────────────────────────────────────────────────


def test_scan_then_list_json(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--add", str(library), "--json"]) == 0
    scan = _last_json(capsys)
    assert scan["ok"] is True
    assert scan["found"] == 2
    assert scan["result"] == "ok"

    assert main(["list", "--json"]) == 0
    listing = _last_json(capsys)
    assert listing["total"] == 2
    paths = {img["path"] for img in listing["images"]}  # type: ignore[index,union-attr]
    assert paths == {str(library / "alpha.jpg"), str(library / "beta.jpg")}


def test_scan_text_output(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--add", str(library)]) == 0
    out = capsys.readouterr().out
    assert "2 found" in out


def test_list_text_escapes_newline_in_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    lib = tmp_path / "lib"
    lib.mkdir()
    imagegen.make_jpeg(lib, "a\nb.jpg", size=(1600, 1000), seed=5)

    assert main(["scan", "--add", str(lib)]) == 0
    capsys.readouterr()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "a\\nb.jpg" in out  # the newline is escaped …
    assert "\na\nb.jpg" not in out  # … so a hostile name cannot forge a line


def test_show_by_path_json(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--add", str(library)]) == 0
    capsys.readouterr()
    assert main(["show", str(library / "alpha.jpg"), "--json"]) == 0
    payload = _last_json(capsys)
    assert payload["ok"] is True
    assert payload["path"] == str(library / "alpha.jpg")
    assert payload["width"] == 1600


def test_show_unknown_is_error(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["show", "/nope/missing.jpg", "--json"]) == 1
    payload = _last_json(capsys)
    assert payload == {"ok": False, "error": "not_found", "detail": "/nope/missing.jpg"}


def test_list_unknown_display_is_error(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--add", str(library)]) == 0
    capsys.readouterr()
    assert main(["list", "--ideal", "--display", "NO-SUCH-OUTPUT", "--json"]) == 1
    payload = _last_json(capsys)
    assert payload["error"] == "no_such_display"


# ── displays ─────────────────────────────────────────────────────────────────────────────────────────────


def test_displays_json(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["displays", "--json"]) == 0
    payload = _last_json(capsys)
    assert payload["ok"] is True
    assert "attempts" in payload


def test_displays_reports_declared(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["displays", "--display", "3840x2160", "--json"]) == 0
    payload = _last_json(capsys)
    sizes = {(d["width"], d["height"]) for d in payload["displays"]}  # type: ignore[index,union-attr]
    assert (3840, 2160) in sizes


def test_bad_display_spec_is_a_usage_error(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", "--add", str(library), "--display", "junk", "--json"]) == 2
    assert _last_json(capsys)["error"] == "bad_display"
    assert main(["displays", "--display", "1920xWRONG", "--json"]) == 2


# ── exclude ──────────────────────────────────────────────────────────────────────────────────────────────


def test_exclude_add_list_and_test_names_the_rule(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["scan", "--add", str(library)]) == 0
    capsys.readouterr()

    skip_dir = str(library / "sub")
    assert main(["exclude", "add", skip_dir, "--json"]) == 0
    rule_id = _last_json(capsys)["rule"]

    assert main(["exclude", "list", "--json"]) == 0
    rules = _last_json(capsys)["rules"]  # type: ignore[index]
    assert any(r["id"] == rule_id for r in rules)  # type: ignore[union-attr]

    # a path under the excluded folder would not be scanned, and the rule that stops it is named
    assert main(["exclude", "test", str(library / "sub" / "x.jpg"), "--json"]) == 0
    verdict = _last_json(capsys)
    assert verdict == {"ok": True, "scanned": False, "rule": rule_id}

    # `exclude test` always exits 0, even for a path that would be scanned
    assert main(["exclude", "test", str(library / "alpha.jpg"), "--json"]) == 0
    assert _last_json(capsys) == {"ok": True, "scanned": True, "rule": None}


def test_exclude_group_toggle(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["exclude", "add", str(library / "sub"), "--group", "Work", "--json"]) == 0
    capsys.readouterr()
    assert main(["exclude", "group", "disable", "Work", "--json"]) == 0
    assert _last_json(capsys) == {"ok": True, "group": "Work", "enabled": False}


def test_catalogue_error_exits_1_with_the_class_name(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``CatalogueError`` that escapes a handler is turned by ``main`` into exit 1 with the class name.
    Adding a rule scoped to a root that does not exist raises one from the writer."""
    rc = main(["exclude", "add", "/some/where", "--root", "/does/not/exist", "--json"])
    assert rc == ExitCode.ERROR == 1
    payload = _last_json(capsys)
    assert payload["ok"] is False
    assert payload["error"] == "CatalogueError"


def test_scan_writer_failure_exits_1_with_the_class_name(
    library: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer job that fails mid-scan makes ``scan()`` return ``result='error'``; §2.9 requires the CLI
    to exit 1 with the error class name in the JSON, not print a summary and exit 0. Bounded: no hang."""
    from src.catalogue import ingest
    from src.catalogue.db import CatalogueError

    def explode(*args: object, **kwargs: object) -> int:
        raise CatalogueError("catalogue on fire")

    monkeypatch.setattr(ingest, "_upsert_image", explode)

    rc = main(["scan", "--add", str(library), "--json"])
    assert rc == ExitCode.ERROR == 1
    payload = _last_json(capsys)
    assert payload["ok"] is False
    assert payload["error"] == "CatalogueError"
    assert payload["result"] == "error"
