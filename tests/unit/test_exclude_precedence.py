"""scanner/exclude.py — precedence, includes (ruling Q8), root scope, volumes, inodes, match_path."""

from __future__ import annotations

import pytest

from src.scanner.exclude import Group, PatternErrorCode, Rule, RuleHit, RuleKind
from tests.unit.test_exclude import (
    HOME,
    build,
    builtin_seed,
    file_,
    folder,
    pattern,
    rule_id,
    seeded_rule_id,
    user_group,
)

# ── file › folder › pattern ──────────────────────────────────────────────────────────────────────────────

FILE, FOLDER, PATTERN = RuleKind.FILE, RuleKind.FOLDER, RuleKind.PATTERN


def _rule(kind: RuleKind, rule_id_: int) -> Rule:
    value = {FILE: "/lib/set/a.jpg", FOLDER: "/lib/set", PATTERN: "*.jpg"}[kind]
    return Rule(rule_id_, kind, value)


@pytest.mark.parametrize(
    ("kinds", "winner"),
    [
        ((FILE,), FILE),
        ((FOLDER,), FOLDER),
        ((PATTERN,), PATTERN),
        ((FILE, FOLDER), FILE),
        ((FOLDER, FILE), FILE),
        ((FILE, PATTERN), FILE),
        ((PATTERN, FILE), FILE),
        ((FOLDER, PATTERN), FOLDER),
        ((PATTERN, FOLDER), FOLDER),
        ((FILE, FOLDER, PATTERN), FILE),
        ((PATTERN, FOLDER, FILE), FILE),
        ((FOLDER, PATTERN, FILE), FILE),
    ],
)
def test_precedence_matrix_is_by_kind_not_by_rule_id(kinds: tuple[RuleKind, ...], winner: RuleKind) -> None:
    rules = [_rule(kind, index + 1) for index, kind in enumerate(kinds)]  # ids follow the listed order
    matcher = build(rules)
    for hit in (matcher.match("/lib/set/a.jpg", False), matcher.match_path("/lib/set/a.jpg")):
        assert hit is not None and hit.kind is winner
        assert hit.rule_id == kinds.index(winner) + 1


def test_the_deepest_folder_rule_is_the_one_recorded() -> None:
    matcher = build([folder(1, "/lib"), folder(2, "/lib/set/deep"), folder(3, "/lib/set")])
    assert rule_id(matcher, "/lib/set/deep/a.jpg") == 2
    assert rule_id(matcher, "/lib/set/a.jpg") == 3
    assert rule_id(matcher, "/lib/a.jpg") == 1


def test_duplicate_rules_resolve_to_the_lowest_id() -> None:
    matcher = build(
        [
            folder(9, "/lib"),
            folder(4, "/lib/"),
            file_(8, "/p/a.jpg"),
            file_(3, "/p/./a.jpg"),
            pattern(7, "*.png"),
            pattern(2, "*.png"),
        ]
    )
    assert rule_id(matcher, "/lib/x.jpg") == 4
    assert rule_id(matcher, "/p/a.jpg") == 3
    assert rule_id(matcher, "/q/a.png") == 2


def test_a_folder_rule_beats_a_pattern_that_pruned_an_ancestor_only_in_attribution() -> None:
    matcher = build([pattern(1, "**/cache/**"), folder(2, "/a/cache/b")])
    assert rule_id(matcher, "/a/cache", True) == 1  # what the walker meets first
    assert matcher.match_path("/a/cache/b/f.jpg") == RuleHit(2, FOLDER, None)  # file › folder › pattern
    assert matcher.match_path("/a/cache/c/f.jpg") == RuleHit(1, PATTERN, None)


# ── includes (ruling Q8) ─────────────────────────────────────────────────────────────────────────────────


def test_an_added_root_beats_the_game_libraries_group() -> None:
    groups, rules = builtin_seed()
    without = build(rules, groups, includes=[HOME])
    with_root = build(rules, groups, includes=[HOME, "~/Games/wallpaper-pack"])
    games = seeded_rule_id(rules, "~/Games")

    assert rule_id(without, "/home/u/Games/wallpaper-pack/a.jpg") == games
    assert with_root.match("/home/u/Games/wallpaper-pack", True) is None
    assert with_root.match("/home/u/Games/wallpaper-pack/a.jpg", False) is None
    assert with_root.match_path("/home/u/Games/wallpaper-pack/sub/a.jpg") is None
    # only beneath the include: the rest of ~/Games stays excluded, and the walk from ~ still prunes it
    assert rule_id(with_root, "/home/u/Games/other/a.jpg") == games
    assert rule_id(with_root, "/home/u/Games", True) == games
    assert with_root.includes_under("/home/u/Games") == ("/home/u/Games/wallpaper-pack",)


def test_an_include_at_the_very_folder_a_builtin_rule_names_wins_too() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=["/usr/share/icons/"])
    assert matcher.match("/usr/share/icons", True) is None
    assert matcher.match("/usr/share/icons/a.png", False) is None
    assert matcher.match("/usr/share/pixmaps/a.png", False) is not None


def test_an_include_suppresses_a_builtin_pattern_only_where_the_pattern_hits_the_include_point() -> None:
    groups, rules = builtin_seed()
    pack = "/mnt/big/steamapps/common/wallpaper-pack"
    matcher = build(rules, groups, includes=[pack])
    node_modules = seeded_rule_id(rules, "**/node_modules/**")

    assert matcher.match(pack, True) is None
    assert matcher.match_path(f"{pack}/a.jpg") is None
    assert matcher.match(f"{pack}/steamapps", True) is None  # suppressed beneath the include, all the way
    # …but every other builtin pattern keeps pruning inside the user's root
    assert rule_id(matcher, f"{pack}/tool/node_modules", True) == node_modules
    assert matcher.match_path(f"{pack}/tool/node_modules/x/logo.png") == RuleHit(node_modules, PATTERN, 4)
    assert rule_id(matcher, f"{pack}/.git", True) == seeded_rule_id(rules, "**/.git/**")
    # and outside the include nothing changed
    assert rule_id(matcher, "/mnt/big/steamapps/common/other/a.jpg") == seeded_rule_id(
        rules, "**/steamapps/**"
    )


def test_node_modules_stays_pruned_inside_a_user_root() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=["/home/u/projects"])
    expected = seeded_rule_id(rules, "**/node_modules/**")
    assert rule_id(matcher, "/home/u/projects/site/node_modules", True) == expected
    assert rule_id(matcher, "/home/u/projects/site/node_modules/a/b.png") == expected
    assert matcher.match("/home/u/projects/site/hero.jpg", False) is None


def test_a_root_named_like_a_builtin_pattern_is_scanned() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=["/home/u/art/textures", "/home/u/art/build/"])
    assert matcher.match("/home/u/art/textures/wood.jpg", False) is None
    assert matcher.match("/home/u/art/build/render.png", False) is None
    assert matcher.match("/home/u/art/textures/icons", True) is not None  # another builtin pattern: still on
    assert matcher.match("/home/u/other/textures/wood.jpg", False) is not None
    nested = build(rules, groups, includes=["/home/u/art/textures", "/home/u/art/textures/sub"])
    assert nested.match("/home/u/art/textures/sub/a.jpg", False) is None  # the deeper include inherits it


def test_an_include_never_beats_the_locked_group() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=["/var/lib/wallpapers", "/proc"])
    assert rule_id(matcher, "/var/lib/wallpapers/a.jpg") == seeded_rule_id(rules, "/var/lib")
    assert rule_id(matcher, "/proc", True) == seeded_rule_id(rules, "/proc")
    assert matcher.includes_under("/var/lib") == ()


def test_an_include_never_beats_a_locked_pattern() -> None:
    locked = Group(1, "system", "System", True, True, True)
    matcher = build([pattern(1, "**/secret/**", group_id=1)], [locked], includes=["/data/secret"])
    assert rule_id(matcher, "/data/secret/a.jpg") == 1


def test_an_include_never_beats_user_rules() -> None:
    rules = [
        folder(1, "/data"),  # above the include
        folder(2, "/pics/2019/private"),  # beneath the include
        pattern(3, "**/raw/**"),
        file_(4, "/pics/2019/x.jpg"),
        folder(5, "/work", group_id=8),  # a *user* group is not a group default either
    ]
    matcher = build(
        rules, [user_group(8)], includes=["/data/photos", "/pics", "/shoots/raw/keep", "/work/walls"]
    )
    assert rule_id(matcher, "/data/photos/a.jpg") == 1
    assert rule_id(matcher, "/pics/2019/private/a.jpg") == 2
    assert rule_id(matcher, "/shoots/raw/keep/a.jpg") == 3
    assert rule_id(matcher, "/pics/2019/x.jpg") == 4
    assert rule_id(matcher, "/work/walls/a.jpg") == 5
    assert matcher.match("/pics/2019/a.jpg", False) is None


def test_a_user_folder_rule_behind_an_overridden_builtin_one_still_applies() -> None:
    builtin = Group(1, "games", "Game libraries", True, False, True)
    rules = [folder(1, "/big", group_id=None), folder(2, "/big/games", group_id=1)]
    matcher = build(rules, [builtin], includes=["/big/games/pack"])
    assert rule_id(matcher, "/big/games/pack/a.jpg") == 1
    alone = build([rules[1]], [builtin], includes=["/big/games/pack"])
    assert alone.match("/big/games/pack/a.jpg", False) is None
    assert rule_id(alone, "/big/games/other.jpg") == 2


def test_user_and_builtin_folder_rule_on_the_same_folder() -> None:
    builtin = Group(1, "games", "Game libraries", True, False, True)
    rules = [folder(1, "/big/games", group_id=1), folder(2, "/big/games")]
    matcher = build(rules, [builtin], includes=["/big/games/pack"])
    assert rule_id(matcher, "/big/games/x.jpg") == 1  # lowest id where no include is involved
    assert rule_id(matcher, "/big/games/pack/a.jpg") == 2  # the user's rule survives the include


def test_the_filesystem_root_as_an_include() -> None:
    groups, rules = builtin_seed()
    matcher = build(rules, groups, includes=["/"])
    assert matcher.explain("/srv/a.jpg").include == "/"
    assert matcher.match("/srv/a.jpg", False) is None
    assert matcher.match("/home/u/.cache", True) is not None  # "/" is not deeper than any rule
    assert matcher.includes_under("/") == ("/home/u/.local/share/backgrounds",)


# ── root scope ───────────────────────────────────────────────────────────────────────────────────────────


def test_root_scoped_folder_and_file_rules_apply_only_under_their_root() -> None:
    matcher = build(
        [
            folder(1, "/r/a", root="/r"),
            folder(2, "/elsewhere/b", root="/r"),  # not under its root: can never match
            file_(3, "/r/x.jpg", root="/r/"),
            file_(4, "/elsewhere/y.jpg", root="/r", device=1, inode=44),
            folder(5, "/big", root="/big/photos"),  # above its root: excludes exactly that root
        ]
    )
    assert matcher.invalid_rules == {}
    assert rule_id(matcher, "/r/a/1.jpg") == 1
    assert rule_id(matcher, "/elsewhere/b/1.jpg") is None
    assert rule_id(matcher, "/r/x.jpg") == 3
    assert rule_id(matcher, "/elsewhere/y.jpg") is None
    assert matcher.match_inode(1, 44) is None
    assert rule_id(matcher, "/big/photos/1.jpg") == 5
    assert rule_id(matcher, "/big/photos", True) == 5
    assert rule_id(matcher, "/big/other/1.jpg") is None


def test_root_scoped_builtin_pattern_is_suppressed_only_for_includes_inside_its_scope() -> None:
    builtin = Group(1, "ui_assets", "UI assets", True, False, True)
    rules = [pattern(1, "**/icons/**", group_id=1, root="/r")]
    matcher = build(rules, [builtin], includes=["/r/icons/mine", "/q/icons/mine", "/r"])
    assert matcher.match("/r/icons/mine/a.png", False) is None
    assert rule_id(matcher, "/r/icons/theirs/a.png") == 1
    assert matcher.match("/q/icons/mine/a.png", False) is None  # out of scope anyway


# ── volumes ──────────────────────────────────────────────────────────────────────────────────────────────

VOLUME = "1234-ABCD"


def _volume_rules() -> list[Rule]:
    return [
        folder(1, "DCIM/old", volume_id=VOLUME),
        file_(2, "DCIM/new/id-card.jpg", volume_id=VOLUME, device=2049, inode=77),
        pattern(3, "/raw/**", volume_id=VOLUME),  # a volume pattern is scoped to the mount point
        pattern(4, "*.thm.jpg", volume_id=VOLUME),
        folder(5, "/leading/slash/", volume_id=VOLUME),
    ]


@pytest.mark.parametrize("mount", ["/media/u/CARD", "/mnt/somewhere/else", "/run/media/u/CARD/"])
def test_volume_rules_follow_the_volume_to_any_mount_point(mount: str) -> None:
    matcher = build(_volume_rules(), mounts={VOLUME: mount})
    at = mount.rstrip("/")
    assert matcher.inert_rule_ids == frozenset()
    assert matcher.invalid_rules == {}
    assert rule_id(matcher, f"{at}/DCIM/old/a.jpg") == 1
    assert rule_id(matcher, f"{at}/DCIM/old", True) == 1
    assert rule_id(matcher, f"{at}/DCIM/new/id-card.jpg") == 2
    assert rule_id(matcher, f"{at}/raw/x/a.jpg") == 3
    assert rule_id(matcher, f"{at}/sub/raw/a.jpg") is None
    assert rule_id(matcher, f"{at}/DCIM/new/a.thm.jpg") == 4
    assert rule_id(matcher, f"{at}/leading/slash/a.jpg") == 5
    assert rule_id(matcher, f"{at}/DCIM/new/a.jpg") is None
    # nothing leaks outside the volume, nor to the literal relative value
    assert rule_id(matcher, "/home/u/DCIM/old/a.jpg") is None
    assert rule_id(matcher, "/DCIM/old/a.jpg") is None
    assert rule_id(matcher, "/home/u/a.thm.jpg") is None


def test_after_a_remount_the_old_mount_point_is_no_longer_excluded() -> None:
    before = build(_volume_rules(), mounts={VOLUME: "/media/u/CARD"})
    after = build(_volume_rules(), mounts={VOLUME: "/mnt/card"})
    assert rule_id(before, "/media/u/CARD/DCIM/old/a.jpg") == 1
    assert rule_id(after, "/media/u/CARD/DCIM/old/a.jpg") is None
    assert rule_id(after, "/mnt/card/DCIM/old/a.jpg") == 1


def test_rules_of_an_unmounted_volume_are_inert() -> None:
    rules = [*_volume_rules(), folder(6, "x", volume_id="OTHER", enabled=False), folder(7, "/plain")]
    for matcher in (build(rules), build(rules, mounts={"UNRELATED": "/mnt/u"})):
        assert matcher.inert_rule_ids == frozenset({1, 2, 3, 4, 5, 6})
        assert rule_id(matcher, "/media/u/CARD/DCIM/old/a.jpg") is None
        assert rule_id(matcher, "/DCIM/old/a.jpg") is None
        assert rule_id(matcher, "/a/b.thm.jpg") is None
        assert matcher.match_inode(2049, 77) is None  # device numbers of an absent volume mean nothing
        assert rule_id(matcher, "/plain/a.jpg") == 7


def test_volume_mounted_at_the_filesystem_root() -> None:
    matcher = build(_volume_rules(), mounts={VOLUME: "/"})
    assert rule_id(matcher, "/DCIM/old/a.jpg") == 1
    assert rule_id(matcher, "/x/a.thm.jpg") == 4


def test_volume_rule_root_may_be_volume_relative_too() -> None:
    rules = [
        pattern(1, "*.png", volume_id=VOLUME, root="exports"),
        folder(2, "exports/tmp", volume_id=VOLUME, root="/mnt/card/exports"),
    ]
    matcher = build(rules, mounts={VOLUME: "/mnt/card"})
    assert rule_id(matcher, "/mnt/card/exports/a.png") == 1
    assert rule_id(matcher, "/mnt/card/other/a.png") is None
    assert rule_id(matcher, "/mnt/card/exports/tmp/a.jpg") == 2


def test_bad_volume_values_are_invalid_not_fatal() -> None:
    rules = [
        folder(1, "../escape", volume_id=VOLUME),
        folder(2, ".", volume_id=VOLUME),
        folder(3, "ok", volume_id=VOLUME),
        folder(4, "ok", volume_id="REL"),
    ]
    matcher = build(rules, mounts={VOLUME: "/mnt/card", "REL": "not/absolute"})
    assert dict(matcher.invalid_rules) == {
        1: PatternErrorCode.BAD_PATH,
        2: PatternErrorCode.MATCHES_EVERYTHING,
        4: PatternErrorCode.BAD_PATH,
    }
    assert rule_id(matcher, "/mnt/card/ok/a.jpg") == 3
    assert rule_id(matcher, "/mnt/escape/a.jpg") is None
    assert rule_id(matcher, "/mnt/card/a.jpg") is None


# ── (device, inode): a renamed file stays excluded ───────────────────────────────────────────────────────


def test_renamed_file_is_still_excluded_by_inode() -> None:
    matcher = build(
        [file_(1, "~/Pictures/id-card.jpg", device=2050, inode=123456, group_id=4)], [user_group(4)]
    )
    assert matcher.match("/home/u/Pictures/id-card.jpg", False) == RuleHit(1, FILE, 4)
    assert matcher.match("/home/u/Pictures/renamed.jpg", False) is None  # by path it is unknown…
    assert matcher.match_inode(2050, 123456) == RuleHit(1, FILE, 4)  # …by identity it is the same file
    assert matcher.match_inode(2050, 123457) is None
    assert matcher.match_inode(2051, 123456) is None


def test_inode_matching_needs_both_numbers_and_an_active_file_rule() -> None:
    rules = [
        file_(1, "/p/a.jpg", device=1),
        file_(2, "/p/b.jpg", inode=5),
        file_(3, "/p/c.jpg", device=1, inode=6, enabled=False),
        file_(4, "/p/d.jpg", device=1, inode=7, group_id=2),
        file_(6, "/p/e2.jpg", device=1, inode=8),
        file_(5, "/p/e.jpg", device=1, inode=8),
        file_(7, "/p/f.jpg", device=0, inode=0),
    ]
    matcher = build(rules, [user_group(2, enabled=False)])
    assert matcher.match_inode(1, 5) is None
    assert matcher.match_inode(1, 6) is None
    assert matcher.match_inode(1, 7) is None
    assert matcher.match_inode(1, 8) == RuleHit(5, FILE, None)  # lowest id
    assert matcher.match_inode(0, 0) == RuleHit(7, FILE, None)  # zero is a number, not "missing"


# ── match_path: catalogue rows, nobody cleared the ancestors ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/lib/a.jpg", None),
        ("/lib/tmp/a.jpg", 1),  # basename pattern matched the directory "tmp"
        ("/lib/x/tmp/y/z/a.jpg", 1),
        ("/lib/tmp", 1),  # the row itself is called tmp
        ("/lib/old-2009/a/b.jpg", 2),
        ("/lib/shots/a.png", None),
        ("/lib/shots.d/a.png", 3),
        ("/lib/shots.d", None),  # "*.d/" is for directories; a row is a file
        ("/lib/keep/thumbs/a.jpg", 4),
        ("/lib/keep/thumbs", None),
        ("/lib/x.tmp.png", 5),
    ],
)
def test_match_path_tests_every_ancestor_as_a_directory_then_the_file(
    path: str, expected: int | None
) -> None:
    matcher = build(
        [
            pattern(1, "tmp"),
            pattern(2, "/lib/old-*"),
            pattern(3, "*.d/"),
            pattern(4, "**/thumbs/**"),
            pattern(5, "*.tmp.png"),
        ]
    )
    hit = matcher.match_path(path)
    assert (hit.rule_id if hit is not None else None) == expected
    assert matcher.explain(path).scanned is (expected is None)


def test_match_path_reports_the_shallowest_pruned_ancestor_like_a_walk_would() -> None:
    matcher = build([pattern(5, "**/b/**"), pattern(9, "a/")])
    verdict = matcher.explain("/x/a/b/c.jpg")
    assert verdict.hit == RuleHit(9, PATTERN, None)
    assert verdict.at == "/x/a"


def test_match_and_match_path_agree_for_files() -> None:
    groups, rules = builtin_seed()
    rules += [folder(100, "/data/x"), file_(101, "/data/y/a.jpg"), pattern(102, "*.bak.png")]
    matcher = build(rules, groups, includes=[HOME, "/data", "~/Games/pack"])
    paths = [
        "/data/x/a.jpg",
        "/data/y/a.jpg",
        "/data/y/b.bak.png",
        "/data/y/b.png",
        "/home/u/Games/pack/a.jpg",
        "/home/u/Games/other/a.jpg",
        "/home/u/src/node_modules/a/b.png",
        "/home/u/.local/share/backgrounds/a.jpg",
        "/home/u/.local/share/x/a.jpg",
        "/proc/1/a.png",
    ]
    for path in paths:
        assert matcher.match(path, False) == matcher.match_path(path), path
