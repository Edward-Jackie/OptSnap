"""Window manipulation via CGWindowList (get) + AXUIElement (set) + SkyLight (alpha).

Uses CGWindowListCopyWindowInfo for position/size/alpha queries (reliable, no AXValue parsing).
Uses AXUIElement for position/size manipulation (AX API).
Uses SkyLight private API for alpha manipulation of third-party windows.
"""

import ctypes
import logging
import objc
import os
import time

from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXFocusedWindowAttribute,
    kAXMainWindowAttribute,
    kAXWindowsAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXRoleAttribute,
    kAXTitleAttribute,
    kAXErrorSuccess,
    kAXErrorCannotComplete,
    kAXTrustedCheckOptionPrompt,
)

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
)

logger = logging.getLogger(__name__)

# ── Private API: _AXUIElementGetWindow ────────────────────────────────────

_app_services = ctypes.CDLL(
    '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices'
)
_AXUIElementGetWindow = _app_services._AXUIElementGetWindow
_AXUIElementGetWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
_AXUIElementGetWindow.restype = ctypes.c_int32  # AXError


def ax_element_get_window_id(ax_element):
    """Get CGWindowID from an AXUIElement using private API.

    Uses objc.pyobjc_id() to get the raw pointer from the AXUIElementRef.
    """
    wid = ctypes.c_uint32()
    ptr = objc.pyobjc_id(ax_element)
    result = _AXUIElementGetWindow(ptr, ctypes.byref(wid))
    if result != 0:
        logger.warning(f"_AXUIElementGetWindow failed: AXError {result}")
        return None
    return wid.value


# ── Window info cache ─────────────────────────────────────────────────────

def _get_window_info():
    """Get current on-screen window info as a dict: window_id → info."""
    info_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    result = {}
    for info in info_list:
        wid = info.get('kCGWindowNumber')
        if wid is not None:
            result[wid] = info
    return result


def _parse_bounds(bounds):
    """Parse kCGWindowBounds dict to (x, y, width, height).

    bounds can be a dict or an NSValue/CFType depending on macOS version.
    """
    if isinstance(bounds, dict):
        return (
            float(bounds.get('X', 0)),
            float(bounds.get('Y', 0)),
            float(bounds.get('Width', 0)),
            float(bounds.get('Height', 0)),
        )
    # Fallback: try NSValue access
    try:
        rect = bounds.rectValue()
        return (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)
    except Exception:
        return (0, 0, 0, 0)


# ── SkyLight private API for window alpha ─────────────────────────────────

_sl = ctypes.CDLL('/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight')

SLSMainConnectionID = _sl.SLSMainConnectionID
SLSMainConnectionID.argtypes = []
SLSMainConnectionID.restype = ctypes.c_int

SLSSetWindowAlpha = _sl.SLSSetWindowAlpha
SLSSetWindowAlpha.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.c_float]
SLSSetWindowAlpha.restype = ctypes.c_int

SLSGetWindowAlpha = _sl.SLSGetWindowAlpha
SLSGetWindowAlpha.argtypes = [ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
SLSGetWindowAlpha.restype = ctypes.c_int

_connection_id = None


def get_connection_id():
    """Get cached SkyLight connection ID."""
    global _connection_id
    if _connection_id is None:
        _connection_id = SLSMainConnectionID()
    return _connection_id


def set_window_alpha(window_id, alpha):
    """Set window transparency via SkyLight. alpha: 0.0–1.0."""
    cid = get_connection_id()
    err = SLSSetWindowAlpha(cid, window_id, ctypes.c_float(alpha))
    if err != 0:
        logger.warning(f"SLSSetWindowAlpha({window_id}, {alpha:.2f}) failed: CGError {err}")
    return err


def get_window_alpha(window_id):
    """Get current window alpha via SkyLight. Returns float or None."""
    cid = get_connection_id()
    alpha = ctypes.c_float()
    err = SLSGetWindowAlpha(cid, window_id, ctypes.byref(alpha))
    if err != 0:
        logger.warning(f"SLSGetWindowAlpha({window_id}) failed: CGError {err}")
        return None
    return alpha.value


# ── Window hit-testing via CGWindowList ───────────────────────────────────

def get_window_at_point(x, y):
    """Find the window at screen coordinate (x, y).

    Returns (CGWindowID, AXUIElementRef, bounds_dict) tuple.
    bounds_dict has keys: 'x', 'y', 'w', 'h' — extracted once, no extra queries.
    Excludes: Dock, Finder desktop, our own process, menubar.
    """
    own_pid = os.getpid()

    info_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )

    # Iterate from front to back — first window containing point wins
    for info in info_list:
        pid = info.get('kCGWindowOwnerPID')
        layer = info.get('kCGWindowLayer', 0)

        # Exclude: system UI layers (Dock=1000, menubar=20, etc.), own process
        if layer != 0:
            continue
        if pid == own_pid:
            continue

        # Check if point is within window bounds
        bounds = info.get('kCGWindowBounds', {})
        if not bounds or not hasattr(bounds, 'get'):
            continue

        wx = float(bounds.get('X', 0))
        wy = float(bounds.get('Y', 0))
        ww = float(bounds.get('Width', 0))
        wh = float(bounds.get('Height', 0))

        if wx <= x <= wx + ww and wy <= y <= wy + wh:
            window_id = info.get('kCGWindowNumber')
            title = info.get('kCGWindowName', '')
            pid = info.get('kCGWindowOwnerPID')

            # Get AX element for this window using PID-based approach
            ax_ref = _get_ax_window_for_pid(pid, window_id, title)

            win_bounds = {'x': wx, 'y': wy, 'w': ww, 'h': wh}
            return window_id, ax_ref, win_bounds

    return None, None, None


def _get_ax_window_for_pid(pid, window_id, title):
    """Get AXUIElementRef for a specific window of a process.

    Uses CGWindowListCopyWindowInfo data instead of _AXUIElementGetWindow
    private API, which can fail with -25201 on process relaunch.
    """
    try:
        app_ref = AXUIElementCreateApplication(pid)
    except Exception:
        return None

    # Try to get the window list and match by window ID using CGWindowList data
    err, windows = AXUIElementCopyAttributeValue(app_ref, kAXWindowsAttribute, None)
    if err != kAXErrorSuccess or not windows:
        return None

    # First window in the list is usually the frontmost one
    # If we can't match by ID, return the first window as fallback
    if len(windows) > 0:
        return windows[0]

    return None


# ── Window position/size via CGWindowList (GET) + AX (SET) ────────────────

def _ax_retry(func, max_attempts=3, backoff=0.1):
    """Retry AX operation on kAXErrorCannotComplete."""
    last_err = None
    for i in range(max_attempts):
        last_err = func()
        if last_err == kAXErrorCannotComplete:
            time.sleep(backoff)
            continue
        return last_err
    return last_err


def get_window_geometry(window_id):
    """Get window (x, y, width, height) from CGWindowList.

    Returns (x, y, w, h) or None.
    This is more reliable than AXUIElement for getting window geometry.
    """
    info_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    for info in info_list:
        if info.get('kCGWindowNumber') == window_id:
            bounds = info.get('kCGWindowBounds', {})
            if bounds and hasattr(bounds, 'get'):
                x = float(bounds.get('X', 0))
                y = float(bounds.get('Y', 0))
                w = float(bounds.get('Width', 0))
                h = float(bounds.get('Height', 0))
                return (x, y, w, h)
    return None


def get_window_position(window_id):
    """Get window top-left position. Returns (x, y) or None."""
    geo = get_window_geometry(window_id)
    if geo:
        return (geo[0], geo[1])
    return None


def get_window_size(window_id):
    """Get window size. Returns (width, height) or None."""
    geo = get_window_geometry(window_id)
    if geo:
        return (geo[2], geo[3])
    return None


def set_window_position(ax_ref, x, y):
    """Set window top-left position via AX."""
    if ax_ref is None:
        return

    def _do_set():
        ax_pos = AXValueCreate(kAXValueCGPointType, (x, y))
        return AXUIElementSetAttributeValue(ax_ref, kAXPositionAttribute, ax_pos)

    err = _ax_retry(_do_set)
    if err != kAXErrorSuccess:
        logger.warning(f"set_window_position({x}, {y}) failed: AXError {err}")
    else:
        logger.debug(f"set_window_position({x:.0f}, {y:.0f}) OK")


def set_window_size(ax_ref, width, height):
    """Set window size via AX."""
    if ax_ref is None:
        return

    def _do_set():
        ax_size = AXValueCreate(kAXValueCGSizeType, (width, height))
        return AXUIElementSetAttributeValue(ax_ref, kAXSizeAttribute, ax_size)

    err = _ax_retry(_do_set)
    if err != kAXErrorSuccess:
        logger.warning(f"set_window_size({width}, {height}) failed: AXError {err}")
    else:
        logger.debug(f"set_window_size({width:.0f}, {height:.0f}) OK")


def get_focused_window():
    """Get (CGWindowID, AXUIElementRef) of the currently focused window."""
    system = AXUIElementCreateSystemWide()
    err, focused = AXUIElementCopyAttributeValue(system, kAXFocusedWindowAttribute, None)
    if err != kAXErrorSuccess or focused is None:
        return None, None

    window_id = ax_element_get_window_id(focused)
    return window_id, focused


def check_accessibility_permission():
    """Check if Accessibility permission is granted."""
    return AXIsProcessTrusted()


def request_accessibility_permission():
    """Request Accessibility permission with system dialog."""
    options = {kAXTrustedCheckOptionPrompt: True}
    AXIsProcessTrustedWithOptions(options)
