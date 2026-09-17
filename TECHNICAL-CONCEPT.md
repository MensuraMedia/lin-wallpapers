# Lin Wallpapers — Technical Concept

**One wallpaper, every screen: a GTK utility that finds, catalogues, previews and applies wallpapers across
the desktop, lock screen, login screen, boot splash and boot menu.**

| | |
| --- | --- |
| Document | Technical concept, v0.1 |
| Date | 2026-09-17 |
| Status | Concept. No application code yet; roadmap in §21, **M0 specified in [docs/milestones.md](docs/milestones.md)**. |
| Repository | https://github.com/MensuraMedia/lin-wallpapers (package `lin-wallpapers`, app ID `io.mensuramedia.LinWallpapers`, CLI `linwp`) |
| License | Free to use, modify, distribute; **commercial use only with prior written permission** ([LICENSE](LICENSE), [NOTICE](NOTICE)) |
| Target platforms | Any Debian-based distribution with GTK 3: Mint, Ubuntu (and Kubuntu/Xubuntu/Lubuntu/Budgie), Debian 12+, Pop!_OS, Zorin, MX, elementary. Desktop, greeter, splash and boot manager are detected, never assumed (§4.2) |
| Stack | Python 3.12 · **GTK 3 (PyGObject), written to port to GTK 4** (§18) · Cairo · GdkPixbuf/Pillow · SQLite · a one-shot polkit helper (**no daemon, nothing runs in the background** — §11.1) |
| Shell template | [mikesdatawork/gtk-python-dashboard-starter](https://github.com/mikesdatawork/gtk-python-dashboard-starter) (sidebar + page routing + theme applicator) |
| Standards | [MensuraMedia/universal-instruction-set](https://github.com/MensuraMedia/universal-instruction-set) v2026.04 (§19) |
| Design reference | `universal-themes/image-reference/ui-kit-yellow-gray-yello.jpg` — dark navy-gray surfaces, single yellow accent (§16) |
| Base script | `reference/apply-08-screen-wallpaper.sh` — the working script that already does surfaces 3–5 on a real machine; the app's apply engine is built around its methods (§4.1) |
| Proving ground | ASUS TUF F15 FX506LI running Mint 22.2, where those surfaces were wired up by hand in `~/projects/optimize-laptop-asus-fx50li` |

---

## 1. Purpose

Setting a desktop wallpaper on Linux takes two clicks. Making the *whole machine* look like it belongs to
you — boot menu, boot splash, login screen, lock screen, desktop — takes root, an image converter, a
Plymouth theme, a greeter config file, an initramfs rebuild and `update-grub`. That work was done by hand
once on the reference laptop, and it is the direct origin of this project: **the manual procedure should be
a product.**

Lin Wallpapers:

1. **Finds** every image on the machine that could work as a wallpaper — across home folders, extra
   partitions, external drives and system wallpaper directories — without the user hunting through folders.
2. **Catalogues** them with dimensions, aspect ratio, format, dominant colors, a suitability score and a
   thumbnail, in a local index that survives restarts and refreshes incrementally.
3. **Browses and previews** them in a fast image browser with a large preview and per-surface simulations
   (what it looks like *as* a boot splash, *as* a login screen, and so on).
4. **Applies** one image to any single surface or to all of them at once, transactionally, with a backup of
   what was there before and one-click undo.
5. **Keeps them in sync**, optionally: change the desktop wallpaper and the other four surfaces follow.

### Non-goals (v1)
- Wallpaper *editing* (crop tool beyond fit/fill choice, filters, color grading).
- Downloading wallpapers from online galleries. The catalogue is local-first; an online source is a later
  provider (§17), not v1.
- Theme engines (GTK themes, icon themes, cursors). Wallpapers and the screens that show them, nothing else.
- Replacing the desktop's own background settings panel; Lin Wallpapers writes the same settings the panel does.
- Windows/macOS. Non-Debian packaging beyond a later Flatpak consideration (§20).

---

## 2. Guiding principles

| Principle | Consequence |
| --- | --- |
| **Discover, don't assume** | Every surface is a capability probe at runtime. No Plymouth? The boot-splash tile says so and explains why, instead of failing on apply. |
| **Least privilege** | The GUI runs as the user and writes only user settings. A small helper, authorized by polkit, writes `/etc`, `/usr/share`, `/boot` and runs `update-initramfs`/`update-grub`. |
| **Every change is reversible** | An apply is a transaction: back up, write, verify, and either commit or roll back. "Undo last apply" restores the previous state of every surface it touched. |
| **Never break boot** | Boot-facing surfaces (GRUB, Plymouth) are validated before installation and fall back to the distribution default if validation fails. The initramfs rebuild is the last step, never the first. |
| **Explain the machine** | Where a surface can't be changed (GDM under Wayland, a locked-down greeter, no `/boot` write access), the app says which component owns it and what the alternative is. |
| **Fast on 50,000 images** | Scanning, hashing and thumbnailing happen in worker threads with a bounded queue; the browser is virtualized; the UI never blocks. |
| **Modular and universal** (binding, per the universal instruction set) | Desktops, greeters, splash systems, boot managers, scan sources and imaging backends are *providers* behind stable interfaces (§17). Adding Xfce, SDDM or dracut is a new module, not a change to the core; no module may branch on a distribution name. |
| **Never hide a feature** | What this machine can't do is greyed out, labelled "Unsupported in {distribution}", and explains itself from a reason code with evidence — never removed, never a bare error (§15.1–15.3). |
| **Calm, premium UI** | Dark navy-gray surfaces, one yellow accent, images carry the color; the chrome never competes with the wallpaper (§16). |

---

## 3. System architecture

```mermaid
flowchart LR
  subgraph User session
    UI["GTK 3 app<br/>lin-wallpapers"] --> VM["View models"]
    VM --> CAT["Catalogue service<br/>SQLite + thumbnails"]
    VM --> PRV["Preview compositor<br/>Cairo"]
    CAT <-- jobs --- SCAN["Scanner pool<br/>walk · probe · score · hash"]
    VM --> PLAN["Apply planner<br/>per-surface plans"]
    PLAN --> UAPP["User applier<br/>GSettings / dconf"]
    PLAN --> HC["Helper client<br/>pkexec + plan on stdin"]
  end
  subgraph System
    HC -- pkexec, one run --> HD["lin-wallpapers-helper<br/>root, runs then exits"]
    HD --> GR["GRUB writer"]
    HD --> PL["Plymouth theme writer"]
    HD --> LG["Greeter writer"]
    HD --> BK[("Backup store<br/>/var/backups/lin-wallpapers")]
  end
  SCAN --> FS[("Filesystems<br/>home · mounts · /usr/share")]
  UAPP --> DE[("Desktop + screensaver<br/>settings")]
```

| Layer | Runs as | Responsibility |
| --- | --- | --- |
| **UI** (`src/ui`, `src/pages`) | user | Starter-template shell: 150 px sidebar, page routing, theme applicator, plus the browser, preview and apply pages |
| **View models** (`src/viewmodels`) | user | Observable state between services and widgets; no GTK imports in services, no file I/O in widgets |
| **Catalogue** (`src/catalogue`) | user | SQLite index, thumbnail cache, queries, filters, collections, change feed |
| **Scanner** (`src/scanner`) | user | Root discovery, walking, format probing, metadata, suitability scoring, perceptual hashing, incremental rescan |
| **Preview** (`src/preview`) | user | Render an image *as* each surface: composited mock-ups drawn with Cairo at display resolution |
| **Transform** (`src/imaging`) | user | Fit/fill/center/stretch to a target geometry, format conversion, color quantization for GRUB, theme asset generation |
| **Planner + appliers** (`src/apply`) | user | Turn "image × surfaces × options" into an ordered plan; execute user-space steps; hand privileged steps to the helper |
| **Helper** (`src/helper`, `lin-wallpapers-helper`) | root, only during an apply | The only component that writes outside `$HOME`; started by `pkexec`, performs one plan, exits. Allow-listed operations, path validation, backups, rollback, verification |
| **Sync agent** (`src/sync`) | user | **Opt-in, off by default:** a session autostart entry that watches the desktop wallpaper setting and re-applies the other surfaces (§12) |
| **CLI** (`src/cli`) | user | `linwp scan|list|show|apply|undo|sync` — the same services without the GUI, for scripting and for the reference laptop's apply-script workflow |

---

## 4. The five surfaces

Each surface is a **provider** implementing one interface (`SurfaceProvider`: `probe()`, `current()`,
`plan(image, options)`, `apply(plan)`, `revert(backup)`, `preview_spec()`). This is what the manual work on
the reference machine turned into.

| # | Surface | Mechanism (Mint 22.2 reference implementation) | Privilege | Notes / risks |
| --- | --- | --- | --- | --- |
| 1 | **Desktop** | `org.cinnamon.desktop.background` `picture-uri` + `picture-options` (GNOME/MATE/XFCE equivalents per backend); optional per-monitor and slideshow XML | user | Instant, no restart. Multi-monitor handled by the backend's capabilities. |
| 2 | **Lock screen** | `org.cinnamon.desktop.screensaver` — either "follow the desktop" (Cinnamon's default) or an explicit image | user | On Cinnamon the lock screen already mirrors the desktop; the app shows this and only writes an override when the user wants a *different* image. |
| 3 | **Login screen** | LightDM + slick-greeter: `background=` and `draw-user-backgrounds=false` in `/etc/lightdm/slick-greeter.conf`; image copied to `/usr/share/backgrounds/lin-wallpapers/` because `$HOME` is typically mode 750 and unreadable by `lightdm` | root | Providers for `lightdm-gtk-greeter`, GDM (limited) and SDDM ship later. The copy step is mandatory, not cosmetic — a path inside `$HOME` silently yields a grey screen. |
| 4 | **Boot splash** | A generated Plymouth **script theme** in `/usr/share/plymouth/themes/lin-wallpapers/` (background sprite + the distribution's throbber frames + password/message callbacks), `update-alternatives --install/--set default.plymouth`, then `update-initramfs -u -k all` | root | Highest-risk surface: the image must be *inside* the initramfs. Verified after the rebuild by listing the initramfs contents (§10). |
| 5 | **Boot menu (GRUB)** | PNG written to `/boot/grub/`, `GRUB_BACKGROUND` set in a `/etc/default/grub.d/` **drop-in** (never in `/etc/default/grub`, which is a package conffile), then `update-grub` | root | Needs a format GRUB can decode; the transform stage writes a conservative 8-bit PNG at the panel's mode. |

**Capability probe examples:** Plymouth present but `/boot` read-only → surface offered as "preview only";
GDM3 on Wayland → login screen marked unsupported with an explanation; no `pkexec`/polkit agent → the three
privileged surfaces are disabled with a single banner rather than five failures.

### 4.1 The base script: what the app is built around

`reference/apply-08-screen-wallpaper.sh` (in this repository, with its Plymouth theme and GRUB drop-in) is
the **working implementation of surfaces 3–5**, written and applied on the reference laptop. It is not an
inspiration or a sketch — it is the engine, and the app's providers reproduce its steps, order, paths,
fallbacks and undo exactly. Full step-by-step mapping: [`reference/README.md`](reference/README.md).

| Script step | Becomes |
| --- | --- |
| Read the desktop wallpaper from GSettings as the invoking user (session-bus address derived from their uid), or `--image` | `desktop_*.current()` and the watcher behind Sync mode (§12) |
| `render()` — Pillow, scale by `max(W/w, H/h)`, center-crop to the panel mode, JPEG q92 / optimized PNG | `imaging/transform.py` (`mode="fill"`), used by both the apply **and** the previews |
| Copy the rendered image to a system path, then `set_ini` `background=` / `draw-user-backgrounds=false` | `greeter_slick.py` (and the INI editor shared by the other LightDM greeters) |
| Install `.plymouth` + `.script`, copy the distribution theme's throbber frames, render `wallpaper.png`, `update-alternatives --install … 150` + `--set`, `update-initramfs -u -k all` | `splash_plymouth.py` + `resources/plymouth-template/` |
| Render the GRUB PNG, install the drop-in only when it differs (`cmp -s`), `update-grub` | `bootmenu_grub.py` |
| `backup()` into `/var/backups/<project>/<timestamp>/` before every write | `apply/backup.py`, now with a JSON manifest (modes, owners, sha256, previous alternative) |
| `--undo`: alternative back to the distribution theme, theme dir removed, greeter keys deleted, GRUB image and drop-in removed, initramfs and GRUB regenerated | `*.revert()`, History page, `linwp undo` |
| `--preview`: `plymouthd` + `plymouth --show-splash` for 8 s | The "run the real splash" live check offered after an apply (§8) |
| The closing report (greeter background, resolved `default.plymouth`, references in `grub.cfg`) | `apply/verify.py` — promoted from *printed afterwards* to *checked before commit*, plus the initramfs content check |

Inherited rules, non-negotiable in the app: root does only what needs root; every step is idempotent; never
edit a package conffile (drop-ins only); the reverse of a step is written with the step; expensive steps
(`update-initramfs`, `update-grub`) run once at the end; every run says what it did.

### 4.2 Universality across Debian-based distributions

The script was written for Mint 22.2, but **nothing in the mechanism is Mint-specific** — only the *names*
(`fx506li`, `mint-logo`) and the *assumption* of which desktop and greeter are installed. The app removes
both: names become `lin-wallpapers`, and every assumption becomes a probe that selects a provider. The
matrix below is what "Debian-based" means concretely; the first column is what the probe detects, never a
release name or `/etc/os-release` string.

| Component detected | Provider | Mechanism | Distributions where it is the default |
| --- | --- | --- | --- |
| Cinnamon | `desktop_cinnamon` | `org.cinnamon.desktop.background` `picture-uri` + `picture-options` | Mint Cinnamon |
| GNOME / Unity-like | `desktop_gnome` | `org.gnome.desktop.background` `picture-uri` **and** `picture-uri-dark` (both, or a light theme reverts at night) | Ubuntu, Debian GNOME, Pop!_OS, Zorin |
| MATE | `desktop_mate` | `org.mate.background` `picture-filename` (a path, not a URI) | Mint MATE, Ubuntu MATE |
| Xfce | `desktop_xfce` | `xfconf-query -c xfce4-desktop`, one `last-image` property **per monitor/workspace** | Xubuntu, Mint Xfce, MX, Debian Xfce |
| KDE Plasma | `desktop_plasma` | `plasma-apply-wallpaperimage` (Plasma 5.23+), falling back to a scripted `org.kde.plasmashell` D-Bus call | Kubuntu, Debian KDE |
| Budgie / LXQt / elementary | `desktop_gnome` / `desktop_lxqt` / `desktop_pantheon` | GSettings schema of that shell; LXQt writes `pcmanfm-qt` config | Ubuntu Budgie, Lubuntu, elementary |
| slick-greeter | `greeter_slick` | `/etc/lightdm/slick-greeter.conf` `background=`, `draw-user-backgrounds=false` | Mint, Ubuntu Budgie |
| lightdm-gtk-greeter | `greeter_lightdm_gtk` | `/etc/lightdm/lightdm-gtk-greeter.conf` `[greeter] background=` | Xubuntu, Debian Xfce, MX |
| GDM3 | `greeter_gdm` | GResource override for `gnome-shell-theme.gresource` (documented, reversible, re-applied after `gnome-shell` upgrades) or, where present, `/etc/dconf/db/gdm.d/` for the login *background* | Ubuntu, Debian GNOME, Pop!_OS |
| SDDM | `greeter_sddm` | `/etc/sddm.conf.d/` drop-in pointing the current theme's `background=` at a system path | Kubuntu, Lubuntu, Debian KDE |
| LightDM present, greeter unknown | `greeter_lightdm_generic` | Reports the greeter binary and offers preview only | — |
| Plymouth | `splash_plymouth` | Generated script theme + `update-alternatives` (Debian family) and `update-initramfs -u -k all`; on distributions using **dracut** (some Debian 13 installs), `dracut --regenerate-all --force` instead | All of them |
| GRUB 2 | `bootmenu_grub` | `/etc/default/grub.d/` drop-in + `update-grub`/`grub-mkconfig -o` at the detected `grub.cfg` path (BIOS, EFI, or `/boot/efi/EFI/<vendor>/`) | All of them |
| systemd-boot / no GRUB | `bootmenu_none` | Surface reported unsupported, with the reason | Some Debian EFI installs |

Distribution-specific facts the probes resolve rather than assume:

| Fact | How it is resolved |
| --- | --- |
| Which throbber/spinner frames to reuse in the generated Plymouth theme | Read from the *currently selected* `default.plymouth` theme's directory (`mint-logo`, `bgrt`, `spinner`, `futureprairie`…); if it has none, the app draws its own from the accent color |
| Where the greeter's readable image directory is | `/usr/share/backgrounds/lin-wallpapers/`, created with mode 0755 — the one place every Debian-based greeter can read |
| Whether `update-grub` exists | `update-grub`, else `grub-mkconfig -o <detected grub.cfg>`; `grub2-*` names are accepted for derivative packaging |
| Initramfs generator | `update-initramfs` (initramfs-tools) or `dracut`, whichever owns `/boot/initrd.img-*` |
| Whether the session is Wayland | `XDG_SESSION_TYPE`; affects monitor enumeration and the GDM path, not the four other surfaces |
| Where the desktop stores per-monitor backgrounds | Backend capability flag `supports_per_monitor`, not a distro check |

**Testing universality:** every provider ships a golden test against a synthetic root
(`tests/fakeroot/<distro-shape>/`) modelled on Mint Cinnamon, Ubuntu GNOME, Debian Xfce, Kubuntu and MX, so
a provider can be verified without that distribution being installed. A `linwp doctor --json` dump from a
real machine is the bug-report format, and the same JSON seeds a new fake root.

---

## 5. Discovery: where wallpapers come from

Scanning is **root-set driven**. Roots come from three places and every one of them is visible and
switchable in Settings:

| Root class | Default | Source |
| --- | --- | --- |
| XDG picture dirs | on | `xdg-user-dir PICTURES`, plus `~/Wallpapers`, `~/Pictures/wallpapers` |
| System wallpapers | on | `/usr/share/backgrounds`, `/usr/share/wallpapers`, `~/.local/share/backgrounds` |
| Mounted volumes | ask | `findmnt` → local filesystems only (`ext4`, `btrfs`, `xfs`, `vfat`, `exfat`, `ntfs3`): `/data`, `/mnt/*`, `/media/$USER/*` |
| Removable media | event | udisks2 mount events → "Scan this drive?" toast, remembered per volume UUID |
| Network mounts | off | `nfs`, `cifs`, `sshfs`, `fuse.*` are excluded by default (latency and quota); opt-in per mount |
| Extra folders | — | Added by the user; also accepted via drag-and-drop onto the browser |

**Exclusions** are applied before `stat`: pseudo-filesystems (`/proc`, `/sys`, `/dev`, `/run`), snapshots and
backups (`/timeshift`, `.snapshots`, `.Trash*`), caches (`~/.cache`, `.thumbnails`), VCS and build dirs,
`node_modules`, Steam/Proton library trees (thousands of textures), and anything matching the user's
ignore globs. Symlinks are not followed across filesystem boundaries; hardlink/inode identity stops
double-counting bind mounts.

**Two-phase scan.** Phase 1 walks with `os.scandir` and keeps only candidates by extension and size
(default: ≥ 200 KB, ≥ 1280 px on the long edge once probed). Phase 2 probes each candidate. Phase 1 is
cheap enough to report progress per directory; phase 2 is the expensive one and is what the progress bar
actually tracks.

**Incremental rescan** uses `(device, inode, mtime, size)`: unchanged files are skipped entirely. A full
rescan of a 40,000-image tree is minutes; a rescan after adding a folder is seconds. Optional `inotify`
watches on a handful of chosen folders pick up new screenshots and downloads live.

---

## 6. Suitability: what makes an image a wallpaper

Every candidate gets a **suitability score** (0–100) plus badges, so "suitable" is explainable rather than magic.

| Signal | Weight | Detail |
| --- | --- | --- |
| Resolution vs. displays | 35 | Compared against each connected output (1920×1080 on the reference laptop). ≥ native scores full; below native is penalized in proportion to the upscale required. |
| Aspect ratio | 20 | Distance from the output's ratio; 16:9/16:10 land well, 1:1 icons and 3:4 phone shots are pushed down but not hidden. |
| Format and integrity | 10 | JPEG/PNG/WebP/AVIF/HEIF/JXL decodable by GdkPixbuf or Pillow; truncated files are flagged, not scored. |
| Detail distribution | 15 | Edge density per region. Busy everywhere → poor for login/lock screens (text over it); calm bands → good. Drives the "text-safe" badge per surface. |
| Color coherence | 10 | Dominant palette (k-means on a downscale), average luminance, contrast range. Feeds the "dark/light", "good for dark panels" badges and, later, accent extraction. |
| Not-a-wallpaper penalties | 10 | Alpha channel, tiny dimensions, GIF animation, icon/sprite-sheet geometry, EXIF `Orientation` requiring rotation, path heuristics (`icons/`, `emoji/`, `textures/`). |

Badges shown on each card: `4K`, `native`, `text-safe`, `dark`, `light`, `duplicate`, `upscaled`, `portrait`.
Duplicates are found with a 64-bit dHash plus size clustering; the first-seen copy wins and the rest collapse
behind a "3 copies" chip.

The score orders the browser by default and never *hides* anything — the filter bar does that, and every
filter is a saved query.

---

## 7. Catalogue: data model

SQLite (WAL, `~/.local/share/lin-wallpapers/catalogue.db`) — one file, portable, rebuildable at any time.

```sql
CREATE TABLE image (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,        -- absolute
  volume_id TEXT,                   -- UUID; survives remount at another path
  device INTEGER, inode INTEGER, mtime INTEGER, size INTEGER,
  width INTEGER, height INTEGER, format TEXT, has_alpha INTEGER,
  aspect REAL, megapixels REAL,
  score INTEGER, badges TEXT,       -- JSON array
  palette TEXT,                     -- JSON: dominant colors + luminance + contrast
  dhash INTEGER,                    -- perceptual hash
  thumb_key TEXT,                   -- content hash → thumbnail file
  first_seen INTEGER, last_seen INTEGER, missing INTEGER DEFAULT 0
);
CREATE TABLE collection(id INTEGER PRIMARY KEY, name TEXT UNIQUE, kind TEXT); -- manual | smart
CREATE TABLE collection_item(collection_id INTEGER, image_id INTEGER, position INTEGER);
CREATE TABLE tag(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE image_tag(image_id INTEGER, tag_id INTEGER);
CREATE TABLE apply_event(                     -- history and undo
  id INTEGER PRIMARY KEY, ts INTEGER, image_id INTEGER, surfaces TEXT,
  options TEXT, backup_ref TEXT, result TEXT, message TEXT
);
CREATE TABLE root(id INTEGER PRIMARY KEY, path TEXT UNIQUE, enabled INTEGER, kind TEXT, last_scan INTEGER);
```

Thumbnails follow the freedesktop thumbnail spec layout in
`~/.cache/lin-wallpapers/thumbnails/{normal,large}/`, keyed by a content hash so moving a file doesn't
regenerate them. Missing files are marked `missing=1` (unplugged drive), never deleted — reconnect the
drive and the catalogue heals by `volume_id`.

---

## 8. Preview: seeing it before it happens

The preview is the feature that makes the app worth running, because four of the five surfaces are
otherwise only visible by rebooting or logging out.

| Preview | How it's built | Fidelity |
| --- | --- | --- |
| **Desktop** | Transformed image + the panel, a few desktop icons and a window frame drawn in Cairo | Layout mock |
| **Lock screen** | Transformed image + the greeter clock, date and unlock field at Cinnamon's real positions | Layout mock |
| **Login screen** | Transformed image + slick-greeter's user avatar, name field, session and power buttons | Layout mock |
| **Boot splash** | The *actual* Plymouth theme rendered offscreen: same cover-scaling math and throbber placement as the generated theme, animated | Pixel-exact geometry |
| **Boot menu** | The quantized GRUB PNG with a menu box, entry list and the real font metrics over it | Near-exact |
| **All screens** | 2×3 grid of the above, one click each to enlarge | — |
| **Live check** | `plymouthd --no-daemon` + `plymouth --show-splash` for 8 s on the real framebuffer, offered after an apply | Exact (the real thing) |

Every preview is rendered from the **same transform pipeline the apply uses** (§9), so what is previewed is
what gets installed — including the crop. The crop handle in the preview (fit / fill / center / stretch, plus
a drag-to-reposition focal point for fill) writes into the plan, not into a separate "preview only" path.

---

## 9. Transform pipeline

One function, many targets: `transform(image, geometry, mode, format_profile) -> bytes`.

| Target | Geometry | Format profile |
| --- | --- | --- |
| Desktop / lock | Native, per output | Original file, untouched (the desktop scales it) |
| Login screen | Largest output | JPEG q92 or PNG, stripped of EXIF, copied to a system path |
| Boot splash | Panel mode (e.g. 1920×1080) | PNG, no alpha, sRGB |
| Boot menu | `GRUB_GFXMODE` (e.g. 1920×1080) | PNG, 8-bit, ≤ 256 colors when the payload would otherwise be large |
| Thumbnails | 256 / 512 long edge | JPEG q85 |

Modes are `fill` (zoom + center crop, the default and what the manual script did), `fit` (letterbox with a
palette-derived matte), `center`, `stretch` and `tile`. EXIF orientation is applied first; ICC profiles are
converted to sRGB; the focal point, if set, biases the crop. Output is deterministic — the same input and
options produce byte-identical output, which makes "is the installed file still the one I chose?" a hash
comparison.

---

## 10. Apply: a transaction, not a button

```
plan  →  precheck  →  backup  →  write  →  verify  →  commit | rollback
```

1. **Plan.** Ordered steps, each with target paths, byte payloads, commands and an estimated duration.
   Displayed in full before anything runs ("Show what this will do" — the plan is the confirmation dialog).
2. **Precheck.** Free space on `/boot` and `/usr`, `/boot` writable, polkit agent present, plymouth and grub
   binaries present, no concurrent `apt`/`dpkg` lock, image decodable. Failures abort before any write.
3. **Backup.** Everything the plan touches is copied to `/var/backups/lin-wallpapers/<timestamp>/` with a
   manifest (path, mode, owner, sha256, and the previous `update-alternatives` selection). User-space settings
   are captured as `dconf` key/value pairs in the same manifest.
4. **Write.** Files are written to a temporary name in the destination filesystem, `fsync`'d, then
   `rename`'d — no half-written theme, and no cross-device copies mid-apply.
5. **Verify.** Per surface: greeter config parses and points at an existing readable file; the Plymouth
   alternative resolves to the new theme *and* the rebuilt initramfs of every installed kernel contains the
   theme's `.plymouth`, `.script` and background (`lsinitramfs | grep`); `/boot/grub/grub.cfg` is newer than
   the drop-in; GSettings read back the expected value.
6. **Commit or roll back.** Any verify failure restores the backup, re-runs `update-initramfs`/`update-grub`
   as needed, and reports which step failed and why. `linwp undo` (and the Undo button) replays the same
   restore later, from the manifest.

Expensive steps are batched: applying to all five surfaces rebuilds the initramfs **once** and runs
`update-grub` **once**, at the end. A typical all-surfaces apply on the reference laptop is ~25 s, almost all
of it initramfs.

---

## 11. Privileged helper and security model

### 11.1 Nothing runs in the background

**Lin Wallpapers is not a service.** There is no daemon, no systemd unit enabled at boot, no tray agent and
no login hook. The app is a window you open when you want to change a wallpaper; when you close it, nothing
of it is left running (`ps` shows nothing, idle CPU is zero, and it costs nothing at boot).

What it produces is **ordinary operating-system configuration** — the same settings, config files, theme
and drop-in that a person would write by hand with the base script (§4.1):

| Screen | What is left behind | Who displays it afterwards |
| --- | --- | --- |
| Desktop / lock | A GSettings (dconf) value in your own profile | Your desktop session |
| Login screen | An image under `/usr/share/backgrounds/lin-wallpapers/` + keys in the greeter's config | LightDM/SDDM/GDM at the next login |
| Boot splash | A theme under `/usr/share/plymouth/themes/lin-wallpapers/`, the `default.plymouth` alternative, and the rebuilt initramfs | Plymouth, from the initramfs, at the next boot |
| Boot menu | A PNG in `/boot/grub/` + a `/etc/default/grub.d/` drop-in baked into `grub.cfg` | GRUB at the next boot |

Uninstall the app afterwards and every screen keeps the wallpaper, because the OS owns the result. The app
is a way to make those changes easily, correctly and reversibly — not a thing that has to stay running for
them to work.

**The two exceptions, both explicit:**

1. **The privileged helper runs for the seconds it takes to apply, then exits** (§11.2). It is not enabled,
   not socket-activated at boot, and not resident.
2. **Sync mode is opt-in and off by default** (§12). It is the only part that keeps running, it is a
   user-session autostart entry (not a system service), it can be switched off in Settings, and the
   wallpaper stays applied when it is off — sync only re-applies when you *change* the desktop wallpaper.

### 11.2 The helper: one-shot, via pkexec

- **`lin-wallpapers-helper`** is a normal executable in `/usr/libexec/`, launched through **`pkexec`** for a
  single apply or revert, exactly the way the base script is launched with `sudo` today. It reads one plan
  on stdin, performs it, prints the result as JSON and exits. No D-Bus name, no `.service` unit, no
  activation, nothing to disable afterwards.
- **One authorization per run.** A five-screen apply is one plan and one password prompt, not five.
- **Allow-listed operations only:** `write_system_image`, `edit_ini`, `install_theme`, `set_alternative`,
  `write_dropin`, `regen_initramfs`, `regen_bootmenu`, `revert_backup`, `probe`. There is no "write this
  file" primitive, no destination path in the plan (destinations are constants in the helper) and no
  operation that takes a shell command.
- **polkit actions** are split so a policy can allow the low-risk ones and prompt for the rest:
  `…apply.login-screen`, `…apply.boot-splash`, `…apply.boot-menu`, `…revert`. Default: `auth_admin_keep`.
- **Input validation.** The image arrives as a file descriptor plus a declared sha256; the helper re-hashes,
  re-decodes with a size limit and re-runs the transform itself, so it never writes client-supplied bytes.
- **No shell.** `subprocess` with argument vectors, absolute binaries, a fixed environment and timeouts;
  `update-initramfs`, `update-grub`, `update-alternatives` only.
- **Sandboxing.** Because it is short-lived and not a unit, hardening is in-process: `umask 022`, dropped
  ambient capabilities, `NoNewPrivileges` via `prctl`, an explicit destination allow-list checked with
  `os.path.realpath`, and `PrivateTmp`-equivalent use of a `mkdtemp` under `/var/tmp` that it removes.
  (A `systemd-run --scope` wrapper with `ProtectSystem=strict` and `ReadWritePaths=` is available as a
  hardening option where systemd is present — still one-shot, still nothing enabled.)
- **Conffile rule.** Package-owned conffiles (`/etc/default/grub`, `/etc/lightdm/lightdm.conf`) are never
  rewritten; the helper only adds drop-ins and its own files. This is a hard rule carried over from the
  reference project, where editing a conffile caused interactive prompts on the next package upgrade.
- **Boot safety.** The Plymouth theme is validated by rendering it offscreen before installation; the GRUB
  image is decoded and size-checked; if the initramfs rebuild fails, the previous theme is restored and the
  initramfs is rebuilt again before the call returns.

---

## 12. Sync mode

Optional, off by default, one switch: **"Keep all screens matching my desktop wallpaper."**

This is the only part of Lin Wallpapers that keeps running, and only if you turn it on. It is a
**user-session autostart entry** (`~/.config/autostart/lin-wallpapers-sync.desktop`), not a system service:
it runs as you, starts with your session, and disappears when you switch it off. Turning it off never
changes any screen — what was applied stays applied.

A user-session agent watches `org.cinnamon.desktop.background picture-uri`. On change it debounces 10 s,
checks that the file is stable and suitable, and runs an apply for the enabled surfaces. Because the
privileged part still goes through polkit, the app offers, at enable time, a one-line explanation of the
trade-off: either authorize each sync (a prompt per wallpaper change) or install a polkit rule for
`apply.*` that allows the active local session without a prompt. The rule is written by the helper, shown
in full first, and removed when sync is disabled.

Slideshows are handled by applying the *current* frame and re-syncing when it changes, with a minimum
interval so an hourly slideshow doesn't rebuild the initramfs hourly (below that interval, only the
user-space surfaces follow).

---

## 13. Application structure

Derived from the starter template, keeping its conventions (`src/main.py` entry point, `BasePage`
subclasses, route keys registered in the content area, sidebar `nav_items` tuples, themes in
`config_themes.py`, CSS in `resources/css/`), extended with a services layer the template doesn't have:

```
lin-wallpapers/
├── run.sh                       # venv + deps + launch (from the template)
├── src/
│   ├── main.py                  # Gtk.Application entry point
│   ├── gtk_version.py           # the ONE place GTK 3/4 is chosen
│   ├── config/                  # config_theme.py · config_layout.py · config_themes.py · config_paths.py
│   ├── ui/                      # dashboard_window.py · sidebar.py · content_area.py · compat.py
│   │   └── components/          # image_card · filter_bar · preview_pane · surface_tile · crop_handle · apply_sheet
│   ├── capability/              # states.py · reasons.py (the §15.2 catalogue) · messages.py
│   ├── pages/                   # page_base.py · page_browse · page_image · page_screens · page_apply · page_diagnostics
│   │                            # page_sources · page_collections · page_history · page_settings · page_about
│   ├── viewmodels/              # browse_vm · image_vm · screens_vm · apply_vm (no GTK imports below this line)
│   ├── scanner/                 # roots.py · walker.py · probe.py · score.py · hash.py · watch.py
│   ├── catalogue/               # db.py · schema.sql · queries.py · thumbs.py · collections.py
│   ├── imaging/                 # transform.py · formats.py · palette.py · grub_png.py
│   ├── preview/                 # compositor.py · surfaces/*.py (one mock per surface)
│   ├── apply/                   # planner.py · executor.py · backup.py · verify.py · registry.py
│   │   └── providers/           # desktop_{cinnamon,gnome,mate,xfce,plasma} · lock_{cinnamon,gnome,xfce,plasma}
│   │                            # greeter_{slick,lightdm_gtk,gdm,sddm,lightdm_generic}
│   │                            # splash_plymouth (initramfs-tools | dracut) · bootmenu_{grub,none}
│   ├── helper/                  # main.py (one-shot) · ops.py · policy/ (polkit actions)
│   ├── sync/                    # agent.py
│   ├── cli/                     # linwp.py
│   └── util/                    # threads.py · log.py · errors.py · units.py
├── resources/                   # css/ · icons/ · fonts/ · plymouth-template/ (script theme skeleton)
├── data/                        # .desktop · AppStream metainfo · polkit actions (no service units)
├── reference/                   # THE BASE SCRIPT: apply-08-screen-wallpaper.sh + plymouth theme + grub drop-in
├── docs/                        # this document, README, mockups, specs
├── tests/                       # unit · golden-image · fake-root integration
└── debian/                      # packaging
```

**Pages** (sidebar routes): `browse`, `image`, `screens`, `sources`, `collections`, `history`, `settings`, `about`.

---

## 14. UI concept

**Window:** 1280×800 default, 960×640 minimum. 150 px sidebar (template width) with the logo block, route
buttons and a scan-status footer; content area on the right.

| Page | What it shows | Key interactions |
| --- | --- | --- |
| **Browse** (default) | Virtualized grid of image cards (thumbnail, filename, resolution chip, score ring, badges). Filter bar: search, min-resolution, aspect, orientation, color, text-safe, duplicates, source. Sort by score, size, date, name, color. | Click = select; double-click = Image page; `Space` = quick preview; drag onto a surface tile = apply to that surface |
| **Image** | Large preview with the crop/fit control, full metadata, palette swatches, badges with tooltips explaining the score, and the five surface tiles down the right side with "currently set here" markers | Fit mode, focal point, Apply to… , Add to collection, Show in Files |
| **Screens** | The five surfaces as large cards: current image, mechanism, capability state ("supported", "needs authorization", "unavailable: reason"), last applied, Preview and Revert | Per-surface apply, per-surface revert, "Apply everywhere", sync switch |
| **Sources** | Scan roots with type, image count, last scan and a progress row while scanning; add folder; per-volume toggles; exclusions editor | Scan now, rescan, remove, enable/disable |
| **Collections** | Manual collections and smart collections (saved filters) | New, rename, reorder, set as slideshow source |
| **History** | Apply events: time, image thumbnail, surfaces, result, backup reference | Undo, re-apply, open backup manifest |
| **Settings** | Scan policy, thumbnail cache size, default fit mode, sync behavior, polkit rule state, GRUB/Plymouth options, logging | Clear cache, rebuild catalogue, export/import settings |
| **Diagnostics** (from Settings, and from every "Why?" popover) | The activity log (§15.3) filtered by area, level and session; the capability table with each feature's state, reason code and evidence; the machine model | Filter, jump to the lines explaining a greyed-out control, Copy diagnostics bundle |

**Apply sheet** (the confirmation): the chosen image, the surfaces, the exact step list from the plan,
estimated duration, the warning that the boot splash triggers an initramfs rebuild, and a single
**Apply** button. Progress is per step; the result is a summary with per-surface ✓/✗ and an Undo button.

**Accessibility and input:** full keyboard navigation (`/` search, arrows in the grid, `Enter` apply,
`Ctrl+Z` undo), focus-visible everywhere, AT-SPI labels on cards and tiles, `prefers-reduced-motion`
honored, no color-only status (icon + text always).

---

## 15. Empty, slow and error states

| State | Treatment |
| --- | --- |
| First run | A "Find wallpapers" hero with the proposed roots listed and a one-click scan; nothing is scanned before the user agrees |
| Scanning | Non-blocking banner with counts (`2,140 found · 830 catalogued`), a cancel button, and results appearing live |
| No results after filtering | The filter chips that excluded everything, each removable |
| Missing file (drive unplugged) | Card dimmed with a "reconnect *VOLUME*" chip; apply is disabled with the reason |
| Unsupported surface | Tile in a muted state with the owning component named and a "Why?" popover |
| Authorization refused | Non-destructive: the plan stops, nothing is half-applied, the sheet offers Retry |
| Apply failed mid-way | Automatic rollback already done; the sheet shows which step failed, the log excerpt and the backup path |

### 15.1 Capability states: nothing is ever removed, only greyed out

The same binary ships everywhere, so on any given machine some features have nothing to drive them. **A
feature this system cannot do is never hidden and never removed from the interface.** It stays in place,
greyed out, labelled with the system it is unsupported on, and able to explain itself.

Every feature — each of the five surfaces, per-monitor wallpapers, slideshows, the live splash check, sync
mode, a format the platform has no loader for — resolves to exactly one of five states:

| State | Control | Label | Example |
| --- | --- | --- | --- |
| **Available** | Live | — | Desktop on Cinnamon |
| **Needs authorization** | Live, with a shield mark | "Asks for your password" | Boot splash with a polkit agent present |
| **Degraded** | Live, with a warning mark | "Partly supported: …" | A greeter whose config parses but whose binary is unknown |
| **Unsupported** | **Greyed out, still visible** | **"Unsupported in Linux Mint 22.2"** + a one-line reason | Boot splash where Plymouth is not installed |
| **Blocked** | Greyed out | "Temporarily unavailable: …" | `/boot` read-only, `dpkg` lock held, drive offline |

The label rule: *"Unsupported in {distribution} {version}"* as the headline, a plain-language reason under
it, and a **"Why?"** popover carrying the reason code, the evidence the probe collected, what would have to
change, and a **Copy diagnostics** button. Nothing says "error" when the honest answer is "this system
doesn't have that component".

### 15.2 Reason codes

Providers never return prose. `detect()`, `capabilities()` and every precheck return a **reason code** plus
evidence; one catalogue turns codes into sentences, so the GUI, the CLI, the log and the bug report all say
the same thing, and a new provider cannot invent a new way of saying "no".

| Code | Headline | Plain-language message (filled from evidence) |
| --- | --- | --- |
| `COMPONENT_MISSING` | Unsupported in {os} | "{Component} isn't installed on this system, so the {surface} can't be changed. Installing `{package}` would enable it." |
| `COMPONENT_NOT_DETECTED` | Unsupported in {os} | "No supported {kind} was found. Detected instead: {evidence}." |
| `OWNED_BY_OTHER` | Unsupported in {os} | "{Owner} manages the {surface} here, and it doesn't allow an image to be set this way." |
| `SESSION_UNSUPPORTED` | Unsupported in this session | "This works on X11; the current session is {session}." |
| `VERSION_TOO_OLD` | Unsupported in {os} | "{Component} {found} is older than {required}." |
| `NO_POLKIT_AGENT` | Temporarily unavailable | "Nothing is running to ask for your password, so system changes can't be authorized." |
| `NOT_WRITABLE` | Temporarily unavailable | "{Path} is read-only right now." |
| `INSUFFICIENT_SPACE` | Temporarily unavailable | "{Path} has {free} free; this needs about {needed}." |
| `PACKAGE_MANAGER_BUSY` | Temporarily unavailable | "A package operation is running; changing boot files now isn't safe." |
| `VOLUME_OFFLINE` | Temporarily unavailable | "The drive {label} holding this image isn't connected." |
| `LOADER_MISSING` | Partly supported | "This system has no loader for {format}; those images are listed but can't be used." |
| `PER_MONITOR_UNSUPPORTED` | Partly supported | "{Desktop} sets one wallpaper for all monitors." |
| `PROVIDER_ERROR` | Something went wrong | "{Component} failed unexpectedly: {summary}. The rest of the app is unaffected." |

Each entry carries the code, the state it maps to, the message template, the evidence keys it expects, and
an optional **remedy** (a package to install, a setting to change, a drive to reconnect) — shown as text,
never as something the app does on the user's behalf.

### 15.3 The activity log

The app keeps its own log, so "why can't I do this?" always has an answer without the user learning
`journalctl`.

- **Where:** `~/.local/state/lin-wallpapers/log/` — JSON Lines, one file per session, rotated (10 files or
  20 MB), with a human-readable view inside the app (Settings → Diagnostics).
- **What is logged:** every probe result with its evidence and reason code; scan summaries (roots, counts,
  skipped with reasons); every plan, every step with its outcome and duration; authorization outcomes;
  verification results; rollbacks; and every capability state change ("Boot splash: unsupported → available,
  Plymouth was installed").
- **Levels and filters:** filter by area (probe, scan, analyse, preview, apply, helper) and level; defaults
  to the current session. Clicking **"Why?"** on a greyed-out control opens the log filtered to exactly the
  lines that explain it.
- **Diagnostics bundle:** one button copies or saves `linwp doctor --json` plus the recent log and the
  distribution details — the bug-report format, and the same JSON that seeds a new test fake root.
- **Privacy:** paths under `$HOME` are included because they matter for diagnosis; nothing is ever sent
  anywhere. No telemetry and no network calls, in any milestone.
- **The helper logs too:** its structured progress lines are captured into the same log and also land in the
  journal, so a privileged failure stays diagnosable afterwards.

---

## 16. Design language

Reference: `universal-themes/image-reference/ui-kit-yellow-gray-yello.jpg` — deep navy-charcoal panels,
neutral gray text, a single saturated yellow accent on small surfaces (icons, chips, primary buttons).

| Token | Value | Use |
| --- | --- | --- |
| `--bg-base` | `#1E2233` | Window background |
| `--bg-surface` | `#252A3E` | Cards, sidebar |
| `--bg-raised` | `#2B3044` | Popovers, hovered cards, inputs |
| `--stroke` | `rgba(255,255,255,.08)` | Hairlines, card borders |
| `--text` | `#F2F3F7` | Primary text |
| `--text-dim` | `#8A8E9E` | Secondary text, metadata |
| `--accent` | `#FFC700` | Primary action, selection, focus ring |
| `--accent-2` | `#FFB500` | Gradient end, hover |
| `--on-accent` | `#1A1400` | Text on yellow |
| `--ok` `--warn` `--danger` | `#4ADE80` `#FFB500` `#EF4444` | Status (red is red, never pink) |

Rules: one accent, used sparingly; gradients only on the accent and on the score ring; 12/16 px radii;
8 px spacing grid; Inter/Manrope-style UI font at 13–15 px with tabular numerals for dimensions;
thumbnails get a 1 px inner stroke so light images don't bleed into the surface; **the image is the
color** — chrome stays neutral behind it. Motion: 120–180 ms ease-out for state, a 240 ms cross-fade for
preview switches, no motion during apply (progress is literal).

---

## 17. Modularity and universality

Modularity and universality are **structural requirements** here, not aspirations — the universal
instruction set's core mandate applied to this app (§19). Everything variable is a provider, registered in
a registry and selected by a runtime probe; nothing in the codebase branches on a distribution name,
release number or `/etc/os-release` string.

### 17.1 The provider contract

```python
class SurfaceProvider(Protocol):
    id: str                      # "greeter_slick"
    surface: Surface             # DESKTOP | LOCK | LOGIN | SPLASH | BOOTMENU
    def detect(self, env: Environment) -> Detection: ...   # confidence 0..1 + evidence strings
    def capabilities(self) -> Capabilities: ...            # can_apply, needs_root, needs_restart,
                                                           # supports_per_monitor, geometry, formats
    def current(self) -> CurrentState | None: ...          # what is set now, and where it came from
    def plan(self, image: Image, options: Options) -> list[Step]: ...
    def apply(self, steps: list[Step], ctx: Context) -> Result: ...
    def verify(self, ctx: Context) -> Verification: ...
    def revert(self, backup: BackupRef) -> Result: ...
    def preview_spec(self) -> PreviewSpec: ...             # geometry + chrome for the mock-up
```

Rules every provider obeys:

1. **No GTK, no UI, no user interaction.** Providers are libraries; the GUI and the CLI both drive them.
2. **Detection is evidence-based** — a binary on `PATH`, a running process, a D-Bus name, a schema in the
   GSettings database, a config file that parses — and returns *why*, so the UI can explain itself.
   A negative result is a **reason code plus evidence** from the §15.2 catalogue, never prose and never a
   bare `False`; the control it belongs to is greyed out, not removed.
3. **Declared capabilities, no surprises.** The planner refuses to build a step a provider hasn't declared.
4. **Plan before act.** `plan()` is pure and side-effect free; `apply()` executes only what `plan()` returned.
5. **Reverse with the forward.** A step that cannot describe its own undo cannot be planned.
6. **Idempotent.** Re-applying the same image is a no-op (the `cmp -s` rule from the base script, §4.1).
7. **Fail closed, degrade locally.** A provider that errors disables its own tile; the other four surfaces
   still apply, and the transaction rolls back only its own steps.
8. **Testable without the platform** — every provider ships golden tests against `tests/fakeroot/`.

### 17.2 The registries

| Interface | Implementations in v1 | Later |
| --- | --- | --- |
| `SurfaceProvider` — desktop | `desktop_cinnamon`, `desktop_gnome`, `desktop_mate`, `desktop_xfce`, `desktop_plasma` | LXQt, Pantheon, Budgie specifics |
| `SurfaceProvider` — lock | `lock_cinnamon`, `lock_gnome`, `lock_xfce` (xfce4-screensaver), `lock_plasma` | swaylock, i3lock |
| `SurfaceProvider` — login | `greeter_slick`, `greeter_lightdm_gtk`, `greeter_sddm`, `greeter_gdm`, `greeter_lightdm_generic` | LXDM, greetd |
| `SurfaceProvider` — splash | `splash_plymouth` (initramfs-tools **and** dracut back ends) | — |
| `SurfaceProvider` — boot menu | `bootmenu_grub`, `bootmenu_none` | systemd-boot, rEFInd |
| `ScanSource` | filesystem roots, mounted volumes, udisks2 events | online galleries, Nextcloud, a photo library |
| `Scorer` | the §6 weighted scorer | ML aesthetic scoring, learning from applies |
| `ThumbnailBackend` / `TransformBackend` | GdkPixbuf + Pillow | libvips, GEGL |
| `PreviewSurface` | one Cairo mock per surface, driven by `preview_spec()` | screenshot-based mocks |
| `PrivilegedOp` (helper side) | `write_system_image`, `edit_ini`, `install_theme`, `set_alternative`, `write_dropin`, `regen_initramfs`, `regen_bootmenu` | — |

The helper's allow-list is itself modular: a provider requests a *named operation* with typed arguments,
and the helper decides whether that operation exists and is permitted. Adding a provider never adds a way
to write an arbitrary path.

### 17.3 Universality checklist (enforced in review)

- [ ] No distribution, release or desktop name in any conditional outside `detect()`.
- [ ] Every path, binary and schema name comes from a probe or a constant table, never from a hard-coded guess.
- [ ] Every new provider ships: detection evidence, capabilities, plan/apply/verify/revert, a preview spec,
      a fake-root golden test, and a row in the §4.2 matrix.
- [ ] Nothing in `src/ui` or `src/pages` imports a provider directly — only through view models.
- [ ] Nothing in `src/scanner`, `src/catalogue`, `src/imaging`, `src/apply` imports GTK.
- [ ] The CLI can do everything the GUI can (proof that the layering holds).
- [ ] `linwp doctor` explains every unsupported surface in plain language, naming the owning component.

---

## 18. GTK 3 → GTK 4 portability rules

| Area | Rule in GTK 3 code | Maps to in GTK 4 |
| --- | --- | --- |
| Version gate | `gi.require_version('Gtk', os.environ.get('LWP_GTK', '3.0'))` in `src/gtk_version.py`, nowhere else | flip to `4.0` |
| Packing | `ui/compat.py` helpers (`append`, `set_child`), never `pack_start`/`add` in pages | `Gtk.Box.append`, `set_child` |
| Visibility | no `show_all()`; `compat.show()` | visible by default |
| Drawing | custom widgets subclass `compat.CanvasArea` exposing `on_draw(cr, w, h)` | `Gtk.DrawingArea.set_draw_func` |
| Input | `Gtk.GestureMultiPress`, `Gtk.EventControllerMotion/Key`, `Gtk.GestureDrag` (crop handle) | `Gtk.GestureClick`, same controllers |
| Grid | `Gtk.FlowBox` in a `Gtk.ScrolledWindow` with recycled children behind `components/image_grid.py` | `Gtk.GridView` + `Gio.ListStore` — the view model already is a list model |
| Images | `Gdk.Texture`-shaped wrapper around `GdkPixbuf` in `preview/compositor.py` | `Gdk.Texture`, `Gtk.Picture` |
| Menus | `Gio.Menu` + `Gtk.Popover`; no `Gtk.Menu`, no `Gtk.StatusIcon` | `Gtk.PopoverMenu` |
| Dialogs | one `ui/dialogs.py` wrapper (file chooser, message) | `Gtk.FileDialog`, `Gtk.AlertDialog` |
| Styling | CSS classes and `@define-color` tokens in one file; no `override_*`, no `-gtk-gradient` | same tokens |
| Threads | workers never touch widgets; results via `GLib.idle_add` | same |

CI runs `tools/gtk4_lint.py`, which fails the build on banned GTK 3-only calls outside `compat.py`.

---

## 19. Build process under the universal instruction set

Initialized and maintained per `universal-instruction-set/CLAUDE.md` v2026.04 (copy, don't reference;
universal files are immutable; project-specific pieces go alongside them):

| Step | Action for `lin-wallpapers` |
| --- | --- |
| 1 | Repo `MensuraMedia/lin-wallpapers` (SSH remote, local checkout `~/projects/lin-wallpapers`); `.gitignore` for Python, venv, build, `debian/` artifacts |
| 2 | `universal-agents/setup.sh ~/projects/lin-wallpapers "Lin Wallpapers" "GTK wallpaper manager for every screen"`, then `universal-permissions/setup.sh` |
| 3 | `CLAUDE.md` from the v2026.04 template with the real commands (`./run.sh`, `pytest`, `ruff`, `mypy`, `dpkg-buildpackage -us -uc`) |
| 4 | Rules: universal `memory-rules.md`, `security.md`, `token-hygiene.md`; project rules `python-gtk.md` (main-thread-only UI, no blocking I/O in callbacks), `privileged-helper.md` (allow-lists, polkit, no shell with user input, never touch conffiles), `boot-safety.md` (validate before install, verify initramfs, rollback path) |
| 5 | Hooks: Python section enabled in `post-edit-lint.sh` (ruff + mypy), security gate and session hooks unchanged |
| 6 | Memory: `decisions.md` seeded with this document's decisions; `pending.md` with the milestones; `changelog.md` first entry |
| 7 | **universal-themes:** `ui-kit-yellow-gray-yello.jpg` is the binding visual reference (§16) |
| 8 | Agents: *architect* for the provider interfaces and helper API, *implementer* for pages and scanners, *code-reviewer* on every helper and boot-path change, *data-checker* for catalogue schema and golden fixtures |
| 9 | Workflow: `/plan-first` per milestone, `/build-test` before each commit, `/session-end` for logs |

---

## 20. Packaging, testing and performance

**Packaging.** Native `.deb` via `debhelper` + `dh-python`: `lin-wallpapers` (GUI + CLI) and
`lin-wallpapers-helper` (the one-shot privileged helper and its polkit actions — no service units, nothing
enabled at install time; `postinst` starts nothing). Ships `.desktop`, AppStream
metainfo, symbolic icons and a GResource bundle. Runtime deps:
`python3-gi gir1.2-gtk-3.0 python3-gi-cairo python3-pil gir1.2-gdkpixbuf-2.0 polkitd dbus`; recommends
`plymouth grub2-common`. Nothing in the dependency list or the maintainer scripts is distribution-specific:
the same two packages install on Mint, Ubuntu and its flavours, Debian, Pop!_OS, Zorin, MX and elementary,
and the providers sort out the differences at runtime (§4.2). Flatpak is deliberately out of scope for v1 — the privileged surfaces need host
access that a Flatpak sandbox complicates.

**Testing.** Unit tests for scoring, hashing, transforms (golden images, byte-exact) and plan building;
provider integration tests against `tests/fakeroot/` (a synthetic `/etc`, `/usr/share`, `/boot`) asserting
the resulting tree and the rollback tree; catalogue tests on a generated 10,000-row library; UI smoke tests
under `xvfb-run`; a `shellcheck`-clean `run.sh`. The one thing that cannot be tested in CI — a real
initramfs rebuild — gets a documented manual checklist per release, run on the reference laptop.

**Performance budgets.** Cold scan ≥ 300 images/s in phase 1 and ≥ 60 probes/s in phase 2 on the reference
hardware; browser scroll at 60 fps with 20,000 cards; thumbnail from cache < 5 ms; preview render < 120 ms;
memory < 250 MB with a 20,000-image catalogue; idle CPU 0 % (no polling, watches only).

---

## 21. Roadmap

| Milestone | Deliverable |
| --- | --- |
| **M0** | Universal scaffold (§19), repo hygiene, `run.sh`, app shell from the starter, theme tokens, empty pages |
| **M1** | Scanner + catalogue + thumbnails; Sources page; Browse page with filters and sorting |
| **M2** | Suitability scoring, badges, duplicates; Image page with metadata, palette and fit control |
| **M3** | Transform pipeline + preview compositor; Screens page with capability probes; all five previews |
| **M4** | Apply engine: planner, backups, verification, rollback, History/undo. Desktop + lock end-to-end on Cinnamon, GNOME, MATE, Xfce, Plasma (the user-space half of the §4.2 matrix) |
| **M5** | One-shot `pkexec` helper and its polkit actions (no service units); the base script's three privileged surfaces end-to-end (slick-greeter, lightdm-gtk-greeter, Plymouth via initramfs-tools, GRUB); `linwp` CLI and `linwp doctor` |
| **M6** | Remaining login providers (GDM, SDDM), dracut back end, fake roots for five distribution shapes, sync mode, collections, slideshows, `.deb` + AppStream, first release |
| **M7** | Breadth: LXQt/Pantheon/Budgie desktops, per-monitor and Wayland refinements, online scan sources |
| **M8** | GTK 4 port (flip `gtk_version.py`, replace the FlowBox grid with `Gtk.GridView`) |

## 22. Risks

| Risk | Mitigation |
| --- | --- |
| A bad Plymouth theme or initramfs leaves an ugly or hung boot | Offscreen validation, initramfs content verification, automatic rollback, and the documented `splash`-removal escape via the GRUB menu |
| `/boot` too small for another initramfs | Precheck free space; refuse rather than half-write |
| GRUB can't decode the background | Conservative 8-bit PNG profile, decode test before install |
| Greeter shows grey because the image is unreadable | The copy-to-system-path step is part of the plan, and verification re-reads the file as the greeter user |
| Scanning a huge or network tree stalls the app | Bounded queues, exclusions by default, cancellable, network mounts opt-in |
| Package upgrades overwrite changed conffiles | Drop-ins only; the app never edits a package conffile |
| Desktop-environment drift across releases | Probes and providers, plus a machine-profile dump command for bug reports |
