"""OptSnap Core — encapsulated engine that can be controlled by GUI."""

import logging
import signal
import threading
import time

from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventGetType,
    CGEventGetLocation,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopAddTimer,
    CFRunLoopRemoveSource,
    CFRunLoopRemoveTimer,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    CFRunLoopTimerCreate,
    CFRunLoopTimerInvalidate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventLeftMouseDragged,
    kCGEventRightMouseDown,
    kCGEventRightMouseUp,
    kCGEventRightMouseDragged,
    kCGEventScrollWheel,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskCommand,
    kCGScrollWheelEventDeltaAxis1,
    kCGKeyboardEventKeycode,
    kCGEventTapDisabledByTimeout,
    kCFRunLoopDefaultMode,
    CGEventTapIsEnabled,
)

try:
    from Quartz import kCGEventTapDisabledByTCC
except ImportError:
    kCGEventTapDisabledByTCC = 14

from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)

from optsnap import window as win
from optsnap.config import TOGGLE_KEYCODE, MODIFIER_NAME, HEALTH_CHECK_INTERVAL
from optsnap.actions import MoveAction, ResizeAction, adjust_alpha, reset_all_alpha

logger = logging.getLogger(__name__)

_MODIFIERS = {
    "alternate": kCGEventFlagMaskAlternate,
    "control": kCGEventFlagMaskControl,
    "command": kCGEventFlagMaskCommand,
}

_MODIFIER_NAMES = {
    kCGEventFlagMaskAlternate: "Option",
    kCGEventFlagMaskControl: "Ctrl",
    kCGEventFlagMaskCommand: "Cmd",
}

_TOGGLE_KEYCODES = [100, 122, 120, 99, 107, 113, 114]  # F8, F1, F2, F5, Scroll Lock, Pause, Insert
_TOGGLE_KEY_NAMES = {100: "F8", 122: "F1", 120: "F2", 99: "F5", 107: "Scroll Lock", 113: "Pause", 114: "Insert"}


def _modifier_to_name(mask):
    return _MODIFIER_NAMES.get(mask, "Option")


def _toggle_keycode_to_name(keycode):
    return _TOGGLE_KEY_NAMES.get(keycode, f"Key {keycode}")


class OptSnapCore:
    """Encapsulated OptSnap engine.

    Can be controlled programmatically (toggle, change modifier, change toggle key).
    Runs the event loop in a separate thread so the GUI stays responsive.
    """

    def __init__(self, modifier_name=None, toggle_keycode=None, on_state_change=None):
        self.enabled = True
        self.modifier_mask = _MODIFIERS.get(modifier_name or MODIFIER_NAME, kCGEventFlagMaskAlternate)
        self.toggle_keycode = toggle_keycode or TOGGLE_KEYCODE
        self.on_state_change = on_state_change  # callback for GUI refresh

        self.mode = "idle"
        self.current_action = None

        self._event_tap = None
        self._event_tap_source = None
        self._health_timer = None
        self._tap_runloop = None  # store the runloop of the tap thread
        self._runloop_lock = threading.Lock()

        self.mode = "idle"
        self.current_action = None

        self._running = False
        self._thread = None

    # ── Public API for GUI ─────────────────────────────────────────────

    def toggle(self):
        self.enabled = not self.enabled
        state = "ENABLED" if self.enabled else "DISABLED"
        logger.info(f"[OptSnap] {state}")
        if not self.enabled:
            reset_all_alpha()
        # Always reset state machine to idle so re-enable starts clean
        self.mode = "idle"
        self.current_action = None
        if self.on_state_change:
            # Dispatch to main thread: on_state_change may do AppKit UI work.
            # Calling AppKit from the event tap thread can stall the callback
            # long enough for macOS to fire kCGEventTapDisabledByTimeout,
            # which kills the tap and prevents the next F8 press from being seen.
            try:
                import AppKit
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    self.on_state_change
                )
            except Exception:
                # Fallback if AppKit not available (headless/test mode)
                threading.Thread(target=self.on_state_change, daemon=True).start()

    def cycle_modifier(self):
        """Cycle: Option → Ctrl → Cmd → Option."""
        order = [kCGEventFlagMaskAlternate, kCGEventFlagMaskControl, kCGEventFlagMaskCommand]
        idx = order.index(self.modifier_mask)
        self.modifier_mask = order[(idx + 1) % len(order)]
        logger.info(f"Modifier changed to {_modifier_to_name(self.modifier_mask)}")
        if self.on_state_change:
            self.on_state_change()

    def cycle_toggle_key(self):
        """Cycle through configured toggle keycodes."""
        idx = _TOGGLE_KEYCODES.index(self.toggle_keycode)
        self.toggle_keycode = _TOGGLE_KEYCODES[(idx + 1) % len(_TOGGLE_KEYCODES)]
        logger.info(f"Toggle key changed to {_toggle_keycode_to_name(self.toggle_keycode)}")
        if self.on_state_change:
            self.on_state_change()

    # ── Permission check ──────────────────────────────────────────────

    @staticmethod
    def check_permissions():
        """Return (has_accessibility, has_input_monitoring)."""
        has_ax = AXIsProcessTrusted()
        test_tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
            (1 << kCGEventFlagsChanged), lambda *args: None, None,
        )
        has_input = test_tap is not None
        if test_tap:
            CFMachPortInvalidate(test_tap)
        return has_ax, has_input

    @staticmethod
    def request_accessibility():
        options = {kAXTrustedCheckOptionPrompt: True}
        AXIsProcessTrustedWithOptions(options)

    # ── Event tap callback ────────────────────────────────────────────

    def _event_callback(self, proxy, event_type, event, refcon):
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByTCC):
            logger.warning("Event tap disabled — recreating")
            self._recreate_tap()
            return event

        # Toggle key
        if event_type == kCGEventKeyDown:
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            if keycode == self.toggle_keycode:
                self.toggle()
                return None

        if not self.enabled:
            return event

        flags = CGEventGetFlags(event)
        modifier_held = bool(flags & self.modifier_mask)
        loc = CGEventGetLocation(event)
        raw_type = CGEventGetType(event)

        # IDLE → action start
        if self.mode == "idle" and modifier_held:
            if raw_type == kCGEventLeftMouseDown:
                window_id, ax_ref, bounds = win.get_window_at_point(loc.x, loc.y)
                if window_id is None:
                    return event
                self.current_action = MoveAction(window_id, ax_ref, loc.x, loc.y, bounds)
                self.mode = "moving"
                return None

            elif raw_type == kCGEventRightMouseDown:
                window_id, ax_ref, bounds = win.get_window_at_point(loc.x, loc.y)
                if window_id is None:
                    return event
                self.current_action = ResizeAction(window_id, ax_ref, loc.x, loc.y, bounds)
                self.mode = "resizing"
                return None

            elif raw_type == kCGEventScrollWheel:
                window_id, ax_ref, bounds = win.get_window_at_point(loc.x, loc.y)
                if window_id is None:
                    return event
                scroll_delta = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
                adjust_alpha(window_id, scroll_delta, bounds)
                return None

        # Moving
        if self.mode == "moving" and raw_type == kCGEventLeftMouseDragged:
            if self.current_action and modifier_held:
                self.current_action.update(loc.x, loc.y)
            elif not modifier_held:
                self.mode = "idle"
                self.current_action = None
            return None

        # Resizing
        if self.mode == "resizing" and raw_type == kCGEventRightMouseDragged:
            if self.current_action:
                self.current_action.update(loc.x, loc.y)
            return None

        # Alpha adjustment is handled in the idle + modifier branch above.
        # Each scroll wheel event is independent; no separate "alpha" mode is needed.

        # Mouse up → IDLE
        if raw_type in (kCGEventLeftMouseUp, kCGEventRightMouseUp):
            if self.mode != "idle":
                self.mode = "idle"
                self.current_action = None
            return event

        return event

    # ── Tap lifecycle ─────────────────────────────────────────────────

    def _build_event_mask(self):
        return (
            (1 << kCGEventLeftMouseDown) | (1 << kCGEventLeftMouseUp) | (1 << kCGEventLeftMouseDragged)
            | (1 << kCGEventRightMouseDown) | (1 << kCGEventRightMouseUp) | (1 << kCGEventRightMouseDragged)
            | (1 << kCGEventScrollWheel) | (1 << kCGEventFlagsChanged)
            | (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp)
        )

    def _recreate_tap(self):
        self._stop_tap()
        self._start_tap()

    def _health_check_callback(self, timer, info):
        if self._event_tap and not CGEventTapIsEnabled(self._event_tap):
            logger.warning("Health check: tap disabled, recreating")
            self._recreate_tap()

    def _start_tap(self):
        mask = self._build_event_mask()

        self._event_tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
            mask, self._event_callback, None,
        )

        if not self._event_tap:
            logger.error("Failed to create event tap")
            return False

        self._event_tap_source = CFMachPortCreateRunLoopSource(None, self._event_tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), self._event_tap_source, kCFRunLoopDefaultMode)
        CGEventTapEnable(self._event_tap, True)

        self._health_timer = CFRunLoopTimerCreate(
            None, time.time() + HEALTH_CHECK_INTERVAL, HEALTH_CHECK_INTERVAL,
            0, 0, self._health_check_callback, None,
        )
        CFRunLoopAddTimer(CFRunLoopGetCurrent(), self._health_timer, kCFRunLoopDefaultMode)

        # Store this thread's run loop so stop() can target it
        with self._runloop_lock:
            self._tap_runloop = CFRunLoopGetCurrent()

        return True

    def _stop_tap(self):
        if self._health_timer:
            CFRunLoopRemoveTimer(CFRunLoopGetCurrent(), self._health_timer, kCFRunLoopDefaultMode)
            CFRunLoopTimerInvalidate(self._health_timer)
            self._health_timer = None

        if self._event_tap_source:
            CFRunLoopRemoveSource(CFRunLoopGetCurrent(), self._event_tap_source, kCFRunLoopDefaultMode)
            self._event_tap_source = None

        if self._event_tap:
            from Quartz import CFMachPortInvalidate
            CFMachPortInvalidate(self._event_tap)
            self._event_tap = None

        reset_all_alpha()
        logger.info("OptSnap tap stopped")

    # ── Run / Stop ────────────────────────────────────────────────────

    def run(self):
        """Start the event loop in the current thread."""
        if not self._start_tap():
            return

        def _signal_handler(sig, frame):
            self.stop()

        # Only set signal handlers in main thread
        import threading
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)

        self._running = True
        try:
            CFRunLoopRun()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_tap()
            self._running = False

    def run_in_thread(self):
        """Start the event loop in a background thread."""
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the event loop from any thread."""
        self._running = False
        self._stop_tap()
        # Stop the run loop on the tap thread
        with self._runloop_lock:
            runloop = self._tap_runloop
        if runloop is not None:
            try:
                from Quartz import CFRunLoopStop
                CFRunLoopStop(runloop)
            except Exception:
                pass
