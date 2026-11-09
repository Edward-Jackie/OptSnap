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
    kCGEventFlagMaskShift,
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
from optsnap import pin
from optsnap.config import (
    TOGGLE_KEYCODE,
    MODIFIER_NAME,
    HEALTH_CHECK_INTERVAL,
    PIN_HOTKEY_KEYCODE,
    PIN_HOTKEY_MODIFIERS,
    PIN_HOTKEYS,
)
from optsnap.actions import MoveAction, ResizeAction, adjust_alpha, reset_all_alpha

logger = logging.getLogger(__name__)

_MODIFIERS = {
    "alternate": kCGEventFlagMaskAlternate,
    "control": kCGEventFlagMaskControl,
    "command": kCGEventFlagMaskCommand,
    "shift": kCGEventFlagMaskShift,
}

# 置顶热键可用的修饰键。和 _MODIFIERS 分开：_MODIFIERS 是「拖拽操作」的修饰键
# （一次只按一个），这里允许组合。
_PIN_MODIFIER_FLAGS = {
    "alternate": kCGEventFlagMaskAlternate,
    "control": kCGEventFlagMaskControl,
    "command": kCGEventFlagMaskCommand,
    "shift": kCGEventFlagMaskShift,
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


def _hotkey_to_name(keycode, modifiers):
    """把「键码 + 修饰键」转成可显示的文字，例如 ⌥⇧P。

    优先用 PIN_HOTKEYS 里的预置名；自定义组合则按修饰键顺序拼中文缩写。
    """
    for kc, mods, name in PIN_HOTKEYS:
        if kc == keycode and list(mods) == list(modifiers):
            return name

    parts = []
    for m in ("control", "alternate", "shift", "command"):
        if m in modifiers:
            parts.append({"control": "⌃", "alternate": "⌥", "shift": "⇧", "command": "⌘"}[m])
    # 字母键码 → 字母。只覆盖常用几个，其余退化成键码显示。
    letters = {35: "P", 36: "O", 17: "T", 15: "R", 0: "A", 1: "S", 2: "D", 3: "F"}
    parts.append(letters.get(keycode, f"Key{keycode}"))
    return "".join(parts)


class OptSnapCore:
    """Encapsulated OptSnap engine.

    Can be controlled programmatically (toggle, change modifier, change toggle key).
    Runs the event loop in a separate thread so the GUI stays responsive.
    """

    def __init__(self, modifier_name=None, toggle_keycode=None, on_state_change=None,
                 pin_hotkey=None):
        self.enabled = True
        self.modifier_mask = _MODIFIERS.get(modifier_name or MODIFIER_NAME, kCGEventFlagMaskAlternate)
        self.toggle_keycode = toggle_keycode or TOGGLE_KEYCODE

        # 置顶热键 = 字母键码 + 需要同时按住的修饰键集合。
        # 用组合键而不是单按功能键：功能键在「媒体键模式」下发出的是
        # NSSystemDefined 事件而非 keyDown，单键热键会收不到。
        kc, mods = pin_hotkey or (PIN_HOTKEY_KEYCODE, PIN_HOTKEY_MODIFIERS)
        self.pin_keycode = kc
        self.pin_modifiers = list(mods)
        self.pin_modifier_mask = 0
        for m in self.pin_modifiers:
            self.pin_modifier_mask |= _PIN_MODIFIER_FLAGS.get(m, 0)

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
        # shutdown() 的幂等标记：退出路径有多条（菜单、信号、atexit），
        # 每条都可能调一次 shutdown，必须保证清理只执行一遍
        self._shutting_down = False

    # ── Public API for GUI ─────────────────────────────────────────────

    def toggle(self):
        self.enabled = not self.enabled
        state = "ENABLED" if self.enabled else "DISABLED"
        logger.info(f"[OptSnap] {state}")
        if not self.enabled:
            reset_all_alpha()
            # 置顶状态也要清掉，否则禁用后窗口会永远卡在浮动层
            pin.reset_all_pins()
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

    def cycle_pin_key(self):
        """轮换置顶热键组合。"""
        current = (self.pin_keycode, tuple(self.pin_modifiers))
        options = [(kc, tuple(mods)) for kc, mods, _ in PIN_HOTKEYS]
        try:
            idx = options.index(current)
        except ValueError:
            idx = -1

        kc, mods = options[(idx + 1) % len(options)]
        self.pin_keycode = kc
        self.pin_modifiers = list(mods)
        self.pin_modifier_mask = 0
        for m in mods:
            self.pin_modifier_mask |= _PIN_MODIFIER_FLAGS.get(m, 0)

        logger.info(f"置顶热键改为 {_hotkey_to_name(kc, mods)}")
        if self.on_state_change:
            self.on_state_change()

    def toggle_pin_under_cursor(self):
        """切换鼠标指针下窗口的置顶状态。返回切换后的状态（None 表示失败）。

        读鼠标位置再命中窗口，而不是用当前焦点窗口：置顶的典型使用场景是
        「指着某个窗口把它钉住」，用指针位置更符合直觉，也避免切换焦点。

        命中顺序很重要：先查「已置顶的窗口」，再查普通窗口。因为置顶后窗口的
        layer 不再是 0，get_window_at_point 会跳过它 —— 不先查已置顶列表的话，
        第二次按快捷键会命中下层窗口，导致取消置顶永远失效。
        """
        from Quartz import CGEventCreate, CGEventGetLocation
        loc = CGEventGetLocation(CGEventCreate(None))

        # 1) 指针下若有已置顶窗口，直接取消它
        pinned_id = pin.pinned_window_at(loc.x, loc.y)
        if pinned_id is not None:
            pin.set_pinned(pinned_id, False)
            return False

        # 2) 否则找普通窗口并置顶
        window_id, _ax_ref, _bounds = win.get_window_at_point(loc.x, loc.y)
        if window_id is None:
            logger.debug("置顶：指针下没有可用窗口")
            return None
        return pin.toggle_pin(window_id)

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
            # 置顶热键：组合键，必须「所有要求的修饰键都按住，且没有多余的」。
            # 只判断 ≥ 会导致 ⌥⇧P 和 ⌥P 互相误触发；只判断 == 又会漏掉按住 CapsLock
            # 这类无关状态位的情况，所以按位掩码精确比对。
            if keycode == self.pin_keycode:
                flags = CGEventGetFlags(event)
                modifiers_now = flags & (
                    kCGEventFlagMaskAlternate | kCGEventFlagMaskControl
                    | kCGEventFlagMaskCommand | kCGEventFlagMaskShift
                )
                if modifiers_now == self.pin_modifier_mask:
                    # 置顶和「全局开关」是并列功能，禁用状态下也响应
                    logger.info(f"置顶热键命中（{_hotkey_to_name(self.pin_keycode, self.pin_modifiers)}）")
                    result = self.toggle_pin_under_cursor()
                    logger.info(f"置顶切换结果: {result}")
                    return None
                else:
                    # 键对了但修饰键不匹配 —— 用 debug 级别记录，首次排查热键时有用
                    logger.debug(
                        f"置顶键 {keycode} 按下，但修饰键不匹配: "
                        f"当前=0x{modifiers_now:x} 需要=0x{self.pin_modifier_mask:x}"
                    )

        if not self.enabled:
            return event

        flags = CGEventGetFlags(event)
        modifier_held = bool(flags & self.modifier_mask)
        loc = CGEventGetLocation(event)
        raw_type = CGEventGetType(event)

        # Any Down event while we're not idle means a previous action never got a
        # matching Up (tap timeout/recreate, or an Up event we somehow missed) —
        # without this, mode stays wedged and every future Down of that button
        # type is silently ignored below until something else happens to reset it.
        if self.mode != "idle" and raw_type in (kCGEventLeftMouseDown, kCGEventRightMouseDown):
            logger.debug(f"{raw_type} while mode={self.mode} (stale) — force-resetting to idle first")
            self.mode = "idle"
            self.current_action = None

        # IDLE → action start
        if self.mode == "idle" and modifier_held:
            if raw_type == kCGEventLeftMouseDown:
                window_id, ax_ref, bounds = win.get_window_at_point(loc.x, loc.y)
                if window_id is None:
                    logger.debug(f"LeftMouseDown+modifier at ({loc.x:.0f}, {loc.y:.0f}) but no window found — ignoring")
                    return event
                self.current_action = MoveAction(window_id, ax_ref, loc.x, loc.y, bounds)
                self.mode = "moving"
                logger.debug(f"mode -> moving (window={window_id})")
                return None

            elif raw_type == kCGEventRightMouseDown:
                window_id, ax_ref, bounds = win.get_window_at_point(loc.x, loc.y)
                if window_id is None:
                    logger.debug(f"RightMouseDown+modifier at ({loc.x:.0f}, {loc.y:.0f}) but no window found — ignoring")
                    return event
                self.current_action = ResizeAction(window_id, ax_ref, loc.x, loc.y, bounds)
                self.mode = "resizing"
                logger.debug(f"mode -> resizing (window={window_id})")
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
            if self.current_action and modifier_held:
                self.current_action.update(loc.x, loc.y)
            elif not modifier_held:
                self.mode = "idle"
                self.current_action = None
            return None

        # Alpha adjustment is handled in the idle + modifier branch above.
        # Each scroll wheel event is independent; no separate "alpha" mode is needed.

        # Mouse up → IDLE
        if raw_type in (kCGEventLeftMouseUp, kCGEventRightMouseUp):
            if self.mode != "idle":
                logger.debug(f"{raw_type} -> mode reset to idle (was {self.mode})")
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
        # 这里不调 pin.reset_all_pins()：置顶还原统一放在 shutdown() 里，
        # 因为它需要「通道还活着」才能生效，而 _stop_tap 之后通道命令仍可发，
        # 但顺序上先还原再停 tap 更稳妥。此处只做描边兜底清理。
        try:
            from optsnap import border
            border.remove_all_borders()
        except Exception as e:
            logger.debug(f"清除描边失败: {e}")
        logger.info("OptSnap tap stopped")

    # ── Run / Stop ────────────────────────────────────────────────────

    def run(self):
        """Start the event loop in the current thread."""
        if not self._start_tap():
            return

        # 信号处理器只在主线程注册（Python 限制），这里通常跑在后台线程，
        # 所以实际注册工作放在 __main__.py:main() 里做。此处保留仅为直接调用 run()
        # 的场景（比如测试脚本），不要依赖它处理退出。
        self._running = True
        try:
            CFRunLoopRun()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_tap()
            self._running = False

    def install_signal_handlers(self):
        """在主线程安装退出信号处理器。

        必须在 main() 里、且在 run_in_thread() 之前调用 —— signal.signal 只能从
        主线程调用，而 core 的事件循环跑在后台线程里，在那边注册会被直接跳过。
        """
        import threading
        if threading.current_thread() is not threading.main_thread():
            logger.debug("非主线程，跳过信号处理器注册")
            return False

        def _handler(sig, frame):
            logger.info(f"收到信号 {sig}，开始清理退出")
            self.shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError) as e:
                logger.debug(f"注册信号 {sig} 失败: {e}")
        return True

    def shutdown(self):
        """完整的退出清理：还原置顶 → 停止事件循环。

        幂等：重复调用只生效一次。退出路径有多条（菜单退出、SIGINT、SIGTERM、
        atexit），任何一条都可能触发，必须保证清理逻辑不会重复执行或互相干扰。
        """
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True

        logger.info("OptSnap 正在退出…")

        # 还原置顶必须放在停止事件循环之前：还原靠写命令文件 + 等回执，
        # 通道还活着才能生效。
        try:
            ok = pin.reset_all_pins(verify=True)
            if not ok:
                logger.warning("退出时未能还原全部置顶窗口，请手动检查")
        except Exception as e:
            logger.error(f"退出时还原置顶失败: {e}")

        try:
            self.stop()
        except Exception as e:
            logger.error(f"停止事件循环失败: {e}")

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
