# LinWallpaper

A small, honest **GTK 4 + libadwaita** app that sets a wallpaper across every screen of a Linux
machine — the **desktop** (per monitor), the **lock screen**, and, with your password, the **login
greeter**, the **boot splash**, and the **GRUB boot menu**. Open an image, pick a fit, see it in a
simulated monitor, and apply. No daemon, no background process; desktop changes need no root, and the
privileged screens ask for your password only when you apply to them.

> Lives in [`linwallpaper/`](linwallpaper/). It is a clean rewrite; the older GTK 3 project under
> `src/` is superseded and kept only for history.

## Install

The app installs with one script — [`linwallpaper/install.sh`](linwallpaper/install.sh) — which adds a
menu entry and panel icon (user-level, no root). It uses your **system** Python and packages; there is
nothing to build and no virtualenv.

```bash
# from a checkout
./linwallpaper/install.sh          # add the menu entry + icon (--uninstall to remove)
python3 -m linwallpaper.main       # or: ./linwallpaper/run.sh — run without installing
```

After installing, launch **LinWallpaper** from your applications menu (or the panel icon). See
[Install & run](#install--run) below for requirements, and [Using it](#using-it) to get started.

---

## What it does

- **Open any image** the desktop can load — the file filter is built from the installed GdkPixbuf
  loaders at runtime (PNG, JPEG, WebP, TIFF, BMP, GIF, and AVIF/HEIF/JXL/SVG where their loader is
  installed), so it accepts exactly what your system accepts.
- **Simulated monitors that never distort.** Each surface is previewed inside a fixed-aspect “monitor”
  (bezel + stand). Resizing the window never stretches the wallpaper — the monitor keeps its aspect and
  centres.
- **Fit modes** — Fill (zoom + centre-crop), Fit (letterbox), Center, Stretch. The preview and the
  applied result come from the **same** transform, so what you see is what you get.
- **The Screens page** is the app. It lists every surface as a monitor card:
  - a **global bar** at the top: a Fit control, **Open image…** (one image for everything), and
    **Apply to all** (applies to every desktop monitor + the lock screen in one click);
  - **per-card** Fit, **Apply**, and **Open image…** — so each screen can carry a **different** image.
- **Non-destructive & reversible.** Desktop applies are a settings write with **Undo**. Privileged
  applies **back up** every file first and support **`--undo`**.

## The five surfaces

| Surface | Needs root? | How LinWallpaper sets it |
| --- | --- | --- |
| **Desktop** (per monitor) | No | the desktop’s own setting (see backends below) |
| **Lock screen** | No | follows the desktop on Cinnamon; else the desktop setting |
| **Login screen** (greeter) | **Yes — password** | greeter config + a rendered background |
| **Boot splash** (Plymouth) | **Yes — password** | a Plymouth theme + initramfs rebuild |
| **Boot menu** (GRUB) | **Yes — password** | a GRUB background drop-in + `update-grub` |

Clicking **Apply** on a privileged surface opens a password dialog; the change runs through a careful,
reversible helper (`linwallpaper/privileged/lw_privileged.py`).

---

## OS support

### Desktop background (no root) — one backend per environment, chosen by evidence

| Environment | Mechanism | Per-monitor | Status on this build |
| --- | --- | --- | --- |
| **Cinnamon** | `gsettings org.cinnamon.desktop.background` | via composite | ✅ live-tested |
| **GNOME / Budgie** | `gsettings org.gnome.desktop.background` | via composite | 🟡 implemented, untested |
| **MATE** | `gsettings org.mate.background` | via composite | 🟡 implemented, untested |
| **Xfce** | `xfconf-query -c xfce4-desktop` | **native** | 🟡 implemented, untested |
| **X11, any WM** | `feh --bg-*` (one image per output) | **native** | 🟡 implemented, untested |
| KDE Plasma / wlroots (sway, Hyprland) | — | — | ⬜ not yet |

The backend is picked by a confidence probe (`$XDG_CURRENT_DESKTOP`, the settings tool on `PATH`); no
code branches on a distro name. On single-background desktops (GNOME/Cinnamon/MATE), “one screen” uses
a spanning **composite** canvas so a single monitor can differ.

### Privileged screens (password) — currently the Debian/Ubuntu/Mint family

| Surface | Mechanism | Family it targets today |
| --- | --- | --- |
| **Login** | `/etc/lightdm/slick-greeter.conf` + a `lightdm-gtk-greeter` drop-in + rendered image | LightDM greeters (Mint, Ubuntu, …) |
| **Boot splash** | Plymouth theme + `update-alternatives` + `update-initramfs -u -k all` | Debian / Ubuntu / Mint |
| **Boot menu** | `/etc/default/grub.d/` drop-in + `update-grub` | Debian / Ubuntu / Mint |

These reproduce the mechanism of `reference/apply-08-screen-wallpaper.sh` (backups, drop-ins only,
idempotent, `--undo`). **Fedora** (`dracut`, `grub2-mkconfig`) and **Arch** (`mkinitcpio`) are not wired
yet — the plan for making them universal is in [`docs/design/cross-distro-apply.md`](docs/design/cross-distro-apply.md).

---

## Install & run

Requirements (from your distribution, not PyPI): `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`,
`gir1.2-gdkpixbuf-2.0`, `python3-pil`. For the privileged screens: `pkexec`/`sudo` and the relevant
tools (`lightdm`/`slick-greeter`, `plymouth` + `update-initramfs`, `grub` + `update-grub`).

```bash
# run from a checkout
python3 -m linwallpaper.main        # or: ./linwallpaper/run.sh

# add a menu entry + icon (user-level; --uninstall to remove)
./linwallpaper/install.sh
```

Uses your **system** python3 (PyGObject/GTK/Pillow are system packages) — no virtualenv.

## Using it

1. **Screens** page → up top, **Open image…** and pick a Fit, then **Apply to all** for the desktop +
   lock in one click; or give a single screen its own image with that card’s **Open image…**.
2. For **Login / Boot splash / Boot menu**, click that card’s **Apply** → enter your password. Backups
   are taken first; revert any surface with:
   ```bash
   sudo python3 linwallpaper/privileged/lw_privileged.py <login|splash|grub> --undo
   ```

## Safety model

- **Nothing runs in the background.** The app applies and exits cleanly; nothing is installed as a
  service or autostart. (On wlroots compositors, a wallpaper *process* is the platform’s own, not the
  app’s.)
- **Desktop** = a reversible settings write (Undo in the toast).
- **Privileged** = every file **backed up** to `/var/backups/linwallpaper/<timestamp>/` with a manifest
  (path, mode, sha256, prior selection) **before** any write; **drop-ins only** (never edits a package
  conffile such as `/etc/default/grub`); **idempotent** (skips identical files); **rolls back** on error;
  **`--undo`** restores from the latest backup.

## Layout

```
linwallpaper/
  main.py monitors.py imaging.py
  backends/   base.py cinnamon.py gnome.py mate.py xfce.py x11_feh.py (_gsettings.py)
  ui/         window.py sidebar.py state.py monitor_frame.py password_dialog.py style.css  pages/
  privileged/ lw_privileged.py  assets/{plymouth,grub.d}
  data/       io.mensuramedia.LinWallpaper.desktop  icons/hicolor/…
  tests/  run.sh  install.sh
```

## Status & docs

- Working & verified: the GTK 4 app, desktop apply on Cinnamon (read-back confirmed), the Screens page,
  the simulated monitors, the password dialog, and the privileged helper’s dry-run/backups. The live
  privileged apply (login/boot) is user-tested with a password.
- Design & reference: [`docs/design/minimal-gtk4-app.md`](docs/design/minimal-gtk4-app.md) (as-built),
  [`docs/design/cross-distro-apply.md`](docs/design/cross-distro-apply.md) (making the privileged apply
  universal), `docs/STATUS.md` (handoff), `reference/` (the origin shell script).
