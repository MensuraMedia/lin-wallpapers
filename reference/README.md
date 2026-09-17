# The base script

`apply-08-screen-wallpaper.sh` is **the origin and the engine of this project**. It is the working shell
script that puts one image on the login screen, the boot splash and the GRUB menu of a real machine
(ASUS TUF F15 FX506LI, Linux Mint 22.2), written and applied in
[optimize-laptop-asus-fx50li](https://github.com/MensuraMedia/optimize-laptop-asus-fx50li) on 2026-09-17.

**Lin Wallpapers is this script, turned into an application.** The app does not invent a new way to change
these screens: every apply provider reproduces the steps below, in the same order, with the same paths,
the same fallbacks and the same undo — with a catalogue, previews, backups and a GUI around them.

| File | What it is |
| --- | --- |
| `apply-08-screen-wallpaper.sh` | The script, verbatim as applied (173 lines, root, idempotent, `--undo`) |
| `plymouth-theme/fx506li-wallpaper.plymouth` | Theme manifest (`ModuleName=script`) — the template the app generates per install |
| `plymouth-theme/fx506li-wallpaper.script` | Plymouth script: cover-scaled background sprite at z = −100, 30 throbber frames at 75 % height, password/question/message callbacks |
| `grub.d/99-fx506li-background.cfg` | The GRUB drop-in: `GRUB_BACKGROUND` + `GRUB_GFXMODE` (never `/etc/default/grub`, a package conffile) |

Names carrying the reference machine (`fx506li`, `/usr/share/backgrounds/fx506li`, theme
`fx506li-wallpaper`) become `lin-wallpapers` in the product; nothing else about the mechanism changes.

---

## What the script does, step by step → where it lives in the app

| # | Script step | Implementation in the script | App module | Notes on the port |
| --- | --- | --- | --- | --- |
| 1 | **Find the source image** | `gsettings get org.cinnamon.desktop.background picture-uri` as `$SUDO_USER` over that user's session bus, `file://` URI unquoted with Python; or `--image FILE` | `apply/providers/desktop_cinnamon.current()`, `sync/agent.py` | The GUI already knows the image (it was picked in the catalogue); the same read is what **Sync mode** watches, and the same D-Bus-address trick is why the helper never needs the user's session |
| 2 | **Render** | `render()`: Pillow, `convert("RGB")`, scale by `max(W/w, H/h)`, center-crop to `1920x1080`, JPEG q92 or optimized PNG | `imaging/transform.py` (`mode="fill"`) | Identical math, now also `fit` / `center` / `stretch`, a focal point, EXIF/ICC handling and a GRUB color profile. The preview compositor renders through this same function, which is why a preview equals the result |
| 3 | **Login screen** | `install -d` `/usr/share/backgrounds/fx506li`, render `wallpaper.jpg`, `chmod 0644`, then `set_ini` `background=` and `draw-user-backgrounds=false` in `/etc/lightdm/slick-greeter.conf` | `apply/providers/greeter_slick.py` | The copy-to-system-path step is mandatory (`$HOME` is mode 750). `set_ini`/`del_ini` become the INI editor in the provider — create file and section if missing, replace in place otherwise |
| 4 | **Boot splash** | Install `.plymouth` + `.script` from `configs/`, copy `throbber-*.png` from `mint-logo`, render `wallpaper.png`, `update-alternatives --install … 150` + `--set`, `update-initramfs -u -k all` | `apply/providers/splash_plymouth.py` + `resources/plymouth-template/` | The theme is generated from the template here instead of copied from a repo; the throbber frames still come from the distribution's own theme (see NOTICE). Priority 150 and the `--set` pair are kept |
| 5 | **GRUB menu** | Render `/boot/grub/fx506li-wallpaper.png`, install the drop-in only when it differs (`cmp -s`), `update-grub` | `apply/providers/bootmenu_grub.py` | `cmp -s` before writing is the idempotence rule the whole apply engine inherits: never write what is already right, never touch a conffile |
| 6 | **Lock screen** | Nothing — cinnamon-screensaver already draws the desktop background | `apply/providers/lock_cinnamon.probe()` | The app states this in the UI instead of leaving it implicit, and only writes an override when the user wants a *different* lock image |
| 7 | **Backups** | `backup()` copies each file it is about to touch into `/var/backups/fx506li/<timestamp>/` | `apply/backup.py` | Same location pattern (`/var/backups/lin-wallpapers/<timestamp>/`), plus a JSON manifest with modes, owners, sha256 and the previous `update-alternatives` selection, so undo is data rather than memory |
| 8 | **Undo** | `--undo`: `update-alternatives --set` back to `mint-logo`, remove the theme dir, `del_ini` the greeter keys, remove the GRUB image and drop-in, `update-initramfs -u -k all`, `update-grub` | `apply/providers/*.revert()`, `cli: linwp undo`, History page | The script's undo is per-surface and complete; the app replays it from the backup manifest of a specific apply event |
| 9 | **Preview** | `--preview`: `plymouthd` + `plymouth --show-splash`, 8 s, `plymouth quit` | `preview/surfaces/splash_plymouth.py` ("Run the real splash") | Kept verbatim as the *live check* offered after an apply; the five in-app previews are the Cairo mock-ups that come before it |
| 10 | **Report** | Prints the greeter background, the resolved `default.plymouth` and the count of theme references in `grub.cfg` | `apply/verify.py`, `linwp doctor` | Verification is promoted from "printed at the end" to "checked before commit", and gains the initramfs content check (`lsinitramfs \| grep`) that was done by hand after this script ran |

## Design rules inherited from the script (non-negotiable in the app)

1. **Root does only what needs root.** The script is run with `sudo` by the user; the app keeps the same
   split, with a polkit-authorized helper in place of `sudo`.
2. **Idempotent.** Re-running changes nothing that is already correct. Every provider must be safe to run twice.
3. **Never edit a package conffile.** Drop-ins only (`/etc/default/grub.d/99-…`), because a modified conffile
   causes interactive prompts on the next package upgrade — a rule learned the hard way in the reference project.
4. **Every step is reversible, and the reverse is written at the same time as the forward step.**
5. **The expensive steps run once.** One `update-initramfs -u -k all`, one `update-grub`, at the end.
6. **Say what happened.** The script prints its result; the app shows it, verifies it, and keeps the history.

## Running the script directly

It still works on its own, and remains the fallback if the app can't run:

```bash
sudo bash apply-08-screen-wallpaper.sh                    # all three, from the current desktop wallpaper
sudo bash apply-08-screen-wallpaper.sh --image FILE       # a specific image
sudo bash apply-08-screen-wallpaper.sh --no-plymouth --no-grub
sudo bash apply-08-screen-wallpaper.sh --preview          # show the boot splash for 8 s, change nothing
sudo bash apply-08-screen-wallpaper.sh --undo             # back to the distribution defaults
```

It expects the Plymouth theme and GRUB drop-in at `../configs/...` relative to itself (the layout of the
project it came from). In this repository those files are in `plymouth-theme/` and `grub.d/`, so run it from
a checkout of the original project, or set `SRC_DIR` accordingly — the app's providers remove this
dependency by generating both from `resources/plymouth-template/`.
