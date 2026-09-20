"""The ONE place the GTK version is chosen (TECHNICAL-CONCEPT §18).

Every module that needs GTK imports it from here, never from ``gi.repository`` after its own
``gi.require_version`` call. ``LWP_GTK=4.0`` selects GTK 4; the app is not expected to *run* on
GTK 4 until M8 — until then this only proves the gate is the single point of choice.
"""

import os

import gi

GTK_VERSION = os.environ.get("LWP_GTK", "3.0")
if GTK_VERSION not in ("3.0", "4.0"):
    raise RuntimeError(f"LWP_GTK must be 3.0 or 4.0, not {GTK_VERSION!r}")

gi.require_version("Gtk", GTK_VERSION)
gi.require_version("Gdk", GTK_VERSION)

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

IS_GTK4 = GTK_VERSION == "4.0"

__all__ = ["GTK_VERSION", "IS_GTK4", "GLib", "GObject", "Gdk", "Gio", "Gtk", "Pango"]
