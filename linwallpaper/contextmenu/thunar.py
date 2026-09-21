"""Thunar (Xfce) — a custom action merged into ``~/.config/Thunar/uca.xml``.

Thunar stores custom actions in one XML file. We add (or replace) a single
``<action>`` identified by a stable ``unique-id`` and leave any others intact.
Thunar reads this file at startup, so a new action may need a Thunar restart.
"""

from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import APP_ID
from .base import ACTION_COMMENT, ACTION_LABEL, ContextMenuProvider

_UID = "linwallpaper-add"


def _uca_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "Thunar" / "uca.xml"


class ThunarProvider(ContextMenuProvider):
    binary = "thunar"
    name = "Thunar (Xfce)"
    desktop_hints = ("xfce",)

    @property
    def _file(self) -> Path:
        return _uca_path()

    def _load_root(self) -> ET.Element:
        try:
            return ET.parse(self._file).getroot()
        except (OSError, ET.ParseError):
            return ET.Element("actions")

    def is_installed(self) -> bool:
        root = self._load_root()
        return any(a.findtext("unique-id") == _UID for a in root.findall("action"))

    def install(self, exec_cmd: str | None = None) -> None:
        root = self._load_root()
        for a in list(root.findall("action")):
            if a.findtext("unique-id") == _UID:
                root.remove(a)
        action = ET.SubElement(root, "action")
        fields = {
            "icon": APP_ID,
            "name": ACTION_LABEL,
            "unique-id": _UID,
            "command": f"{self._exec(exec_cmd)} %F",
            "description": ACTION_COMMENT,
            "patterns": "*",
        }
        for tag, value in fields.items():
            ET.SubElement(action, tag).text = value
        # Offer on image files and on directories.
        ET.SubElement(action, "image-files")
        ET.SubElement(action, "directories")
        self._write_xml(root)

    def uninstall(self) -> None:
        root = self._load_root()
        removed = False
        for a in list(root.findall("action")):
            if a.findtext("unique-id") == _UID:
                root.remove(a)
                removed = True
        if removed:
            self._write_xml(root)

    def _write_xml(self, root: ET.Element) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = ET.tostring(root, encoding="unicode")
        tmp = self._file.with_name(self._file.name + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self._file)
