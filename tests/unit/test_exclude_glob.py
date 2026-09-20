"""scanner/exclude.py — glob semantics (contract §2.1), refusals, limits, and the no-backtracking proof."""

from __future__ import annotations

import time

import pytest

from src.scanner.exclude import (
    MAX_GLOBSTARS,
    MAX_PATTERN_CHARS,
    PatternError,
    PatternErrorCode,
    RuleKind,
    validate_rule,
)
from tests.unit.test_exclude import build, pattern, rule_id

F = False
D = True

# (pattern, path, is the path a directory, does the rule exclude it)
CASES: list[tuple[str, str, bool, bool]] = [
    # "*" = any run without "/"; it never crosses a separator
    ("*.jpg", "/a/b/x.jpg", F, True),
    ("*.jpg", "/x.jpg", F, True),
    ("*.jpg", "/a/x.jpeg", F, False),
    ("*.jpg", "/a/.jpg", F, True),  # "*" may be empty, and hidden names are not special
    ("/data/*/x.jpg", "/data/a/x.jpg", F, True),
    ("/data/*/x.jpg", "/data/a/b/x.jpg", F, False),
    ("/data/*/x.jpg", "/data/x.jpg", F, False),
    ("/data/*", "/data/a", D, True),
    ("/data/*", "/data", D, False),
    ("IMG_*_edit*.png", "/p/IMG_001_edit_final.png", F, True),
    ("IMG_*_edit*.png", "/p/IMG_001.png", F, False),
    ("a*b*c", "/p/abc", F, True),
    ("a*b*c", "/p/a-b-c", F, True),
    ("a*b*c", "/p/acb", F, False),  # the pieces must appear in order without overlapping
    ("ab*ba", "/p/abba", F, True),
    ("ab*ba", "/p/aba", F, False),
    ("a*a", "/p/a", F, False),
    ("*abc", "/p/xxabc", F, True),
    ("*abc", "/p/abcx", F, False),
    ("abc*", "/p/abcx", F, True),
    ("abc*", "/p/xabc", F, False),
    ("*abc*", "/p/xabcx", F, True),
    ("*abc*", "/p/ab-c", F, False),
    ("*a?c*", "/p/xxabcxx", F, True),
    ("*a?c*", "/p/xxacxx", F, False),
    ("a**b", "/p/aXXb", F, True),  # "**" inside a segment is just "*"
    ("a**b", "/p/a/b", F, False),
    ("a***b", "/p/ab", F, True),
    # "?" = exactly one character
    ("IMG_?.jpg", "/p/IMG_1.jpg", F, True),
    ("IMG_?.jpg", "/p/IMG_12.jpg", F, False),
    ("IMG_?.jpg", "/p/IMG_.jpg", F, False),
    ("IMG_?.jpg", "/p/IMG_\n.jpg", F, True),
    ("IMG_?.jpg", "/p/IMG_é.jpg", F, True),
    ("/a?b", "/a/b", F, False),
    # character classes
    ("[abc].png", "/p/a.png", F, True),
    ("[abc].png", "/p/d.png", F, False),
    ("[abc].png", "/p/ab.png", F, False),
    ("[a-c]x", "/p/bx", F, True),
    ("[a-c]x", "/p/dx", F, False),
    ("[a-cx-z]1", "/p/y1", F, True),
    ("[!abc]x", "/p/dx", F, True),
    ("[!abc]x", "/p/ax", F, False),
    ("[!a-c]x", "/p/bx", F, False),
    ("[]]x", "/p/]x", F, True),  # "]" first is a member
    ("[!]]x", "/p/]x", F, False),
    ("[!]]x", "/p/ax", F, True),
    ("[a-]x", "/p/-x", F, True),  # "-" last is a member
    ("[a-]x", "/p/bx", F, False),
    ("[-a]x", "/p/-x", F, True),
    ("[*]", "/p/*", F, True),  # a literal star, via a class
    ("[*]", "/p/x", F, False),
    ("x[*]y.png", "/p/x*y.png", F, True),
    ("x[*]y.png", "/p/xzzy.png", F, False),
    ("[?]", "/p/?", F, True),
    ("[?]", "/p/x", F, False),
    ("[[]x", "/p/[x", F, True),
    ("[^a]", "/p/^", F, True),  # only "!" negates; "^" is a member
    ("[^a]", "/p/b", F, False),
    ("[\\]]", "/p/\\]", F, True),  # no escapes: the class holds "\", then comes a literal "]"
    ("[\\]]", "/p/\\", F, False),
    ("[\\]x", "/p/\\x", F, True),
    ("[a&&b]", "/p/&", F, True),
    ("[a~~b]", "/p/~", F, True),
    ("[a||b]", "/p/|", F, True),
    # "**" as a whole segment = zero or more segments
    ("/data/**/x.jpg", "/data/x.jpg", F, True),
    ("/data/**/x.jpg", "/data/a/x.jpg", F, True),
    ("/data/**/x.jpg", "/data/a/b/c/x.jpg", F, True),
    ("/data/**/x.jpg", "/other/x.jpg", F, False),
    ("/data/**/x.jpg", "/data/a/y.jpg", F, False),
    ("/a/**/b/**/c", "/a/b/c", F, True),
    ("/a/**/b/**/c", "/a/1/b/2/3/c", F, True),
    ("/a/**/b/**/c", "/a/1/c", F, False),
    ("/a/**/b/**/c", "/a/c/b", F, False),
    ("/a/**/a", "/a", D, False),  # the head and the tail may not share a segment
    ("/a/**/a", "/a/a", D, True),
    ("/a/**/**/b", "/a/b", F, True),
    ("/a/b/c", "/a", D, False),
    ("**/x/y/*.png", "/q/x/y/a.png", F, True),
    ("**/x/y/*.png", "/x/y/a.png", F, True),
    ("**/x/y/*.png", "/q/x/z/y/a.png", F, False),
    # X/** matches everything beneath X and the directory X itself
    ("**/thumbs/**", "/p/thumbs", D, True),
    ("**/thumbs/**", "/p/thumbs", F, False),  # a *file* called thumbs is not a subtree
    ("**/thumbs/**", "/p/thumbs/a.jpg", F, True),
    ("**/thumbs/**", "/p/thumbs/a/b/c.jpg", F, True),
    ("**/thumbs/**", "/thumbs", D, True),
    ("**/thumbs/**", "/p/thumbs2/a.jpg", F, False),
    ("**/.Trash*/**", "/mnt/d/.Trash-1000", D, True),
    ("**/.Trash*/**", "/mnt/d/.Trash-1000/files/a.jpg", F, True),
    ("**/.Trash*/**", "/mnt/d/Trash/a.jpg", F, False),
    ("/data/raw/**", "/data/raw", D, True),
    ("/data/raw/**", "/data/raw/a.jpg", F, True),
    ("/data/raw/**", "/data/raw", F, False),
    ("/data/raw/**", "/data/rawer/a.jpg", F, False),
    ("/data/*/cache/**", "/data/app/cache/x/y.png", F, True),
    ("/data/*/cache/**", "/data/app/sub/cache/y.png", F, False),
    ("thumbs/**/", "/p/thumbs/a", D, True),
    ("thumbs/**/", "/p/thumbs/a.jpg", F, True),  # through the directory thumbs, which the pattern matches
    ("thumbs/**/", "/p/thumbs", F, False),
    # a pattern that matches a directory excludes its subtree
    ("*.d", "/etc/conf.d", D, True),
    ("*.d", "/etc/conf.d/a/b.png", F, True),
    ("/data/old-*", "/data/old-2009/x/y.jpg", F, True),
    # anchoring: leading "/" = filesystem root, "~/" = home
    ("/thumbs", "/thumbs", D, True),
    ("/thumbs", "/a/thumbs", D, False),
    ("~/shots/*.png", "/home/u/shots/a.png", F, True),
    ("~/shots/*.png", "/home/x/shots/a.png", F, False),
    ("~/shots/*.png", "/mnt/home/u/shots/a.png", F, False),
    ("~", "/home/u", D, True),
    ("~", "/home/u/a.jpg", F, True),
    ("~/", "/home/u", D, True),
    ("~/**", "/home/u/a/b.jpg", F, True),
    ("~/**", "/home/v/a.jpg", F, False),
    ("~x", "/p/~x", F, True),  # "~" is special only as "~" or "~/"
    ("a/~/b", "/a/~/b", F, True),
    # no leading "/": basename at any depth, or "**/" + pattern when it contains "/"
    ("thumbs", "/thumbs", D, True),
    ("thumbs", "/a/b/thumbs", D, True),
    ("thumbs", "/a/b/thumbs", F, True),
    ("thumbs", "/a/b/thumbsx", F, False),
    ("a/b", "/a/b", F, True),
    ("a/b", "/q/r/a/b", F, True),
    ("a/b", "/q/a/c/b", F, False),
    ("a/*.png", "/q/a/x.png", F, True),
    ("a/*.png", "/q/b/x.png", F, False),
    # a trailing "/" = directories only
    ("thumbs/", "/p/thumbs", D, True),
    ("thumbs/", "/p/thumbs", F, False),
    ("thumbs/", "/p/thumbs/a.jpg", F, True),  # beneath the matched directory
    ("/data/*/", "/data/x", D, True),
    ("/data/*/", "/data/x", F, False),
    ("*.app/", "/p/x.app", F, False),
    # normalisation of the pattern itself
    ("./thumbs", "/a/thumbs", D, True),
    ("a//b", "/q/a/b", F, True),
    ("/data/./raw//x.jpg", "/data/raw/x.jpg", F, True),
    ("thumbs//", "/p/thumbs", F, False),
    # everything that is not a wildcard is literal — this is not a regular expression
    ("a.jpg", "/p/aXjpg", F, False),
    ("a+b(1).jpg", "/p/a+b(1).jpg", F, True),
    ("a+b(1).jpg", "/p/aab1.jpg", F, False),
    ("(a|b).png", "/p/a.png", F, False),
    ("(a|b).png", "/p/(a|b).png", F, True),
    ("^x$", "/p/^x$", F, True),
    ("x{1,3}", "/p/xx", F, False),
    ("x{1,3}", "/p/x{1,3}", F, True),
    (".*", "/p/abc", F, False),
    (".*", "/p/.abc", F, True),
    ("a\\*", "/p/a\\zzz", F, True),  # backslash is literal, the star still a wildcard
    ("a\\*", "/p/a*", F, False),
    ("\\d+", "/p/123", F, False),
    ("-rf", "/p/-rf", F, True),
    ("--*", "/p/--help", F, True),
    ("a b", "/p/a b", F, True),
    (" ", "/p/ ", F, True),
    ("new\nline*", "/p/new\nline.jpg", F, True),
    ("new*", "/p/new\nline.jpg", F, True),
    ("*line.jpg", "/p/new\nline.jpg", F, True),
    ("*.jpg", "/p/a.jpg\n", F, False),  # no "$"-style leniency about a trailing newline
    ("a.jpg", "/p/a.jpg\n", F, False),
    ("?.jpg", "/p/\n.jpg", F, True),
    # case-sensitive, no Unicode normalisation (ruling Q9)
    ("*.JPG", "/p/a.jpg", F, False),
    ("*.JPG", "/p/a.JPG", F, True),
    ("Thumbs", "/p/thumbs", D, False),
    ("café", "/p/café", F, True),
    ("café", "/p/café", F, False),
    ("café", "/p/café", F, True),
    ("日本*", "/p/日本語.png", F, True),
    ("*🖼*", "/p/a🖼b", F, True),
    ("[α-ω]*", "/p/λ.png", F, True),
    ("[α-ω]*", "/p/l.png", F, False),
    # case-sensitivity of a multi-segment literal pattern (goes through _Seg.matches, not the
    # single-segment _SegIndex dict lookup used by basename/**-NAME-** fast paths above)
    ("**/Foo/Bar/**", "/x/foo/bar/y", F, False),
    ("**/Foo/Bar/**", "/x/Foo/Bar/y", F, True),
]


@pytest.mark.parametrize(
    ("glob", "path", "is_dir", "excluded"), CASES, ids=[f"{c[0]!r}~{c[1]!r}" for c in CASES]
)
def test_glob_semantics(glob: str, path: str, is_dir: bool, excluded: bool) -> None:
    validate_rule(RuleKind.PATTERN, glob)
    matcher = build([pattern(1, glob)])
    assert matcher.invalid_rules == {}
    assert (rule_id(matcher, path, is_dir) == 1) is excluded
    if not is_dir:
        assert (matcher.match_path(path) is not None) is excluded


SCOPED: list[tuple[str, str, str, bool]] = [
    # (pattern, root, path, excluded): with a root, the pattern sees the path relative to that root
    ("/sub/*.png", "/r", "/r/sub/a.png", True),
    ("/sub/*.png", "/r", "/sub/a.png", False),
    ("/sub/*.png", "/r", "/r/x/sub/a.png", False),
    ("/sub/*.png", "/r", "/other/r/sub/a.png", False),
    ("/sub/*.png", "/r", "/rr/sub/a.png", False),
    ("sub/*.png", "/r", "/r/x/sub/a.png", True),
    ("sub/*.png", "/r", "/q/x/sub/a.png", False),
    ("*.png", "/r", "/r/a.png", True),
    ("*.png", "/r", "/q/a.png", False),
    ("*.png", "/r/", "/r/deep/a.png", True),
    ("r", "/r", "/r/a.jpg", False),  # the root's own name is outside the relative path
    ("r", "/r", "/r/r/a.jpg", True),
    ("**/tmp/**", "/r", "/r/a/tmp/b.png", True),
    ("**/tmp/**", "/r", "/tmp/r/b.png", False),
    ("**/tmp/**", "~/pics", "/home/u/pics/tmp/b.png", True),
    ("~/pics/raw/**", "~/pics", "/home/u/pics/raw/a.png", True),  # "~/" stays absolute
    ("~/other/**", "~/pics", "/home/u/other/a.png", False),  # …but the scope still applies
    ("*.png", "/", "/anywhere/a.png", True),
]


@pytest.mark.parametrize(("glob", "root", "path", "excluded"), SCOPED)
def test_root_scoped_patterns_see_the_path_relative_to_the_root(
    glob: str, root: str, path: str, excluded: bool
) -> None:
    matcher = build([pattern(1, glob, root=root)])
    assert matcher.invalid_rules == {}
    assert (rule_id(matcher, path) == 1) is excluded
    assert (matcher.match_path(path) is not None) is excluded


REFUSED: list[tuple[str, PatternErrorCode]] = [
    ("", PatternErrorCode.EMPTY),
    ("*", PatternErrorCode.MATCHES_EVERYTHING),
    ("**", PatternErrorCode.MATCHES_EVERYTHING),
    ("***", PatternErrorCode.MATCHES_EVERYTHING),
    ("/", PatternErrorCode.MATCHES_EVERYTHING),
    ("//", PatternErrorCode.MATCHES_EVERYTHING),
    (".", PatternErrorCode.MATCHES_EVERYTHING),
    ("./", PatternErrorCode.MATCHES_EVERYTHING),
    ("/*", PatternErrorCode.MATCHES_EVERYTHING),
    ("/**", PatternErrorCode.MATCHES_EVERYTHING),
    ("*/", PatternErrorCode.MATCHES_EVERYTHING),
    ("**/", PatternErrorCode.MATCHES_EVERYTHING),
    ("**/*", PatternErrorCode.MATCHES_EVERYTHING),
    ("*/**", PatternErrorCode.MATCHES_EVERYTHING),
    ("/*/**", PatternErrorCode.MATCHES_EVERYTHING),
    ("**/**", PatternErrorCode.MATCHES_EVERYTHING),
    ("**/**/**/**/**/**", PatternErrorCode.MATCHES_EVERYTHING),
    ("*/*/*", PatternErrorCode.MATCHES_EVERYTHING),
    ("./**/./*", PatternErrorCode.MATCHES_EVERYTHING),
    # not all-star, yet they match every probe path (/a, /home/u/p.jpg, /mnt/d/e/f.png)
    ("?*", PatternErrorCode.MATCHES_EVERYTHING),
    ("*?", PatternErrorCode.MATCHES_EVERYTHING),
    ("**/?*", PatternErrorCode.MATCHES_EVERYTHING),
    ("[!/]*", PatternErrorCode.BAD_CLASS),  # "/" always separates, so this is an unclosed "[!"
    ("[!\n]*", PatternErrorCode.MATCHES_EVERYTHING),
    ("/?*/**", PatternErrorCode.MATCHES_EVERYTHING),  # prunes every top-level directory
    ("?*/", PatternErrorCode.MATCHES_EVERYTHING),  # every directory
    ("/[a-z]*", PatternErrorCode.MATCHES_EVERYTHING),
    ("a\0b", PatternErrorCode.NUL),
    ("\0", PatternErrorCode.NUL),
    ("x" * (MAX_PATTERN_CHARS + 1), PatternErrorCode.TOO_LONG),
    ("a/**/b/**/c/**/d/**/e/**/f", PatternErrorCode.TOO_MANY_GLOBSTARS),
    ("[abc", PatternErrorCode.BAD_CLASS),
    ("[", PatternErrorCode.BAD_CLASS),
    ("[!", PatternErrorCode.BAD_CLASS),
    ("[]", PatternErrorCode.BAD_CLASS),
    ("[!]", PatternErrorCode.BAD_CLASS),
    ("x[a-", PatternErrorCode.BAD_CLASS),
    ("[z-a]", PatternErrorCode.BAD_CLASS),
    ("a[b/c]d", PatternErrorCode.BAD_CLASS),
    ("..", PatternErrorCode.BAD_PATH),
    ("../x", PatternErrorCode.BAD_PATH),
    ("/a/../b", PatternErrorCode.BAD_PATH),
    ("~/../v/**", PatternErrorCode.BAD_PATH),
]


@pytest.mark.parametrize(("glob", "code"), REFUSED, ids=[repr(glob)[:30] for glob, _code in REFUSED])
def test_refused_patterns_carry_a_code_and_a_reason(glob: str, code: PatternErrorCode) -> None:
    with pytest.raises(PatternError) as caught:
        validate_rule(RuleKind.PATTERN, glob)
    assert caught.value.code is code
    assert caught.value.reason
    matcher = build([pattern(1, glob)])
    assert dict(matcher.invalid_rules) == {1: code}
    for probe, is_dir in (("/a", True), ("/home/u/p.jpg", False), ("/mnt/d/e/f.png", False)):
        assert matcher.match(probe, is_dir) is None


@pytest.mark.parametrize(
    "glob",
    [
        "x" * MAX_PATTERN_CHARS,
        "a/**/b/**/c/**/d/**/e",
        "**/a/**/b/**/c/**",
        "...",
        "*.*",
        "*a*",
        "/home/**",
        "~/**",
        "~/*",
        "/mnt/*/**",
        "?",
        "??*.jpg",
        "[!.]*.png",
    ],
)
def test_accepted_patterns(glob: str) -> None:
    validate_rule(RuleKind.PATTERN, glob)
    assert build([pattern(1, glob)]).invalid_rules == {}


def test_the_limits_are_the_contracts() -> None:
    assert (MAX_PATTERN_CHARS, MAX_GLOBSTARS) == (1024, 4)


def test_error_codes_are_stable_strings() -> None:
    assert {code.value for code in PatternErrorCode} == {
        "empty",
        "matches_everything",
        "too_long",
        "too_many_globstars",
        "nul",
        "bad_class",
        "bad_path",
    }


def test_lowest_rule_id_wins_among_patterns_whatever_their_shape() -> None:
    shapes = ["*.png", "a.png", "**/*.png", "/p/**/*.png", "a.p?g", "*a*", "a*"]
    for winner in range(len(shapes)):
        order = shapes[winner:] + shapes[:winner]
        matcher = build([pattern(index + 10, glob) for index, glob in enumerate(order)])
        assert rule_id(matcher, "/p/a.png") == 10, order[0]
    matcher = build([pattern(3, "**/x/**"), pattern(2, "x/"), pattern(1, "/p/x/**")])
    assert rule_id(matcher, "/p/x", True) == 1
    assert rule_id(build([pattern(3, "**/x/**"), pattern(2, "x/")]), "/p/x", True) == 2
    assert rule_id(build([pattern(2, "**/x*/**"), pattern(3, "x/")]), "/p/x", True) == 2


# ── bounded: no catastrophic backtracking ────────────────────────────────────────────────────────────────


def _fastest(runs: int, call: object) -> float:
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        call()  # type: ignore[operator]
        best = min(best, time.perf_counter() - started)
    return best


def test_pathological_star_pattern_on_a_255_char_name_stays_linear() -> None:
    glob = "*a" * 500 + "*b"  # as a regex, ".*a.*a.*a…b" on "aaaa…" never finishes
    name = "a" * 255
    validate_rule(RuleKind.PATTERN, glob)
    matcher = build([pattern(1, glob)])
    assert matcher.match(f"/p/{name}", False) is None
    assert rule_id(build([pattern(1, "*a" * 200 + "*b")]), f"/p/{name}b") == 1
    paths = [f"/p{index}/{name}" for index in range(20)]  # distinct directories: no cache help
    elapsed = _fastest(3, lambda: [matcher.match(path, False) for path in paths])
    assert elapsed / len(paths) < 0.005  # contract: < 5 ms per match; measured ≈ 0.02 ms


def test_pathological_wildcards_with_classes_stay_linear() -> None:
    glob = "*[ab]?" * 150 + "*c"
    matcher = build([pattern(1, glob)])
    paths = [f"/p{index}/{'ab' * 127}" for index in range(10)]
    elapsed = _fastest(3, lambda: [matcher.match(path, False) for path in paths])
    assert elapsed / len(paths) < 0.02
    assert matcher.match("/p/" + "ab" * 127, False) is None


def test_pathological_globstars_on_a_deep_path_stay_linear() -> None:
    glob = "/a/**/a/a/**/a/a/**/a/a/**/b"
    matcher = build([pattern(1, glob)])
    deep = "/a" * 2000
    started = time.perf_counter()
    assert matcher.match(deep, False) is None
    assert rule_id(matcher, deep + "/b") == 1
    assert time.perf_counter() - started < 2.0
