"""GTK glue: turn a Pillow image (the shared render) into a Gdk paintable."""

from __future__ import annotations

import io

from gi.repository import Gdk, GdkPixbuf, Gio, GLib


def pil_to_texture(img) -> Gdk.Texture:
    """Encode a Pillow image to PNG bytes and wrap as a Gdk.Texture."""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = GLib.Bytes.new(buf.getvalue())
    try:
        return Gdk.Texture.new_from_bytes(data)
    except Exception:
        stream = Gio.MemoryInputStream.new_from_bytes(data)
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
        return Gdk.Texture.new_for_pixbuf(pixbuf)


def texture_from_file(path: str) -> Gdk.Texture:
    return Gdk.Texture.new_from_filename(path)
