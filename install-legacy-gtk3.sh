#!/usr/bin/env bash
#
# install-legacy-gtk3.sh — desktop integration for the superseded GTK 3 Lin Wallpapers (src/).
# Kept for history; the current app installs with ./install.sh (LinWallpaper, GTK 4).
#
# Installs the launcher icon (into the hicolor icon theme) and the application's
# .desktop entry (into the applications menu), then refreshes the icon and
# desktop caches. This is *desktop integration only* — it does not install the
# Python application itself; full distribution packaging arrives in the
# packaging milestone. By default it launches the app from this source tree via
# run.sh; override with --exec once a real launcher exists.
#
# In keeping with the project's first rule, nothing here installs a service, a
# daemon, an autostart entry or a login hook. There is no system tray.
#
# Usage:
#   ./install-legacy-gtk3.sh [--user | --system] [--prefix DIR] [--exec CMD] [--uninstall]
#
#   --user        Install for the current user (default): $XDG_DATA_HOME or ~/.local/share
#   --system      Install system-wide under --prefix (default /usr/local); needs write access
#   --prefix DIR  Prefix for --system (default: /usr/local)
#   --exec CMD    Command the .desktop entry runs (default: this tree's run.sh)
#   --uninstall   Remove what a matching install placed
#   -h, --help    Show this help
#
set -eu

APP_ID="io.mensuramedia.LinWallpapers"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_SIZES="16 22 24 32 48 64 128 256"

MODE="user"
PREFIX="/usr/local"
EXEC_CMD=""
ACTION="install"

usage() {
    sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --user)      MODE="user" ;;
        --system)    MODE="system" ;;
        --prefix)    shift; PREFIX="${1:?--prefix needs a directory}" ;;
        --prefix=*)  PREFIX="${1#--prefix=}" ;;
        --exec)      shift; EXEC_CMD="${1:?--exec needs a command}" ;;
        --exec=*)    EXEC_CMD="${1#--exec=}" ;;
        --uninstall) ACTION="uninstall" ;;
        -h|--help)   usage; exit 0 ;;
        *) printf 'install-legacy-gtk3.sh: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [ "$MODE" = "system" ]; then
    DATA_DIR="$PREFIX/share"
else
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
fi

ICON_ROOT="$DATA_DIR/icons/hicolor"
APP_DIR="$DATA_DIR/applications"
SCALABLE="$ICON_ROOT/scalable/apps/$APP_ID.svg"
SYMBOLIC="$ICON_ROOT/symbolic/apps/$APP_ID-symbolic.svg"
DESKTOP_DEST="$APP_DIR/$APP_ID.desktop"

SRC_SCALABLE="$SCRIPT_DIR/resources/icons/hicolor/scalable/apps/$APP_ID.svg"
SRC_SYMBOLIC="$SCRIPT_DIR/resources/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
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
    # Emit PNGs for each size when a rasteriser is available; otherwise the
    # scalable SVG alone is a valid hicolor install. Returns 1 if none found.
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
        [ -f "$f" ] || { printf 'install-legacy-gtk3.sh: missing source file: %s\n' "$f" >&2; exit 1; }
    done

    exec_line="${EXEC_CMD:-$SCRIPT_DIR/run.sh}"

    install -Dm644 "$SRC_SCALABLE" "$SCALABLE"
    install -Dm644 "$SRC_SYMBOLIC" "$SYMBOLIC"

    if rasterize "$SRC_SCALABLE"; then
        printf 'Rasterised PNG icons (%s).\n' "$ICON_SIZES"
    else
        printf 'No SVG rasteriser found — installed the scalable icon only ' >&2
        printf '(install librsvg2-bin, inkscape or imagemagick for PNGs).\n' >&2
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
            printf 'install-legacy-gtk3.sh: desktop-file-validate reported warnings (non-fatal).\n' >&2
    fi

    refresh_caches
    printf 'Installed Lin Wallpapers desktop integration:\n'
    printf '  icon    %s\n' "$SCALABLE"
    printf '  desktop %s  (Exec=%s)\n' "$DESKTOP_DEST" "$exec_line"
}

do_uninstall() {
    rm -f "$SCALABLE" "$SYMBOLIC" "$DESKTOP_DEST"
    for size in $ICON_SIZES; do
        rm -f "$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
    done
    refresh_caches
    printf 'Removed Lin Wallpapers desktop integration from %s\n' "$DATA_DIR"
}

case "$ACTION" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
esac
