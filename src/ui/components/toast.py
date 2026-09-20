"""A small undo toast for the Browse page (M1.7: "every exclusion offers Undo in a toast").

A ``Gtk.Revealer`` holding a one-line message and an **Undo** button. The page shows it after an
exclude; its Undo calls back, and it dismisses itself after a few seconds. Pure GTK-through-``compat``;
it knows nothing of view models. Nothing runs in the background — the auto-dismiss is a single
one-shot ``GLib`` timeout that is cancelled if the toast is replaced or undone first.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import GLib, Gtk
from src.ui import compat

_DISMISS_MS = 6000


class Toast(Gtk.Revealer):  # type: ignore[misc]
    """One reusable undo toast; ``show_message`` swaps its text and Undo handler."""

    def __init__(self) -> None:
        super().__init__()
        self.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_reveal_child(False)

        self._on_undo: Callable[[], None] | None = None
        self._timeout: int = 0

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.MEDIUM)
        compat.add_class(row, "toast")
        self._label = Gtk.Label(label="")
        self._label.set_xalign(0)
        compat.add_class(self._label, "toast-message")
        compat.append(row, self._label, expand=True)

        self._undo = Gtk.Button(label="Undo")
        compat.add_class(self._undo, "flat", "toast-undo")
        self._undo.connect("clicked", self._undo_clicked)
        compat.append(row, self._undo)

        compat.set_child(self, row)
        # No armed auto-dismiss may fire on a torn-down widget (the no-daemon rule): drop the pending
        # timeout when the toast is unrealized (window close, page teardown). ``unrealize`` exists on
        # both GTK 3 and GTK 4; ``show_message`` re-arms it if the toast is shown again.
        self.connect("unrealize", self._on_unrealize)

    def show_message(self, text: str, on_undo: Callable[[], None]) -> None:
        self._cancel_timeout()
        self._on_undo = on_undo
        self._label.set_text(text)
        self.set_reveal_child(True)
        compat.show(self)
        self._timeout = GLib.timeout_add(_DISMISS_MS, self._auto_dismiss)

    def dismiss(self) -> None:
        self._cancel_timeout()
        self._on_undo = None
        self.set_reveal_child(False)

    def _undo_clicked(self, _button: Any) -> None:
        handler = self._on_undo
        self.dismiss()
        if handler is not None:
            handler()

    def _auto_dismiss(self) -> bool:
        self._timeout = 0
        self.dismiss()
        return False

    def _on_unrealize(self, _widget: Any) -> None:
        self._cancel_timeout()

    def _cancel_timeout(self) -> None:
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
