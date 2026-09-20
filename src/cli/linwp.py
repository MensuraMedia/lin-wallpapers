"""linwp — the Lin Wallpapers command line.

Everything the GUI can do, without GTK. In M0 the argument surface is complete and every
subcommand except ``--version``/``--help`` reports the milestone that implements it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from enum import IntEnum

from src import __version__


class ExitCode(IntEnum):
    """The exit-code table (README §10)."""

    OK = 0
    ERROR = 1
    USAGE = 2
    NOT_IMPLEMENTED = 3
    NOTHING_TO_DO = 4
    PRECHECK_FAILED = 5
    ROLLED_BACK = 6
    AUTH_REFUSED = 7
    UNSUPPORTED_SURFACE = 8
    ROLLBACK_FAILED = 9


EXIT_CODE_HELP = """exit codes:
  0  success
  1  error
  2  usage error
  3  not implemented yet (names the milestone)
  4  nothing to do — already set
  5  precheck failed, nothing was changed
  6  failed and rolled back
  7  authorization refused, nothing was changed
  8  unsupported surface on this machine
  9  failed and the rollback failed (names the backup directory)
"""

# subcommand → (milestone, help)
COMMANDS: dict[str, tuple[str, str]] = {
    "scan": ("M1", "scan the configured roots"),
    "list": ("M1", "list catalogued images"),
    "displays": ("M1", "the display dimensions the scan measured, and from where"),
    "exclude": ("M1", "exclude folders, files, patterns or groups of them from the scan"),
    "show": ("M1", "metadata, score, badges and where an image is applied"),
    "preview": ("M3", "render a screen preview to a file"),
    "plan": ("M4", "print the apply plan, change nothing"),
    "apply": ("M4", "apply an image to one or more screens (privileged screens: M5)"),
    "undo": ("M4", "revert the last apply"),
    "history": ("M4", "list applies and undos"),
    "sync": ("M6", "enable or disable sync mode"),
    "doctor": ("M3", "capability probe: what this machine supports, and why not"),
}

SURFACES = "desktop,lock,login,splash,menu,all"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linwp",
        description="Lin Wallpapers: one wallpaper, every screen.",
        epilog=EXIT_CODE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"linwp {__version__}")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[shared], help=COMMANDS[name][1])

    scan = add("scan")
    scan.add_argument("--add", metavar="PATH", help="add a root and scan it")
    scan.add_argument("--display", metavar="WxH[,WxH...]", help="also judge for an unconnected display")

    add("displays")

    exclude = add("exclude")
    exclude.add_argument("action", choices=["add", "remove", "list", "test", "group"])
    exclude.add_argument("values", nargs="*", metavar="<path|glob|enable|disable NAME>")
    exclude.add_argument("--group", metavar="NAME", help="put the rule in a named group")
    exclude.add_argument("--root", metavar="PATH", help="apply the rule under one root only")

    listing = add("list")
    listing.add_argument("--min-width", type=int)
    listing.add_argument("--min-height", type=int)
    listing.add_argument("--ideal", action="store_true", help="images whose dimensions suit this desktop")
    listing.add_argument("--near-miss", action="store_true", help="images that almost fit, and why not")
    listing.add_argument("--display", metavar="NAME", help="with --ideal: one display only")
    listing.add_argument("--text-safe", action="store_true")
    listing.add_argument("--badge", action="append", default=[])
    listing.add_argument("--sort", choices=["score", "name", "date", "size", "resolution"])
    listing.add_argument("--limit", type=int)

    add("show").add_argument("image", metavar="<id|path>")

    preview = add("preview")
    preview.add_argument("image", metavar="<id|path>")
    preview.add_argument("--surface", required=True)
    preview.add_argument("--out", metavar="FILE")
    preview.add_argument("--live", action="store_true", help="run the real splash for 8 s (M5)")

    for name in ("plan", "apply"):
        command = add(name)
        command.add_argument("image", metavar="<id|path>")
        command.add_argument("--surface", default="all", help=f"comma-separated: {SURFACES}")
        command.add_argument("--mode", choices=["fill", "fit", "center", "stretch", "tile"], default="fill")
        if name == "apply":
            command.add_argument("--dry-run", action="store_true")

    add("undo").add_argument("--id", type=int, help="the apply to revert (default: the last one)")
    add("history")

    sync = add("sync")
    toggle = sync.add_mutually_exclusive_group()
    toggle.add_argument("--enable", action="store_true")
    toggle.add_argument("--disable", action="store_true")

    add("doctor")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return ExitCode.USAGE

    milestone = COMMANDS[args.command][0]
    message = f"linwp {args.command}: not implemented yet — arrives in {milestone}"
    if args.json:
        print(
            json.dumps(
                {"ok": False, "error": "not_implemented", "command": args.command, "milestone": milestone}
            )
        )
    else:
        print(message, file=sys.stderr)
    return ExitCode.NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
