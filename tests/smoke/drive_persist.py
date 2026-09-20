"""Opens the real app against whatever GSettings backend the caller configured, reports what it
restored, optionally navigates and resizes, then leaves by the requested door.

    python -m tests.smoke.drive_persist close|quit|report [route] [width] [height]

Run by test_persistence.py with GSETTINGS_BACKEND=keyfile and a temporary XDG_CONFIG_HOME, so the
user's real dconf is never read or written. It refuses to run against any other backend."""

from __future__ import annotations

import os
import sys

if os.environ.get("GSETTINGS_BACKEND") != "keyfile" or not os.environ.get("XDG_CONFIG_HOME"):
    sys.exit("drive_persist: needs GSETTINGS_BACKEND=keyfile and a temporary XDG_CONFIG_HOME")

from src.gtk_version import Gio, GLib
from src.main import LinWallpapersApp


def main() -> int:
    how = sys.argv[1]
    route = sys.argv[2] if len(sys.argv) > 2 else None
    size = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else None
    app = LinWallpapersApp("io.mensuramedia.LinWallpapers.SmokePersist", Gio.ApplicationFlags.NON_UNIQUE)

    def opened() -> bool:
        window = app.window
        assert window is not None
        assert window.state.persistent, "no settings schema: run ./run.sh --setup"
        stored = window.state.size((0, 0))
        current = window.nav_manager.get_current_page()
        print(f"restored route={current} size={stored[0]}x{stored[1]}", flush=True)
        if route:
            window.activate_action("navigate", GLib.Variant("s", route))
        if size:
            window.unmaximize()
            window.resize(*size)  # GTK 3 only; the smoke driver is not ported code
        GLib.timeout_add(500, leave)
        return False

    def leave() -> bool:
        window = app.window
        assert window is not None
        width, height = window.get_size()  # GTK 3 only
        print(f"leaving route={window.nav_manager.get_current_page()} size={width}x{height}", flush=True)
        if how == "close":
            window.close()  # the window manager's close button: delete-event, then the app exits by itself
        else:
            app.activate_action("quit", None)  # Ctrl+Q
        return False

    app.connect("activate", lambda *_: GLib.timeout_add(300, opened))
    return int(app.run([]))


if __name__ == "__main__":
    sys.exit(main())
