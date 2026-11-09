"""置顶窗口的描边标记 —— 让用户一眼看出哪些窗口处于置顶状态。

实现方式：给每个被置顶的窗口叠一个无边框、点击穿透的 NSPanel，面板的 CALayer 只画
一圈细边框（背景透明）。面板层级比置顶窗口高一级，所以描边总是可见。

为什么用轮询跟随位置：OptSnap 已经通过 CGEventTap 拦下了拖拽事件，但置顶窗口也可能
被别的程序移动（动画、脚本、系统重排），靠事件推断位置不可靠。这里按固定间隔整表刷新
一次 CGWindowList，一次调用就能拿到所有窗口的几何信息，比每个窗口单独查便宜。

所有 AppKit 操作都必须在主线程执行（见 _run_on_main）。
"""

import logging

from optsnap import window as win
from optsnap.config import (
    BORDER_COLOR,
    BORDER_WIDTH,
    BORDER_CORNER_RADIUS,
    BORDER_LEVEL,
    BORDER_REFRESH_INTERVAL,
)

logger = logging.getLogger(__name__)

# window_id → NSPanel
_borders = {}
_timer = None


def _run_on_main(fn):
    """把 fn 调度到 AppKit 主线程执行。

    复用 overlay.py 里那份实现：同样是「事件线程触发、必须回主线程碰 AppKit」的场景，
    重复实现只会让两处的异常兜底逻辑慢慢跑偏。
    """
    from optsnap.overlay import _run_on_main as dispatch
    dispatch(fn)


def _border_rect(bounds):
    """把 CG 坐标（左上原点）的窗口尺寸转成 NS 坐标（左下原点）的矩形。

    跨屏换算用主屏高度做基准：CG 全局坐标以主屏左上角为原点 y 向下增长，
    AppKit 全局坐标以主屏左下角为原点 y 向上增长，所以
    ns_y = 主屏高度 - cg_y - 窗口高度 对任意显示器都成立。
    """
    import AppKit

    x = bounds['x']
    y = bounds['y']
    w = bounds['w']
    h = bounds['h']

    main_h = AppKit.NSScreen.mainScreen().frame().size.height
    ns_y = main_h - y - h

    # 描边画在窗口外沿，向外扩半个线宽，避免盖住窗口自身内容
    inset = 0.0
    return ((x - inset, ns_y - inset), (w + inset * 2, h + inset * 2))


def _make_border():
    """创建一个只有边框的透明面板。"""
    import AppKit

    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (0, 0)),
        AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
        AppKit.NSBackingStoreBuffered,
        False,
    )
    panel.setOpaque_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setHasShadow_(False)
    # 点击穿透：描边只是视觉标记，不能挡住窗口本身的交互
    panel.setIgnoresMouseEvents_(True)
    panel.setLevel_(BORDER_LEVEL)
    # 跟随窗口出现在所有空间，切换桌面后描边不丢
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorTransient
        | AppKit.NSWindowCollectionBehaviorIgnoresCycle
    )

    view = panel.contentView()
    view.setWantsLayer_(True)
    layer = view.layer()
    if layer is not None:
        r, g, b, a = BORDER_COLOR
        layer.setBorderWidth_(BORDER_WIDTH)
        layer.setBorderColor_(
            AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a).CGColor()
        )
        layer.setCornerRadius_(BORDER_CORNER_RADIUS)
        layer.setBackgroundColor_(AppKit.NSColor.clearColor().CGColor())
        # Retina 屏上不加这个会让 1.5px 的线糊成 3px
        try:
            layer.setContentsScale_(AppKit.NSScreen.mainScreen().backingScaleFactor())
        except Exception:
            pass

    return panel


def _ensure_timer():
    """启动位置跟随定时器（只在有描边时运行，避免空闲轮询）。"""
    global _timer
    if _timer is not None:
        return

    import AppKit
    from Foundation import NSRunLoop, NSRunLoopCommonModes

    def _tick(timer):
        try:
            refresh()
        except Exception as e:
            logger.debug(f"描边刷新失败: {e}")

    _timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        BORDER_REFRESH_INTERVAL, True, _tick
    )
    # 加入 common modes：菜单弹出、窗口拖动等 tracking 模式下定时器依然触发，
    # 否则拖动期间描边会明显滞后。
    NSRunLoop.currentRunLoop().addTimer_forMode_(_timer, NSRunLoopCommonModes)
    logger.debug("描边跟随定时器已启动")


def _stop_timer_if_idle():
    global _timer
    if _timer is None or _borders:
        return
    try:
        _timer.invalidate()
    except Exception:
        pass
    _timer = None
    logger.debug("描边跟随定时器已停止")


def refresh():
    """把所有描边对齐到对应窗口的当前几何位置。必须在主线程调用。"""
    if not _borders:
        _stop_timer_if_idle()
        return

    # 一次 CGWindowList 拿全部窗口几何，而不是每个窗口查一次
    info = win._get_window_info()

    for window_id, panel in list(_borders.items()):
        w = info.get(window_id)
        if not w:
            # 窗口被关闭、最小化或切到其它空间 —— 先隐藏，保留状态
            if panel.isVisible():
                panel.orderOut_(None)
            continue

        bounds = w.get('kCGWindowBounds')
        if not bounds or not hasattr(bounds, 'get'):
            continue

        rect = {
            'x': float(bounds.get('X', 0)),
            'y': float(bounds.get('Y', 0)),
            'w': float(bounds.get('Width', 0)),
            'h': float(bounds.get('Height', 0)),
        }
        if rect['w'] <= 0 or rect['h'] <= 0:
            if panel.isVisible():
                panel.orderOut_(None)
            continue

        panel.setFrame_display_(_border_rect(rect), False)
        if not panel.isVisible():
            panel.orderFrontRegardless()


def set_border(window_id, enabled):
    """设置/移除某个窗口的描边。线程安全。"""
    if window_id is None:
        return

    def _do():
        if enabled:
            if window_id not in _borders:
                _borders[window_id] = _make_border()
                logger.debug(f"描边已添加: window={window_id}")
            _ensure_timer()
            refresh()
        else:
            panel = _borders.pop(window_id, None)
            if panel is not None:
                panel.orderOut_(None)
                panel.close()
                logger.debug(f"描边已移除: window={window_id}")
            _stop_timer_if_idle()

    _run_on_main(_do)


def remove_all_borders():
    """移除所有描边（禁用/退出时调用）。线程安全。"""
    def _do():
        for window_id, panel in list(_borders.items()):
            try:
                panel.orderOut_(None)
                panel.close()
            except Exception as e:
                logger.debug(f"关闭描边失败 (window={window_id}): {e}")
        _borders.clear()
        _stop_timer_if_idle()

    _run_on_main(_do)


def border_count():
    """当前显示的描边数量，供状态展示用。"""
    return len(_borders)
