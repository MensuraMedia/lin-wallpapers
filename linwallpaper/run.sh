#!/usr/bin/env bash
# Launch LinWallpaper with the system Python (gi/GTK4/Adw/PIL are system packages).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"
exec python3 -m linwallpaper.main "$@"
