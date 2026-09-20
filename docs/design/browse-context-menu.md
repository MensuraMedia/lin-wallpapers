# Browse right-click menu, quick preview, and apply flow

Status: **design + mockups.** A cohesive right-click UX for the Browse grid that threads together features
which already exist, are half-specified elsewhere, or arrive in later milestones. No code follows from this
document until the relevant milestones schedule it; the point here is to fix the interaction, the data flow,
and *which* engine each action rides on, so nothing is built twice or against the wrong layer.

Mockups (rendered artboards): `docs/mockups/png/BrowseMenu.png`, `Collect.png`, `QuickApply.png`
(sources: `docs/mockups/{BrowseMenu,Collect,QuickApply}.dc.html`). The existing `Preview.png` and
`Screens.png` are the full-page destinations this flow leads into.

---

## 1. The interaction

Right-clicking (or pressing the keyboard menu key on a focused card) in the **Browse** grid opens a context
menu on the image under the cursor:

```
  Exclude Image
  Exclude Folder
  ───────────────
  Add to Collection   ▸   (submenu: existing collections + New collection…)
  Preview…                (opens the quick-preview & apply popup)
```

The same four actions appear on the **Image page** (M2.6) and, where they act on a selection, on the
selection action bar. Multi-select is honoured: with several cards selected, *Exclude Image* excludes each,
*Add to Collection* adds all, *Preview…* previews the primary and applies to the chosen surfaces.

**Where it is wired.** The menu is a small **gi-free menu model on `BrowseVM`** — a frozen
`ContextMenu(items: tuple[MenuItem, ...])` DTO whose items carry an action id, a label, an enabled flag and a
reason (so a disabled item can say *why*). `page_browse` turns that model into a `Gtk.PopoverMenu` /
`Gio.Menu` and routes each activation back to a view model — `SourcesVM` (exclusions), `CollectionsVM`
(collections), or a future `ApplyVM` (preview/apply). Pages still import only view models; no page ever sees a
`catalogue`/`scanner`/`apply` type. This keeps the `pages → viewmodels` import contract intact and the whole
menu logic unit-testable without a display.

---

## 2. Exclude Image / Exclude Folder — **buildable now** (the engine exists)

This is already specified in **M1.7** ("right-click in Browse and on the Image page → *Exclude this image* /
*Exclude this folder* / *Exclude folders like this…* (pre-fills a pattern); every exclusion offers Undo in a
toast"). Only the menu affordance is missing; the engine shipped in M1.

- **Exclude Image** → a `FILE` exclusion rule for that exact path (inode-pinned, so it survives a rename).
- **Exclude Folder** → a `FOLDER` rule scoped to the image's directory.
- **Data flow:** `BrowseVM` action → `SourcesVM.add_rule(kind, value)` → `CatalogueWriter` →
  `db.add_rule` + `db.apply_exclusions(matcher)`; the writer emits `RULES_CHANGED` + `IMAGES_FLAGGED`;
  `BrowseVM` coalesces and the excluded rows **leave the grid instantly** (they also leave the ideal segment
  and any collection view). No rescan, nothing deleted — the rows keep their thumbnails, tags and score and
  simply carry `excluded_by = <rule id>` (M1.7).
- **It shows up in Sources → Exclusions** because that is the same `exclusion` table the Sources panel already
  reads; a per-rule skip count appears there and in the log (M1.7 "never silent").
- **Undo:** every exclusion raises a toast with **Undo**, which calls `SourcesVM.remove_rule(rule_id)` — the
  flag clears just as fast and the images return. Precedence stays file › folder › pattern; an explicit
  include still wins (M1.7).
- **Not built yet:** the `Gtk.PopoverMenu`, the toast, and a `SourcesVM.add_file_rule/add_folder_rule`
  convenience (`add_rule` already exists). A natural **P6 follow-up**, no schema or engine work.

## 3. Add to Collection — **later (M6.7); needs the deferred tables**

Collections are deferred (design decision **D9**: the `collection` / `collection_item` tables are added by the
milestone that first uses them) and the feature itself is **M6.7** ("Manual collections and smart collections
on the Collections page"). The right-click entry is the natural creation point.

- **Interaction:** *Add to Collection ▸* opens a submenu / small dialog (see `Collect.png`) listing existing
  collections with their counts and a checkmark for ones the image is already in, plus a **+ New collection…**
  row with an inline name field and **Create**. Toggling a row adds/removes the image; **Create** makes the
  collection and adds it in one step.
- **Minimal schema** (a second real migration, per D9):
  ```sql
  CREATE TABLE collection(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'manual'
      CHECK (kind IN ('manual','smart')), query TEXT, created INTEGER, sort INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE collection_item(
    collection_id INTEGER NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
    added INTEGER, PRIMARY KEY (collection_id, image_id)) WITHOUT ROWID;
  ```
  A `smart` collection stores a `QuerySpec` as `query` (JSON) instead of rows — the "saved filter" case. An
  excluded or missing image stays a member but is filtered at query time, exactly like the ideal segment (D7).
- **New layer:** a gi-free `CollectionsVM` (list/create/rename/delete, `add(image_ids, collection_id)`,
  `collections_for(image_id)`) over `catalogue.collections` query helpers, and the dialog in
  `ui/components/collection_picker.py`. The existing **Collections page** (today a read-only list of the
  built-in segments) becomes the manager.
- **No daemon / no background:** creating and populating a collection is one writer transaction; nothing polls.

## 4. Preview… — **later (M3); the quick popup**

*Preview…* opens a lightweight popup (see `QuickApply.png`) — a per-image shortcut into the M3 preview
compositor and the M3.5 Screens surfaces, without leaving Browse.

- **The preview image** is produced by the **same `transform()`** the apply will use (M3.1) — zoom + centre-
  crop to the target geometry, then the per-surface format profile — so what is shown cannot drift from what
  gets installed (M3 acceptance #1). The current display and the fitted resolution are printed **under** the
  preview, e.g. *Fitted to 2560 × 1080 · HDMI-A-0* (from the M1 display detection already in `ScanVM`/
  `SourcesVM`).
- **The surface checkboxes** are the five `Surface`s from `apply/registry.py`: **Desktop, Lock Screen, Login
  Screen, Boot Splash, Boot Menu**. Each row's state comes from that surface's provider probe (M3.2):
  - a supported surface is a normal, checkable row;
  - an unsupported / not-yet-available one is **greyed with its reason code**, never hidden (§15 "never hide a
    feature" — `NEEDS_AUTHORIZATION`, `UNSUPPORTED`, `BLOCKED`, e.g. *No provider detected* / *needs
    authorization*). This is the `CapabilityState` catalogue from `capability/reasons.py`.
- **Apply** is disabled until the apply engine exists: **M4** makes it live for Desktop + Lock; **M5** adds the
  three privileged surfaces (Login, Splash, Boot Menu) through the **one-shot `pkexec` helper** — still no
  daemon, no autostart. Until then the button carries a tooltip naming the milestone (M3.5 "no dead buttons").
- **New layer:** an `ApplyVM` exposing `preview(image_id) -> PreviewDTO` (bytes per surface + fitted geometry +
  per-surface capability) and, from M4, `apply(image_id, surfaces)`; the popup is
  `ui/components/quick_apply.py`. The compositor's canvas is the only `imaging`/`preview` code that touches
  GTK, via `compat` (M3 acceptance #10).

## 5. Apply → Screens — **the handoff (M3.5 page, M4/M5 apply)**

Pressing **Apply** in the popup runs the apply for the checked surfaces and then **navigates to the Screens
page** (M3.5), so the user lands where they can see the whole machine and decide whether to spread the image
further:

- The Screens page shows the **five surface cards**, each with a live mini preview, the **provider name and
  mechanism**, the probe verdict (`applied` / `follows desktop` / `needs authorization` / `unavailable:
  <reason>`), **what is currently set**, and the owning component when unsupported (M3.5). So after applying to
  Desktop + Lock, the user immediately sees the other three and can apply there too.
- **Apply is a one-shot transaction** with a plan, per-step progress, **backups and Undo**, and per-surface
  ✓/✗ results (M4.6). A privileged step escalates once through `pkexec` and the process exits — **nothing runs
  in the background** (project rule 1). "Lock follows the desktop" is reported as such rather than as a
  redundant second apply (M4.5).
- Every apply is recorded on the **History page** with thumbnails, surfaces, result badges and per-row Undo /
  Re-apply / Show manifest (M4.6).

---

## 6. Buildable now vs later

| Menu item | Rides on | Status | New work needed |
| --- | --- | --- | --- |
| **Exclude Image** | `scanner.exclude` + `db.add_rule/apply_exclusions` + `SourcesVM` + `BrowseVM` (all shipped) | **Now** — P6 follow-up; already M1.7-specced | `Gtk.PopoverMenu` in `page_browse`; a toast; `SourcesVM.add_file_rule` convenience |
| **Exclude Folder** | same | **Now** — P6 follow-up | `SourcesVM.add_folder_rule` convenience |
| **Add to Collection** | new `collection`/`collection_item` tables (D9), `CollectionsVM` | **M6.7** | 2nd migration; `catalogue.collections`; `CollectionsVM`; `collection_picker` dialog; Collections page becomes a manager |
| **Preview (popup)** | M3 `transform()` + compositor + M3.2 probes; `apply/registry` surfaces; `capability.reasons` | **M3** | `ApplyVM.preview`; `quick_apply` popup; surface capability rows with reason codes |
| **Apply (from popup) → Screens** | M4 executor (desktop/lock) + M5 helper (login/splash/menu); M3.5 Screens page; M4.6 History | **M4 / M5** | `ApplyVM.apply`; Screens Apply/Revert live; plan sheet; backups + Undo |

**Sequencing.** Nothing here jumps a milestone. The *only* piece worth pulling forward is the **Exclude**
menu, because its engine is done and it is already an M1 acceptance item that P6 didn't wire — a small,
self-contained follow-up. Everything else lands with the milestone that builds its engine, and the menu simply
grows an item (greyed with a milestone tooltip until then, per the "no dead buttons" rule).

---

## 7. Mockups

| Artboard | Shows |
| --- | --- |
| `BrowseMenu.dc.html` → `png/BrowseMenu.png` | The Browse grid with the right-click context menu open over a card: Exclude Image · Exclude Folder · Add to Collection ▸ · Preview… |
| `Collect.dc.html` → `png/Collect.png` | The **Add to Collection** dialog: existing collections with counts + a *New collection…* inline field |
| `QuickApply.dc.html` → `png/QuickApply.png` | The **Preview** popup: the fitted preview, the resolution line, the five surface checkboxes (one greyed with a reason), and Apply |
| `Preview.dc.html` → `png/Preview.png` *(existing)* | The full five-surface Preview page the popup is a shortcut into |
| `Screens.dc.html` → `png/Screens.png` *(existing)* | The Screens page the Apply button lands on |

All artboards reuse the shared sidebar and the Lin Wallpapers tokens (surfaces `#1E2233/#252A3E/#2B3044`,
accent `#FFC700→#FFB500`, on-accent `#1A1400`, Ubuntu), and render with `./docs/mockups/render.py <name>`.
