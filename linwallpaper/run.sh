#!/usr/bin/env bash
# Launch LinWallpaper with the system Python (gi/GTK4/Adw/PIL are system packages).
# Robust to being called by absolute path, symlink or from any directory.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
cd "$here"
exec python3 -m linwallpaper.main "$@"
