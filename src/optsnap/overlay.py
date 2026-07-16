"""Window dimming overlay for macOS 15+ (SkyLight alpha API unavailable cross-process).

Renders as a frosted-glass blur — a light, adjustable-radius blur via the private
SLSSetWindowBackgroundBlurRadius API (the same one iTerm2 uses for its "Blur content
behind window" option) — rather than a flat color, so dimming doesn't read as "the
window turned black."
"""

import logging
import platform

from optsnap.window import set_window_blur_radius

logger = logging.getLogger(__name__)

_MACOS_MAJOR = int(platform.mac_ver()[0].split('.')[0])
_overlays = {}  # window_id -> NSPanel


def _run_on_main(fn):
    """Dispatch fn to AppKit main thread (safe to call from any thread)."""
    try:
        import AppKit
        # 如果已经在主线程，直接执行
        if AppKit.NSThread.isMainThread():
            fn()
        else:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(fn)
    except Exception as e:
        logger.error(f"Main-thread dispatch failed: {e}")
        # Fallback: try direct execution
        try:
            fn()
        except Exception as e2:
            logger.error(f"Direct fallback also failed: {e2}")


def set_overlay_dim(window_id, dim_alpha, bounds):
    """
    Show/update a dimming overlay over the target window.
    dim_alpha: 0.0 = no overlay (fully visible), up to ~0.8 = heavily dimmed.
    bounds: dict with keys 'x', 'y', 'w', 'h' in CG screen coordinates (top-left origin).
    """
    if dim_alpha <= 0 and window_id not in _overlays:
        return  # nothing to do

    def _do():
        try:
            import AppKit
            screen_h = AppKit.NSScreen.mainScreen().frame().size.height
            # Convert CG top-left origin → NS bottom-left origin
            ns_x = bounds['x']
            ns_y = screen_h - bounds['y'] - bounds['h']
            ns_rect = ((ns_x, ns_y), (bounds['w'], bounds['h']))

            # dim_alpha (0..~0.9) drives a real, continuously adjustable blur radius
            # via SLSSetWindowBackgroundBlurRadius — this is the primary "dimmed"
            # signal. The white tint is kept deliberately faint (just enough to be
            # visible over a flat-colored window with nothing to blur); confirmed
            # empirically that SLSSetWindowAlpha can't make the *target* window
            # itself translucent cross-process on macOS 15+ (call reports success
            # but the alpha never actually changes), so this panel-over-the-window
            # blur is the closest available approximation to "see-through," not a
            # true match for it — a heavier tint here would fight against that.
            blur_radius = int(dim_alpha * 48)
            tint_alpha = dim_alpha * 0.12
            tint = AppKit.NSColor.colorWithWhite_alpha_(1.0, tint_alpha)

            if window_id not in _overlays:
                panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                    ns_rect,
                    AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
                    AppKit.NSBackingStoreBuffered,
                    False,
                )
                panel.setBackgroundColor_(tint)
                panel.setIgnoresMouseEvents_(True)
                panel.setLevel_(AppKit.NSFloatingWindowLevel)
                panel.setHasShadow_(False)
                panel.setOpaque_(False)
                panel.setCollectionBehavior_(
                    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                    | AppKit.NSWindowCollectionBehaviorTransient
                    | AppKit.NSWindowCollectionBehaviorIgnoresCycle
                )
                panel.orderFrontRegardless()
                set_window_blur_radius(panel.windowNumber(), blur_radius)
                _overlays[window_id] = panel
            else:
                panel = _overlays[window_id]
                panel.setFrame_display_(ns_rect, False)
                panel.setBackgroundColor_(tint)
                panel.orderFrontRegardless()
                set_window_blur_radius(panel.windowNumber(), blur_radius)

            # Remove when fully transparent
            if dim_alpha <= 0:
                _close_overlay(window_id)
        except Exception as e:
            logger.warning(f"Overlay set_dim failed (window={window_id}): {e}")

    _run_on_main(_do)


def _close_overlay(window_id):
    """Must be called on main thread."""
    if window_id in _overlays:
        _overlays[window_id].close()
        del _overlays[window_id]


def remove_overlay(window_id):
    """Remove overlay for a single window (thread-safe)."""
    def _do():
        _close_overlay(window_id)
    _run_on_main(_do)


def remove_all_overlays():
    """Remove all overlays (thread-safe)."""
    def _do():
        for wid in list(_overlays.keys()):
            _close_overlay(wid)
    _run_on_main(_do)
