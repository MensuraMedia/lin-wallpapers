# Lin Wallpapers

**One wallpaper, every screen.**
Lin Wallpapers finds the images already on your machine, catalogues them into a fast browser, and applies
the one you pick to your **desktop, lock screen, login screen, boot splash and boot menu** — with a preview
of each screen before anything changes, and one-click undo after.

> **Status: design phase.** This repository currently holds the technical concept, this README and the UI
> mockups. Application code begins at milestone **M0** ([TECHNICAL-CONCEPT.md §21](TECHNICAL-CONCEPT.md#21-roadmap)).
> Everything below describes the target of v1.0.

| | |
| --- | --- |
| Platforms | Any Debian-based distribution with GTK 3 — Mint, Ubuntu and its flavours, Debian 12+, Pop!_OS, Zorin, MX, elementary. The desktop, greeter, boot splash and boot manager are **detected, never assumed** |
| Stack | Python 3.12 · GTK 3 (PyGObject), written to port to GTK 4 · Cairo · GdkPixbuf/Pillow · SQLite · D-Bus + polkit |
| Based on | [gtk-python-dashboard-starter](https://github.com/mikesdatawork/gtk-python-dashboard-starter) (app shell) · [`reference/apply-08-screen-wallpaper.sh`](reference/README.md) (the working base script the apply engine is built around) |
| Standards | [MensuraMedia/universal-instruction-set](https://github.com/MensuraMedia/universal-instruction-set) v2026.04 |
| Design reference | `universal-themes/image-reference/ui-kit-yellow-gray-yello.jpg` (dark navy-gray, one yellow accent) |
| License | Free to use, modify and distribute. **Commercial use requires prior written permission.** ([LICENSE](LICENSE), [NOTICE](NOTICE)) |

---

## Contents
1. [Why this exists](#1-why-this-exists)
2. [What it does](#2-what-it-does)
3. [The five screens](#3-the-five-screens)
3a. [Every Debian-based distro](#3a-every-debian-based-distro)
3b. [The base script](#3b-the-base-script)
4. [Using the app](#4-using-the-app)
5. [The GTK Python stack](#5-the-gtk-python-stack)
6. [Architecture and modularity](#6-architecture-and-modularity)
7. [Design language](#7-design-language)
8. [Safety and security](#8-safety-and-security)
9. [Installation](#9-installation)
10. [Command line](#10-command-line)
11. [Development](#11-development)
12. [Project layout](#12-project-layout)
13. [Roadmap](#13-roadmap)
14. [Documentation](#14-documentation)
15. [License and credits](#15-license-and-credits)

---

## 1. Why this exists

Changing the desktop wallpaper is easy. Making the *whole machine* match it is not:

| Screen | What it actually takes by hand |
| --- | --- |
| Desktop | a settings panel — fine |
| Lock screen | usually follows the desktop, unless it doesn't |
| Login screen | root: copy the image somewhere the greeter user can read (your home folder is mode 750), then edit the greeter config |
| Boot splash | root: write a Plymouth theme, register it with `update-alternatives`, rebuild the initramfs for every kernel |
| Boot menu | root: convert the image to something GRUB can decode, add a `/etc/default/grub.d` drop-in, run `update-grub` |

That procedure was written and run by hand on an ASUS TUF F15 (Linux Mint 22.2) — it works, it is in this
repository as [`reference/apply-08-screen-wallpaper.sh`](reference/README.md), and it is far too much work
to repeat for the next wallpaper, let alone on another machine or another distribution. Lin Wallpapers
turns that script into an application: discovery, a catalogue, real previews, a transactional apply and an
undo — and providers that make the same steps work beyond Mint.

## 2. What it does

| Area | Functionality |
| --- | --- |
| **Discover** | Scans home folders, XDG picture directories, system wallpaper directories, extra partitions and external drives. Network mounts, caches, snapshots, game libraries and build trees are excluded by default. Incremental rescans skip unchanged files; new drives offer themselves. |
| **Catalogue** | A local SQLite index: resolution, aspect, format, dominant palette, perceptual hash, duplicates, badges and a suitability score, with a thumbnail cache. Rebuildable at any time; an unplugged drive dims its images instead of losing them. |
| **Judge** | A transparent 0–100 suitability score — resolution against your actual displays, aspect match, detail distribution (is there a calm area for the login prompt?), color coherence, format integrity, and penalties for icons, sprites and tiny images. Every badge explains itself. |
| **Browse** | A virtualized grid that stays smooth at tens of thousands of images: search, filter by resolution/aspect/orientation/color/text-safe/duplicates/source, sort, tag, collect, and smart collections from saved filters. |
| **Preview** | See the image *as each screen* before applying: desktop with panel and icons, lock screen with clock, login screen with the greeter's fields, boot splash rendered with the real theme geometry, and the boot menu over the quantized image. Optionally run the real splash for 8 seconds on the framebuffer. |
| **Apply** | To one screen or to all five. You see the exact step list first. Every apply backs up what was there, verifies the result (including that the theme really is inside the new initramfs) and rolls back on failure. |
| **Undo** | Full history of applies with thumbnails and results; undo restores every file and setting from the backup manifest. |
| **Sync** | Optional: keep all screens matching the desktop wallpaper automatically, with a clear explanation of the authorization trade-off. |
| **Script** | The `linwp` CLI does everything the GUI does, for automation and headless use. |

## 3. The five screens

| Screen | How it's set | Needs root | Takes effect |
| --- | --- | --- | --- |
| **Desktop** | Desktop settings (`org.cinnamon.desktop.background` and equivalents), per monitor where supported | no | instantly |
| **Lock screen** | Follows the desktop, or an explicit override | no | next lock |
| **Login screen** | Image copied to a system path + greeter configuration (slick-greeter first) | yes | next logout |
| **Boot splash** | Generated Plymouth theme + `update-alternatives` + initramfs rebuild | yes | next boot |
| **Boot menu** | GRUB-safe PNG + `/etc/default/grub.d` drop-in + `update-grub` | yes | next boot |

Each screen is probed at runtime. If your machine can't do one of them — no Plymouth, a read-only `/boot`,
GDM under Wayland — the app says so, names the component that owns it, and disables that tile instead of
failing halfway through an apply.

## 3a. Every Debian-based distro

Nothing in the mechanism is Mint-specific; only the *names* and the *assumptions* were. Both are replaced by
runtime detection, so the same build works across the family. What gets detected, and what it selects:

| Your machine has | Lin Wallpapers uses | Typically |
| --- | --- | --- |
| Cinnamon · GNOME · MATE · Xfce · Plasma | that desktop's own background mechanism (GSettings, `xfconf`, `plasma-apply-wallpaperimage`) | Mint · Ubuntu/Debian/Pop!_OS/Zorin · Ubuntu MATE · Xubuntu/MX · Kubuntu |
| slick-greeter · lightdm-gtk-greeter · SDDM · GDM3 | that greeter's own configuration (drop-in or config key; GDM through its documented, reversible override) | Mint · Xubuntu/MX/Debian Xfce · Kubuntu/Lubuntu · Ubuntu/Debian GNOME |
| Plymouth with initramfs-tools · with dracut | a generated script theme + `update-alternatives`, then `update-initramfs -u -k all` or `dracut --regenerate-all` | all of them |
| GRUB 2 · no GRUB | a `/etc/default/grub.d` drop-in + `update-grub`/`grub-mkconfig`, or the surface reported unsupported with the reason | all of them · some EFI installs |

Distribution-specific details are resolved the same way: the spinner frames for the generated boot theme are
taken from whichever Plymouth theme is currently selected (`mint-logo`, `bgrt`, `spinner`, …), the boot-menu
command and the `grub.cfg` location are detected, and the initramfs generator is whichever one owns
`/boot/initrd.img-*`. No code branches on a distribution name — full matrix in
[TECHNICAL-CONCEPT.md §4.2](TECHNICAL-CONCEPT.md).

`linwp doctor` prints exactly what was detected on your machine, and why any screen is unavailable.

## 3b. The base script

[`reference/apply-08-screen-wallpaper.sh`](reference/README.md) is the working script that already does the
three privileged screens on a real machine — and it *is* the engine. Each of its steps maps to a module:
reading the current wallpaper from the desktop settings, the zoom/center-crop render, copying the image to a
greeter-readable system path and editing the greeter config, generating the Plymouth theme and rebuilding
the initramfs, writing the GRUB drop-in and regenerating the menu, backing up before each write, and the
complete `--undo`. The app adds the catalogue, previews, verification and history around those steps; it
does not replace them. Mapping table: [`reference/README.md`](reference/README.md).

## 4. Using the app

1. **First run** — Lin Wallpapers proposes scan locations (your Pictures folder, system wallpapers, mounted
   partitions). Nothing is scanned until you say go.
2. **Browse** — the grid fills as the scan runs. Filter to `≥ native resolution` and `text-safe` if you want
   candidates that work on every screen.
3. **Pick** — open an image for the large preview, metadata, palette and fit mode (fill / fit / center /
   stretch, with a drag-to-position focal point).
4. **Preview the screens** — the five surface previews are built from the same transform that will be
   installed, so the crop you see is the crop you get.
5. **Apply** — choose one screen or *Apply everywhere*. The sheet shows the exact steps and warns that the
   boot splash rebuilds the initramfs (about 20 seconds). Authorize once; progress is per step.
6. **Check** — desktop and lock screen change immediately; log out for the login screen; reboot for the
   splash and boot menu. If anything looks wrong, **Undo** puts it all back.

## 5. The GTK Python stack

| Layer | Technology | Why |
| --- | --- | --- |
| Language | **Python 3.12** (3.11 minimum) | Native on Debian/Mint, fast to iterate, strong stdlib (`sqlite3`, `hashlib`, `os.scandir`, `concurrent.futures`) |
| UI toolkit | **GTK 3.24** via **PyGObject 3.48** (`gi.repository.Gtk`, `Gdk`, `GLib`, `Gio`) | Native Linux widgets and performance; the starter template's base. Written to port to GTK 4 (concept §18). |
| Graphics | **Cairo** via **pycairo** | The screen previews (splash, greeter, GRUB menu mock-ups), score rings and crop overlay are drawn, not faked in images |
| Images | **GdkPixbuf** (loading, thumbnails, animation-safe probing) + **Pillow 10** (transforms, EXIF/ICC, quantization, format conversion) | GdkPixbuf integrates with GTK; Pillow does the pixel work GdkPixbuf doesn't |
| Styling | **GTK CSS** with `@define-color` design tokens, bundled in a **GResource** | One source of truth for the yellow/gray theme; the starter's theme applicator picks it up |
| App model | `Gtk.Application` (single instance), `Gio.SimpleAction`, `GObject` signals | Desktop integration, clean state flow, no `Gtk.main()` |
| Lists | `Gtk.FlowBox` with child recycling behind one component (→ `Gtk.GridView` in GTK 4) | Smooth scrolling at 20,000+ cards |
| Concurrency | Worker threads (`concurrent.futures`) for scan/probe/thumbnail/transform; `GLib.idle_add` back to the UI; `GLib` frame-clock ticks for animation | The UI never blocks on I/O |
| Storage | **SQLite** (`sqlite3`, WAL) for the catalogue; freedesktop-style thumbnail cache; JSON for plans and backup manifests | One portable file, rebuildable, no server |
| System access | **D-Bus** via `Gio.DBusProxy` (helper, udisks2, logind); **GSettings**/dconf via `Gio.Settings`; `findmnt`, `xdg-user-dir`, `xrandr`/`Gdk.Monitor` for displays | Standard interfaces, no distro sniffing |
| Privileged actions | `lin-wallpapersd` on the **system bus**, authorized by **polkit**, started on demand by **systemd** with `ProtectSystem=strict` | The GUI never runs as root |
| Boot-facing tools | `plymouth`, `update-alternatives`, `update-initramfs`, `grub-mkconfig`/`update-grub` — called with argument vectors, never a shell | The only way to change splash and menu, done safely |
| Quality | `ruff`, `mypy`, `pytest` (+ golden-image and fake-root tests), `xvfb-run` UI smoke tests, `shellcheck`, a GTK 4 portability lint | Keeps the modular structure and the port honest |
| Packaging | `debhelper` + `dh-python` `.deb`, `.desktop`, AppStream metainfo, polkit actions, systemd + D-Bus units | Native install on Debian/Ubuntu/Mint |

**Runtime system packages:**
`python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 python3-gi-cairo python3-pil polkitd dbus`
**Recommended:** `plymouth grub2-common udisks2`

**Why GTK 3 today, GTK 4 tomorrow:** the starter template and Mint 22.2's default session are GTK 3, so v1
ships there. The GTK version is chosen in exactly one module, pages use a small compatibility layer instead
of GTK 3-only calls, custom drawing goes through one canvas wrapper, and CI fails on banned APIs — so the
GTK 4 port (M8) is mechanical rather than a rewrite.

## 6. Architecture and modularity

```
UI (pages, components)  →  view models  →  services  →  providers  →  system
        GTK only              no GTK          no GTK      one per backend
```

- **Providers, not conditionals.** Each screen, desktop environment, greeter, splash system, boot manager,
  scan source, scorer and imaging backend is a module behind a stable interface, chosen by a runtime
  capability probe. Supporting Xfce, SDDM or dracut means adding a file, not editing the core. A broken
  provider degrades one tile, not the app. **No code branches on a distribution name** — that rule is in the
  review checklist, along with "every new provider ships detection evidence, capabilities,
  plan/apply/verify/revert, a preview spec and a fake-root golden test".
- **Layer discipline.** Services never import GTK; widgets never touch the filesystem. This is what makes
  the CLI, the tests and the GTK 4 port possible.
- **Everything is a plan.** An apply is data (ordered steps, payload hashes, backups) before it is an
  action — which is why it can be shown, tested against a fake root, executed by the CLI and rolled back.
- **The helper is small on purpose.** Six methods, no path arguments, no shell, allow-listed destinations.

Details: [TECHNICAL-CONCEPT.md §3, §13, §17](TECHNICAL-CONCEPT.md).

## 7. Design language

Dark navy-charcoal surfaces, neutral gray text, a single saturated yellow accent — from
`ui-kit-yellow-gray-yello.jpg` in the universal theme reference.

| Token | Value |
| --- | --- |
| Window / surface / raised | `#1E2233` / `#252A3E` / `#2B3044` |
| Text / dim text | `#F2F3F7` / `#8A8E9E` |
| Accent / accent-2 / on-accent | `#FFC700` / `#FFB500` / `#1A1400` |
| OK / warning / danger | `#4ADE80` / `#FFB500` / `#EF4444` |

The chrome stays neutral because **the wallpaper is the color**. Mockups: [docs/mockups/](docs/mockups/).

## 8. Safety and security

- **Nothing is overwritten without a backup.** Every apply writes a manifest (paths, modes, hashes, previous
  settings and the previous Plymouth alternative) to `/var/backups/lin-wallpapers/<timestamp>/`.
- **Verified, then committed.** The greeter config must parse and point at a readable file; the Plymouth
  theme must appear inside the rebuilt initramfs of every installed kernel; `grub.cfg` must be regenerated.
  A failed check rolls back automatically.
- **Package conffiles are never edited** (`/etc/default/grub`, `lightdm.conf`) — drop-ins only, so package
  upgrades stay silent.
- **Atomic writes:** temp file in the destination filesystem → `fsync` → `rename`.
- **The helper** runs only when called, exits after 30 seconds idle, accepts no destination paths, re-hashes
  and re-renders anything the client sends, calls binaries with argument vectors, and is sandboxed by systemd.
- **Boot escape hatch:** if a splash ever misbehaves, remove `splash` from the kernel line in the GRUB menu
  for one boot, then `linwp undo`.

## 9. Installation

*(from M6; until then, run from source — §11)*

```bash
sudo apt install ./lin-wallpapers_<version>_all.deb ./lin-wallpapers-helper_<version>_all.deb
lin-wallpapers
```

## 10. Command line

```bash
linwp scan                          # scan the configured roots
linwp scan --add /media/user/photos # add a root and scan it
linwp list --min-width 1920 --text-safe --sort score --limit 20
linwp show <id|path>                # metadata, score, badges, where it's currently applied
linwp preview <id|path> --surface splash --out /tmp/splash.png
linwp apply <id|path> --surface all --mode fill        # prompts through polkit
linwp apply <id|path> --surface desktop,lock
linwp plan  <id|path> --surface all                    # print the plan, change nothing
linwp undo                          # revert the last apply
linwp history
linwp sync --enable
linwp doctor                        # capability probe: what this machine supports, and why not
```

`--json` on any command for machine-readable output; exit codes distinguish "refused authorization",
"unsupported surface" and "failed and rolled back".

## 11. Development

```bash
git clone git@github.com:MensuraMedia/lin-wallpapers.git
cd lin-wallpapers
sudo apt install python3-gi gir1.2-gtk-3.0 python3-gi-cairo python3-pil
./run.sh                 # creates the venv, installs deps, launches the app

pytest                   # unit + fake-root provider tests
ruff check . && mypy src # lint and types
python3 tools/gtk4_lint.py   # portability guard
LWP_GTK=4.0 ./run.sh     # (from M8) the GTK 4 build
```

Tests never touch the real system: provider tests run against `tests/fakeroot/`, a synthetic `/etc`,
`/usr/share` and `/boot`, and assert both the applied tree and the rolled-back tree.

## 12. Project layout

```
lin-wallpapers/
├── README.md · TECHNICAL-CONCEPT.md · LICENSE · NOTICE · changelog.md
├── reference/       # the base script + its Plymouth theme and GRUB drop-in, with the mapping to modules
├── docs/            # specs and mockups (docs/mockups/)
├── src/             # main.py · gtk_version.py · config · ui · pages · viewmodels
│                    # scanner · catalogue · imaging · preview · apply(+providers) · helper · sync · cli · util
├── resources/       # css · icons · fonts · plymouth-template
├── data/            # .desktop · AppStream · polkit actions · D-Bus + systemd units
├── tests/           # unit · golden images · fakeroot
└── debian/          # packaging
```

## 13. Roadmap

| Milestone | Deliverable |
| --- | --- |
| M0 | Scaffold, app shell, theme tokens, empty pages |
| M1 | Scanner, catalogue, thumbnails, Sources + Browse |
| M2 | Scoring, badges, duplicates, Image page |
| M3 | Transform pipeline, previews, Screens page with capability probes |
| M4 | Apply engine (plan, backup, verify, rollback), History/undo; desktop + lock on Cinnamon, GNOME, MATE, Xfce, Plasma |
| M5 | Helper daemon, polkit, the base script's three privileged screens end-to-end (slick + lightdm-gtk greeters, Plymouth, GRUB), `linwp` CLI and `doctor` |
| M6 | GDM and SDDM providers, dracut back end, five distribution fake roots, sync mode, collections, slideshows, `.deb`, first release |
| M7 | Breadth: LXQt/Pantheon/Budgie, per-monitor and Wayland refinements, online sources |
| M8 | GTK 4 port |

## 14. Documentation

| Document | Contents |
| --- | --- |
| [TECHNICAL-CONCEPT.md](TECHNICAL-CONCEPT.md) | Architecture, the five surfaces, scanning, scoring, catalogue schema, previews, transforms, the apply transaction, the helper and its security model, UI concept, design tokens, modularity, GTK 4 rules, packaging, testing, roadmap, risks |
| [reference/README.md](reference/README.md) | The base script: what each step does and which module it becomes; the rules the app inherits from it |
| [docs/mockups/](docs/mockups/) | UI mockups of the main screens |

## 15. License and credits

Free to use, modify and distribute; **commercial use requires prior written permission** — see
[LICENSE](LICENSE) and [NOTICE](NOTICE).

- Application shell derived from [gtk-python-dashboard-starter](https://github.com/mikesdatawork/gtk-python-dashboard-starter) by mikesdatawork.
- Visual reference: `universal-themes/image-reference/ui-kit-yellow-gray-yello.jpg` from
  [MensuraMedia/universal-instruction-set](https://github.com/MensuraMedia/universal-instruction-set).
- The base script and the five-screen procedure this app automates were first worked out by hand in
  [optimize-laptop-asus-fx50li](https://github.com/MensuraMedia/optimize-laptop-asus-fx50li) (`scripts/apply-08-screen-wallpaper.sh`).
