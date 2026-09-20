#!/usr/bin/env bash
#
# install.sh — user-level desktop integration for LinWallpaper.
#
# Installs the application icon (into the hicolor icon theme) and the .desktop
# entry (into the applications menu) under $XDG_DATA_HOME (or ~/.local/share),
# then refreshes the icon and desktop caches. It does NOT install the Python
# app itself: the .desktop Exec points back at this checkout's run.sh, which
# launches `python3 -m linwallpaper.main` with the system Python.
#
# In keeping with the project's first rule, nothing here installs a service,
# daemon, autostart entry or login hook.
#
# Usage:
#   ./install.sh [--exec CMD] [--uninstall] [-h|--help]
#
#   --exec CMD   Command the .desktop entry runs (default: this tree's run.sh)
#   --uninstall  Remove what a matching install placed
#   -h, --help   Show this help
#
set -eu

APP_ID="io.mensuramedia.LinWallpaper"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_SIZES="16 22 24 32 48 64 128 256"

EXEC_CMD=""
ACTION="install"

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --exec)      shift; EXEC_CMD="${1:?--exec needs a command}" ;;
        --exec=*)    EXEC_CMD="${1#--exec=}" ;;
        --uninstall) ACTION="uninstall" ;;
        -h|--help)   usage; exit 0 ;;
        *) printf 'install.sh: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_ROOT="$DATA_DIR/icons/hicolor"
APP_DIR="$DATA_DIR/applications"
SCALABLE="$ICON_ROOT/scalable/apps/$APP_ID.svg"
SYMBOLIC="$ICON_ROOT/symbolic/apps/$APP_ID-symbolic.svg"
DESKTOP_DEST="$APP_DIR/$APP_ID.desktop"

SRC_SCALABLE="$SCRIPT_DIR/data/icons/hicolor/scalable/apps/$APP_ID.svg"
SRC_SYMBOLIC="$SCRIPT_DIR/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
SRC_ICON_ROOT="$SCRIPT_DIR/data/icons/hicolor"
SRC_DESKTOP="$SCRIPT_DIR/data/$APP_ID.desktop"

refresh_caches() {
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "$ICON_ROOT" 2>/dev/null || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "$APP_DIR" 2>/dev/null || true
    fi
}

rasterize() {
    # Emit PNGs per size when a rasteriser is available; otherwise the scalable
    # SVG alone is a valid hicolor install. Returns 1 if no rasteriser found.
    src="$1"
    for size in $ICON_SIZES; do
        dest="$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
        mkdir -p "$(dirname "$dest")"
        if command -v rsvg-convert >/dev/null 2>&1; then
            rsvg-convert -w "$size" -h "$size" "$src" -o "$dest"
        elif command -v inkscape >/dev/null 2>&1; then
            inkscape "$src" --export-type=png --export-filename="$dest" \
                -w "$size" -h "$size" >/dev/null 2>&1
        elif command -v magick >/dev/null 2>&1; then
            magick -background none "$src" -resize "${size}x${size}" "$dest"
        elif command -v convert >/dev/null 2>&1; then
            convert -background none "$src" -resize "${size}x${size}" "$dest"
        else
            return 1
        fi
    done
    return 0
}

do_install() {
    for f in "$SRC_SCALABLE" "$SRC_SYMBOLIC" "$SRC_DESKTOP"; do
        [ -f "$f" ] || { printf 'install.sh: missing source file: %s\n' "$f" >&2; exit 1; }
    done

    exec_line="${EXEC_CMD:-$SCRIPT_DIR/run.sh}"

    install -Dm644 "$SRC_SCALABLE" "$SCALABLE"
    install -Dm644 "$SRC_SYMBOLIC" "$SYMBOLIC"

    # Prefer the PNGs shipped in the repo — reliable everywhere, including systems
    # whose SVG pixbuf loader is broken/missing (the panel can't show an SVG there).
    # Fall back to rasterising the SVG only if no PNGs are shipped.
    installed_png=0
    for size in $ICON_SIZES; do
        src_png="$SRC_ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
        if [ -f "$src_png" ]; then
            install -Dm644 "$src_png" "$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
            installed_png=1
        fi
    done
    if [ "$installed_png" -eq 1 ]; then
        printf 'Installed PNG icons (%s).\n' "$ICON_SIZES"
    elif rasterize "$SRC_SCALABLE"; then
        printf 'Rasterised PNG icons from the SVG (%s).\n' "$ICON_SIZES"
    else
        printf 'No PNG icons shipped and no SVG rasteriser — scalable SVG only.\n' >&2
    fi

    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    grep -v '^Exec=' "$SRC_DESKTOP" > "$tmp"
    printf 'Exec=%s\n' "$exec_line" >> "$tmp"
    install -Dm644 "$tmp" "$DESKTOP_DEST"
    rm -f "$tmp"
    trap - EXIT

    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$DESKTOP_DEST" || \
            printf 'install.sh: desktop-file-validate reported warnings (non-fatal).\n' >&2
    fi

    refresh_caches
    printf 'Installed LinWallpaper desktop integration:\n'
    printf '  icon    %s\n' "$SCALABLE"
    printf '  desktop %s  (Exec=%s)\n' "$DESKTOP_DEST" "$exec_line"
}

do_uninstall() {
    rm -f "$SCALABLE" "$SYMBOLIC" "$DESKTOP_DEST"
    for size in $ICON_SIZES; do
        rm -f "$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
    done
    refresh_caches
    printf 'Removed LinWallpaper desktop integration from %s\n' "$DATA_DIR"
}

case "$ACTION" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
esac
