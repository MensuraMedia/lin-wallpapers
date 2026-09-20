"""``linwp exclude add|remove|list|test|group …`` — exclusion rules and groups (M1 §2.9).

``add`` infers the rule kind from the value (a glob → PATTERN, otherwise FOLDER) and, after storing it,
re-evaluates the affected catalogue rows so an added rule takes effect at once. ``test PATH`` reports
whether the path would be scanned and, if not, which rule excludes it — and always exits 0. ``group
enable|disable NAME`` toggles a group (a locked group refuses). A refused pattern is a usage error (2).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from src.catalogue.db import (
    CatalogueError,
    Change,
    ChangeKind,
    add_rule,
    apply_exclusions,
    load_rules,
    remove_rule,
    set_group_enabled,
)
from src.cli.context import Context, emit_json, emit_text, escape_control, warn
from src.scanner.exclude import PatternError, RuleKind, compile_matcher

_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2

_GLOB_CHARS = set("*?[")


def _infer_kind(value: str) -> RuleKind:
    return RuleKind.PATTERN if any(ch in _GLOB_CHARS for ch in value) else RuleKind.FOLDER


def _add(args: argparse.Namespace, ctx: Context) -> int:
    if not args.values:
        warn("linwp exclude add: a path or glob is required")
        return _EXIT_USAGE
    value = args.values[0]
    kind = _infer_kind(value)

    def job(conn: sqlite3.Connection) -> int:
        return add_rule(conn, kind, value, group=args.group, root=args.root)

    try:
        rule_id = ctx.writer.submit(job).result()
    except PatternError as error:
        if args.json:
            emit_json({"ok": False, "error": "bad_pattern", "code": error.code.value})
        else:
            warn(f"linwp exclude add: {error}")
        return _EXIT_USAGE
    _reapply(ctx)
    ctx.feed.emit(Change(ChangeKind.RULES_CHANGED))
    if args.json:
        emit_json({"ok": True, "rule": rule_id, "kind": kind.value, "value": value})
    else:
        emit_text(f"added rule {rule_id}: {kind.value} {escape_control(value)}")
    return _EXIT_OK


def _remove(args: argparse.Namespace, ctx: Context) -> int:
    if not args.values or not args.values[0].isdigit():
        warn("linwp exclude remove: a numeric rule id is required")
        return _EXIT_USAGE
    rule_id = int(args.values[0])

    def job(conn: sqlite3.Connection) -> None:
        remove_rule(conn, rule_id)

    ctx.writer.submit(job).result()
    _reapply(ctx)
    ctx.feed.emit(Change(ChangeKind.RULES_CHANGED))
    if args.json:
        emit_json({"ok": True, "removed": rule_id})
    else:
        emit_text(f"removed rule {rule_id}")
    return _EXIT_OK


def _list(args: argparse.Namespace, ctx: Context) -> int:
    conn = ctx.read()
    rules, groups = load_rules(conn)
    if args.json:
        emit_json(
            {
                "ok": True,
                "groups": [
                    {"id": g.id, "key": g.key, "name": g.name, "locked": g.locked, "enabled": g.enabled}
                    for g in groups
                ],
                "rules": [
                    {
                        "id": r.id,
                        "kind": r.kind.value,
                        "value": r.value,
                        "group_id": r.group_id,
                        "enabled": r.enabled,
                    }
                    for r in rules
                ],
            }
        )
    else:
        for group in groups:
            state = "on" if group.enabled else "off"
            lock = " (locked)" if group.locked else ""
            emit_text(f"[{group.id}] {group.name}: {state}{lock}")
        for rule in rules:
            state = "" if rule.enabled else " (disabled)"
            emit_text(f"  {rule.id:>4}  {rule.kind.value:<7} {escape_control(rule.value)}{state}")
    return _EXIT_OK


def _test(args: argparse.Namespace, ctx: Context) -> int:
    """Always exit 0 (contract §2.9): a query about a path, not an action."""
    if not args.values:
        if args.json:
            emit_json({"ok": True, "scanned": True, "rule": None})
        else:
            emit_text("a path is required")
        return _EXIT_OK
    path = str(Path(args.values[0]).expanduser().absolute())
    conn = ctx.read()
    rules, groups = load_rules(conn)
    includes = [row["path"] for row in conn.execute("SELECT path FROM root WHERE enabled = 1")]
    matcher = compile_matcher(rules, groups, includes=includes, home=str(Path.home()))
    hit = matcher.match_path(path)
    scanned = hit is None
    rule_id = None if hit is None else hit.rule_id
    if args.json:
        emit_json({"ok": True, "scanned": scanned, "rule": rule_id})
    elif scanned:
        emit_text(f"{escape_control(path)}: would be scanned")
    else:
        emit_text(f"{escape_control(path)}: excluded by rule {rule_id}")
    return _EXIT_OK


def _group(args: argparse.Namespace, ctx: Context) -> int:
    if len(args.values) < 2 or args.values[0] not in ("enable", "disable"):
        warn("linwp exclude group: use 'enable NAME' or 'disable NAME'")
        return _EXIT_USAGE
    on = args.values[0] == "enable"
    name = args.values[1]

    def job(conn: sqlite3.Connection) -> None:
        set_group_enabled(conn, name, on)

    try:
        ctx.writer.submit(job).result()
    except CatalogueError as error:
        if args.json:
            emit_json({"ok": False, "error": type(error).__name__, "detail": str(error)})
        else:
            warn(f"linwp exclude group: {error}")
        return _EXIT_ERROR
    _reapply(ctx)
    ctx.feed.emit(Change(ChangeKind.RULES_CHANGED))
    if args.json:
        emit_json({"ok": True, "group": name, "enabled": on})
    else:
        emit_text(f"group {name}: {'enabled' if on else 'disabled'}")
    return _EXIT_OK


def _reapply(ctx: Context) -> None:
    """Recompute ``image.excluded_by`` for every row against the current rules."""

    def job(conn: sqlite3.Connection) -> None:
        rules, groups = load_rules(conn)
        includes = [row["path"] for row in conn.execute("SELECT path FROM root WHERE enabled = 1")]
        matcher = compile_matcher(rules, groups, includes=includes, home=str(Path.home()))
        apply_exclusions(conn, matcher)

    ctx.writer.submit(job).result()


_ACTIONS = {
    "add": _add,
    "remove": _remove,
    "list": _list,
    "test": _test,
    "group": _group,
}


def run(args: argparse.Namespace, ctx: Context) -> int:
    return _ACTIONS[args.action](args, ctx)
