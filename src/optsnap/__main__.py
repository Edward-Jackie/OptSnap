"""OptSnap 菜单栏入口。"""

import atexit
import logging
import os
import subprocess
import sys
import threading
import time

import AppKit
import rumps

from optsnap import permissions, pin
from optsnap import window as win
from optsnap.core import OptSnapCore, _modifier_to_name, _toggle_keycode_to_name, _pin_keycode_to_name

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("OPTSNAP_DEBUG") else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

_MENUBAR_ICON = os.path.join(os.path.dirname(__file__), "resources", "menubar_icon.png")


def _sf_icon(name):
    """从 SF Symbol 名构建模板图标，不可用时返回 None。"""
    try:
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is not None:
            image.setTemplate_(True)
        return image
    except Exception:
        return None


class OptSnapMenuApp(rumps.App):
    """OptSnap 菜单栏应用。"""

    def __init__(self, core):
        self.core = core
        core.on_state_change = self._refresh_menu
        super().__init__(
            name="OptSnap",
            icon=_MENUBAR_ICON if os.path.exists(_MENUBAR_ICON) else None,
            title=None if os.path.exists(_MENUBAR_ICON) else "⬡",
            # rumps 默认在 .run() 时插入一次自带退出项；我们每次状态变化都重
            # 建整个菜单（见 _build_menu），自己持有退出项，置 None 避免重复插入报错。
            quit_button=None,
        )
        self._quit_item = rumps.MenuItem("退出 OptSnap", callback=self._quit)
        self._quit_item._menuitem.setImage_(_sf_icon("xmark.circle"))
        self._build_menu()

    # ── 菜单构建 ──────────────────────────────────────────────────────

    def _refresh_menu(self):
        # 由 core.toggle 通过主线程队列调度过来，可以安全操作 AppKit。
        self._build_menu()
        state = "已启用" if self.core.enabled else "已禁用"
        try:
            rumps.notification("OptSnap", "状态切换", state)
        except Exception as e:
            logger.debug(f"通知发送跳过: {e}")

    def _build_menu(self):
        enabled = self.core.enabled
        modifier_name = _modifier_to_name(self.core.modifier_mask)
        toggle_name = _toggle_keycode_to_name(self.core.toggle_keycode)
        pin_name = _pin_keycode_to_name(self.core.pin_keycode)

        status_icon = "●" if enabled else "○"
        status_text = "已启用" if enabled else "已禁用"

        status_item = rumps.MenuItem(f"{status_icon} {status_text}")
        status_item._menuitem.setImage_(_sf_icon("power.circle.fill" if enabled else "power.circle"))

        toggle_item = rumps.MenuItem("切换启用/禁用", callback=self._toggle)
        toggle_item._menuitem.setImage_(_sf_icon("power"))

        modifier_item = rumps.MenuItem(f"修饰键: {modifier_name}", callback=self._cycle_modifier)
        modifier_item._menuitem.setImage_(_sf_icon("option"))

        toggle_key_item = rumps.MenuItem(f"激活键: {toggle_name}", callback=self._cycle_toggle_key)
        toggle_key_item._menuitem.setImage_(_sf_icon("keyboard"))

        # ── 置顶 ──────────────────────────────────────────────────────
        pin_supported, pin_ready = pin.channel_status()
        if not pin_supported:
            pin_state_text = "不支持（需 macOS 15+）"
        elif pin_ready:
            pinned_count = len(pin._pinned_state)
            pin_state_text = f"通道就绪（已置顶 {pinned_count}）" if pinned_count else "通道就绪"
        else:
            pin_state_text = "通道未就绪"

        pin_toggle_item = rumps.MenuItem(
            f"置顶指针下的窗口    {pin_name}", callback=self._toggle_pin
        )
        pin_toggle_item._menuitem.setImage_(_sf_icon("pin"))
        # 通道没就绪时置灰，避免用户点了没反应又不知道为什么
        pin_toggle_item._menuitem.setEnabled_(bool(pin_supported))

        pin_clear_item = rumps.MenuItem("取消全部置顶", callback=self._clear_pins)
        pin_clear_item._menuitem.setImage_(_sf_icon("pin.slash"))
        pin_clear_item._menuitem.setEnabled_(bool(pin_supported and pin.is_pinned_any()))

        pin_state_item = rumps.MenuItem(f"置顶状态: {pin_state_text}")
        pin_state_item._menuitem.setImage_(_sf_icon("info.circle"))

        pin_key_item = rumps.MenuItem(f"置顶键: {pin_name}", callback=self._cycle_pin_key)
        pin_key_item._menuitem.setImage_(_sf_icon("keyboard"))

        items = [
            status_item,
            rumps.separator,
            toggle_item,
            modifier_item,
            toggle_key_item,
            rumps.separator,
            pin_toggle_item,
            pin_clear_item,
            pin_key_item,
            pin_state_item,
        ]

        # ── 权限引导 ──────────────────────────────────────────────────
        perm_items = self._build_permission_items()
        if perm_items:
            items.append(rumps.separator)
            items.extend(perm_items)

        items.append(rumps.separator)

        # rumps 的 `menu = [...]` 会「追加」而不是替换，所以必须先 clear，
        # 否则每次重建都会堆一批过期的动态标题项。
        self.menu.clear()
        self.menu = items
        # clear() 把退出项也清了，每次重建都要加回来。
        self.menu.add(self._quit_item)

    def _build_permission_items(self):
        """按当前权限状态生成引导项。全部满足时只留一个「已就绪」提示。"""
        status = permissions.snapshot()
        items = []

        # 辅助功能 / 输入监听：OptSnap 核心功能必需
        for key, label, icon, opener in (
            ("accessibility", "辅助功能权限", "hand.raised", permissions.open_accessibility_settings),
            ("input_monitoring", "输入监听权限", "keyboard.badge.ellipsis", permissions.open_input_monitoring_settings),
        ):
            granted = status[key]
            mark = "✓" if granted else "⚠"
            item = rumps.MenuItem(
                f"{mark} {label}: {'已授予' if granted else '未授予，点击前往设置'}",
                callback=(lambda s, fn=opener: fn()) if not granted else None,
            )
            item._menuitem.setImage_(_sf_icon(icon if granted else "exclamationmark.triangle"))
            # 已授予的项目不需要点击，置灰纯展示
            item._menuitem.setEnabled_(not granted)
            items.append(item)

        # 置顶依赖：开发者模式 / 命令行工具
        if pin.is_supported():
            missing = permissions.missing_for_pin(status)
            if not missing:
                ready = rumps.MenuItem("✓ 置顶功能依赖已就绪")
                ready._menuitem.setImage_(_sf_icon("checkmark.seal"))
                ready._menuitem.setEnabled_(False)
                items.append(ready)
            else:
                # 缺命令行工具时给出明确动作（触发 Xcode CLT 安装）
                if not status["clang"] or not status["lldb"]:
                    clt = rumps.MenuItem(
                        "安装 Xcode 命令行工具（置顶所需）",
                        callback=self._install_clt,
                    )
                    clt._menuitem.setImage_(_sf_icon("wrench.and.screwdriver"))
                    items.append(clt)

                if not status["developer_mode"]:
                    dev = rumps.MenuItem(
                        "开启开发者模式（置顶所需）",
                        callback=self._enable_developer_mode,
                    )
                    dev._menuitem.setImage_(_sf_icon("hammer"))
                    items.append(dev)

        return items

    # ── 置顶操作 ──────────────────────────────────────────────────────

    def _toggle_pin(self, sender):
        """菜单里点置顶：优先作用于指针下窗口，其次当前焦点窗口。"""
        result = self.core.toggle_pin_under_cursor()
        if result is None:
            # 指针下没窗口或通道未就绪，用焦点窗口兜底
            window_id, _ax_ref = win.get_focused_window()
            if window_id is not None:
                result = pin.toggle_pin(window_id)
        self._build_menu()
        if result is not None:
            try:
                rumps.notification(
                    "OptSnap", "置顶", "已置顶" if result else "已取消置顶"
                )
            except Exception as e:
                logger.debug(f"通知发送跳过: {e}")

    def _clear_pins(self, sender):
        pin.reset_all_pins()
        self._build_menu()

    def _cycle_pin_key(self, sender):
        self.core.cycle_pin_key()
        self._build_menu()

    # ── 权限相关动作 ──────────────────────────────────────────────────

    def _install_clt(self, sender):
        """触发 Xcode 命令行工具安装向导。"""
        try:
            subprocess.Popen(["xcode-select", "--install"])
            rumps.notification(
                "OptSnap", "安装命令行工具",
                "已弹出安装窗口，装完后重启 OptSnap 即可使用置顶功能",
            )
        except Exception as e:
            logger.error(f"启动命令行工具安装失败: {e}")
            rumps.alert(
                title="无法自动安装",
                message="请在终端执行：xcode-select --install",
            )

    def _enable_developer_mode(self, sender):
        """开发者模式需要管理员权限，给出可直接复制的命令并请求提权。"""
        script = (
            'do shell script "/usr/sbin/DevToolsSecurity -enable" '
            'with administrator privileges'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                rumps.notification(
                    "OptSnap", "开发者模式已开启", "置顶通道可以注入了"
                )
                # 开完立刻尝试建立通道
                threading.Thread(
                    target=pin.ensure_channel, kwargs={"wait": True}, daemon=True
                ).start()
            else:
                msg = (result.stderr or "").strip()[:300]
                logger.warning(f"开启开发者模式失败: {msg}")
                rumps.alert(title="开启失败", message=msg or "已取消授权")
        except Exception as e:
            logger.error(f"开启开发者模式异常: {e}")
            rumps.alert(
                title="开启失败",
                message="请在终端执行：sudo DevToolsSecurity -enable",
            )
        self._build_menu()

    # ── 原有操作 ──────────────────────────────────────────────────────

    def _toggle(self, sender):
        self.core.toggle()
        self._build_menu()

    def _cycle_modifier(self, sender):
        self.core.cycle_modifier()
        self._build_menu()

    def _cycle_toggle_key(self, sender):
        self.core.cycle_toggle_key()
        self._build_menu()

    def _quit(self, sender):
        logger.info("用户请求退出 — 终止进程")
        self.core.stop()
        sys.exit(0)


def main():
    print("OptSnap — macOS 窗口管理工具")
    print("=" * 50)

    core = OptSnapCore()

    def _cleanup():
        logger.info("清理：停止核心")
        core.stop()

    atexit.register(_cleanup)

    has_ax, has_input = core.check_permissions()

    if not has_ax:
        print("[OptSnap] 辅助功能权限未授予，正在请求...")
        core.request_accessibility()
        for _ in range(30):
            time.sleep(1)
            if core.check_permissions()[0]:
                print("[OptSnap] 辅助功能权限已授予")
                break
        else:
            print("[OptSnap] 错误：辅助功能权限未授予")
            sys.exit(1)

    if not has_input:
        print("[OptSnap] 输入监听权限未授予，请在系统设置中添加")
        permissions.open_input_monitoring_settings()
        print("  等待 60 秒…")
        for _ in range(30):
            time.sleep(2)
            if core.check_permissions()[1]:
                print("[OptSnap] 输入监听权限已授予")
                break
        else:
            print("[OptSnap] 错误：输入监听权限未授予")
            sys.exit(1)

    print(f"[OptSnap] 修饰键: {_modifier_to_name(core.modifier_mask)}")
    print(f"[OptSnap] 激活键: {_toggle_keycode_to_name(core.toggle_keycode)}")
    print(f"[OptSnap] 置顶键: {_pin_keycode_to_name(core.pin_keycode)}")

    core.run_in_thread()

    # 置顶通道在后台预热：注入要 10-15 秒，放主线程会卡住菜单栏。
    # 失败也不影响其它功能，菜单里会显示原因和引导。
    if pin.is_supported():
        threading.Thread(target=pin.ensure_channel, kwargs={"wait": True}, daemon=True).start()

    print("[OptSnap] 菜单栏已启动。点击图标进行设置。")
    OptSnapMenuApp(core).run()


if __name__ == "__main__":
    main()
