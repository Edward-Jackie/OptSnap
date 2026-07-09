"""Action logic: move, resize, alpha manipulation."""

import logging
import platform
import time
from optsnap import window as win
from optsnap.config import ALPHA_STEP, ALPHA_MIN, ALPHA_MAX, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT

logger = logging.getLogger(__name__)

_MACOS_MAJOR = int(platform.mac_ver()[0].split('.')[0])

# ── Alpha state ───────────────────────────────────────────────────────────

_alpha_cache = {}  # window_id → user-facing opacity (1.0 = fully visible)


# ── Move Action ───────────────────────────────────────────────────────────

class MoveAction:
    """Track mouse drag delta and reposition window."""

    def __init__(self, window_id, ax_ref, start_mouse_x, start_mouse_y, bounds=None):
        self.window_id = window_id
        self.ax_ref = ax_ref
        self.start_mouse_x = start_mouse_x
        self.start_mouse_y = start_mouse_y

        # Use pre-fetched bounds if available (zero extra queries)
        if bounds:
            self.start_win_x = bounds['x']
            self.start_win_y = bounds['y']
        else:
            pos = win.get_window_position(window_id)
            if pos:
                self.start_win_x = pos[0]
                self.start_win_y = pos[1]
            else:
                self.start_win_x = 0
                self.start_win_y = 0

    def update(self, current_mouse_x, current_mouse_y):
        """Apply delta from initial click position."""
        dx = current_mouse_x - self.start_mouse_x
        dy = current_mouse_y - self.start_mouse_y

        new_x = self.start_win_x + dx
        new_y = self.start_win_y + dy

        win.set_window_position(self.ax_ref, new_x, new_y)


# ── Resize Action ─────────────────────────────────────────────────────────

# Throttle: only call AX API every N ms to avoid lag
RESIZE_THROTTLE_MS = 16  # ~60fps


class ResizeAction:
    """Simple resize: right-click drag adjusts width/height from bottom-right."""

    def __init__(self, window_id, ax_ref, start_mouse_x, start_mouse_y, bounds=None):
        self.window_id = window_id
        self.ax_ref = ax_ref
        self.start_mouse_x = start_mouse_x
        self.start_mouse_y = start_mouse_y

        # Use pre-fetched bounds if available (zero extra queries)
        if bounds:
            self.start_win_x = bounds['x']
            self.start_win_y = bounds['y']
            self.start_win_w = bounds['w']
            self.start_win_h = bounds['h']
        else:
            pos = win.get_window_position(window_id)
            size = win.get_window_size(window_id)
            if pos and size:
                self.start_win_x = pos[0]
                self.start_win_y = pos[1]
                self.start_win_w = size[0]
                self.start_win_h = size[1]
            else:
                self.start_win_x = self.start_win_y = 0
                self.start_win_w = self.start_win_h = 100

        self._last_update = 0  # Ensure first update always fires

    def update(self, current_mouse_x, current_mouse_y):
        """Resize window: width += dx, height += dy."""
        # Throttle to avoid spamming AX API
        now = time.time()
        if (now - self._last_update) * 1000 < RESIZE_THROTTLE_MS:
            return
        self._last_update = now

        dx = current_mouse_x - self.start_mouse_x
        dy = current_mouse_y - self.start_mouse_y

        new_w = max(MIN_WINDOW_WIDTH, self.start_win_w + dx)
        new_h = max(MIN_WINDOW_HEIGHT, self.start_win_h + dy)

        win.set_window_size(self.ax_ref, new_w, new_h)


# ── Alpha Action ──────────────────────────────────────────────────────────

def adjust_alpha(window_id, scroll_delta, bounds=None):
    """Adjust window transparency by scroll delta.
    
    On macOS 15+: uses NSPanel overlay dimming (bounds required).
    On older macOS: uses SkyLight SLSSetWindowAlpha.
    
    scroll_delta > 0 (finger up)  → more opaque
    scroll_delta < 0 (finger down) → more transparent
    """
    global _alpha_cache

    if _MACOS_MAJOR >= 15:
        # ── Overlay dimming mode ──────────────────────────────────────────
        if bounds is None:
            logger.warning(f"Alpha adjustment skipped: no bounds for window {window_id}")
            return  # Can't create overlay without position info
        current_opacity = _alpha_cache.get(window_id, 1.0)
        delta = ALPHA_STEP if scroll_delta > 0 else -ALPHA_STEP
        new_opacity = max(ALPHA_MIN, min(ALPHA_MAX, current_opacity + delta))
        # overlay_dim = 1.0 - opacity, capped at 0.8 to avoid fully blocking
        overlay_dim = min(0.8, 1.0 - new_opacity)
        from optsnap.overlay import set_overlay_dim
        set_overlay_dim(window_id, overlay_dim, bounds)
        _alpha_cache[window_id] = new_opacity
        logger.info(f"Overlay dim: window={window_id}, opacity {current_opacity:.2f} → {new_opacity:.2f}")
        return new_opacity
    else:
        # ── SkyLight mode (macOS 12-14) ───────────────────────────────────
        if window_id not in _alpha_cache:
            current = win.get_window_alpha(window_id)
            _alpha_cache[window_id] = current if current is not None else 1.0
        current = _alpha_cache[window_id]
        delta = ALPHA_STEP if scroll_delta > 0 else -ALPHA_STEP
        new_alpha = max(ALPHA_MIN, min(ALPHA_MAX, current + delta))
        win.set_window_alpha(window_id, new_alpha)
        _alpha_cache[window_id] = new_alpha
        logger.info(f"Alpha: window={window_id}, {current:.2f} → {new_alpha:.2f}")
        return new_alpha


def reset_all_alpha():
    """Restore all windows to fully opaque / remove all overlays."""
    global _alpha_cache
    if _MACOS_MAJOR >= 15:
        from optsnap.overlay import remove_all_overlays
        remove_all_overlays()
    else:
        for window_id, alpha in _alpha_cache.items():
            if alpha < 1.0:
                win.set_window_alpha(window_id, 1.0)
        logger.info("All window alpha restored to 1.0")
    _alpha_cache.clear()
