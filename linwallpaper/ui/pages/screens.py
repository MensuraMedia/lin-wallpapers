"""Screens page — one card per SURFACE with per-surface Fit + live preview + Apply.

Each surface card is two columns:
  * LEFT  — a control column: a Fit segmented control (Fill/Fit/Center/Stretch,
            per-surface state) and, at the bottom, an **Apply** button. For the
            root-owned surfaces a small "requires password" caption sits under it.
  * RIGHT — the simulated :class:`MonitorFrame`, showing the *selected image*
            (``state.image_path``) rendered at that surface's chosen fit. Changing
            the fit updates the sim monitor live. It never distorts (AspectFrame).

Surfaces (the concept's five, §4):
  * Desktop      — one card per physical monitor; Apply uses the desktop backend.
  * Lock screen  — mirrors the primary desktop; Apply uses the desktop backend.
  * Login screen — LightDM greeter; Apply needs root → password dialog.
  * Boot splash  — Plymouth theme; Apply needs root → password dialog.
  * Boot menu    — GRUB background; Apply needs root → password dialog.
"""

from __future__ import annotations

from pathlib import Path

from gi.repository import Gtk

from ... import imaging
from ..monitor_frame import MonitorFrame
from ..password_dialog import run_privileged
from .base import BasePage

# The privileged (root-owned) surfaces: (title, owner, helper surface id).
_PRIVILEGED = (
    ("Login screen", "LightDM / slick-greeter background", "login"),
    ("Boot splash", "Plymouth boot theme", "splash"),
    ("Boot menu", "GRUB menu background", "grub"),
)

_NO_IMAGE_HINT = "Open an image on the Wallpaper page first"


class ScreensPage(BasePage):
    route = "screens"
    title = "Screens"
    subtitle = "Every surface a wallpaper can live on — pick a fit, preview it, apply it."

    def build_content(self) -> Gtk.Widget:
        # Per-surface fit state, keyed by surface key (connector / lock / login…).
        self._fits: dict[str, str] = getattr(self, "_fits", {})
        # key -> (frame, ratio, image-path-getter) for live re-render on fit change.
        self._previews: dict[str, tuple] = {}

        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(2)
        self.flow.set_min_children_per_line(1)
        self.flow.set_column_spacing(18)
        self.flow.set_row_spacing(18)
        self.flow.set_homogeneous(False)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._rebuild()
        return self.flow

    # ---- build ------------------------------------------------------------
    def _rebuild(self) -> None:
        self._previews = {}
        child = self.flow.get_first_child()
        while child:
            self.flow.remove(child)
            child = self.flow.get_first_child()

        current = self._current_desktop_path()

        for mon in self.state.monitors:
            self.flow.append(self._desktop_card(mon, current))
        self.flow.append(self._lock_card(current))
        for name, owner, surface_id in _PRIVILEGED:
            self.flow.append(self._privileged_card(name, owner, surface_id))

    # ---- desktop + lock (no password) -------------------------------------
    def _desktop_card(self, mon, current: str | None):
        key = mon.name
        ratio = self._aspect(mon)
        applied = self._is_applied(mon.name)

        def image_for() -> str | None:
            return self.state.image_path or current

        badges = []
        if mon.primary:
            badges.append(("PRIMARY", "lw-badge"))
        if applied:
            badges.append(("● APPLIED", "lw-badge-good"))

        can_apply = bool(self.state.image_path and self.state.backend)
        meta = f"Desktop · {mon.px_width} × {mon.px_height} · scale {mon.scale}×"
        return self._surface_card(
            key=key,
            title=f"Desktop — {mon.name}",
            meta=meta,
            ratio=ratio,
            image_getter=image_for,
            badges=badges,
            can_apply=can_apply,
            apply_cb=lambda: self._apply_desktop(mon.name, mon.name),
            disabled_reason=None if can_apply else _NO_IMAGE_HINT,
        )

    def _lock_card(self, current: str | None):
        primary = self._primary_monitor()
        ratio = self._aspect(primary) if primary else 16 / 9

        def image_for() -> str | None:
            return self.state.image_path or current

        can_apply = bool(self.state.image_path and self.state.backend)
        return self._surface_card(
            key="lock",
            title="Lock screen",
            meta="Mirrors the primary desktop on Cinnamon",
            ratio=ratio,
            image_getter=image_for,
            badges=[],
            can_apply=can_apply,
            apply_cb=lambda: self._apply_desktop("lock", "all"),
            disabled_reason=None if can_apply else _NO_IMAGE_HINT,
        )

    # ---- privileged (root → password dialog) ------------------------------
    def _privileged_card(self, title: str, owner: str, surface_id: str):
        primary = self._primary_monitor()
        ratio = self._aspect(primary) if primary else 16 / 9

        def image_for() -> str | None:
            return self.state.image_path

        can_apply = bool(self.state.image_path)
        return self._surface_card(
            key=surface_id,
            title=title,
            meta=owner,
            ratio=ratio,
            image_getter=image_for,
            badges=[],
            can_apply=can_apply,
            apply_cb=lambda: self._apply_privileged(surface_id),
            disabled_reason=None if can_apply else _NO_IMAGE_HINT,
            requires_password=True,
        )

    # ---- card scaffold ----------------------------------------------------
    def _surface_card(
        self,
        *,
        key: str,
        title: str,
        meta: str,
        ratio: float,
        image_getter,
        badges,
        can_apply: bool,
        apply_cb,
        disabled_reason: str | None,
        requires_password: bool = False,
    ) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("lw-screen-card")
        card.set_size_request(460, -1)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        body.set_margin_top(16)
        body.set_margin_bottom(16)
        body.set_margin_start(16)
        body.set_margin_end(16)

        # LEFT: control column.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_hexpand(True)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=title, xalign=0.0)
        name.add_css_class("lw-card-title")
        head.append(name)
        for text, css in badges:
            b = Gtk.Label(label=text)
            b.add_css_class(css)
            b.set_valign(Gtk.Align.CENTER)
            head.append(b)
        left.append(head)

        sub = Gtk.Label(label=meta, xalign=0.0)
        sub.add_css_class("lw-sub")
        sub.set_wrap(True)
        left.append(sub)

        fit_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        fit_lbl = Gtk.Label(label="FIT")
        fit_lbl.add_css_class("lw-label")
        fit_lbl.set_valign(Gtk.Align.CENTER)
        fit_row.append(fit_lbl)
        fit_row.append(self._fit_control(key))
        left.append(fit_row)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        left.append(spacer)

        # Apply button + optional "requires password" caption.
        apply_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        apply_area.set_halign(Gtk.Align.END)
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("lw-primary")
        apply_btn.set_sensitive(can_apply)
        if not can_apply and disabled_reason:
            apply_btn.set_tooltip_text(disabled_reason)
        apply_btn.connect("clicked", lambda *_: apply_cb())
        apply_area.append(apply_btn)
        if requires_password:
            caption = Gtk.Label(label="requires password", xalign=1.0)
            caption.add_css_class("lw-caption")
            apply_area.append(caption)
        left.append(apply_area)

        body.append(left)

        # RIGHT: simulated monitor with the live preview.
        frame = MonitorFrame(ratio=ratio)
        frame.set_valign(Gtk.Align.CENTER)
        body.append(frame)

        self._previews[key] = (frame, ratio, image_getter)
        self._render_preview(key)

        card.append(body)
        return card

    def _fit_control(self, key: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("lw-seg")
        active = self._fits.get(key, imaging.FIT_FILL)
        first = None
        for fit in imaging.FITS:
            btn = Gtk.ToggleButton(label=imaging.FIT_LABELS[fit])
            btn.set_has_frame(False)
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.set_active(fit == active)
            btn.connect("toggled", self._on_fit, key, fit)
            box.append(btn)
        return box

    # ---- live preview -----------------------------------------------------
    def _render_preview(self, key: str) -> None:
        entry = self._previews.get(key)
        if entry is None:
            return
        frame, ratio, image_getter = entry
        path = image_getter()
        if not path:
            frame.set_placeholder("No image\n(open one on Wallpaper)")
            return
        fit = self._fits.get(key, imaging.FIT_FILL)
        w = 480
        h = max(1, round(w / ratio))
        try:
            img = imaging.transform(path, (w, h), fit)
            frame.set_image(img)
        except Exception:
            frame.set_placeholder("Preview unavailable")

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

    def _res(self) -> str:
        mon = self._primary_monitor()
        if mon:
            return f"{mon.px_width}x{mon.px_height}"
        return "1920x1080"

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
        return path if path and Path(path).exists() else None

    def _is_applied(self, connector: str) -> bool:
        img = self.state.image_path
        if not img:
            return False
        applied = getattr(self.state, "applied", {})
        return applied.get(connector) == img or applied.get("all") == img

    # ---- events -----------------------------------------------------------
    def _on_fit(self, btn, key: str, fit: str) -> None:
        if btn.get_active():
            self._fits[key] = fit
            self._render_preview(key)

    def _apply_desktop(self, fit_key: str, target: str) -> None:
        # Apply via the desktop backend at this surface's chosen fit (no password).
        self.state.fit = self._fits.get(fit_key, imaging.FIT_FILL)
        self.state.target = target
        self.win.apply(target)
        self._rebuild()

    def _apply_privileged(self, surface_id: str) -> None:
        if not self.state.image_path:
            self.win.toast(_NO_IMAGE_HINT)
            return
        fit = self._fits.get(surface_id, imaging.FIT_FILL)
        run_privileged(
            self.win,
            surface_id,
            self.state.image_path,
            fit,
            res=self._res(),
        )

    def refresh(self) -> None:
        self._rebuild()
