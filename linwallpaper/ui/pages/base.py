"""BasePage — starter convention: subclasses implement build_content()/refresh()."""

from __future__ import annotations

from gi.repository import Gtk


class BasePage(Gtk.Box):
    #: sidebar route this page answers to
    route = ""
    title = ""
    subtitle = ""

    def __init__(self, state, win) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.add_css_class("lw-main")
        self.state = state
        self.win = win
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h1 = Gtk.Label(label=self.title, xalign=0.0)
        h1.add_css_class("lw-h1")
        header.append(h1)
        if self.subtitle:
            sub = Gtk.Label(label=self.subtitle, xalign=0.0)
            sub.add_css_class("lw-sub")
            sub.set_wrap(True)
            self._subtitle_label = sub
            header.append(sub)
        self.append(header)
        content = self.build_content()
        if content is not None:
            self.append(content)
        state.subscribe(self.refresh)

    def build_content(self) -> Gtk.Widget | None:  # pragma: no cover - UI
        raise NotImplementedError

    def refresh(self) -> None:  # pragma: no cover - UI
        pass
