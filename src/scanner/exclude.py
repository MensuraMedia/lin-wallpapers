"""User exclusions: folders, files, patterns, and the groups that switch sets of them (concept §5.1, M1.1a).

Pure: no I/O, no clock, no ``os.path.expanduser``. Rules, groups, includes, the home directory and the
mount table are passed in; :func:`compile_matcher` turns them into a :class:`Matcher` once per scan, and
``Matcher.match`` is then cheap enough to run before every ``stat``.

Path model
    Paths are absolute POSIX strings, compared case-sensitively and without Unicode normalisation
    (ruling Q9). They are never resolved against the filesystem. Input that is not in normal form
    (duplicate slashes, ``.`` and ``..`` segments, a trailing slash) is normalised *lexically*; a relative
    path is refused (``ValueError`` from the matching methods, ``BAD_PATH`` from validation).

Globs, not regular expressions
    ``*`` = any run without ``/``; ``?`` = one character; ``[abc] [a-z] [!abc]`` = one character; ``**`` as a
    whole segment = zero or more segments. Everything else, the backslash included, is literal. A pattern is
    split on ``/`` and matched segment-wise; inside a segment the pieces between ``*`` have a fixed length and
    are located leftmost-first, so matching is linear and cannot backtrack catastrophically.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from types import MappingProxyType

__all__ = [
    "BUILTIN_GROUPS",
    "BuiltinGroup",
    "Group",
    "Matcher",
    "PatternError",
    "PatternErrorCode",
    "Rule",
    "RuleHit",
    "RuleKind",
    "Verdict",
    "compile_matcher",
    "normalize_path",
    "validate_rule",
]

MAX_PATTERN_CHARS = 1024
MAX_PATH_CHARS = 4096
MAX_GLOBSTARS = 4

_PROBE_HOME = "/home/u"
# A pattern that excludes every probe (directly, or by pruning one of its ancestors) is refused. The first
# three are the contract's; the last two keep a harmless "?" from being refused just because the contract's
# probes happen to contain one-letter directories.
_PROBE_PATHS = (
    "/a",
    "/home/u/p.jpg",
    "/mnt/d/e/f.png",
    "/srv/photos/2019/holiday.jpeg",
    "/media/usb0/DCIM/100CANON/IMG_0001.JPG",
)


# ── records ──────────────────────────────────────────────────────────────────────────────────────────────


class RuleKind(Enum):
    FOLDER = "folder"
    FILE = "file"
    PATTERN = "pattern"


@dataclass(frozen=True)
class Rule:
    id: int
    kind: RuleKind
    value: str  # FOLDER/FILE: absolute path ("~/" allowed), or volume-relative if volume_id; PATTERN: glob
    group_id: int | None = None
    root: str | None = None  # absolute root path the rule is scoped to; None = everywhere
    volume_id: str | None = None
    device: int | None = None  # FILE rules only
    inode: int | None = None  # FILE rules only
    enabled: bool = True


@dataclass(frozen=True)
class Group:
    id: int
    key: str
    name: str
    builtin: bool
    locked: bool
    enabled: bool


@dataclass(frozen=True)
class BuiltinGroup:
    key: str
    name: str
    locked: bool
    rules: tuple[tuple[RuleKind, str], ...]
    exceptions: tuple[str, ...] = ()  # become includes while the group is on


@dataclass(frozen=True)
class RuleHit:
    rule_id: int
    kind: RuleKind
    group_id: int | None


@dataclass(frozen=True)
class Verdict:
    """The answer to ``linwp exclude test <path>``: would this be scanned, and if not, which rule says no."""

    path: str  # the normalised path that was judged
    scanned: bool
    hit: RuleHit | None = None
    rule: Rule | None = None
    group: Group | None = None
    at: str | None = None  # where the rule hit: the path itself or the ancestor that is pruned
    include: str | None = None  # the deepest include that is the path or one of its ancestors


class PatternErrorCode(StrEnum):
    EMPTY = "empty"
    MATCHES_EVERYTHING = "matches_everything"
    TOO_LONG = "too_long"
    TOO_MANY_GLOBSTARS = "too_many_globstars"
    NUL = "nul"
    BAD_CLASS = "bad_class"
    BAD_PATH = "bad_path"  # relative where an absolute path is needed, or ".." leaving the volume / in a glob


class PatternError(ValueError):
    """A rule value was refused. ``code`` is stable and machine-readable, ``reason`` is for people."""

    def __init__(self, code: PatternErrorCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ── built-in groups (data; seeded into the catalogue by P4) ──────────────────────────────────────────────

_F = RuleKind.FOLDER
_P = RuleKind.PATTERN

BUILTIN_GROUPS: tuple[BuiltinGroup, ...] = (
    BuiltinGroup(
        key="system",
        name="System and pseudo-filesystems",
        locked=True,
        rules=((_F, "/proc"), (_F, "/sys"), (_F, "/dev"), (_F, "/run"), (_F, "/snap"), (_F, "/var/lib")),
    ),
    BuiltinGroup(
        key="snapshots",
        name="Snapshots, backups and trash",
        locked=False,
        rules=(
            (_F, "/timeshift"),
            (_P, "**/.snapshots/**"),
            (_P, "**/.Trash*/**"),
            (_P, "**/lost+found/**"),
        ),
    ),
    BuiltinGroup(
        key="caches",
        name="Caches and thumbnails",
        locked=False,
        rules=(
            (_F, "~/.cache"),
            (_P, "**/.thumbnails/**"),
            (_P, "**/cache/**"),
            (_P, "**/.cache/**"),
            (_F, "~/.mozilla"),
            (_F, "~/.config/google-chrome"),
            (_F, "~/.config/chromium"),
            (_F, "~/.config/BraveSoftware"),
            (_F, "~/.config/microsoft-edge"),
            (_F, "~/.config/vivaldi"),
        ),
    ),
    BuiltinGroup(
        key="code",
        name="Code and build trees",
        locked=False,
        rules=(
            (_P, "**/.git/**"),
            (_P, "**/node_modules/**"),
            (_P, "**/.venv/**"),
            (_P, "**/build/**"),
            (_P, "**/dist/**"),
            (_P, "**/target/**"),
        ),
    ),
    BuiltinGroup(
        key="games",
        name="Game libraries",
        locked=False,
        rules=(
            (_F, "~/.steam"),
            (_F, "~/.local/share/Steam"),
            (_F, "~/.var/app/com.valvesoftware.Steam"),
            (_F, "~/.local/share/lutris"),
            (_F, "~/.config/heroic"),
            (_F, "~/Games"),
            (_P, "**/steamapps/**"),
            (_P, "**/SteamLibrary/**"),
            (_P, "**/compatdata/**"),
        ),
    ),
    BuiltinGroup(
        key="ui_assets",
        name="Icons, emoji and UI assets",
        locked=False,
        rules=(
            (_P, "**/icons/**"),
            (_P, "**/emoji/**"),
            (_P, "**/sprites/**"),
            (_P, "**/textures/**"),
            (_F, "/usr/share/icons"),
            (_F, "/usr/share/pixmaps"),
        ),
    ),
    BuiltinGroup(
        key="app_data",
        name="Application data",
        locked=False,
        rules=((_F, "~/.local/share"), (_F, "~/.config"), (_F, "~/.var"), (_F, "~/snap")),
        exceptions=("~/.local/share/backgrounds",),
    ),
)

_BUILTIN_BY_KEY: Mapping[str, BuiltinGroup] = MappingProxyType({g.key: g for g in BUILTIN_GROUPS})


# ── paths ────────────────────────────────────────────────────────────────────────────────────────────────


def normalize_path(path: str, *, home: str | None = None) -> str:
    """Lexical normal form: ``~`` expanded from ``home``, no ``//``, ``.``, ``..`` or trailing slash.

    ``..`` is collapsed textually (``/a/b/../c`` → ``/a/c``, ``/..`` → ``/``); nothing is resolved against the
    filesystem. A relative path raises ``PatternError(BAD_PATH)``.
    """
    if home is not None and (path == "~" or path.startswith("~/")):
        path = home + path[1:]
    if not path.startswith("/"):
        raise PatternError(PatternErrorCode.BAD_PATH, f"not an absolute path: {path!r}")
    out: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/" + "/".join(out)


def _normalize_relative(value: str) -> str:
    """Normal form of a volume-relative value ("" = the volume itself). A leading ``/`` is tolerated."""
    out: list[str] = []
    for seg in value.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not out:
                raise PatternError(PatternErrorCode.BAD_PATH, f"path leaves its volume: {value!r}")
            out.pop()
            continue
        out.append(seg)
    return "/".join(out)


def _join(base: str, relative: str) -> str:
    return normalize_path(base + "/" + relative)


def _split(path: str) -> list[str]:
    return path[1:].split("/") if path != "/" else []


def _is_under(path: str, ancestor: str) -> bool:
    """True when ``path`` is ``ancestor`` or lies beneath it (both normalised)."""
    return path == ancestor or ancestor == "/" or path.startswith(ancestor + "/")


# ── globs ────────────────────────────────────────────────────────────────────────────────────────────────


class _Seg:
    """One pattern segment. Pieces between ``*`` have a fixed length, so matching never backtracks."""

    __slots__ = (
        "exact",
        "first",
        "last",
        "last_len",
        "literal",
        "middle",
        "min_len",
        "prefix",
        "star_only",
        "suffix",
    )

    def __init__(self, chunks: list[tuple[str, int, str | None]]) -> None:
        # chunks: (regex source, length in characters, literal text or None); one more chunk than stars.
        self.literal: str | None = None
        self.exact: re.Pattern[str] | None = None
        self.first: re.Pattern[str] | None = None
        self.middle: tuple[re.Pattern[str], ...] = ()
        self.last: re.Pattern[str] | None = None
        self.last_len = 0
        self.min_len = sum(length for _src, length, _lit in chunks)
        self.star_only = len(chunks) > 1 and self.min_len == 0
        self.prefix = ""  # literal text every match starts with / ends with; "" = unknown
        self.suffix = ""
        if len(chunks) == 1:
            src, _length, lit = chunks[0]
            if lit is not None:
                self.literal = lit
            else:
                self.exact = re.compile(src)
            return
        head, tail = chunks[0], chunks[-1]
        if head[1]:
            self.first = re.compile(head[0])
            self.prefix = head[2] or ""
        self.middle = tuple(re.compile(src) for src, length, _lit in chunks[1:-1] if length)
        if tail[1]:
            self.last = re.compile(tail[0] + r"\Z")
            self.last_len = tail[1]
            self.suffix = tail[2] or ""

    @classmethod
    def from_literal(cls, text: str) -> _Seg:
        return cls([(re.escape(text), len(text), text)])

    def matches(self, name: str) -> bool:
        if self.literal is not None:
            return name == self.literal
        if self.exact is not None:
            return self.exact.fullmatch(name) is not None
        if len(name) < self.min_len:
            return False
        pos = 0
        if self.first is not None:
            found = self.first.match(name)
            if found is None:
                return False
            pos = found.end()
        for piece in self.middle:
            found = piece.search(name, pos)
            if found is None:
                return False
            pos = found.end()
        if self.last is not None:
            start = len(name) - self.last_len
            return start >= pos and self.last.match(name, start) is not None
        return True


def _bad_class(pattern: str, why: str) -> PatternError:
    return PatternError(PatternErrorCode.BAD_CLASS, f"{why} in pattern {pattern!r}")


def _parse_class(seg: str, start: int, pattern: str) -> tuple[str, int]:
    """Parse the class opening at ``seg[start] == "["``; returns (regex source, index after ``]``)."""
    j = start + 1
    n = len(seg)
    negate = j < n and seg[j] == "!"
    if negate:
        j += 1
    items: list[str] = []
    first = True
    while True:
        if j >= n:
            raise _bad_class(pattern, "unclosed '['")
        char = seg[j]
        if char == "]" and not first:
            break
        first = False
        if j + 2 < n and seg[j + 1] == "-" and seg[j + 2] != "]":
            high = seg[j + 2]
            if high < char:
                raise _bad_class(pattern, f"reversed range {char}-{high}")
            items.append(re.escape(char) + "-" + re.escape(high))
            j += 3
        else:
            items.append(re.escape(char))
            j += 1
    return "[" + ("^" if negate else "") + "".join(items) + "]", j + 1


def _parse_segment(seg: str, pattern: str) -> _Seg:
    chunks: list[tuple[str, int, str | None]] = []
    src: list[str] = []
    length = 0
    literal: list[str] | None = []
    i = 0
    n = len(seg)
    while i < n:
        char = seg[i]
        if char == "*":
            chunks.append(("".join(src), length, "".join(literal) if literal is not None else None))
            src, length, literal = [], 0, []
            while i < n and seg[i] == "*":  # a**b ≡ a*b
                i += 1
            continue
        if char == "?":
            src.append("[^/]")
            literal = None
            i += 1
        elif char == "[":
            class_src, i = _parse_class(seg, i, pattern)
            src.append(class_src)
            literal = None
        else:
            src.append(re.escape(char))
            if literal is not None:
                literal.append(char)
            i += 1
        length += 1
    chunks.append(("".join(src), length, "".join(literal) if literal is not None else None))
    return _Seg(chunks)


class _Glob:
    """A compiled pattern: a head run, then runs that each follow a ``**``; all runs have a fixed length."""

    __slots__ = ("dir_only", "floats", "head", "subtree")

    def __init__(self, items: list[_Seg | None], dir_only: bool) -> None:
        # items: segments, None = "**"; consecutive None already collapsed.
        self.dir_only = dir_only
        self.subtree = bool(items) and items[-1] is None  # X/** : X itself (a directory) and all beneath
        if self.subtree:
            items = items[:-1]
        runs: list[list[_Seg]] = [[]]
        for item in items:
            if item is None:
                runs.append([])
            else:
                runs[-1].append(item)
        self.head: tuple[_Seg, ...] = tuple(runs[0])
        self.floats: tuple[tuple[_Seg, ...], ...] = tuple(tuple(run) for run in runs[1:])

    @property
    def unbounded(self) -> bool:
        return not self.head and not self.floats

    def match(self, segs: list[str], lo: int, n: int, is_dir: bool) -> bool:
        """Does the pattern match ``segs[lo:n]``? ``is_dir`` describes the last segment."""
        if self.dir_only and not is_dir:
            return False
        pos = lo
        if n - pos < len(self.head):
            return False
        for seg in self.head:
            if not seg.matches(segs[pos]):
                return False
            pos += 1
        floats = self.floats
        anchored_tail = len(floats) if self.subtree else len(floats) - 1
        for index, run in enumerate(floats):
            width = len(run)
            if index == anchored_tail:  # the last run of a pattern without a trailing "**" ends the path
                start = n - width
                return start >= pos and _run_matches(run, segs, start)
            start = pos
            limit = n - width
            while start <= limit and not _run_matches(run, segs, start):
                start += 1
            if start > limit:
                return False
            pos = start + width
        if self.subtree:
            return pos < n or is_dir
        return pos == n


def _run_matches(run: tuple[_Seg, ...], segs: list[str], start: int) -> bool:
    return all(seg.matches(segs[start + offset]) for offset, seg in enumerate(run))


def _glob_hits_along(glob: _Glob, segs: list[str], lo: int, is_dir: bool) -> bool:
    """True when the glob matches the path or any ancestor of it (ancestors are directories)."""
    n = len(segs)
    return any(glob.match(segs, lo, k, k < n or is_dir) for k in range(lo + 1, n + 1))


def _compile_glob(pattern: str, home: str) -> tuple[_Glob, bool]:
    """Parse and check a pattern. Returns the glob and whether it is absolute despite a scope (``~/…``)."""
    if pattern == "":
        raise PatternError(PatternErrorCode.EMPTY, "the pattern is empty")
    if "\0" in pattern:
        raise PatternError(PatternErrorCode.NUL, "the pattern contains a NUL character")
    if len(pattern) > MAX_PATTERN_CHARS:
        raise PatternError(
            PatternErrorCode.TOO_LONG, f"the pattern is longer than {MAX_PATTERN_CHARS} characters"
        )
    home_anchored = pattern == "~" or pattern.startswith("~/")
    anchored = home_anchored or pattern.startswith("/")
    body = pattern[1:] if home_anchored else pattern
    raw = [seg for seg in body.split("/") if seg not in ("", ".")]
    if ".." in raw:
        raise PatternError(PatternErrorCode.BAD_PATH, f"'..' can never match a scanned path: {pattern!r}")
    dir_only = body.endswith("/") and bool(raw)
    items: list[_Seg | None] = []
    globstars = 0
    for seg in raw:
        if seg == "**":
            globstars += 1
            if not items or items[-1] is not None:
                items.append(None)
        else:
            items.append(_parse_segment(seg, pattern))
    if not home_anchored and all(item is None or item.star_only for item in items):
        raise PatternError(PatternErrorCode.MATCHES_EVERYTHING, f"{pattern!r} would exclude everything")
    if globstars > MAX_GLOBSTARS:
        raise PatternError(
            PatternErrorCode.TOO_MANY_GLOBSTARS, f"more than {MAX_GLOBSTARS} '**' in {pattern!r}"
        )
    if home_anchored:
        prefix: list[_Seg | None] = [_Seg.from_literal(seg) for seg in _split(home)]
        items = prefix + items
    elif not anchored and items[0] is not None:
        items.insert(0, None)  # "name" ≡ "**/name": the basename at any depth
    glob = _Glob(items, dir_only)
    if glob.unbounded:  # "~/**" with home "/"
        raise PatternError(PatternErrorCode.MATCHES_EVERYTHING, f"{pattern!r} would exclude everything")
    if all(any(_glob_hits_along(glob, _split(probe), 0, d) for d in (False, True)) for probe in _PROBE_PATHS):
        raise PatternError(PatternErrorCode.MATCHES_EVERYTHING, f"{pattern!r} would exclude everything")
    return glob, home_anchored


def _check_path_value(value: str, home: str, volume_relative: bool) -> str:
    """Validate a FOLDER/FILE value; returns its normal form (relative when ``volume_relative``)."""
    if value == "":
        raise PatternError(PatternErrorCode.EMPTY, "the path is empty")
    if "\0" in value:
        raise PatternError(PatternErrorCode.NUL, "the path contains a NUL character")
    if len(value) > MAX_PATH_CHARS:
        raise PatternError(PatternErrorCode.TOO_LONG, f"the path is longer than {MAX_PATH_CHARS} characters")
    if volume_relative:
        relative = _normalize_relative(value)
        if relative == "":
            raise PatternError(PatternErrorCode.MATCHES_EVERYTHING, "the rule would exclude its whole volume")
        return relative
    path = normalize_path(value, home=home)
    if path == "/":
        raise PatternError(PatternErrorCode.MATCHES_EVERYTHING, "'/' would exclude everything")
    return path


def validate_rule(kind: RuleKind, value: str, *, volume_relative: bool = False) -> None:
    """Raise :class:`PatternError` when the value must not become a rule. Pure; knows no home or mounts."""
    if kind is RuleKind.PATTERN:
        _compile_glob(value, _PROBE_HOME)
    else:
        _check_path_value(value, _PROBE_HOME, volume_relative)


# ── the matcher ──────────────────────────────────────────────────────────────────────────────────────────


_Entry = tuple[RuleHit, bool, _Seg]  # hit, directories only, the segment pattern


class _SegIndex:
    """Single-segment patterns, found by the literal start or end of the name instead of one by one."""

    __slots__ = ("exact", "prefixes", "rest", "suffixes")

    def __init__(self) -> None:
        self.exact: dict[str, list[_Entry]] = {}
        self.prefixes: dict[int, dict[str, list[_Entry]]] = {}
        self.suffixes: dict[int, dict[str, list[_Entry]]] = {}
        self.rest: list[_Entry] = []

    def add(self, seg: _Seg, hit: RuleHit, dir_only: bool) -> None:
        entry = (hit, dir_only, seg)
        if seg.literal is not None:
            self.exact.setdefault(seg.literal, []).append(entry)
        elif seg.prefix:
            self.prefixes.setdefault(len(seg.prefix), {}).setdefault(seg.prefix, []).append(entry)
        elif seg.suffix:
            self.suffixes.setdefault(len(seg.suffix), {}).setdefault(seg.suffix, []).append(entry)
        else:
            self.rest.append(entry)

    def find(self, name: str, is_dir: bool, skip: frozenset[int], best: RuleHit | None) -> RuleHit | None:
        """The lowest-id entry matching ``name``, if its id is below ``best``; otherwise ``best``."""
        entries = self.exact.get(name)
        if entries is not None:
            best = _first(entries, name, is_dir, skip, best)
        for length, table in self.prefixes.items():
            entries = table.get(name[:length])
            if entries is not None:
                best = _first(entries, name, is_dir, skip, best)
        for length, table in self.suffixes.items():
            entries = table.get(name[-length:])
            if entries is not None:
                best = _first(entries, name, is_dir, skip, best)
        if self.rest:
            best = _first(self.rest, name, is_dir, skip, best)
        return best


def _first(
    entries: list[_Entry], name: str, is_dir: bool, skip: frozenset[int], best: RuleHit | None
) -> RuleHit | None:
    for hit, dir_only, seg in entries:  # ascending rule id
        if best is not None and hit.rule_id >= best.rule_id:
            break
        if (is_dir or not dir_only) and hit.rule_id not in skip and seg.matches(name):
            return hit
    return best


class _Point:
    """What sits at one path of the folder index: an include, and/or folder rules."""

    __slots__ = ("best", "hard", "include")

    def __init__(self) -> None:
        self.include = False
        self.best: RuleHit | None = None  # lowest rule id of any folder rule here
        self.hard: RuleHit | None = None  # lowest rule id among rules an include cannot override


class _Pattern:
    __slots__ = ("glob", "hit", "lo", "scope", "soft")

    def __init__(self, hit: RuleHit, glob: _Glob, scope: str | None, lo: int, soft: bool) -> None:
        self.hit = hit
        self.glob = glob
        self.scope = scope  # None, or the prefix ("/root/") every matching path starts with
        self.lo = lo  # index of the first segment the glob sees
        self.soft = soft  # rule of an unlocked builtin group: an include may suppress it

    def matches(self, path: str, segs: list[str], n: int, is_dir: bool) -> bool:
        if self.scope is not None and not path.startswith(self.scope):
            return False
        return n > self.lo and self.glob.match(segs, self.lo, n, is_dir)


_Judged = tuple[RuleHit | None, str | None, frozenset[int]]  # hit, the path it hit at, suppressed rule ids
_CACHED_DIRS = 4096
_NO_MOUNTS: Mapping[str, str] = MappingProxyType({})
_NOTHING: frozenset[int] = frozenset()


class Matcher:
    """Compiled rules. Safe to share between threads: the rules never change after construction, and the
    only mutable state is a bounded cache of per-directory verdicts, touched by single dict operations."""

    def __init__(
        self,
        rules: Iterable[Rule],
        groups: Iterable[Group],
        *,
        includes: Iterable[str] = (),
        home: str,
        mounts: Mapping[str, str] = _NO_MOUNTS,
    ) -> None:
        self._home = normalize_path(home)
        self._groups = {group.id: group for group in groups}
        self._rules: dict[int, Rule] = {}
        self._points: dict[str, _Point] = {}
        self._files: dict[str, RuleHit] = {}
        self._inodes: dict[tuple[int, int], RuleHit] = {}
        self._tree = _SegIndex()  # **/SEG/**
        self._base = _SegIndex()  # SEG and SEG/ : the basename at any depth
        self._generic: list[_Pattern] = []
        self._soft: list[_Pattern] = []
        inert: set[int] = set()
        invalid: dict[int, PatternErrorCode] = {}

        include_set = {normalize_path(include, home=self._home) for include in includes}
        for group in self._groups.values():
            builtin = _BUILTIN_BY_KEY.get(group.key) if group.builtin else None
            if builtin is not None and (group.enabled or group.locked):
                include_set.update(normalize_path(path, home=self._home) for path in builtin.exceptions)
        for include in include_set:
            self._point(include).include = True
        self.includes: tuple[str, ...] = tuple(sorted(include_set))

        for rule in sorted(rules, key=lambda r: r.id):
            self._rules[rule.id] = rule
            mount: str | None = None
            if rule.volume_id is not None:
                mount = mounts.get(rule.volume_id)
                if mount is None:
                    inert.add(rule.id)
                    continue
            owner = self._groups.get(rule.group_id) if rule.group_id is not None else None
            locked = owner is not None and owner.locked
            if not locked and not (rule.enabled and (owner is None or owner.enabled)):
                continue
            soft = owner is not None and owner.builtin and not locked
            try:
                self._add(rule, mount, soft)
            except PatternError as error:
                invalid[rule.id] = error.code

        self._generic.sort(key=lambda p: p.hit.rule_id)
        self._generic_exact = [p for p in self._generic if not p.glob.subtree]
        self._cache: dict[str, _Judged] = {}
        self._suppress: dict[str, frozenset[int]] = {}
        for include in include_set:
            segs = _split(include)
            ids = frozenset(
                p.hit.rule_id
                for p in self._soft
                if (p.scope is None or (include + "/").startswith(p.scope))
                and _glob_hits_along(p.glob, segs, p.lo, True)
            )
            if ids:
                self._suppress[include] = ids
        self.inert_rule_ids: frozenset[int] = frozenset(inert)
        self.invalid_rules: Mapping[int, PatternErrorCode] = MappingProxyType(invalid)

    # ── compilation ──

    def _point(self, path: str) -> _Point:
        point = self._points.get(path)
        if point is None:
            point = self._points[path] = _Point()
        return point

    def _add(self, rule: Rule, mount: str | None, soft: bool) -> None:
        hit = RuleHit(rule.id, rule.kind, rule.group_id)
        mount = normalize_path(mount) if mount is not None else None
        root: str | None = None
        if rule.root is not None:
            if mount is not None and not rule.root.startswith(("/", "~")):
                root = _join(mount, _normalize_relative(rule.root))
            else:
                root = normalize_path(rule.root, home=self._home)
        if rule.kind is RuleKind.PATTERN:
            self._add_pattern(rule, hit, root if root is not None else mount, soft)
            return
        if mount is not None:
            path = _join(mount, _check_path_value(rule.value, self._home, True))
        else:
            path = _check_path_value(rule.value, self._home, False)
        if root is not None and not _is_under(path, root):
            if rule.kind is RuleKind.FILE or not _is_under(root, path):
                return  # scoped to a root it is not part of: can never match
            path = root  # a folder above its root excludes exactly that root ("/" was refused, so root ≠ "/")
        if rule.kind is RuleKind.FILE:
            self._files.setdefault(path, hit)
            if rule.device is not None and rule.inode is not None:
                self._inodes.setdefault((rule.device, rule.inode), hit)
            return
        point = self._point(path)
        if point.best is None:
            point.best = hit
        if not soft and point.hard is None:
            point.hard = hit

    def _add_pattern(self, rule: Rule, hit: RuleHit, scope: str | None, soft: bool) -> None:
        glob, absolute = _compile_glob(rule.value, self._home)
        if scope is None or scope == "/":
            pattern = _Pattern(hit, glob, None, 0, soft)
        else:
            pattern = _Pattern(hit, glob, scope + "/", 0 if absolute else len(_split(scope)), soft)
        if soft:
            self._soft.append(pattern)
        run = glob.floats[0] if not glob.head and len(glob.floats) == 1 else ()
        if len(run) != 1 or pattern.scope is not None or (glob.subtree and glob.dir_only):
            self._generic.append(pattern)
        elif glob.subtree:
            self._tree.add(run[0], hit, False)
        else:
            self._base.add(run[0], hit, glob.dir_only)

    # ── matching ──

    def _normal(self, path: str) -> tuple[str, list[str]]:
        if path[:1] != "/":
            raise ValueError(f"not an absolute path: {path!r}")
        segs = path[1:].split("/")
        if "" in segs or "." in segs or ".." in segs:
            path = normalize_path(path)
            segs = _split(path)
        return path, segs

    def _folder(self, path: str) -> tuple[RuleHit | None, int, str | None]:
        """Deepest folder rule at or above ``path`` that no include overrides; also the deepest include."""
        points = self._points
        include: str | None = None
        end = len(path)
        while end > 0:
            point = points.get(path[:end])
            if point is not None:
                if include is None and point.include:
                    include = path[:end]
                hit = point.best if include is None else point.hard
                if hit is not None:
                    return hit, end, include
            end = path.rfind("/", 0, end)
        return None, 0, include  # only reached from "/" or from a point, so "/" itself needs no extra look

    def _deepest_include(self, path: str) -> str | None:
        end = len(path)
        while end > 0:
            point = self._points.get(path[:end])
            if point is not None and point.include:
                return path[:end]
            end = path.rfind("/", 0, end)
        return "/" if "/" in self._points else None

    def _patterns(
        self, path: str, segs: list[str], n: int, is_dir: bool, skip: frozenset[int], subtrees: bool
    ) -> RuleHit | None:
        """Lowest-id pattern rule matching ``segs[:n]``. ``subtrees=False`` leaves out every ``X/**`` rule."""
        best = self._base.find(segs[n - 1], is_dir, skip, None)
        if subtrees and is_dir:
            best = self._tree.find(segs[n - 1], True, skip, best)
        for pattern in self._generic if subtrees else self._generic_exact:
            rule_id = pattern.hit.rule_id
            if best is not None and rule_id > best.rule_id:
                break
            if rule_id not in skip and pattern.matches(path, segs, n, is_dir):
                best = pattern.hit
                break
        return best

    def _judge(self, path: str, segs: list[str], n: int, is_dir: bool) -> _Judged:
        """The self-contained decision for ``segs[:n]``: folder rules first, then patterns top-down."""
        hit, end, include = self._folder(path)
        skip = self._suppress.get(include, _NOTHING) if include is not None else _NOTHING
        if hit is not None:
            return hit, path[:end], skip
        for k in range(1, n + 1):
            hit = self._patterns(path, segs, k, k < n or is_dir, skip, True)
            if hit is not None:
                return hit, "/" + "/".join(segs[:k]), skip
        return None, None, skip

    def _judged(self, path: str, segs: list[str], n: int) -> _Judged:
        """The decision for the directory ``segs[:n]``, derived from its parent's and remembered.

        A directory inherits its parent's verdict and suppressed rules unless it carries a folder rule or an
        include itself. Iterative, so a path of two thousand segments cannot exhaust the stack.
        """
        cache = self._cache
        todo: list[int] = []
        end = len(path)
        while True:
            here = path[:end] or "/"
            judged = cache.get(here)
            if judged is None and (n == 0 or here in self._points):
                judged = self._remember(here, self._judge(here, segs, n, True))
            if judged is not None:
                break
            todo.append(end)
            end = path.rfind("/", 0, end)
            n -= 1
        for end in reversed(todo):
            n += 1
            if judged[0] is None:
                here = path[:end]
                hit = self._patterns(here, segs, n, True, judged[2], True)
                if hit is not None:
                    judged = (hit, here, judged[2])
            self._remember(path[:end], judged)
        return judged

    def _remember(self, path: str, judged: _Judged) -> _Judged:
        if len(self._cache) >= _CACHED_DIRS:
            self._cache.clear()
        self._cache[path] = judged
        return judged

    def _locate(self, path: str, is_dir: bool) -> tuple[RuleHit | None, str | None, str]:
        """The hit, the path it hit at (the path itself or a pruned ancestor), and the normalised path."""
        path, segs = self._normal(path)
        n = len(segs)
        if is_dir or n == 0:
            hit, at, _skip = self._judged(path, segs, n)
            return hit, at, path
        file_hit = self._files.get(path)
        if file_hit is not None:
            return file_hit, path, path
        if path in self._points:  # a folder rule or an include naming what turned out to be a file
            hit, at, _skip = self._judge(path, segs, n, False)
            return hit, at, path
        hit, at, skip = self._judged(path[: path.rfind("/")] or "/", segs, n - 1)
        if hit is None:
            # The ancestors are clear, and an X/** rule reaches a file only through one of them.
            hit = self._patterns(path, segs, n, False, skip, False)
            at = path if hit is not None else None
        return hit, at, path

    def match(self, path: str, is_dir: bool) -> RuleHit | None:
        """Would this path be skipped, and by which rule? ``None`` = scan it.

        A hit with ``is_dir=True`` means *prune*: the directory must not be entered, listed or ``stat``ed.
        The walker only asks about entries of directories it was allowed to enter; asked about any other
        path, the answer is still right (ancestors are judged as directories), just slower on a cold cache.
        """
        return self._locate(path, is_dir)[0]

    def match_inode(self, device: int, inode: int) -> RuleHit | None:
        """FILE rules by identity: a renamed file stays excluded. Only meaningful on stable-inode volumes."""
        return self._inodes.get((device, inode))

    def match_path(self, path: str) -> RuleHit | None:
        """Judge a catalogued file whose ancestors nobody has cleared: each is tested as a directory."""
        return self._locate(path, False)[0]

    def explain(self, path: str, *, is_dir: bool = False) -> Verdict:
        """``linwp exclude test``: would ``path`` be scanned, and if not, which rule (and where) says no."""
        hit, at, normal = self._locate(path, is_dir)
        include = self._deepest_include(normal)
        if hit is None:
            return Verdict(path=normal, scanned=True, include=include)
        rule = self._rules[hit.rule_id]
        group = self._groups.get(hit.group_id) if hit.group_id is not None else None
        return Verdict(path=normal, scanned=False, hit=hit, rule=rule, group=group, at=at, include=include)

    def includes_under(self, path: str) -> tuple[str, ...]:
        """Includes strictly beneath ``path`` that are themselves scannable.

        A pruned directory is never entered, yet an include may lie beneath it (``~/.local/share`` is
        excluded, ``~/.local/share/backgrounds`` is not): the walker starts a sub-walk at each of these.
        """
        path = self._normal(path)[0]
        return tuple(
            include
            for include in self.includes
            if include != path and _is_under(include, path) and self._locate(include, True)[0] is None
        )


def compile_matcher(
    rules: Iterable[Rule],
    groups: Iterable[Group],
    *,
    includes: Iterable[str] = (),
    home: str,
    mounts: Mapping[str, str] = _NO_MOUNTS,
) -> Matcher:
    """Compile once per scan. ``includes`` are the enabled roots; ``mounts`` maps volume id → mount point.

    Builtin ``exceptions`` of every active builtin group are added to the includes here. Rules whose value is
    refused by validation never match and are listed in ``Matcher.invalid_rules`` — one bad row cannot
    exclude everything or stop a scan.
    """
    return Matcher(rules, groups, includes=includes, home=home, mounts=mounts)
