"""``python3 -m linwallpaper.addcli <path>…`` — add images to the library.

The single, GUI-free integration seam every file-manager "Add to LinWallpaper"
context-menu entry targets. Appends the given files/folders to the collection
index and exits; it copies nothing. A running app picks the change up the next
time the Wallpaper page is shown.
"""

from __future__ import annotations

import sys

from .collection import Collection


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python3 -m linwallpaper.addcli <image-or-folder> …", file=sys.stderr)
        return 2

    res = Collection().add_paths(args)
    parts = [f"added {res.added}"]
    if res.skipped:
        parts.append(f"skipped {res.skipped}")
    if res.dirs_scanned:
        parts.append(f"scanned {res.dirs_scanned} folder(s)")
    print("LinWallpaper: " + ", ".join(parts) + ".")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
