"""``GdkDisplayProbe`` — the one view model that reaches GTK (M1 §2.2, D2, ruling Q5).

It implements the :class:`~src.scanner.displays.DisplayProbe` protocol from live GDK monitors, so the GUI
probe chain is ``[GdkDisplayProbe(), *service_probes(...)]``. GTK is imported only from ``src.gtk_version``
(never ``gi`` directly), which is exactly the one edge the "view models are gi-free" import-linter contract
carves out. A monitor size is its geometry × integer ``scale_factor``; the name is the connector (GTK 4) or
model. ``probe()`` never raises — ``detect()`` treats an exception as a failed attempt — so any GDK quirk
degrades to an empty tuple. It also exposes ``connect_monitors_changed`` so a page can re-probe on hotplug.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.gtk_version import IS_GTK4, Gdk
from src.scanner.displays import Display, DisplaySource


class GdkDisplayProbe:
    """A :class:`DisplayProbe` backed by the current GDK display."""

    source = DisplaySource.GDK

    def __init__(self, display: Gdk.Display | None = None) -> None:
        self._display = display

    def probe(self) -> tuple[Display, ...]:
        display = self._display or Gdk.Display.get_default()
        if display is None:
            return ()
        return tuple(self._read(display))

    def connect_monitors_changed(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback`` whenever monitors are added/removed. Returns a disconnect handle."""
        display = self._display or Gdk.Display.get_default()
        if display is None:
            return lambda: None
        handles: list[tuple[Any, int]] = []
        if IS_GTK4:
            monitors = display.get_monitors()
            handles.append((monitors, monitors.connect("items-changed", lambda *_: callback())))
        else:
            for signal in ("monitor-added", "monitor-removed"):
                handles.append((display, display.connect(signal, lambda *_: callback())))

        def disconnect() -> None:
            for obj, handle in handles:
                obj.disconnect(handle)

        return disconnect

    # -- internals --------------------------------------------------------------------------------------

    def _read(self, display: Gdk.Display) -> list[Display]:
        out: list[Display] = []
        for index, monitor in enumerate(self._monitors(display)):
            found = self._to_display(monitor, index)
            if found is not None:
                out.append(found)
        return out

    def _monitors(self, display: Gdk.Display) -> list[object]:
        if IS_GTK4:
            model = display.get_monitors()
            return [model.get_item(i) for i in range(model.get_n_items())]
        return [display.get_monitor(i) for i in range(display.get_n_monitors())]

    def _to_display(self, monitor: object, index: int) -> Display | None:
        geometry = monitor.get_geometry()  # type: ignore[attr-defined]
        scale = monitor.get_scale_factor() or 1  # type: ignore[attr-defined]
        width = int(geometry.width * scale)
        height = int(geometry.height * scale)
        if width <= 0 or height <= 0:
            return None
        return Display(
            name=self._name(monitor, index),
            width=width,
            height=height,
            scale=float(scale),
            primary=self._primary(monitor),
            source=DisplaySource.GDK,
        )

    def _name(self, monitor: object, index: int) -> str:
        if IS_GTK4:
            connector = monitor.get_connector()  # type: ignore[attr-defined]
            if connector:
                return str(connector)
        model = monitor.get_model()  # type: ignore[attr-defined]
        if model:
            return str(model)
        return f"monitor-{index}"

    def _primary(self, monitor: object) -> bool:
        is_primary = getattr(monitor, "is_primary", None)  # GTK 4 monitors have no primary concept
        if is_primary is None:
            return False
        return bool(is_primary())
