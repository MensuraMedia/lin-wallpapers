"""Navigation manager (starter-template convention): page registry and routing state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class NavigationManager:
    """Owns the route table and switches the page stack. Knows nothing about GTK beyond the stack."""

    def __init__(self) -> None:
        self.pages: dict[str, Any] = {}
        self.current_page: str | None = None
        self.page_stack: Any = None
        self.callbacks: list[Callable[[str], None]] = []

    def register_page(self, page_id: str, page_widget: Any) -> None:
        self.pages[page_id] = page_widget

    def set_page_stack(self, stack: Any) -> None:
        self.page_stack = stack

    def navigate_to(self, page_id: str) -> bool:
        if page_id not in self.pages or self.page_stack is None:
            return False
        self.current_page = page_id
        self.page_stack.set_visible_child_name(page_id)
        for callback in self.callbacks:
            callback(page_id)
        return True

    def on_navigate(self, callback: Callable[[str], None]) -> None:
        self.callbacks.append(callback)

    def get_current_page(self) -> str | None:
        return self.current_page

    def get_page_widget(self, page_id: str) -> Any:
        return self.pages.get(page_id)
