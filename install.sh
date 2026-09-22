#!/usr/bin/env bash
#
# install.sh — one-command installer for LinWallpaper (GTK 4 + libadwaita).
#
#   git clone https://github.com/MensuraMedia/linwallpapers.git && bash linwallpapers/install.sh
#
# 1. installs the runtime packages that are missing (Debian / Ubuntu / Linux Mint / Pop!_OS …, via apt;
#    asks for sudo only when something is missing): python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1,
#    gir1.2-gdkpixbuf-2.0, python3-pil, and pkexec (for the login / boot-splash / GRUB screens)
# 2. checks GTK 4, libadwaita and Pillow load (headless — no window opens)
# 3. hands over to linwallpaper/install.sh for the menu entry + icons:
#      default    user-level, runs from this checkout (update later with `git pull`), no root
#      --system   copies the app to /usr/local (or --prefix DIR) + a `linwallpaper` command, for all users
#
# Nothing is installed as a service, daemon, autostart entry or login hook. Safe to re-run.
#
# Usage:
#   bash install.sh [--system [--prefix DIR]] [--no-deps] [--uninstall] [-h|--help]
#
#   --system      system-wide install (uses sudo for the copy)
#   --prefix DIR  prefix for --system (default /usr/local)
#   --no-deps     skip the package step (you installed the packages yourself)
#   --uninstall   remove the menu entry + icons (and, with --system, the system copy); packages stay
#
set -eu

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP_INSTALLER="$HERE/linwallpaper/install.sh"
PACKAGES="python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 python3-pil pkexec"

SYSTEM=0; PREFIX=""; DEPS=1; UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --system)    SYSTEM=1 ;;
        --prefix)    shift; PREFIX="${1:?--prefix needs a directory}" ;;
        --prefix=*)  PREFIX="${1#--prefix=}" ;;
        --no-deps)   DEPS=0 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)   sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) printf 'install.sh: unknown option: %s (see --help)\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

if [ -t 1 ]; then B=$(printf '\033[1m'); G=$(printf '\033[32m'); Y=$(printf '\033[33m'); R=$(printf '\033[31m'); N=$(printf '\033[0m')
else B=""; G=""; Y=""; R=""; N=""; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$N"; }
ok()   { printf '    %sOK%s    %s\n' "$G" "$N" "$*"; }
note() { printf '    %sNOTE%s  %s\n' "$Y" "$N" "$*"; }
die()  { printf '    %sFAIL%s  %s\n' "$R" "$N" "$*" >&2; exit 1; }

[ -f "$APP_INSTALLER" ] || die "linwallpaper/install.sh not found next to this script - run it from a full clone"
if [ "$(id -u)" -eq 0 ] && [ -z "${SUDO_USER:-}" ] && [ "$SYSTEM" -eq 0 ]; then
    die "run as your normal user (the menu entry is per-user); it asks for sudo when needed, or use --system"
fi
if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SYSTEM" -eq 0 ]; then
    die "don't use sudo for the default install (it would install for root) - run: bash install.sh"
fi
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

run_app_installer() {
    if [ "$SYSTEM" -eq 1 ]; then
        # shellcheck disable=SC2086
        $SUDO "$APP_INSTALLER" --system ${PREFIX:+--prefix "$PREFIX"} "$@"
    else
        "$APP_INSTALLER" "$@"
    fi
}

if [ "$UNINSTALL" -eq 1 ]; then
    step "Removing LinWallpaper"
    run_app_installer --uninstall
    ok "Removed (packages and your wallpaper library/settings were left in place)"
    exit 0
fi

step "Runtime packages"
if [ "$DEPS" -eq 0 ]; then
    note "skipped (--no-deps)"
elif command -v apt-get >/dev/null 2>&1; then
    missing=""
    for p in $PACKAGES; do
        dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing="$missing $p"
    done
    if [ -z "$missing" ]; then
        ok "all present: $PACKAGES"
    else
        printf '          installing:%s (sudo)\n' "$missing"
        $SUDO apt-get update -qq || die "apt-get update failed (network?)"
        # shellcheck disable=SC2086
        if ! $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $missing >/dev/null; then
            die "apt-get could not install:$missing"
        fi
        ok "installed:$missing"
    fi
else
    note "not a Debian-family system - install these yourself, then re-run with --no-deps:"
    note "  Fedora: sudo dnf install python3-gobject gtk4 libadwaita python3-pillow polkit"
    note "  Arch:   sudo pacman -S python-gobject gtk4 libadwaita python-pillow polkit"
fi

step "Checking GTK 4, libadwaita and Pillow (no window opens)"
if python3 - <<'EOF' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
import PIL  # noqa: F401
EOF
then
    ok "python3 $(python3 -c 'import platform; print(platform.python_version())'), GTK 4 and libadwaita importable"
else
    die "GTK 4 / libadwaita / Pillow not importable - install: $PACKAGES"
fi

step "Menu entry and icons"
if [ "$SYSTEM" -eq 1 ]; then
    run_app_installer
    ok "system install: launch from the menu, or run: linwallpaper"
else
    run_app_installer
    ok "installed for $(id -un): launch LinWallpaper from the menu, or run: $HERE/linwallpaper/run.sh"
    printf '          update later with: git -C %s pull   (no reinstall needed)\n' "$HERE"
fi

printf '\n%s%sLinWallpaper is ready.%s\n' "$G" "$B" "$N"
