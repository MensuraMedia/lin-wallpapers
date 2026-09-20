"""scanner/exclude.py — rule kinds, groups, builtins, validation, hostile input, the walker contract, perf.

Glob semantics live in test_exclude_glob.py, precedence/includes/volumes in test_exclude_precedence.py.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable, Mapping

import pytest

from src.scanner.exclude import (
    BUILTIN_GROUPS,
    MAX_PATH_CHARS,
    Group,
    Matcher,
    PatternError,
    PatternErrorCode,
    Rule,
    RuleHit,
    RuleKind,
    compile_matcher,
    normalize_path,
    validate_rule,
)

HOME = "/home/u"


# ── builders shared by the three exclude test modules ────────────────────────────────────────────────────


def folder(rule_id: int, value: str, **kw: object) -> Rule:
    return Rule(rule_id, RuleKind.FOLDER, value, **kw)  # type: ignore[arg-type]


def file_(rule_id: int, value: str, **kw: object) -> Rule:
    return Rule(rule_id, RuleKind.FILE, value, **kw)  # type: ignore[arg-type]


def pattern(rule_id: int, value: str, **kw: object) -> Rule:
    return Rule(rule_id, RuleKind.PATTERN, value, **kw)  # type: ignore[arg-type]


def user_group(group_id: int, *, enabled: bool = True, locked: bool = False, builtin: bool = False) -> Group:
    return Group(group_id, f"g{group_id}", f"Group {group_id}", builtin, locked, enabled)


def build(
    rules: Iterable[Rule],
    groups: Iterable[Group] = (),
    *,
    includes: Iterable[str] = (),
    mounts: Mapping[str, str] | None = None,
    home: str = HOME,
) -> Matcher:
    if mounts is None:
        return compile_matcher(rules, groups, includes=includes, home=home)
    return compile_matcher(rules, groups, includes=includes, home=home, mounts=mounts)


def builtin_seed(disabled: Iterable[str] = ()) -> tuple[list[Group], list[Rule]]:
    """What the catalogue seeds from BUILTIN_GROUPS: group ids 1…7, rule ids from 1 in table order."""
    off = set(disabled)
    groups: list[Group] = []
    rules: list[Rule] = []
    for group_id, builtin in enumerate(BUILTIN_GROUPS, start=1):
        groups.append(
            Group(group_id, builtin.key, builtin.name, True, builtin.locked, builtin.key not in off)
        )
        for kind, value in builtin.rules:
            rules.append(Rule(len(rules) + 1, kind, value, group_id=group_id))
    return groups, rules


def rule_id(matcher: Matcher, path: str, is_dir: bool = False) -> int | None:
    hit = matcher.match(path, is_dir)
    return hit.rule_id if hit is not None else None


def seeded_rule_id(rules: Iterable[Rule], value: str) -> int:
    return next(rule.id for rule in rules if rule.value == value)


def timing_is_meaningful() -> bool:
    """False under a line tracer (``pytest --cov``): it slows pure-Python loops by an order of magnitude."""
    return sys.gettrace() is None


# ── rule kinds ───────────────────────────────────────────────────────────────────────────────────────────


def test_no_rules_excludes_nothing() -> None:
    matcher = build([])
    assert matcher.match("/home/u/Pictures/a.jpg", False) is None
    assert matcher.match("/home/u/Pictures", True) is None
    assert matcher.match("/", True) is None
    assert matcher.match_path("/home/u/Pictures/a.jpg") is None
    assert matcher.match_inode(1, 2) is None
    assert matcher.inert_rule_ids == frozenset()
    assert matcher.invalid_rules == {}


@pytest.mark.parametrize(
    ("path", "is_dir", "expected"),
    [
        ("/data/photos/scans-2009", True, 1),  # the folder itself: pruned
        ("/data/photos/scans-2009/a.jpg", False, 1),
        ("/data/photos/scans-2009/deep/er/a.jpg", False, 1),
        ("/data/photos/scans-2009/deep", True, 1),
        ("/data/photos/scans-2009x", True, None),  # a name that merely starts the same
        ("/data/photos/scans-2009x/a.jpg", False, None),
        ("/data/photos/scans-200", True, None),
        ("/data/photos", True, None),
        ("/data/photos/other.jpg", False, None),
        ("/DATA/photos/scans-2009", True, None),  # case-sensitive (ruling Q9)
    ],
)
def test_folder_rule_excludes_the_directory_and_everything_beneath(
    path: str, is_dir: bool, expected: int | None
) -> None:
    matcher = build([folder(1, "/data/photos/scans-2009")])
    assert rule_id(matcher, path, is_dir) == expected


def test_folder_rule_hit_is_attributable() -> None:
    matcher = build([folder(7, "/data/x", group_id=3)], [user_group(3)])
    assert matcher.match("/data/x/y.jpg", False) == RuleHit(7, RuleKind.FOLDER, 3)


def test_file_rule_excludes_exactly_one_path() -> None:
    matcher = build([file_(4, "~/Pictures/id-card.jpg")])
    assert matcher.match("/home/u/Pictures/id-card.jpg", False) == RuleHit(4, RuleKind.FILE, None)
    assert matcher.match("/home/u/Pictures/id-card.jpg.bak", False) is None
    assert matcher.match("/home/u/Pictures/other.jpg", False) is None
    assert matcher.match("/home/u/Pictures", True) is None


def test_folder_rule_naming_what_turns_out_to_be_a_file_excludes_that_file() -> None:
    matcher = build([folder(1, "/data/thing"), pattern(2, "*.jpg")], includes=["/pics/one.jpg"])
    assert rule_id(matcher, "/data/thing", False) == 1
    assert rule_id(matcher, "/pics/one.jpg", False) == 2  # an include on a file changes nothing here


def test_file_rule_does_not_prune_a_directory_of_the_same_name() -> None:
    matcher = build([file_(1, "/data/thing")])
    assert matcher.match("/data/thing", True) is None
    assert matcher.match("/data/thing/a.jpg", False) is None


def test_pattern_rule_excludes_matching_files_and_folders() -> None:
    matcher = build([pattern(1, "**/thumbs/**"), pattern(2, "*.screenshot.png"), pattern(3, "IMG_E*.jpg")])
    assert rule_id(matcher, "/p/thumbs", True) == 1
    assert rule_id(matcher, "/p/thumbs/a.jpg") == 1
    assert rule_id(matcher, "/p/x.screenshot.png") == 2
    assert rule_id(matcher, "/p/IMG_E0012.jpg") == 3
    assert rule_id(matcher, "/p/IMG_0012.jpg") is None


def test_disabled_rule_never_matches() -> None:
    matcher = build(
        [
            folder(1, "/a", enabled=False),
            file_(2, "/b.jpg", enabled=False),
            pattern(3, "*.png", enabled=False),
        ]
    )
    assert matcher.match("/a/x.jpg", False) is None
    assert matcher.match("/b.jpg", False) is None
    assert matcher.match("/c.png", False) is None


def test_tilde_is_expanded_from_the_injected_home_only() -> None:
    matcher = build([folder(1, "~/.cache"), folder(2, "~")], home="/srv/homes/ann/")
    assert rule_id(matcher, "/srv/homes/ann/.cache/x.png") == 1
    assert rule_id(matcher, "/srv/homes/ann/x.png") == 2
    assert rule_id(matcher, "/home/u/.cache/x.png") is None


def test_a_relative_home_is_refused() -> None:
    with pytest.raises(PatternError) as caught:
        build([], home="home/u")
    assert caught.value.code is PatternErrorCode.BAD_PATH


# ── groups ───────────────────────────────────────────────────────────────────────────────────────────────


def test_group_switches_its_rules_as_one_unit() -> None:
    rules = [
        folder(1, "/work", group_id=5),
        pattern(2, "*.psd.png", group_id=5),
        file_(3, "/x/y.jpg", group_id=5),
    ]
    on = build(rules, [user_group(5, enabled=True)])
    off = build(rules, [user_group(5, enabled=False)])
    for path in ("/work/a.jpg", "/p/a.psd.png", "/x/y.jpg"):
        assert on.match(path, False) is not None
        assert off.match(path, False) is None


def test_group_off_leaves_stand_alone_rules_alone() -> None:
    matcher = build([folder(1, "/work", group_id=5), folder(2, "/other")], [user_group(5, enabled=False)])
    assert rule_id(matcher, "/work/a.jpg") is None
    assert rule_id(matcher, "/other/a.jpg") == 2


def test_locked_group_cannot_be_disabled() -> None:
    locked_but_off = user_group(1, enabled=False, locked=True, builtin=True)
    matcher = build(
        [folder(1, "/proc", group_id=1), folder(2, "/sys", group_id=1, enabled=False)], [locked_but_off]
    )
    assert rule_id(matcher, "/proc/1/x.png") == 1
    assert rule_id(matcher, "/sys/x.png") == 2  # not even rule by rule


def test_rule_of_an_unknown_group_counts_as_a_stand_alone_rule() -> None:
    matcher = build([folder(1, "/a", group_id=99)])
    assert matcher.match("/a/x.jpg", False) == RuleHit(1, RuleKind.FOLDER, 99)
    assert matcher.explain("/a/x.jpg").group is None


# ── the builtin table ────────────────────────────────────────────────────────────────────────────────────


def test_builtin_table_has_the_seven_groups_of_the_concept() -> None:
    assert [group.key for group in BUILTIN_GROUPS] == [
        "system",
        "snapshots",
        "caches",
        "code",
        "games",
        "ui_assets",
        "app_data",
    ]
    assert [group.key for group in BUILTIN_GROUPS if group.locked] == ["system"]
    assert len({group.name for group in BUILTIN_GROUPS}) == 7


@pytest.mark.parametrize(
    ("kind", "value"), [rule for group in BUILTIN_GROUPS for rule in group.rules], ids=lambda v: str(v)
)
def test_every_builtin_rule_validates(kind: RuleKind, value: str) -> None:
    validate_rule(kind, value)
    assert kind is not RuleKind.FILE


def test_builtins_compile_without_invalid_rules_and_keep_tilde_as_data() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups)
    assert matcher.invalid_rules == {}
    assert any(value.startswith("~/") for group in BUILTIN_GROUPS for _kind, value in group.rules)
    assert all(not value.startswith("/home") for group in BUILTIN_GROUPS for _kind, value in group.rules)


@pytest.mark.parametrize(
    ("path", "is_dir", "group_key"),
    [
        ("/proc", True, "system"),
        ("/sys/class/drm", True, "system"),
        ("/var/lib/x/a.png", False, "system"),
        ("/timeshift", True, "snapshots"),
        ("/mnt/d/.snapshots", True, "snapshots"),
        ("/mnt/d/.Trash-1000", True, "snapshots"),
        ("/mnt/d/lost+found", True, "snapshots"),
        ("/home/u/.cache", True, "caches"),
        ("/home/u/Pictures/.thumbnails", True, "caches"),
        ("/home/u/.mozilla", True, "caches"),
        ("/home/u/src/app/.git", True, "code"),
        ("/home/u/src/app/node_modules", True, "code"),
        ("/home/u/src/app/node_modules/pkg/logo.png", False, "code"),
        ("/home/u/.steam", True, "games"),
        ("/mnt/games/steamapps", True, "games"),
        ("/usr/share/icons", True, "ui_assets"),
        ("/opt/app/textures", True, "ui_assets"),
        ("/home/u/.config", True, "app_data"),
        ("/home/u/.local/share", True, "app_data"),
        ("/home/u/snap", True, "app_data"),
        ("/home/u/Pictures", True, None),
        ("/home/u/Pictures/holiday/a.jpg", False, None),
        ("/home/u/.local", True, None),
        ("/usr/share/backgrounds/a.jpg", False, None),
    ],
)
def test_builtin_groups_exclude_what_the_concept_lists(
    path: str, is_dir: bool, group_key: str | None
) -> None:
    groups, rules = builtin_seed()
    hit = build(rules, groups, includes=[HOME]).match(path, is_dir)
    key = None if hit is None else next(g.key for g in groups if g.id == hit.group_id)
    assert key == group_key


def test_a_builtin_group_can_be_switched_off_but_the_locked_one_cannot() -> None:
    groups, rules = builtin_seed(disabled=["code", "system"])
    matcher = build(rules, groups)
    assert matcher.match("/home/u/src/app/node_modules", True) is None
    assert matcher.match("/proc", True) is not None


def test_builtin_exception_is_an_include_only_while_its_group_is_on() -> None:
    groups, rules = builtin_seed()
    assert build(rules, groups).includes == ("/home/u/.local/share/backgrounds",)
    groups, rules = builtin_seed(disabled=["app_data"])
    assert build(rules, groups).includes == ()


def test_application_data_except_backgrounds() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=[HOME])
    assert matcher.match("/home/u/.local/share/backgrounds/a.jpg", False) is None
    assert matcher.match_path("/home/u/.local/share/backgrounds/a.jpg") is None
    assert matcher.match_path("/home/u/.local/share/other/a.jpg") is not None
    # The walker prunes ~/.local/share and is told which includes it has to visit separately.
    assert matcher.match("/home/u/.local/share", True) is not None
    assert matcher.includes_under("/home/u/.local/share") == ("/home/u/.local/share/backgrounds",)
    assert matcher.includes_under("/home/u/.local/share/backgrounds") == ()
    assert matcher.includes_under("/home/u/Pictures") == ()


def test_includes_under_leaves_out_includes_that_are_excluded_anyway() -> None:
    matcher = build([folder(1, "/data"), folder(2, "/data/keep/private")], includes=["/data/keep/private/x"])
    assert matcher.includes_under("/data") == ()  # user rules beat includes (ruling Q8)


# ── validation ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "value", "code"),
    [
        (RuleKind.FOLDER, "", PatternErrorCode.EMPTY),
        (RuleKind.FILE, "", PatternErrorCode.EMPTY),
        (RuleKind.FOLDER, "/", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FOLDER, "//", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FOLDER, "/.", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FOLDER, "/a/..", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FOLDER, "/../..", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FILE, "/", PatternErrorCode.MATCHES_EVERYTHING),
        (RuleKind.FOLDER, "/a\0b", PatternErrorCode.NUL),
        (RuleKind.FILE, "/a\0", PatternErrorCode.NUL),
        (RuleKind.FOLDER, "/" + "a" * MAX_PATH_CHARS, PatternErrorCode.TOO_LONG),
        (RuleKind.FOLDER, "relative/dir", PatternErrorCode.BAD_PATH),
        (RuleKind.FOLDER, "./dir", PatternErrorCode.BAD_PATH),
        (RuleKind.FOLDER, "-rf", PatternErrorCode.BAD_PATH),
        (RuleKind.FILE, "~other/x.jpg", PatternErrorCode.BAD_PATH),
        (RuleKind.FOLDER, "   ", PatternErrorCode.BAD_PATH),
    ],
)
def test_path_rules_refused(kind: RuleKind, value: str, code: PatternErrorCode) -> None:
    with pytest.raises(PatternError) as caught:
        validate_rule(kind, value)
    assert caught.value.code is code
    assert caught.value.reason and str(caught.value) == caught.value.reason
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", PatternErrorCode.EMPTY),
        (".", PatternErrorCode.MATCHES_EVERYTHING),
        ("/", PatternErrorCode.MATCHES_EVERYTHING),
        ("a/../..", PatternErrorCode.BAD_PATH),
        ("../x", PatternErrorCode.BAD_PATH),
        ("x\0", PatternErrorCode.NUL),
    ],
)
def test_volume_relative_path_rules_refused(value: str, code: PatternErrorCode) -> None:
    with pytest.raises(PatternError) as caught:
        validate_rule(RuleKind.FOLDER, value, volume_relative=True)
    assert caught.value.code is code


@pytest.mark.parametrize(
    "value",
    ["/a", "~", "~/x", "/-rf", "/a b/c\nd", "/ü/日本", "/a/./b/../c/", "/" + "a" * (MAX_PATH_CHARS - 1)],
)
def test_path_rules_accepted(value: str) -> None:
    validate_rule(RuleKind.FOLDER, value)
    validate_rule(RuleKind.FILE, value)


def test_volume_relative_values_accepted() -> None:
    validate_rule(RuleKind.FOLDER, "DCIM/old", volume_relative=True)
    validate_rule(RuleKind.FILE, "/DCIM/./a/../b.jpg", volume_relative=True)


def test_an_invalid_stored_rule_is_reported_and_never_matches() -> None:
    matcher = build(
        [
            folder(1, "/"),
            pattern(2, "**"),
            folder(3, "relative"),
            pattern(4, "[abc"),
            folder(5, "~", enabled=True),
            folder(6, "/ok"),
            folder(7, "/x", root="not/absolute"),
            pattern(8, "**", enabled=False),  # disabled: not even looked at
        ],
        home="/",
    )
    assert dict(matcher.invalid_rules) == {
        1: PatternErrorCode.MATCHES_EVERYTHING,
        2: PatternErrorCode.MATCHES_EVERYTHING,
        3: PatternErrorCode.BAD_PATH,
        4: PatternErrorCode.BAD_CLASS,
        5: PatternErrorCode.MATCHES_EVERYTHING,  # "~" with home "/" is "/"
        7: PatternErrorCode.BAD_PATH,
    }
    assert rule_id(matcher, "/anything/at/all.jpg") is None
    assert rule_id(matcher, "/ok/a.jpg") == 6


def test_home_anchored_pattern_is_refused_when_home_is_the_filesystem_root() -> None:
    matcher = build([pattern(1, "~/**")], home="/")
    assert dict(matcher.invalid_rules) == {1: PatternErrorCode.MATCHES_EVERYTHING}
    assert matcher.match("/a.jpg", False) is None


def test_a_relative_include_is_a_caller_error() -> None:
    with pytest.raises(PatternError):
        build([], includes=["Pictures"])


# ── path normal form: defined behaviour for input that is not normal ─────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "normal"),
    [
        ("/", "/"),
        ("//", "/"),
        ("/a", "/a"),
        ("/a/", "/a"),
        ("/a//b", "/a/b"),
        ("/a/./b/.", "/a/b"),
        ("/a/b/../c", "/a/c"),
        ("/..", "/"),
        ("/../a", "/a"),
        ("~", "/home/u"),
        ("~/", "/home/u"),
        ("~/x//y/", "/home/u/x/y"),
        ("/~/x", "/~/x"),
        ("/a\nb", "/a\nb"),
        ("/-", "/-"),
    ],
)
def test_normalize_path(raw: str, normal: str) -> None:
    assert normalize_path(raw, home=HOME) == normal


@pytest.mark.parametrize("raw", ["", "a", "a/b", "./a", "../a", "~x", "~"])
def test_normalize_path_refuses_relative_paths(raw: str) -> None:
    with pytest.raises(PatternError) as caught:
        normalize_path(raw)  # no home given: "~" is just a relative name
    assert caught.value.code is PatternErrorCode.BAD_PATH


@pytest.mark.parametrize(
    "spelling",
    ["/data//x/a.jpg", "/data/./x/a.jpg", "/data/y/../x/a.jpg", "//data/x/a.jpg", "/data/x/./a.jpg"],
)
def test_match_normalises_sloppy_paths(spelling: str) -> None:
    matcher = build([folder(1, "/data/x")])
    assert rule_id(matcher, spelling) == 1
    assert matcher.match_path(spelling) is not None
    assert matcher.explain(spelling).path == "/data/x/a.jpg"


def test_match_accepts_a_trailing_slash_on_directories() -> None:
    matcher = build([folder(1, "/data/x/")])
    assert rule_id(matcher, "/data/x/", True) == 1
    assert matcher.includes_under("/data/") == ()


@pytest.mark.parametrize("relative", ["", "a/b.jpg", "./a", "~/a.jpg", "-rf"])
def test_matching_a_relative_path_is_a_value_error(relative: str) -> None:
    matcher = build([pattern(1, "*.jpg")])
    with pytest.raises(ValueError, match="absolute"):
        matcher.match(relative, False)
    with pytest.raises(ValueError, match="absolute"):
        matcher.match_path(relative)
    with pytest.raises(ValueError, match="absolute"):
        matcher.explain(relative)


def test_rule_values_are_normalised_like_paths() -> None:
    matcher = build([folder(1, "/data//x/./y/../z/"), file_(2, "/p/./q//r.jpg"), folder(3, "/-rf")])
    assert rule_id(matcher, "/data/x/z/a.jpg") == 1
    assert rule_id(matcher, "/p/q/r.jpg") == 2
    assert rule_id(matcher, "/-rf/a.jpg") == 3


# ── hostile names ────────────────────────────────────────────────────────────────────────────────────────

HOSTILE = [
    "new\nline",
    "tab\there",
    " leading and trailing ",
    "-rf",
    "--help",
    "quote'\"`$(rm -rf ~)",
    "back\\slash",
    "star*name",
    "quest?ion",
    "[bracket]",
    "{brace},",
    "dollar$^.+()|",
    "ünï¢ödé-日本語-🖼",
    "é",  # NFD é
    "é",  # NFC é
    "\udcff\udcfe",  # surrogate-escaped undecodable bytes
    "‮gnp.exe",  # right-to-left override
    "a" * 255,
    "~",
    "...",
]


@pytest.mark.parametrize("name", HOSTILE, ids=[repr(name)[:24] for name in HOSTILE])
def test_hostile_names_are_matched_literally_by_folder_and_file_rules(name: str) -> None:
    matcher = build([folder(1, f"/data/{name}"), file_(2, f"/pics/{name}")])
    assert rule_id(matcher, f"/data/{name}", True) == 1
    assert rule_id(matcher, f"/data/{name}/x.jpg") == 1
    assert rule_id(matcher, f"/pics/{name}") == 2
    assert rule_id(matcher, f"/data/{name}x/x.jpg") is None
    assert rule_id(matcher, f"/other/{name}") is None
    assert matcher.match_path(f"/data/{name}/x.jpg") == RuleHit(1, RuleKind.FOLDER, None)


@pytest.mark.parametrize("name", HOSTILE, ids=[repr(name)[:24] for name in HOSTILE])
def test_hostile_names_never_break_pattern_matching(name: str) -> None:
    matcher = build([pattern(1, "*.jpg"), pattern(2, "**/x/**"), pattern(3, "/a/*/b")])
    assert rule_id(matcher, f"/p/{name}") is None
    assert rule_id(matcher, f"/p/{name}.jpg") == 1
    assert rule_id(matcher, f"/x/{name}") == 2
    assert rule_id(matcher, f"/a/{name}/b") == 3


def test_nfc_and_nfd_are_different_names() -> None:
    matcher = build([folder(1, "/data/café")])
    assert rule_id(matcher, "/data/café/a.jpg") == 1
    assert rule_id(matcher, "/data/café/a.jpg") is None


def test_a_very_deep_path_does_not_exhaust_the_stack() -> None:
    matcher = build([pattern(1, "**/needle/**")])
    deep = "/a" * 3000
    assert matcher.match(deep + "/x.jpg", False) is None
    assert rule_id(matcher, deep + "/needle/x.jpg") == 1


# ── the walker contract ──────────────────────────────────────────────────────────────────────────────────

TREE: dict[str, list[tuple[str, bool]]] = {
    "/r": [
        ("a.jpg", False),
        ("keep", True),
        ("node_modules", True),
        ("private", True),
        ("b.screenshot.png", False),
    ],
    "/r/keep": [("c.jpg", False), ("secret.jpg", False), ("thumbs", True)],
    "/r/keep/thumbs": [("t.jpg", False)],
    "/r/node_modules": [("pkg", True), ("logo.png", False)],
    "/r/node_modules/pkg": [("icon.png", False)],
    "/r/private": [("p.jpg", False), ("deeper", True)],
    "/r/private/deeper": [("q.jpg", False)],
}


class CountingMatcher:
    """Wraps a Matcher and records every question the walk asks."""

    def __init__(self, inner: Matcher) -> None:
        self.inner = inner
        self.asked: list[tuple[str, bool]] = []

    def match(self, path: str, is_dir: bool) -> RuleHit | None:
        self.asked.append((path, is_dir))
        return self.inner.match(path, is_dir)


def reference_walk(root: str, matcher: CountingMatcher) -> tuple[list[str], list[str], dict[int, int]]:
    """The smallest loop that honours the contract: ask first, never list a pruned directory."""
    files: list[str] = []
    listed: list[str] = []
    skips: dict[int, int] = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        listed.append(directory)
        for name, is_dir in TREE[directory]:
            path = f"{directory}/{name}"
            hit = matcher.match(path, is_dir)
            if hit is not None:
                skips[hit.rule_id] = skips.get(hit.rule_id, 0) + 1
            elif is_dir:
                stack.append(path)
            else:
                files.append(path)
    return sorted(files), sorted(listed), skips


def test_a_pruned_directory_is_asked_about_once_and_its_children_never() -> None:
    rules = [
        folder(1, "/r/private"),
        file_(2, "/r/keep/secret.jpg"),
        pattern(3, "**/node_modules/**"),
        pattern(4, "*.screenshot.png"),
        pattern(5, "thumbs/"),
    ]
    counting = CountingMatcher(build(rules, includes=["/r"]))
    files, listed, skips = reference_walk("/r", counting)

    assert files == ["/r/a.jpg", "/r/keep/c.jpg"]
    assert listed == ["/r", "/r/keep"]
    assert skips == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}  # every skip attributed, a pruned tree counted once
    assert ("/r/private", True) in counting.asked
    assert ("/r/node_modules", True) in counting.asked
    assert ("/r/keep/thumbs", True) in counting.asked
    asked_paths = [path for path, _is_dir in counting.asked]
    for pruned in ("/r/private/", "/r/node_modules/", "/r/keep/thumbs/"):
        assert not [path for path in asked_paths if path.startswith(pruned)]
    assert len(asked_paths) == len(set(asked_paths)) == 8
    for path, is_dir in counting.asked:  # directories were announced as directories
        assert is_dir == (path in TREE)


def test_match_stays_right_when_nobody_cleared_the_ancestors() -> None:
    matcher = build([pattern(1, "*.d"), pattern(2, "**/cache/**")])
    assert rule_id(matcher, "/a/conf.d/x.jpg") == 1
    assert rule_id(matcher, "/a/cache/deep/er/x.jpg") == 2
    assert matcher.explain("/a/cache/deep/er/x.jpg").at == "/a/cache"


def test_the_directory_cache_is_bounded_and_does_not_change_answers() -> None:
    matcher = build([pattern(1, "**/skip/**"), folder(2, "/data/d7")])
    for index in range(5000):  # more directories than the cache holds
        assert rule_id(matcher, f"/data/d{index}/a.jpg") == (2 if index == 7 else None)
        assert rule_id(matcher, f"/data/d{index}/skip/a.jpg") == (2 if index == 7 else 1)
    assert len(matcher._cache) <= 4096
    assert rule_id(matcher, "/data/d7/a.jpg") == 2
    assert rule_id(matcher, "/data/d8/a.jpg") is None


# ── linwp exclude test <path> ────────────────────────────────────────────────────────────────────────────


def test_explain_says_scanned_when_no_rule_matches() -> None:
    verdict = build([folder(1, "/data/x")], includes=["/home/u/Pictures"]).explain("/home/u/Pictures/a.jpg")
    assert verdict.scanned is True
    assert (verdict.hit, verdict.rule, verdict.group, verdict.at) == (None, None, None, None)
    assert verdict.include == "/home/u/Pictures"
    assert verdict.path == "/home/u/Pictures/a.jpg"


def test_explain_names_the_rule_the_group_and_where_it_hit() -> None:
    groups, rules = builtin_seed()
    verdict = build(rules, groups, includes=[HOME]).explain("/home/u/src/app/node_modules/pkg/logo.png")
    assert verdict.scanned is False
    assert verdict.rule is not None and verdict.rule.value == "**/node_modules/**"
    assert verdict.hit == RuleHit(verdict.rule.id, RuleKind.PATTERN, verdict.rule.group_id)
    assert verdict.group is not None and verdict.group.key == "code"
    assert verdict.at == "/home/u/src/app/node_modules"
    assert verdict.include == HOME


def test_explain_for_file_folder_and_directory_questions() -> None:
    matcher = build([file_(1, "/p/a.jpg"), folder(2, "/q"), pattern(3, "tmp/")], includes=["/"])
    by_file = matcher.explain("/p/a.jpg")
    assert (by_file.hit, by_file.at, by_file.include) == (RuleHit(1, RuleKind.FILE, None), "/p/a.jpg", "/")
    by_folder = matcher.explain("/q/deep/b.jpg")
    assert (by_folder.rule, by_folder.at) == (folder(2, "/q"), "/q")
    assert matcher.explain("/x/tmp").scanned is True  # as a file, "tmp/" does not apply
    as_dir = matcher.explain("/x/tmp", is_dir=True)
    assert (as_dir.scanned, as_dir.at) == (False, "/x/tmp")
    assert matcher.explain("/", is_dir=True).scanned is True
    assert build([]).explain("/p/a.jpg").include is None


# ── performance ──────────────────────────────────────────────────────────────────────────────────────────


def _five_hundred_rules() -> tuple[list[Group], list[Rule]]:
    groups, rules = builtin_seed()
    next_id = len(rules) + 1
    while len(rules) < 500:
        index = len(rules)
        kind = index % 5
        if kind == 0:
            rules.append(folder(next_id, f"/data/excluded-{index}"))
        elif kind == 1:
            rules.append(file_(next_id, f"/data/photos/private-{index}.jpg", device=1, inode=index))
        elif kind == 2:
            rules.append(pattern(next_id, f"IMG_E{index}*.jpg"))
        elif kind == 3:
            rules.append(pattern(next_id, f"**/junk-{index}/**"))
        else:
            rules.append(pattern(next_id, f"*.tmp{index}.png"))
        next_id += 1
    rules.extend(pattern(next_id + n, f"/data/*/raw-{n}/**/*.dng.jpg") for n in range(10))
    return groups, rules


def test_compile_500_rules_and_run_200k_matches_within_budget() -> None:
    groups, rules = _five_hundred_rules()
    assert len(rules) == 510
    total = 200_000 if timing_is_meaningful() else 10_000  # under --cov only the behaviour is checked
    files = total * 19 // 20
    paths = [(f"/home/u/Pictures/album-{index // 200}/IMG_{index}.jpg", False) for index in range(files)]
    paths += [(f"/home/u/Pictures/album-{index}", True) for index in range(total - files)]

    started = time.perf_counter()
    matcher = build(rules, groups, includes=[HOME, "/data"])
    compiled = time.perf_counter()
    hits = sum(1 for path, is_dir in paths if matcher.match(path, is_dir) is not None)
    finished = time.perf_counter()

    assert matcher.invalid_rules == {}
    assert hits == 0
    assert len(paths) == total
    # Budget §2.1: ≥ 200k match()/s. The bound here is 5× slacker so a loaded CI machine stays green.
    if timing_is_meaningful():
        assert compiled - started < 2.0
        assert finished - compiled < 5.0


def test_match_path_on_40k_rows_in_directory_order_is_fast() -> None:
    groups, rules = _five_hundred_rules()
    matcher = build(rules, groups, includes=[HOME])
    total = 40_000 if timing_is_meaningful() else 4_000
    rows = [
        f"/home/u/Pictures/y{index // 4000}/album-{index // 100}/IMG_{index}.jpg" for index in range(total)
    ]
    started = time.perf_counter()
    assert all(matcher.match_path(row) is None for row in rows)
    if timing_is_meaningful():
        assert time.perf_counter() - started < 3.0  # D8 asks for ≤ 300 ms; 10× slack
