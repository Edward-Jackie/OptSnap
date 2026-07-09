"""OptSnap GUI — macOS menu bar app using rumps."""

import logging
import threading

import rumps

from optsnap.config import TOGGLE_KEYCODE, MODIFIER_NAME
from optsnap.config import (
    MODIFIER_NAMES,
    TOGGLE_KEY_NAMES,
    TOGGLE_KEYCODES,
    MODIFIER_TO_NAME,
    TOGGLE_KEYCODE_TO_NAME,
)

logger = logging.getLogger(__name__)

# Map between names and keycodes (shared with config)
_MODIFIER_MAP = {
    "alternate": "Option",
    "control": "Ctrl",
    "command": "Cmd",
}

_TOGGLE_KEY_MAP = {
    99: "F5", 100: "F8", 107: "Scroll Lock",
    113: "Pause", 114: "Insert", 120: "F2", 122: "F1",
}


class OptSnapMenuApp(rumps.App):
    """Menu bar app for OptSnap."""

    def __init__(self, optsnap_core):
        """Initialize the menu bar app.

        Args:
            optsnap_core: OptSnapCore instance for controlling the engine.
        """
        super().__init__(
            name="OptSnap",
            title="⌘",
            icon=None,
            quit_button="退出",
        )
        self.core = optsnap_core
        self._update_menu()

    def _update_menu(self):
        """Rebuild menu items based on current state."""
        enabled = self.core.enabled
        modifier_name = MODIFIER_TO_NAME.get(self.core.modifier_mask, "Option")
        toggle_name = TOGGLE_KEYCODE_TO_NAME.get(self.core.toggle_keycode, "F8")

        status_text = "✓ 已启用" if enabled else "✗ 已禁用"

        self.menu = [
            rumps.MenuItem(status_text),
            rumps.separator(),
            rumps.MenuItem(
                "切换启用/禁用",
                callback=self._toggle,
            ),
            rumps.MenuItem(
                f"修饰键: {modifier_name}",
                callback=self._cycle_modifier,
            ),
            rumps.MenuItem(
                f"激活键: {toggle_name}",
                callback=self._cycle_toggle_key,
            ),
            rumps.separator(),
        ]

    def _toggle(self, sender):
        """Toggle OptSnap on/off."""
        self.core.toggle()
        self._update_menu()

    def _cycle_modifier(self, sender):
        """Cycle through modifier keys: Option → Ctrl → Cmd → Option."""
        self.core.cycle_modifier()
        self._update_menu()

    def _cycle_toggle_key(self, sender):
        """Cycle through toggle keys."""
        self.core.cycle_toggle_key()
        self._update_menu()
