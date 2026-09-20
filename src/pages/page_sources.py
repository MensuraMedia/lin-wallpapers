"""Sources page (M1 §2.9, acceptance #1): propose roots, scan on the user's word, edit exclusions.

The entry point for scanning. On first run it lists the *real* proposed roots from ``SourcesVM`` — the
user's Pictures folder among them — each with a toggle, and a prominent Scan button; nothing is scanned
until that button is pressed. While a scan runs the banner fills live. The page binds to the injected
view models only; no catalogue or scanner type is ever imported here (import-linter enforces it).
"""

from __future__ import annotations

from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat
from src.ui.components.displays_strip import DisplaysStrip
from src.ui.components.exclusions_panel import ExclusionsPanel
from src.ui.components.scan_banner import ScanBanner

from .page_base import BasePage


class SourcesPage(BasePage):
    route = "sources"
    title = "Sources"
    wants_context = True

    def __init__(self, context: Any = None) -> None:
        self.context = context
        super().__init__()

    def build_content(self) -> None:
        self.add_title(self.title)
        self.add_subtitle("Where wallpapers come from. Choose folders, then scan.")

        self._sources: Any = getattr(self.context, "sources_vm", None)
        self._scan: Any = getattr(self.context, "scan_vm", None)
        if self._sources is None or self._scan is None:
            self.add_paragraph("Sources are unavailable — the catalogue could not be opened.")
            return

        self._chosen: dict[str, bool] = {}

        self._banner = ScanBanner(on_cancel=self._scan.cancel)
        compat.append(self, self._banner)

        self._hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.SMALL)
        compat.add_class(self._hero, "card", "hero")
        compat.append(self, self._hero)

        self._displays = DisplaysStrip()
        compat.append(self, self._displays)

        self._exclusions = ExclusionsPanel(
            on_group_toggle=self._group_toggled, on_rule_remove=self._rule_removed
        )
        compat.append(self, self._exclusions)

        self._scan.add_observer(self._on_scan)
        self._sources.add_observer(self._on_snapshot)
        self._banner.update(self._scan.state)
        self._sources.refresh()

    # -- view-model observers ---------------------------------------------------------------------------

    def _on_snapshot(self, snapshot: Any) -> None:
        self._build_hero(snapshot)
        self._displays.update(snapshot.displays)
        self._exclusions.update(snapshot.groups, snapshot.rules)

    def _on_scan(self, state: Any) -> None:
        self._banner.update(state)
        if not state.running and state.result == "ok":
            self._sources.refresh()

    # -- the "Find wallpapers" hero ---------------------------------------------------------------------

    def _build_hero(self, snapshot: Any) -> None:
        compat.clear_children(self._hero)
        enabled_roots = [root for root in snapshot.roots if root.enabled]
        title = "Find wallpapers" if not enabled_roots else "Scan for wallpapers"
        heading = Gtk.Label(label=title)
        heading.set_xalign(0)
        compat.add_class(heading, "hero-title")
        compat.append(self._hero, heading)

        intro = Gtk.Label(
            label="Turn on the folders to search, then press Scan. Nothing is read until you do."
        )
        intro.set_xalign(0)
        compat.set_wrap(intro)
        compat.add_class(intro, "dim")
        compat.append(self._hero, intro)

        for root in snapshot.roots:
            compat.append(self._hero, self._root_row(root, stored=True))
        for proposal in snapshot.proposals:
            compat.append(self._hero, self._root_row(proposal, stored=False))
        if not snapshot.roots and not snapshot.proposals:
            empty = Gtk.Label(label="No picture folders were found to propose. Add one from Settings.")
            empty.set_xalign(0)
            compat.set_wrap(empty)
            compat.add_class(empty, "dim")
            compat.append(self._hero, empty)

        scan_button = Gtk.Button(label="Scan")
        compat.add_class(scan_button, "pill", "primary")
        scan_button.set_halign(Gtk.Align.START)
        scan_button.connect("clicked", self._scan_clicked)
        compat.append(self._hero, scan_button)
        compat.show(self._hero)

    def _root_row(self, root: Any, *, stored: bool) -> Any:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        active = root.enabled if stored else self._chosen.get(root.path, root.default_on)
        check = Gtk.CheckButton()
        check.set_active(active)
        if stored:
            check.connect("toggled", self._stored_root_toggled, root.id)
        else:
            check.connect("toggled", self._proposed_root_toggled, root.path)
        compat.append(row, check)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        path = Gtk.Label(label=root.path)
        path.set_xalign(0)
        compat.append(text, path)
        note = root.reason or (root.kind if stored else f"suggested · {root.kind}")
        if note:
            sub = Gtk.Label(label=note)
            sub.set_xalign(0)
            compat.add_class(sub, "dim")
            compat.append(text, sub)
        compat.append(row, text, expand=True)
        return row

    # -- actions ----------------------------------------------------------------------------------------

    def _scan_clicked(self, _button: Any) -> None:
        snapshot = self._sources.state
        pending = []
        if snapshot is not None:
            pending = [
                proposal.path
                for proposal in snapshot.proposals
                if self._chosen.get(proposal.path, proposal.default_on)
            ]
        self._add_then_scan(pending)

    def _add_then_scan(self, paths: list[str]) -> None:
        if not paths:
            self._scan.start()
            return
        head, *rest = paths
        self._sources.add_root(head, cb=lambda _snapshot: self._add_then_scan(rest))

    def _stored_root_toggled(self, button: Any, root_id: int) -> None:
        self._sources.set_root_enabled(root_id, button.get_active())

    def _proposed_root_toggled(self, button: Any, path: str) -> None:
        self._chosen[path] = button.get_active()

    def _group_toggled(self, key: str, on: bool) -> None:
        self._sources.set_group_enabled(key, on)

    def _rule_removed(self, rule_id: int) -> None:
        self._sources.remove_rule(rule_id)
