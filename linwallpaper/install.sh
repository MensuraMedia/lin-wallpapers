#!/usr/bin/env bash
#
# install.sh — desktop integration for LinWallpaper.
#
# Two modes:
#
#   (default) user-level — install the .desktop entry + icons under
#             $XDG_DATA_HOME (or ~/.local/share) and point Exec at THIS
#             checkout's run.sh (run-from-checkout). No root.
#
#   --system  system install — copy the Python package to
#             PREFIX/lib/linwallpaper, install a PREFIX/bin/linwallpaper
#             launcher, and the .desktop + icons under PREFIX/share. The app
#             then runs independently of this checkout. Needs write access to
#             PREFIX (usually via sudo). Default PREFIX=/usr/local.
#
# In keeping with the project's first rule, nothing here installs a service,
# daemon, autostart entry or login hook. The "Add to LinWallpaper" file-manager
# menu is a separate, runtime, user-level toggle in the app's Settings.
#
# Usage:
#   ./install.sh [--exec CMD] [--uninstall] [-h|--help]
#   ./install.sh --system [--prefix DIR] [--uninstall]
#
set -eu

APP_ID="io.mensuramedia.LinWallpaper"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"     # the linwallpaper/ package dir
CHECKOUT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # the dir that CONTAINS the package
ICON_SIZES="16 22 24 32 48 64 128 256"

EXEC_CMD=""
ACTION="install"
MODE="user"
PREFIX="/usr/local"

usage() {
    cat <<'EOF'
install.sh — desktop integration for LinWallpaper

Default (user-level): install the .desktop + icons under $XDG_DATA_HOME and
point Exec at this checkout's run.sh (run-from-checkout).
    ./install.sh [--exec CMD] [--uninstall]

--system: copy the package to PREFIX/lib/linwallpaper, install a
PREFIX/bin/linwallpaper launcher, and .desktop + icons under PREFIX/share
(independent of this checkout; needs write access to PREFIX — usually sudo).
    ./install.sh --system [--prefix DIR] [--uninstall]

Options:
    --exec CMD    Command the user-level .desktop runs (default: this tree's run.sh)
    --system      System install (see above)
    --prefix DIR  Install prefix for --system (default: /usr/local)
    --uninstall   Remove what a matching install placed
    -h, --help    Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --exec)      shift; EXEC_CMD="${1:?--exec needs a command}" ;;
        --exec=*)    EXEC_CMD="${1#--exec=}" ;;
        --system)    MODE="system" ;;
        --prefix)    shift; PREFIX="${1:?--prefix needs a directory}" ;;
        --prefix=*)  PREFIX="${1#--prefix=}" ;;
        --uninstall) ACTION="uninstall" ;;
        -h|--help)   usage; exit 0 ;;
        *) printf 'install.sh: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# ---- resolve destinations per mode ---------------------------------------
if [ "$MODE" = "system" ]; then
    DATA_DIR="$PREFIX/share"
    BIN_DIR="$PREFIX/bin"
    PKG_PARENT="$PREFIX/lib/linwallpaper"       # goes on PYTHONPATH; holds linwallpaper/
    LAUNCHER="$BIN_DIR/linwallpaper"
else
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
fi
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

install_icons() {
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
}

install_desktop() {
    # $1 = the Exec command line to record.
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    grep -v '^Exec=' "$SRC_DESKTOP" > "$tmp"
    printf 'Exec=%s\n' "$1" >> "$tmp"
    install -Dm644 "$tmp" "$DESKTOP_DEST"
    rm -f "$tmp"
    trap - EXIT

    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$DESKTOP_DEST" || \
            printf 'install.sh: desktop-file-validate reported warnings (non-fatal).\n' >&2
    fi
}

install_package() {
    # Copy the package to PKG_PARENT/linwallpaper (excluding tests + caches) and
    # write a launcher that runs it with the right PYTHONPATH.
    install -d "$PKG_PARENT"
    rm -rf "${PKG_PARENT:?}/linwallpaper"
    ( cd "$CHECKOUT_ROOT" && tar --exclude='__pycache__' --exclude='linwallpaper/tests' -cf - linwallpaper ) \
        | ( cd "$PKG_PARENT" && tar -xf - )

    install -d "$BIN_DIR"
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    {
        printf '#!/bin/sh\n'
        printf '# LinWallpaper launcher (system install)\n'
        printf 'exec env PYTHONPATH="%s" python3 -m linwallpaper.main "$@"\n' "$PKG_PARENT"
    } > "$tmp"
    install -Dm755 "$tmp" "$LAUNCHER"
    rm -f "$tmp"
    trap - EXIT
}

require_writable_prefix() {
    d="$PREFIX"
    while [ ! -e "$d" ]; do d="$(dirname "$d")"; done
    if [ ! -w "$d" ]; then
        printf 'install.sh: %s is not writable — re-run with sudo, or pass --prefix DIR.\n' "$PREFIX" >&2
        exit 1
    fi
}

do_install() {
    for f in "$SRC_SCALABLE" "$SRC_SYMBOLIC" "$SRC_DESKTOP"; do
        [ -f "$f" ] || { printf 'install.sh: missing source file: %s\n' "$f" >&2; exit 1; }
    done

    if [ "$MODE" = "system" ]; then
        install_package
        exec_line="$LAUNCHER"
    else
        exec_line="${EXEC_CMD:-$SCRIPT_DIR/run.sh}"
    fi

    install_icons
    install_desktop "$exec_line"
    refresh_caches

    printf 'Installed LinWallpaper (%s):\n' "$MODE"
    if [ "$MODE" = "system" ]; then
        printf '  package %s/linwallpaper\n' "$PKG_PARENT"
        printf '  launcher %s\n' "$LAUNCHER"
    fi
    printf '  icon    %s\n' "$SCALABLE"
    printf '  desktop %s  (Exec=%s)\n' "$DESKTOP_DEST" "$exec_line"
}

do_uninstall() {
    rm -f "$SCALABLE" "$SYMBOLIC" "$DESKTOP_DEST"
    for size in $ICON_SIZES; do
        rm -f "$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
    done
    if [ "$MODE" = "system" ]; then
        rm -f "$LAUNCHER"
        rm -rf "${PKG_PARENT:?}"
    fi
    refresh_caches
    printf 'Removed LinWallpaper (%s) from %s\n' "$MODE" "$DATA_DIR"
}

if [ "$MODE" = "system" ]; then
    require_writable_prefix
fi

case "$ACTION" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
esac
