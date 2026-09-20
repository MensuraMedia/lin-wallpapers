"""The exclusions editor on the Sources page (M1 §2.9).

Renders the built-in exclusion groups with an enable toggle each (locked groups are shown but not
editable) and the user's own rules with a remove button. It is fed the ``SourcesSnapshot`` DTOs and
plain callbacks; no catalogue type crosses the boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from src.config.config_layout import Layout
from src.gtk_version import Gtk
from src.ui import compat


class ExclusionsPanel(Gtk.Box):  # type: ignore[misc]
    """Group toggles and user-rule rows; call :meth:`update` with the snapshot's groups and rules."""

    def __init__(
        self,
        *,
        on_group_toggle: Callable[[str, bool], None],
        on_rule_remove: Callable[[int], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.SMALL)
        compat.add_class(self, "card", "exclusions")
        self._on_group_toggle = on_group_toggle
        self._on_rule_remove = on_rule_remove

        eyebrow = Gtk.Label()
        compat.set_tracked_text(eyebrow, "EXCLUSIONS")
        eyebrow.set_xalign(0)
        compat.add_class(eyebrow, "eyebrow")
        compat.append(self, eyebrow)

        self._groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        compat.append(self, self._groups_box)
        self._rules_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=Layout.spacing.XSMALL)
        compat.append(self, self._rules_box)

    def update(self, groups: Sequence[Any], rules: Sequence[Any]) -> None:
        compat.clear_children(self._groups_box)
        for group in groups:
            compat.append(self._groups_box, self._group_row(group))

        compat.clear_children(self._rules_box)
        user_rules = [rule for rule in rules if rule.group_id is None]
        if user_rules:
            heading = Gtk.Label(label="Your rules")
            heading.set_xalign(0)
            compat.add_class(heading, "dim")
            compat.append(self._rules_box, heading)
        for rule in user_rules:
            compat.append(self._rules_box, self._rule_row(rule))
        compat.show(self)

    def _group_row(self, group: Any) -> Any:
        check = Gtk.CheckButton(label=group.name)
        check.set_active(group.enabled)
        if group.locked:
            check.set_sensitive(False)
            check.set_tooltip_text("Always on — this group protects the system.")
        else:
            check.connect("toggled", self._group_check_toggled, group.key)
        return check

    def _group_check_toggled(self, button: Any, key: str) -> None:
        self._on_group_toggle(key, button.get_active())

    def _rule_row(self, rule: Any) -> Any:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=Layout.spacing.SMALL)
        label = Gtk.Label(label=rule.value)
        label.set_xalign(0)
        label.set_hexpand(True)
        compat.append(row, label, expand=True)
        remove = Gtk.Button(label="Remove")
        compat.add_class(remove, "pill")
        remove.connect("clicked", lambda _button, rule_id=rule.id: self._on_rule_remove(rule_id))
        compat.append(row, remove)
        return row
