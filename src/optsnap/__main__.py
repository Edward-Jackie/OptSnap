"""OptSnap entry point — GUI menu bar app."""

import atexit
import logging
import time
import sys
import os

import AppKit
import rumps

from optsnap.core import OptSnapCore, _modifier_to_name, _toggle_keycode_to_name

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("OPTSNAP_DEBUG") else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

_MENUBAR_ICON = os.path.join(os.path.dirname(__file__), "resources", "menubar_icon.png")


def _sf_icon(name):
    """Build a template NSImage from an SF Symbol name, or None if unavailable."""
    try:
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is not None:
            image.setTemplate_(True)
        return image
    except Exception:
        return None


class OptSnapMenuApp(rumps.App):
    """Menu bar app for OptSnap."""

    def __init__(self, core):
        self.core = core
        core.on_state_change = self._refresh_menu
        super().__init__(
            name="OptSnap",
            icon=_MENUBAR_ICON if os.path.exists(_MENUBAR_ICON) else None,
            title=None if os.path.exists(_MENUBAR_ICON) else "⬡",
            # rumps normally adds its own quit_button to the menu exactly once, when
            # .run() starts. We rebuild the menu ourselves on every state change (see
            # _build_menu), so we own the quit item entirely instead — quit_button=None
            # stops rumps from also trying to insert it (that second insert would raise
            # "Item to be inserted into menu already is in another menu").
            quit_button=None,
        )
        self._quit_item = rumps.MenuItem("退出 OptSnap", callback=self._quit)
        self._quit_item._menuitem.setImage_(_sf_icon("xmark.circle"))
        self._build_menu()

    def _refresh_menu(self):
        # Called on main thread (dispatched from core.toggle via NSOperationQueue).
        self._build_menu()
        state = "已启用" if self.core.enabled else "已禁用"
        try:
            rumps.notification("OptSnap", "状态切换", state)
        except Exception as e:
            logger.debug(f"Notification skipped: {e}")

    def _build_menu(self):
        enabled = self.core.enabled
        modifier_name = _modifier_to_name(self.core.modifier_mask)
        toggle_name = _toggle_keycode_to_name(self.core.toggle_keycode)

        status_icon = "●" if enabled else "○"
        status_text = "已启用" if enabled else "已禁用"

        status_item = rumps.MenuItem(f"{status_icon} {status_text}")
        toggle_item = rumps.MenuItem("切换启用/禁用", callback=self._toggle)
        modifier_item = rumps.MenuItem(f"修饰键: {modifier_name}", callback=self._cycle_modifier)
        toggle_key_item = rumps.MenuItem(f"激活键: {toggle_name}", callback=self._cycle_toggle_key)

        status_item._menuitem.setImage_(_sf_icon("power.circle.fill" if enabled else "power.circle"))
        toggle_item._menuitem.setImage_(_sf_icon("power"))
        modifier_item._menuitem.setImage_(_sf_icon("option"))
        toggle_key_item._menuitem.setImage_(_sf_icon("keyboard"))

        # rumps' `menu = [...]` setter calls Menu.update(), which *adds* items whose
        # key (title text) isn't already present rather than replacing the menu — since
        # these titles embed dynamic state, every rebuild was appending a fresh set of
        # stale items instead of replacing the old ones. Clear first so rebuilds don't
        # accumulate.
        self.menu.clear()
        self.menu = [
            status_item,
            rumps.separator,
            toggle_item,
            modifier_item,
            toggle_key_item,
            rumps.separator,
        ]
        # clear() wipes the quit item too, so re-add it every rebuild (see __init__
        # for why we own it instead of rumps' built-in quit_button).
        self.menu.add(self._quit_item)

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
        logger.info("User requested quit — terminating process")
        self.core.stop()
        sys.exit(0)


def main():
    print("OptSnap — AltSnap-like window manager for macOS")
    print("=" * 50)

    core = OptSnapCore()

    # Register cleanup on exit
    def _cleanup():
        logger.info("Cleanup: stopping core")
        core.stop()

    atexit.register(_cleanup)

    # Check permissions
    has_ax, has_input = core.check_permissions()

    if not has_ax:
        print("[OptSnap] 辅助功能权限未授予，正在请求...")
        core.request_accessibility()
        for i in range(30):
            time.sleep(1)
            if core.check_permissions()[0]:
                print("[OptSnap] 辅助功能权限已授予")
                break
        else:
            print("[OptSnap] ERROR: 辅助功能权限未授予")
            sys.exit(1)

    if not has_input:
        print("[OptSnap] 输入监听权限未授予，请在系统设置中添加 Python.app")
        print("  系统设置 → 隐私与安全性 → 输入监听 → + → 添加 Python.app")
        print("  等待 60s...")
        for i in range(30):
            time.sleep(2)
            _, has_input = core.check_permissions()
            if has_input:
                print("[OptSnap] 输入监听权限已授予")
                break
        else:
            print("[OptSnap] ERROR: 输入监听权限未授予")
            sys.exit(1)

    print(f"[OptSnap] 修饰键: {_modifier_to_name(core.modifier_mask)}")
    print(f"[OptSnap] 激活键: {_toggle_keycode_to_name(core.toggle_keycode)}")

    # Start core in background thread
    core.run_in_thread()

    # Run menu bar app (blocks main thread)
    print("[OptSnap] 菜单栏已启动。点击图标进行设置。")
    OptSnapMenuApp(core).run()


if __name__ == "__main__":
    main()
