from __future__ import annotations

import json

import pytest

from src import __version__
from src.cli.linwp import COMMANDS, ExitCode, main

ARGS = {
    "scan": ["--display", "3840x2160"],
    "list": [
        "--ideal",
        "--display",
        "eDP-1",
        "--min-width",
        "1920",
        "--text-safe",
        "--sort",
        "score",
        "--limit",
        "20",
    ],
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


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_every_readme_command_is_stubbed() -> None:
    assert set(ARGS) == set(COMMANDS)


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_unimplemented_commands_exit_3_and_name_their_milestone(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command, *ARGS[command]]) == ExitCode.NOT_IMPLEMENTED == 3
    assert COMMANDS[command][0] in capsys.readouterr().err


def test_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "error": "not_implemented", "command": "doctor", "milestone": "M3"}


def test_no_command_is_a_usage_error() -> None:
    assert main([]) == ExitCode.USAGE


def test_cli_does_not_import_gtk() -> None:
    import subprocess
    import sys

    code = "import sys, src.cli.linwp; sys.exit(1 if 'gi' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
