# Feasibility — Per-virtual-desktop wallpapers

Status: **feasibility study / exploration.** Not a milestone, not scheduled, not a commitment. No code, no
schema, no provider is to be written from this document until the team has read it and ruled. Its only job is
to answer three questions honestly: *can* Lin give each virtual desktop its own wallpaper, *where* can it do so
without breaking the project's rules, and *what would the automation look like* if we chose to build it.

Sources for every current-state claim are listed at the end. Written 2026-09-19 against Plasma 6, GNOME 46/47,
Xfce 4.18/4.20, and current wlroots compositors.

---

## 1. What is being asked, precisely

> Apply wallpapers to Linux **virtual desktops** (if possible), with an optional **automation** feature where
> each virtual desktop is assigned a specified wallpaper *type* and *selection*.

Terms, so the rest of the document is unambiguous:

- **Virtual desktop / workspace** — a switchable arrangement of windows on the *same* monitors. GNOME calls it a
  *workspace*; KDE calls it a *virtual desktop*; Xfce calls it a *workspace*. One is active at a time (per
  monitor, on some setups). This is **not** the same as a **monitor** (Lin already treats those, and M7 adds
  per-monitor apply) and **not** the same as a KDE **Activity** (see §4.2 — that distinction turns out to matter
  more than anything else here).
- **Per-desktop wallpaper** — desktop *N* shows image *N*; switching desktops changes the background.
- **Automation** — instead of the user picking image *N* by hand for each desktop, they specify a *rule* per
  desktop ("desktop 1: an ideal dark landscape; desktop 2: this exact image; desktop 3: a slideshow of my
  16:10 photos") and Lin resolves it against the catalogue and materialises the result.

Out of scope for this study: live/animated backgrounds, per-desktop widgets, and anything that is really an
*Activity* rather than a *desktop*.

---

## 2. The one rule that decides everything

Lin's first convention (CLAUDE.md, TECHNICAL-CONCEPT §17): **nothing runs in the background — no daemon, no
unit, no login hook.** Lin writes configuration and exits; the desktop environment, which is *already* running,
renders the result.

Per-desktop wallpaper can be delivered by exactly two mechanisms, and only one of them survives that rule:

- **Mechanism A — persistent config the DE acts on itself.** Lin writes a per-desktop mapping into a store the
  desktop environment reads, and the environment's *own* always-running desktop component does the switching on
  every workspace change. Lin touched nothing at runtime. **This is identical to how Lin already sets a single
  wallpaper** (write config → DE renders), so it fits the architecture with zero new standing processes.
- **Mechanism B — a resident agent that reacts to switch events.** Where the DE has no persistent per-desktop
  store, the only way to change the background when the user switches desktop is for *some process to be running*
  that listens for the switch and swaps the global wallpaper. That process is a daemon by any honest definition,
  whoever ships it.

**Everything below is a question of which environments offer Mechanism A.** Where only Mechanism B is available,
the feature is *technically possible on Linux* but *not possible within Lin as specified* — and saying so, with a
reason code and evidence, is exactly the behaviour §15 already requires ("never hide a feature; unsupported →
greyed out with a reason and evidence").

---

## 3. Why per-desktop is not a display-server primitive

It helps to know why this is hard before looking at each DE.

- **X11.** The background lives in the *root window* pixmap (`_XROOTPMAP_ID` / `ESETROOT_PMAP_ID`), which is a
  single surface shared by every workspace — X11 has no notion of a workspace at all. Workspaces are a
  *window-manager* abstraction advertised through EWMH (`_NET_NUMBER_OF_DESKTOPS`, `_NET_CURRENT_DESKTOP`). So
  on X11 a per-desktop wallpaper can only come from (a) a DE desktop component that draws the background *itself*
  and keys it on the current workspace (Xfce's `xfdesktop` does this), or (b) an external agent watching
  `_NET_CURRENT_DESKTOP` and rewriting the root pixmap on each change (Mechanism B).
- **Wayland.** There is no root window and no client-settable background at all. The **compositor** owns the
  background surface; standalone tools (`swaybg`, `hyprpaper`, `swww`) draw it through `wlr-layer-shell` and are
  themselves long-lived daemons. There is no cross-compositor protocol for "the wallpaper," let alone a
  per-workspace one; each compositor exposes its own IPC. Detecting the *current* workspace on Wayland is
  likewise compositor-specific (sway/hyprland IPC), with no portable equivalent to EWMH.

The consequence: per-desktop wallpaper is always the *desktop environment's* feature, never the platform's. Lin's
job reduces to "does this DE persist a per-desktop mapping I can write, or not?"

---

## 4. Capability survey (per environment)

### 4.1 Xfce — native, persistent, daemon-free ✅ (the best fit)

`xfdesktop` draws the desktop and supports a wallpaper *per workspace per monitor*, stored in the `xfce4-desktop`
xfconf channel (persisted to `~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml`). The switching is
done by `xfdesktop`, which is part of the session — **no Lin process is involved after writing config.**

- Turn off single-wallpaper mode: `/backdrop/single-workspace-mode` → `false`.
- Per slot: `/backdrop/screen0/monitor<CONNECTOR>/workspace<N>/last-image` (string, absolute path),
  plus `image-style`, and for slideshows `backdrop-cycle-enable`, `image-list`, `backdrop-cycle-period`.
- `<CONNECTOR>` is the output name (e.g. `monitorHDMI-A-1`; older builds use `monitor0`). Lin already detects
  connector names in M1, so the key path is derivable.
- Workspace count is EWMH (`_NET_NUMBER_OF_DESKTOPS`) or `wmctrl -d`.

**Verdict:** true per-desktop, per-monitor, static *or* slideshow, entirely through persistent config Lin writes
once. Verifiable (read the key back), undoable (restore the prior xml / keys), transactional. This is a textbook
Mechanism-A provider and maps onto the existing apply engine (M4) unchanged.

### 4.2 KDE Plasma — Activities yes, virtual desktops no (natively) ⚠️

This is the subtle one, and the community tooling confirms it. In Plasma:

- **Activities** each carry their own wallpaper *natively and persistently*, stored as containment config in
  `~/.config/plasma-org.kde.plasma.desktop-appletsrc`. The supported way to set it is the plasmashell scripting
  API — a **one-shot** D-Bus call (`org.kde.PlasmaShell.evaluateScript`, iterating `desktops()`), not a resident
  process. That fits Mechanism A.
- **Virtual desktops** do **not** have per-desktop wallpaper natively. The reason is structural and widely
  documented: *Plasma scripts can change the wallpaper but cannot tell which virtual desktop is current, and KWin
  scripts can tell the current desktop but cannot change the wallpaper.* Bridging the two requires a resident
  KWin script driving a plasmashell script on every switch — Mechanism B. Third-party switchers
  (`wallpaperswitch` for Plasma 6, the old "Vallpaper" for Plasma 5) exist and are exactly that resident bridge.

So Plasma gives us a real, daemon-free per-*context* wallpaper — but the context is an **Activity**, not a
virtual desktop. Whether that satisfies the request is a **product** question (Q1 below), not a technical one.
(Plasma is also actively changing this area — recent work on per-screen virtual desktops — so any provider here
must probe capabilities at runtime rather than assume a version.)

### 4.3 GNOME (Mutter) — no ❌

Mutter draws one background for all workspaces; there is no per-workspace store and no supported API. Every
"per-workspace wallpaper on GNOME" solution is a **Shell extension** (Workspace Wallpapers, Walkpaper, BackSlide,
autowallp) that runs inside the shell, listens for the workspace-switch signal, and swaps the *global* wallpaper
— Mechanism B, and additionally version-fragile (several already lag GNOME 47/48). Not available to Lin without
shipping a resident component.

### 4.4 Cinnamon / MATE / Budgie — no ❌

Single global background via GSettings (`org.cinnamon.desktop.background`, `org.mate.background`, GNOME's key for
Budgie). No per-workspace concept in the desktop component at all. Even a Mechanism-B agent would only be
swapping the one global key on switch.

### 4.5 wlroots compositors — sway / Hyprland / river — possible but daemon-based ❌ (for Lin)

The wallpaper itself is drawn by a long-lived daemon (`swaybg`, `hyprpaper`, `swww`). Per-workspace is achieved
by binding a workspace-change event in the compositor config to an IPC call that retargets that daemon
(`hyprctl`, `swww img`, sway IPC). Two standing processes in the chain (the wallpaper daemon and the event
binding), neither of them Lin's but both required — Mechanism B. Lin could *write the compositor config lines*,
but it cannot make the effect happen without those daemons, and the wallpaper daemon is not something the DE
guarantees is present.

### 4.6 Summary matrix

| Environment | Per-desktop native? | Persistent store Lin can write | Daemon-free (fits Lin) | Granularity | Slideshow per slot |
| --- | --- | --- | --- | --- | --- |
| **Xfce** (xfdesktop) | **Yes** | xfconf `xfce4-desktop` | **Yes ✅** | per-workspace **×** per-monitor | Yes |
| **KDE Plasma — Activities** | Yes (per *activity*) | appletsrc via plasmashell script | **Yes ✅** | per-activity (× screen) | Yes |
| **KDE Plasma — virtual desktops** | No | — | No (needs KWin+Plasma bridge) | — | — |
| **GNOME** | No | — | No (Shell extension) | — | — |
| **Cinnamon / MATE / Budgie** | No | — | No | — | — |
| **sway / Hyprland / river** | Via IPC | compositor config | No (wallpaper daemon + event hook) | per-workspace | daemon-dependent |

---

## 5. If we built it: the automation model

The automation the user described — *"each virtual desktop gets a specified wallpaper type and selection"* — sits
very cleanly on top of Mechanism A, because it is just "resolve N selections, then write N config slots." It
reuses machinery Lin is already building:

- A **DesktopPlan** = an ordered list of `(target → selection)` where a *target* is a workspace index (and, on
  Xfce, optionally a specific monitor), and a *selection* is one of:
  - an **explicit image** (a catalogue id / path);
  - a **query** against the catalogue — a `QuerySpec` (M1) narrowed by *type* (orientation, aspect, dominant
    tone once M2 scoring lands) and ranked by the **ideal-for-this-display segment** (M1.5a), so "an ideal dark
    landscape for this screen" resolves to a concrete, screen-appropriate image;
  - a **slideshow set** — a resolved list plus a period, where the DE supports per-slot cycling (Xfce, KDE).
- **Resolution happens at apply time**, once, deterministically: Lin picks concrete images for each target and
  records them, so the result is reproducible and undoable. No process stays behind to "keep it fresh."
- **Reconciliation rules** (must be specified, not implicit): what happens when the workspace *count* changes
  after a plan is applied (clamp / cycle the selections / leave surplus desktops untouched), and when monitors
  change (Xfce's matrix is workspace × monitor). These are the same class of decisions M7's per-monitor work
  already has to make.

Optional, and needing a ruling (Q3): a "**re-materialise each login**" variant — a fresh random pick per desktop
at session start — is *only* daemon-free if the DE's own autostart runs `linwp` once at login. That is arguably
still "no daemon" (it is one-shot, like the M5 helper), but it is a login hook, which the rules currently forbid.
Flagging it, not assuming it.

---

## 6. Fit with Lin's architecture (if it ever ships)

Per-desktop is **not a sixth surface.** It is a finer-grained *target* within the existing `DESKTOP` surface —
the same axis as per-monitor. The cleanest fit with the current code (`src/apply/registry.py`):

- Extend `Capabilities` with `supports_per_workspace: bool` (alongside the existing `supports_per_monitor`), and
  introduce a small `Target` abstraction (monitor × workspace) that the desktop provider's `plan()` iterates. No
  new registry, no new `Surface` value.
- Keep it **providers, not conditionals.** An `XfceDesktopProvider` reports `supports_per_workspace = True` and
  knows the xfconf key layout; a hypothetical `PlasmaActivityProvider` reports the *activity* capability and its
  own limits; every other provider simply reports `False`. No branching on DE name outside each `detect()`.
- The **plan/verify/revert** contract already models exactly what we need: each `Step` must name its inverse, so
  writing N per-desktop keys is N reversible steps, and `verify()` reads them back — the transactional apply and
  undo (M4) carry over verbatim.
- **Detection is evidence-based** (`Detection` already forbids a bare bool): the provider states which desktops
  it measured and how (EWMH count, xfconf channel present, plasmashell reachable).

### Proposed reason codes (following `capability/reasons.py`)

To keep the promise that unsupported never means invisible, per-desktop would add catalogue entries in the exact
`ReasonSpec` shape already in `src/capability/reasons.py`:

| Code | State | Meaning |
| --- | --- | --- |
| `PERDESKTOP_UNSUPPORTED` | `UNSUPPORTED` | This desktop environment has no per-desktop wallpaper Lin can set without a background agent (evidence: DE, session type). |
| `PERDESKTOP_ACTIVITIES_ONLY` | `DEGRADED` | Per-*activity* wallpaper is available (KDE); per-*virtual-desktop* is not. Offer the activity mapping instead. |
| `PERDESKTOP_NEEDS_AGENT` | `UNSUPPORTED` | Achievable only with a resident switcher, which Lin does not run (names the third-party tools that do). |
| `WORKSPACE_COUNT_UNKNOWN` | `DEGRADED` | The number of workspaces could not be read (no EWMH, unknown compositor); a count can be declared manually. |

---

## 7. Feasibility verdict

**Feasible, but only in a minority of environments, and only there because those environments do the runtime
work themselves.**

- **Tier 1 — build-able within Lin's philosophy, today's mechanisms:**
  - **Xfce** — full per-workspace (× per-monitor), static or slideshow, pure persistent config. This is the one
    unambiguous win and the natural first (and possibly only) provider.
  - **KDE via Activities** — genuine daemon-free per-*context* wallpaper, but the context is an Activity, not a
    virtual desktop. Ship it *as Activities*, labelled honestly, or not at all — do not pretend it is virtual
    desktops.
- **Tier 2 — technically possible on Linux, not within Lin as specified:** GNOME, KDE virtual desktops proper,
  Cinnamon/MATE/Budgie, and all Wayland compositors. Each needs a resident agent (Mechanism B). Delivering these
  would require **revisiting the no-daemon rule** — a first-order architectural decision, not a feature toggle.
  Until then the correct behaviour is a greyed-out control with `PERDESKTOP_UNSUPPORTED` / `PERDESKTOP_NEEDS_AGENT`
  and the evidence, per §15.

**Recommendation.** Treat this as a *provider-scoped* capability, not a headline feature. If we pursue it, do a
small **read-only spike** first — an `XfceDesktopProvider.detect()/capabilities()` and a KDE
activity-enumeration probe — that reports what each machine can do, changes nothing, and validates the key
layouts against real `xfdesktop`/`plasmashell` before any apply code exists. Roadmap-wise it belongs with or
after **M7** ("more providers, per-monitor, Wayland"), because it shares the per-monitor target model and the
Wayland reality-check. It should **not** jump ahead of M1–M6, and it must not become the reason the no-daemon
rule is quietly relaxed.

---

## 8. Open questions for the team

- **Q1 (product).** Does "virtual desktop wallpaper" include **KDE Activities**? If yes, KDE joins Tier 1
  labelled as Activities. If the user specifically means numbered virtual desktops, KDE is Tier 2.
- **Q2 (scope).** Is an **Xfce-only** Tier-1 feature worth building, given Xfce's share of the target audience?
  A one-provider feature is honest and cheap, but narrow.
- **Q3 (rules).** Is a **one-shot login re-materialise** (fresh pick per desktop at session start, via the DE's
  autostart running `linwp`) compatible with "no login hook," or is it the thing the rule exists to forbid?
- **Q4 (rules).** Is there *any* appetite to introduce an **optional, user-installed resident helper** for the
  Tier-2 environments (clearly separate from Lin's core, opt-in), or is the no-daemon rule absolute? This single
  answer determines whether GNOME/Wayland are ever in scope.
- **Q5 (model).** Reconciliation defaults when workspace count or monitor set changes after a plan is applied —
  clamp, cycle, or leave surplus untouched?

---

## 9. References (current-state, retrieved 2026-09-19)

- KDE — why per-virtual-desktop needs a KWin↔Plasma bridge, and the Activities alternative:
  [cadence.moe: Implementing different wallpapers on KDE virtual desktops](https://cadence.moe/blog/2022-12-03-implementing-different-wallpapers-on-kde-virtual-desktops),
  [wallpaperswitch (Plasma 6 third-party switcher)](https://github.com/martenjj/wallpaperswitch),
  [This Week in Plasma: per-screen virtual desktops](https://blogs.kde.org/2026/04/18/this-week-in-plasma-per-screen-virtual-desktops-and-wayland-session-restore/).
- GNOME — no native support; extensions are resident and version-fragile:
  [Workspace Wallpapers extension](https://extensions.gnome.org/extension/10072/workspace-wallpapers/),
  [Walkpaper extension](https://extensions.gnome.org/extension/1200/walkpaper/),
  [OMG! Ubuntu: static workspace background extension](https://www.omgubuntu.co.uk/2025/09/static-workspace-background-gnome-extension).
- Xfce — per-workspace via xfconf:
  [Xfce Forums: config for different wallpapers per workspace](https://forum.xfce.org/viewtopic.php?id=15274),
  [Xfce Forums: set a different wallpaper for each workspace](https://forum.xfce.org/viewtopic.php?id=17617),
  [Changing the Xfce wallpaper from the command line](https://www.friendlyskies.net/notebook/how-to-change-xfce-wallpaper-from-the-command-line-or-terminal).
- wlroots — daemon + IPC per workspace:
  [Hyprland Wiki: Wallpapers](https://wiki.hypr.land/Useful-Utilities/Wallpapers/),
  [hyprpaper (IPC-controlled Wayland wallpaper daemon)](https://github.com/hyprwm/hyprpaper),
  [Hyprland discussion: different wallpapers per workspace](https://github.com/hyprwm/Hyprland/discussions/8565).
