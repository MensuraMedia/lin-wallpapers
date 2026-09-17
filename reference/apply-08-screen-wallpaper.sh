#!/usr/bin/env bash
# scripts/apply-08-screen-wallpaper.sh — boot, login and lock screens use the desktop wallpaper (FX506LI).
#
#   Source image: the invoking user's Cinnamon wallpaper (org.cinnamon.desktop.background picture-uri),
#   or the path given with --image. It is zoomed and center-cropped to 1920x1080, like Cinnamon's
#   "zoom" option, so every screen matches the desktop.
#
#   1. Login screen (slick-greeter): /usr/share/backgrounds/fx506li/wallpaper.jpg, set as background= in
#      /etc/lightdm/slick-greeter.conf (draw-user-backgrounds=false; the home folder isn't readable by lightdm)
#   2. Boot splash (Plymouth): theme "fx506li-wallpaper" (wallpaper + Mint throbber), set as the default;
#      initramfs rebuilt for all kernels
#   3. GRUB menu: /boot/grub/fx506li-wallpaper.png via /etc/default/grub.d/99-fx506li-background.cfg; update-grub
#   Lock screen: nothing to do — cinnamon-screensaver already draws the desktop wallpaper.
#
# USAGE (from the project folder)
#   sudo bash scripts/apply-08-screen-wallpaper.sh                 # all three, from the current wallpaper
#   sudo bash scripts/apply-08-screen-wallpaper.sh --image FILE    # use another image
#   sudo bash scripts/apply-08-screen-wallpaper.sh --no-plymouth --no-grub   # login screen only
#   sudo bash scripts/apply-08-screen-wallpaper.sh --preview       # show the boot splash for 8 s (no changes)
#   sudo bash scripts/apply-08-screen-wallpaper.sh --undo          # back to Mint's defaults
#
# Re-run it after changing the desktop wallpaper.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/configs"
RES=${RES:-1920x1080}
BG_DIR=/usr/share/backgrounds/fx506li
GREETER_CONF=/etc/lightdm/slick-greeter.conf
THEME=fx506li-wallpaper
THEME_DIR=/usr/share/plymouth/themes/$THEME
MINT_THEME=/usr/share/plymouth/themes/mint-logo/mint-logo.plymouth
GRUB_IMG=/boot/grub/fx506li-wallpaper.png
GRUB_DROPIN=/etc/default/grub.d/99-fx506li-background.cfg
BACKUP=/var/backups/fx506li/$(date +%Y%m%d-%H%M%S)
IMAGE="" DO_PLY=1 DO_GRUB=1 MODE=apply

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo bash $0 ${*:-}" >&2; exit 1; }
while (($#)); do
  case $1 in
    --image) IMAGE=$2; shift ;;
    --no-plymouth) DO_PLY=0 ;;
    --no-grub) DO_GRUB=0 ;;
    --preview) MODE=preview ;;
    --undo) MODE=undo ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '==> %s\n' "$*"; }
backup() {
  [[ -e $1 ]] || return 0
  mkdir -p "$BACKUP$(dirname "$1")"
  cp -a "$1" "$BACKUP$1"
  echo "    backup: $BACKUP$1"
}
set_ini() {  # set_ini FILE SECTION KEY VALUE (creates file/section if needed)
  python3 - "$@" <<'PY'
import configparser, sys
path, section, key, value = sys.argv[1:5]
c = configparser.ConfigParser(interpolation=None); c.optionxform = str
c.read(path)
if not c.has_section(section): c.add_section(section)
c.set(section, key, value)
with open(path, "w") as f: c.write(f, space_around_delimiters=False)
PY
}
del_ini() {  # del_ini FILE SECTION KEY
  python3 - "$@" <<'PY'
import configparser, sys, os
path, section, key = sys.argv[1:4]
if not os.path.exists(path): sys.exit(0)
c = configparser.ConfigParser(interpolation=None); c.optionxform = str
c.read(path)
if c.has_section(section): c.remove_option(section, key)
with open(path, "w") as f: c.write(f, space_around_delimiters=False)
PY
}

if [[ $MODE == preview ]]; then
  command -v plymouthd >/dev/null || { echo "plymouth not installed" >&2; exit 1; }
  say "Previewing the current default boot splash for 8 s (press nothing; it closes by itself)"
  plymouthd; plymouth --show-splash; sleep 8; plymouth quit
  exit 0
fi

if [[ $MODE == undo ]]; then
  say "Login screen: back to Mint's default background"
  backup "$GREETER_CONF"
  del_ini "$GREETER_CONF" Greeter background
  del_ini "$GREETER_CONF" Greeter draw-user-backgrounds
  rm -rf "$BG_DIR"
  say "Boot splash: back to mint-logo"
  update-alternatives --set default.plymouth "$MINT_THEME" || true
  update-alternatives --remove default.plymouth "$THEME_DIR/$THEME.plymouth" 2>/dev/null || true
  rm -rf "$THEME_DIR"
  update-initramfs -u -k all
  say "GRUB: no background"
  rm -f "$GRUB_DROPIN" "$GRUB_IMG"
  update-grub
  say "Undo complete. Reboot to see the default boot screens."
  exit 0
fi

# ---- source image --------------------------------------------------------------------------------
if [[ -z $IMAGE ]]; then
  [[ -n ${SUDO_USER:-} ]] || { echo "No SUDO_USER; pass --image FILE" >&2; exit 1; }
  uid=$(id -u "$SUDO_USER")
  uri=$(sudo -u "$SUDO_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
        gsettings get org.cinnamon.desktop.background picture-uri 2>/dev/null || true)
  IMAGE=$(python3 -c 'import sys, urllib.parse as u; s=sys.argv[1].strip("\x27 "); print(u.unquote(u.urlparse(s).path) if s.startswith("file://") else "")' "$uri")
fi
[[ -r $IMAGE ]] || { echo "Wallpaper not found or unreadable: '${IMAGE}' (use --image FILE)" >&2; exit 1; }
say "Source wallpaper: $IMAGE"

render() {  # render SRC DEST — zoom/center-crop to $RES
  python3 - "$1" "$2" "$RES" <<'PY'
import sys
from PIL import Image
src, dst, res = sys.argv[1], sys.argv[2], sys.argv[3]
W, H = (int(v) for v in res.split("x"))
im = Image.open(src).convert("RGB")
s = max(W / im.width, H / im.height)
im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
l, t = (im.width - W) // 2, (im.height - H) // 2
im = im.crop((l, t, l + W, t + H))
im.save(dst, quality=92) if dst.endswith(".jpg") else im.save(dst, optimize=True)
print(f"    rendered {dst} ({W}x{H})")
PY
}

# ---- 1. login screen -----------------------------------------------------------------------------
say "Login screen (slick-greeter)"
install -d -m 0755 "$BG_DIR"
render "$IMAGE" "$BG_DIR/wallpaper.jpg"
chmod 0644 "$BG_DIR/wallpaper.jpg"
backup "$GREETER_CONF"
set_ini "$GREETER_CONF" Greeter background "$BG_DIR/wallpaper.jpg"
set_ini "$GREETER_CONF" Greeter draw-user-backgrounds false
sed 's/^/    /' "$GREETER_CONF"

# ---- 2. boot splash ------------------------------------------------------------------------------
if ((DO_PLY)); then
  say "Boot splash (Plymouth theme $THEME)"
  install -d -m 0755 "$THEME_DIR"
  install -m 0644 "$SRC_DIR$THEME_DIR/$THEME.plymouth" "$SRC_DIR$THEME_DIR/$THEME.script" "$THEME_DIR/"
  cp /usr/share/plymouth/themes/mint-logo/throbber-*.png "$THEME_DIR/"
  render "$IMAGE" "$THEME_DIR/wallpaper.png"
  update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$THEME_DIR/$THEME.plymouth" 150
  update-alternatives --set default.plymouth "$THEME_DIR/$THEME.plymouth"
  say "Rebuilding initramfs for all kernels (a minute or two)"
  update-initramfs -u -k all
fi

# ---- 3. GRUB menu --------------------------------------------------------------------------------
if ((DO_GRUB)); then
  say "GRUB menu background"
  render "$IMAGE" "$GRUB_IMG"
  if ! cmp -s "$SRC_DIR$GRUB_DROPIN" "$GRUB_DROPIN"; then
    backup "$GRUB_DROPIN"
    install -D -m 0644 "$SRC_DIR$GRUB_DROPIN" "$GRUB_DROPIN"
  fi
  update-grub
fi

say "Result"
echo "    greeter background: $(grep -E '^background=' "$GREETER_CONF" || echo none)"
echo "    plymouth default:   $(readlink -f /usr/share/plymouth/themes/default.plymouth)"
echo "    grub background:    $(grep -c fx506li-wallpaper /boot/grub/grub.cfg 2>/dev/null || echo 0) reference(s) in grub.cfg"
echo "Done. Lock screen already follows the desktop wallpaper."
echo "Check: log out (login screen), reboot (GRUB + splash), or preview the splash: sudo bash $0 --preview"
