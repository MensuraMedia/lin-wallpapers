"""Screens page — an honest card per SURFACE, each with a simulated monitor.

Surfaces (the concept's five, §4):
  * Desktop      — one card per physical monitor, live and correct.
  * Lock screen  — mirrors the primary desktop ("Follows the desktop" on Cinnamon).
  * Login screen — placeholder + reason; needs the privileged apply engine.
  * Boot splash  — placeholder + reason; needs the privileged apply engine.
  * Boot menu    — placeholder + reason; needs the privileged apply engine.

The cards may stretch with the window; the :class:`MonitorFrame` inside each never
distorts its image (that is the whole point).
"""

from __future__ import annotations

from gi.repository import Gtk

from ... import imaging
from ..monitor_frame import MonitorFrame
from .base import BasePage

# The single reason shown on every surface the privileged engine owns.
_PRIV_REASON = "Not set by LinWallpaper — needs the privileged apply engine"

# The privileged (root-owned) surfaces, in concept order.
_PRIVILEGED = (
    ("Login screen", "LightDM / greeter background"),
    ("Boot splash", "Plymouth theme"),
    ("Boot menu", "GRUB background"),
)


class ScreensPage(BasePage):
    route = "screens"
    title = "Screens"
    subtitle = "Every surface a wallpaper can live on, and what it shows right now."

    def build_content(self) -> Gtk.Widget:
        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(3)
        self.flow.set_min_children_per_line(1)
        self.flow.set_column_spacing(18)
        self.flow.set_row_spacing(18)
        self.flow.set_homogeneous(False)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._rebuild()
        return self.flow

    # ---- build ------------------------------------------------------------
    def _rebuild(self) -> None:
        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()

        current = self._current_desktop_path()

        # Desktop: one card per physical monitor (live).
        for mon in self.state.monitors:
            self.flow.append(self._desktop_card(mon, current))

        # Lock screen: mirrors the primary desktop image.
        self.flow.append(self._lock_card(current))

        # Login / boot surfaces: placeholder + reason, disabled action.
        for name, owner in _PRIVILEGED:
            self.flow.append(self._privileged_card(name, owner))

    def _desktop_card(self, mon, current: str | None) -> Gtk.Widget:
        ratio = self._aspect(mon)
        applied = self._is_applied(mon.name)

        frame = MonitorFrame(ratio=ratio)
        if applied and self.state.image_path:
            self._render(frame, self.state.image_path, ratio)
        elif current:
            self._render(frame, current, ratio)
        else:
            frame.set_placeholder("No wallpaper set")

        badges = []
        if mon.primary:
            badges.append(("PRIMARY", "lw-badge"))
        if applied:
            badges.append(("● APPLIED", "lw-badge-good"))

        set_btn = Gtk.Button(label="Set here")
        set_btn.add_css_class("lw-ghost")
        can_set = bool(self.state.image_path and self.state.backend)
        set_btn.set_sensitive(can_set)
        if not can_set:
            set_btn.set_tooltip_text("Open an image on the Wallpaper page first")
        set_btn.connect("clicked", self._on_set_here, mon.name)

        meta = f"Desktop · {mon.px_width} × {mon.px_height} · scale {mon.scale}×"
        return self._card(f"Desktop — {mon.name}", meta, frame, badges, set_btn)

    def _lock_card(self, current: str | None) -> Gtk.Widget:
        primary = self._primary_monitor()
        ratio = self._aspect(primary) if primary else 16 / 9
        frame = MonitorFrame(ratio=ratio)
        if current:
            self._render(frame, current, ratio)
        else:
            frame.set_placeholder("No wallpaper set")

        chip = self._reason_chip("Follows the desktop", ok=True)
        return self._card(
            "Lock screen",
            "Mirrors the primary desktop on Cinnamon",
            frame,
            badges=[],
            action=None,
            footer=chip,
        )

    def _privileged_card(self, name: str, owner: str) -> Gtk.Widget:
        primary = self._primary_monitor()
        ratio = self._aspect(primary) if primary else 16 / 9
        frame = MonitorFrame(ratio=ratio)
        frame.set_placeholder("Not shown\n(no preview yet)")

        set_btn = Gtk.Button(label="Set here")
        set_btn.add_css_class("lw-ghost")
        set_btn.set_sensitive(False)
        set_btn.set_tooltip_text(_PRIV_REASON)

        chip = self._reason_chip(_PRIV_REASON, ok=False)
        return self._card(name, owner, frame, badges=[], action=set_btn, footer=chip)

    # ---- card scaffold ----------------------------------------------------
    def _card(
        self,
        title: str,
        meta: str,
        frame: Gtk.Widget,
        badges,
        action,
        footer: Gtk.Widget | None = None,
    ) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("lw-screen-card")
        card.set_size_request(340, -1)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(16)
        body.set_margin_bottom(16)
        body.set_margin_start(16)
        body.set_margin_end(16)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=title, xalign=0.0)
        name.add_css_class("lw-card-title")
        head.append(name)
        for text, css in badges:
            b = Gtk.Label(label=text)
            b.add_css_class(css)
            b.set_valign(Gtk.Align.CENTER)
            head.append(b)
        body.append(head)

        sub = Gtk.Label(label=meta, xalign=0.0)
        sub.add_css_class("lw-sub")
        sub.set_wrap(True)
        body.append(sub)

        body.append(frame)

        if footer is not None:
            body.append(footer)

        if action is not None:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            row.append(spacer)
            row.append(action)
            body.append(row)

        card.append(body)
        return card

    def _reason_chip(self, text: str, ok: bool) -> Gtk.Widget:
        chip = Gtk.Label(label=text, xalign=0.0)
        chip.add_css_class("lw-reason")
        chip.add_css_class("ok" if ok else "warn")
        chip.set_wrap(True)
        return chip

    # ---- helpers ----------------------------------------------------------
    def _aspect(self, mon) -> float:
        if mon and mon.px_height:
            return mon.px_width / mon.px_height
        return 16 / 9

    def _primary_monitor(self):
        for mon in self.state.monitors:
            if mon.primary:
                return mon
        return self.state.monitors[0] if self.state.monitors else None

    def _render(self, frame: MonitorFrame, path: str, ratio: float) -> None:
        w = 480
        h = max(1, round(w / ratio))
        try:
            img = imaging.transform(path, (w, h), imaging.FIT_FILL)
            frame.set_image(img)
        except Exception:
            frame.set_placeholder("Preview unavailable")

    def _current_desktop_path(self) -> str | None:
        be = self.state.backend
        if be is None:
            return None
        try:
            cur = be.current()
        except Exception:
            return None
        uri_key = getattr(be, "uri_key", "picture-uri")
        raw = cur.get(uri_key, "")
        if not raw:
            return None
        try:
            from ...backends._gsettings import uri_to_path

            path = uri_to_path(raw) if not getattr(be, "uri_is_path", False) else raw
        except Exception:
            path = raw
        from pathlib import Path

        return path if path and Path(path).exists() else None

    def _is_applied(self, connector: str) -> bool:
        img = self.state.image_path
        if not img:
            return False
        applied = getattr(self.state, "applied", {})
        return applied.get(connector) == img or applied.get("all") == img

    # ---- events -----------------------------------------------------------
    def _on_set_here(self, _btn, connector: str) -> None:
        self.state.set_target(connector)
        self.win.apply(connector)
        self._rebuild()

    def refresh(self) -> None:
        self._rebuild()
