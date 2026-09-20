# Technical concept — Cross-distro wallpaper application

_How to grow `reference/apply-08-screen-wallpaper.sh` (Linux-Mint-only) into a mechanism that applies one
image across the boot/login/lock surfaces on **any** mainstream Linux distribution. This is design; it maps
onto the app's existing `SurfaceProvider` protocol (`src/apply/registry.py`) and its M4/M5/M7 milestones. It
does not itself schedule work._

Status: **concept.** Written 2026-09-20 against the reference script and TECHNICAL-CONCEPT §15 (capability
states), §17 (providers). Distro-specific commands marked _(verify on target)_ must be confirmed on a real
machine of that family before a provider ships.

---

## 1. Why the script isn't portable, in one line

`reference/apply-08-screen-wallpaper.sh` hardwires **one** implementation of each surface:
LightDM+slick-greeter, Plymouth-via-`update-alternatives`, `update-initramfs`, GRUB2-via-`update-grub`, and a
Cinnamon `gsettings` source read — plus a borrowed **mint-logo** throbber. Change any one of those (Fedora's
`dracut`, KDE's SDDM, GNOME's GDM, systemd-boot…) and the step fails, and `set -euo pipefail` aborts the run.
Universality is therefore not a matter of adding `if distro == …` branches — it is a matter of **one surface,
many interchangeable providers, each detected by evidence.** That is exactly the model the app already declares.

## 2. The core idea: surface × provider, detected by evidence

Each surface is a *capability*; each way of delivering it on some stack is a *provider*. The contract already
exists (`src/apply/registry.py`): a `SurfaceProvider` has `detect(env) → Detection(confidence, evidence,
reason_code)`, `capabilities()`, `current()`, `plan(image, options) → [Step(op, description, inverse,
needs_root)]`, `apply()`, `verify()`, `revert()`. The registry picks the **highest-confidence** provider per
surface. Two rules make this universal instead of brittle:

- **Providers, not conditionals (concept §17).** No code branches on a distro or release *name*. A provider
  decides it applies by probing what is actually present — a binary on `PATH`, a config file, a systemd unit
  target, a directory. The distro name is at most a tiebreaker inside one `detect()`.
- **Never hide a feature (§15).** Where no provider can serve a surface (e.g. a menu background under
  systemd-boot), the surface is shown **greyed with a reason code and evidence**, never omitted.

The five surfaces (`Surface` enum): `DESKTOP` (source of truth / where the image is chosen), `LOCK`, `LOGIN`
(greeter), `SPLASH` (boot), `BOOTMENU`. Below, each gets its provider landscape.

## 3. The variant landscape (what to build, per surface)

### 3.1 Source read — "use the current desktop wallpaper" (convenience only)
In the app the image comes from the catalogue, so this matters only for the script/CLI convenience and for
Sync mode. Detect the running desktop and read its key:

| Desktop | Read | Provider |
| --- | --- | --- |
| Cinnamon | `gsettings get org.cinnamon.desktop.background picture-uri` | `source_cinnamon` |
| GNOME | `org.gnome.desktop.background picture-uri` (+ `-dark`) | `source_gnome` |
| MATE | `org.mate.background picture-filename` | `source_mate` |
| Xfce | `xfconf-query -c xfce4-desktop -p .../last-image` | `source_xfce` |
| KDE Plasma | `plasma-org.kde.plasma.desktop-appletsrc` / plasmashell script | `source_plasma` |
| wlroots (sway/hyprland) | compositor IPC / `swww query` _(verify)_ | `source_wlroots` |

`--image FILE` (the one portable path today) stays the universal override.

### 3.2 LOGIN — the greeter
The display manager is authoritative: read the enabled unit
(`readlink /etc/systemd/system/display-manager.service`).

| Greeter | Mechanism | Reversible? | Provider |
| --- | --- | --- | --- |
| **slick-greeter** (Mint) | `[Greeter] background=` in a `/etc/lightdm/slick-greeter.conf.d/*.conf` drop-in (prefer the drop-in dir over the main file) | yes | `greeter_slick` (exists in the reference) |
| **lightdm-gtk-greeter** (Xubuntu, Lubuntu) | `[greeter] background=` in `/etc/lightdm/lightdm-gtk-greeter.conf.d/*.conf` | yes | `greeter_lightdm_gtk` |
| **SDDM** (KDE/Plasma) | a `/etc/sddm.conf.d/*.conf` `[Theme] Current=` pointing at a small generated theme whose `background=` is our image; or the current theme's `theme.conf.user` background _(verify)_ | yes | `greeter_sddm` |
| **GDM** (GNOME) | **hard/limited.** GDM's background is baked into `gnome-shell-theme.gresource`; there is no supported per-key setting. Options: a gresource override installed to `/usr/share/gnome-shell/` (fragile, breaks on shell upgrades) or declare **UNSUPPORTED** with `LOGIN_GDM_UNSUPPORTED`. Recommend the latter for v1. | partial | `greeter_gdm` (probe → reason) |
| LXDM / others | niche; declare unsupported until asked | — | — |

Shared rule: copy the rendered image to a **system path** (`/usr/share/backgrounds/lin-wallpapers/`), 0644,
because `$HOME` is not readable by the greeter user — the reference already does this and it is universal.

### 3.3 SPLASH — the boot splash (Plymouth) + initramfs
Two independent choices: how to *select* the Plymouth theme, and how to *rebuild* the initramfs.

| Concern | Debian/Ubuntu | Fedora/RHEL/openSUSE | Arch | Detection |
| --- | --- | --- | --- | --- |
| Select theme | `update-alternatives --install/--set default.plymouth …` | `plymouth-set-default-theme <t>` | `plymouth-set-default-theme <t>` | prefer `plymouth-set-default-theme` where present; else `update-alternatives` |
| Rebuild initramfs | `update-initramfs -u -k all` | `dracut -f --regenerate-all` | `mkinitcpio -P` | `command -v` the three, in that order |
| Theme dir | `/usr/share/plymouth/themes/lin-wallpapers/` (same everywhere) | " | " | — |

**Kill the mint-logo dependency:** ship our **own** theme from `resources/plymouth-template/` (the `script`
plugin, as the reference uses) with our **own** spinner frames, or better, render a self-contained theme that
needs no external throbber (a static or generated spinner). No provider may `cp` another theme's assets.
Providers: `splash_plymouth_altsel` (update-alternatives) and `splash_plymouth_setdefault`
(`plymouth-set-default-theme`), each pairing with an initramfs provider `initramfs_{update,dracut,mkinitcpio}`.
Where there is no Plymouth at all → `SPLASH_NO_PLYMOUTH` (greyed, with the evidence).

### 3.4 BOOTMENU — the boot manager
This is where "drop-ins only" gets distro-specific, because only Ubuntu's GRUB sources `/etc/default/grub.d/`.

| Boot manager | Set background | Regenerate | Reversible approach | Provider |
| --- | --- | --- | --- | --- |
| **GRUB2 (Debian/Ubuntu)** | `GRUB_BACKGROUND=` in `/etc/default/grub.d/99-lin.cfg` drop-in | `update-grub` → `/boot/grub/grub.cfg` | remove the drop-in + image | `bootmenu_grub_ubuntu` (exists) |
| **GRUB2 (Fedora/RHEL/SUSE)** | no sourced drop-in dir; add an **additive** script `/etc/grub.d/09_lin_background` that `echo`s `set background_image=…` (never edit `/etc/default/grub`, a conffile) **or** install a `GRUB_THEME` theme dir | `grub2-mkconfig -o /boot/grub2/grub.cfg` (or the EFI path) _(verify)_ | remove our `/etc/grub.d` script / theme dir | `bootmenu_grub2_mkconfig` |
| **systemd-boot** | **no menu image** — the menu is text | — | — | `bootmenu_sdboot` → `BOOTMENU_UNSUPPORTED` |
| **rEFInd** | theme/background supported (`theme.conf`) | none | replace/remove our theme entry | `bootmenu_refind` (later) |

Detect by artifact: `/boot/grub/grub.cfg` + `command -v update-grub` → Ubuntu-style; `/boot/grub2/` +
`grub2-mkconfig` → Fedora-style; `/boot/loader/loader.conf` + `bootctl` → systemd-boot; `/boot/EFI/refind` →
rEFInd.

### 3.5 LOCK — the lock screen
Often "follows the desktop" (Cinnamon, GNOME); some lockers take an explicit image (KScreenLocker,
swaylock, i3lock via a helper). Provider `lock_follows_desktop.probe()` states this in the UI (as the
reference does implicitly); a real override provider is only needed where the user wants a *different* lock
image. Mostly a probe + a reason string, not a write.

## 4. Detection: evidence, not distro names

Each provider's `detect(env)` returns a `Detection(confidence, evidence, reason_code)` from concrete probes,
all runnable against a fake root in tests:

- **Display manager / greeter:** `readlink /etc/systemd/system/display-manager.service`; for LightDM,
  `greeter-session=` across `/etc/lightdm/lightdm.conf` + `.d/`.
- **Plymouth select tool:** `command -v plymouth-set-default-theme`; else `update-alternatives --list
  default.plymouth`.
- **Initramfs tool:** first of `update-initramfs` / `dracut` / `mkinitcpio` on `PATH`.
- **Boot manager:** the artifact probes in §3.4.
- **Desktop (for source read):** `$XDG_CURRENT_DESKTOP` cross-checked with the presence of the matching
  settings tool/schema.

`confidence` lets two providers coexist (e.g. `plymouth-set-default-theme` present on a Debian box that also
has `update-alternatives`); the registry picks the strongest, and the loser is inert, not an error. `os-release`
`ID`/`ID_LIKE` is allowed only as a **tiebreaker inside one provider**, never as the branch that selects it.

## 5. The universal engine contract (inherited from the script, kept everywhere)

These are the reference script's own rules, promoted to invariants every provider obeys — they are what make a
multi-distro engine safe rather than a pile of special cases:

1. **Root does only what needs root.** One-shot, polkit-authorized helper (M5) in place of `sudo`; **no
   daemon, no service, no login hook.** The helper takes a *plan* (a list of `Step`s) and executes it.
2. **Idempotent.** `cmp -s` before every write; re-running changes nothing already correct.
3. **Additive, reversible artifacts — never edit a package conffile.** Prefer a `*.d/` drop-in; where a distro
   has none (Fedora GRUB), add a **new** file we own (`/etc/grub.d/09_lin_background`, a theme dir) rather than
   touching `/etc/default/grub`. Each `Step` names its own `inverse` at plan time (the protocol enforces this —
   a step with no inverse cannot be planned).
4. **Backups are data.** Before touching a file, copy it to `/var/backups/lin-wallpapers/<ts>/` and record a
   JSON manifest (path, mode, owner, sha256, and the prior `update-alternatives`/theme selection), so `revert`
   replays from data, not memory.
5. **Expensive steps run once.** Collect all providers' steps into one plan; run a single initramfs rebuild and
   a single boot-manager regeneration at the end, even when several surfaces changed.
6. **Verify before commit, and say what happened.** `verify()` reads the result back (greeter key set, resolved
   `default.plymouth`, `grep` count in the boot config, `lsinitramfs | grep` for the splash asset) before the
   apply is declared successful; failures roll back from the backup manifest.

## 6. Handling the genuinely unsupportable — honestly

Some (surface, stack) pairs have no clean mechanism. The engine must state this, not fake it. Proposed reason
codes (concept §15.2 catalogue; shape as in `src/capability/reasons.py`):

| Code | State | Meaning |
| --- | --- | --- |
| `LOGIN_GDM_UNSUPPORTED` | UNSUPPORTED | GDM has no supported background key; a gresource override is fragile and opt-in only. |
| `SPLASH_NO_PLYMOUTH` | UNSUPPORTED | No Plymouth on this system; boot splash cannot be set. |
| `BOOTMENU_UNSUPPORTED` | UNSUPPORTED | systemd-boot (or a text-only menu) has no background image. |
| `INITRAMFS_TOOL_UNKNOWN` | DEGRADED | None of `update-initramfs`/`dracut`/`mkinitcpio` found; splash theme set but not activated until the user rebuilds. |
| `BOOT_REGEN_TOOL_UNKNOWN` | DEGRADED | Background staged but no `update-grub`/`grub2-mkconfig` found to activate it. |

The UI greys the surface tile with the reason and the evidence (the probes that failed), exactly as §15
requires — the user always sees *why*, never a silent gap.

## 7. Bundled assets — remove every distro-asset dependency

- **Plymouth theme** generated from `resources/plymouth-template/` (already the plan), with **our own** spinner
  frames — no `cp` from `mint-logo` or any distro theme (NOTICE stays honest).
- **GRUB theme/background** rendered by us; on Fedora, a minimal `GRUB_THEME` dir we install, not a distro one.
- Renders come from the one `imaging/transform.py` `fill` path (identical math to the script's `render()`), so a
  preview equals the applied result on every distro.

## 8. Provider registry → compatibility, at a glance

Building these providers turns the matrix from §"the script today" (Mint only) into broad coverage:

| Surface | Providers to build | Covers |
| --- | --- | --- |
| LOGIN | `greeter_slick`, `greeter_lightdm_gtk`, `greeter_sddm`, `greeter_gdm`(probe) | Mint, Xubuntu/Lubuntu, KDE (SDDM), GNOME(limited) |
| SPLASH | `splash_plymouth_altsel` + `splash_plymouth_setdefault`; `initramfs_{update,dracut,mkinitcpio}` | Debian/Ubuntu, Fedora/RHEL/SUSE, Arch |
| BOOTMENU | `bootmenu_grub_ubuntu`, `bootmenu_grub2_mkconfig`, `bootmenu_sdboot`(probe), `bootmenu_refind`(later) | Ubuntu-GRUB, Fedora-GRUB, systemd-boot(honest N/A), rEFInd |
| LOCK | `lock_follows_desktop`(probe) + optional per-locker overrides | most desktops |
| SOURCE | `source_{cinnamon,gnome,mate,xfce,plasma,wlroots}` | wallpaper auto-read per desktop |

With those, the engine **fully serves** the mainstream families — Debian/Ubuntu/Mint, Fedora/RHEL, openSUSE,
Arch/Manjaro, and KDE/GNOME/Xfce/Cinnamon desktops — with honest greying only where a stack genuinely offers no
mechanism (systemd-boot menu, GDM login).

## 9. Phased plan (maps onto the existing milestones)

1. **M4 (user-space apply), extend the provider set beyond Mint:** `greeter_lightdm_gtk`, `greeter_sddm`; the
   Plymouth split (`setdefault` + `dracut`/`mkinitcpio`); `bootmenu_grub2_mkconfig`. These need no new
   architecture — just more providers behind the existing protocol.
2. **M5 (privileged):** the one-shot helper already carries a *plan* of `Step`s; nothing per-distro changes in
   the helper — only the steps it's handed differ. Add the backup-manifest replay for `revert`.
3. **M7 (reach):** `source_*` readers, `bootmenu_refind`, per-locker LOCK overrides, and the GDM gresource
   route behind an explicit opt-in.
4. Throughout: bundle our own Plymouth/GRUB assets (§7) so no provider depends on a distro theme.

## 10. Testing — no real system touched

Every provider is `detect()`/`plan()`/`verify()`/`revert()` against **`tests/fakeroot/<distro>/`** fixtures
that mimic each family's artifacts: `mint/` (lightdm+slick, update-alternatives, /boot/grub), `fedora/`
(gdm or sddm, plymouth-set-default-theme, dracut, /boot/grub2), `arch/` (mkinitcpio, systemd-boot), `kde/`
(sddm). `plan()` produces the `Step` list with inverses; a golden test asserts the exact commands/paths per
fixture; `apply()` runs only against the fake root (the real commands are injected runners, as
`scanner/displays.py` already does). A per-distro **dry-run** (`linwp apply --plan --json`) prints the plan
without executing — the safe way to validate coverage on a real machine before wiring the helper.

## 11. Non-goals / risks

- **Not** a daemon and **not** a per-distro fork of the script — one engine, many providers, one plan.
- GDM and systemd-boot are genuinely limited; the concept's answer is an honest reason code, not a hack that
  breaks on the next upgrade.
- Every distro-specific command marked _(verify on target)_ must be confirmed on a real machine of that family
  and pinned with a `tests/fakeroot` fixture before its provider is trusted — the reference script earned its
  correctness by being *applied*, and each new provider must earn it the same way.
