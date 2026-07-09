"""OptSnap configuration — edit these values to customize behavior."""

# ── Toggle hotkey ─────────────────────────────────────────────────────────
# Keycode that toggles OptSnap on/off globally.
TOGGLE_KEYCODE = 100  # F8 (default)

# ── Modifier key ──────────────────────────────────────────────────────────
MODIFIER_NAME = "alternate"  # one of: alternate, control, command

# ── Transparency ──────────────────────────────────────────────────────────
ALPHA_STEP = 0.05   # Alpha change per scroll tick
ALPHA_MIN = 0.1     # Minimum alpha (0.0 = fully transparent)
ALPHA_MAX = 1.0     # Maximum alpha (fully opaque)

# ── Window limits ─────────────────────────────────────────────────────────
MIN_WINDOW_WIDTH = 100
MIN_WINDOW_HEIGHT = 50

# ── Event Tap ─────────────────────────────────────────────────────────────
HEALTH_CHECK_INTERVAL = 2.0   # seconds between tap health checks

# ── Named constants for GUI ───────────────────────────────────────────────
MODIFIER_NAMES = {
    "alternate": "Option",
    "control": "Ctrl",
    "command": "Cmd",
}

TOGGLE_KEYCODES = [100, 122, 120, 99, 107, 113, 114]
TOGGLE_KEY_NAMES = {100: "F8", 122: "F1", 120: "F2", 99: "F5", 107: "Scroll Lock", 113: "Pause", 114: "Insert"}

# Reverse maps
MODIFIER_TO_NAME = {v: k for k, v in MODIFIER_NAMES.items()}  # not used, keep for completeness
TOGGLE_KEYCODE_TO_NAME = TOGGLE_KEY_NAMES
