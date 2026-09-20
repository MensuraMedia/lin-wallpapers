#!/usr/bin/env bash
# run.sh — create the venv, build the resource bundle and settings schema, launch Lin Wallpapers.
#
#   ./run.sh              launch the app
#   ./run.sh --setup      prepare venv + build outputs only (used by `make`)
#   ./run.sh --dev        also install the development tools (ruff, mypy, pytest, ...)
#   LWP_GTK=4.0 ./run.sh  (from M8) the GTK 4 build
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=.venv
BUILD=build
mode=run
case "${1:-}" in
  --setup) mode=setup; shift ;;
  --dev) mode=dev; shift ;;
esac

if ! python3 -c 'import gi, cairo, PIL' 2>/dev/null; then
  echo "Missing system packages. Install them with:" >&2
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 python3-gi-cairo python3-pil" >&2
  exit 1
fi

if [[ ! -x $VENV/bin/python ]]; then
  echo "Creating $VENV (with system site packages, for PyGObject)"
  python3 -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -e .
fi
if [[ $mode == dev && ! -x $VENV/bin/ruff ]]; then
  "$VENV/bin/pip" install --quiet -r requirements-dev.txt
fi

mkdir -p "$BUILD/schemas"
if command -v glib-compile-resources >/dev/null; then
  glib-compile-resources --sourcedir=resources --target="$BUILD/lin-wallpapers.gresource" \
    resources/lin-wallpapers.gresource.xml
else
  echo "glib-compile-resources not found (libglib2.0-dev-bin): loading CSS from resources/ instead" >&2
fi
cp data/io.mensuramedia.LinWallpapers.gschema.xml "$BUILD/schemas/"
glib-compile-schemas --strict "$BUILD/schemas"

[[ $mode == run ]] || exit 0
exec "$VENV/bin/python" -m src.main "$@"
