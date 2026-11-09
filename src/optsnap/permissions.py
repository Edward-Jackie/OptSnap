"""权限检测与引导 —— 菜单里展示当前权限状态，并给出可操作的跳转入口。

OptSnap 依赖两类系统权限：
- 辅助功能（Accessibility）：移动/调整窗口、读写窗口位置
- 输入监听（Input Monitoring）：全局鼠标键盘事件 tap

置顶功能额外依赖「开发者模式」：它通过 lldb 附加 Dock 注入载荷，这是调试通道，
不是常规 API。开发者模式未开启时，注入会失败 —— 所以单独检测并引导。

设计原则：引导要在菜单里能直接点，而不是打印一段文字让用户自己去翻系统设置。
"""

import logging
import platform
import subprocess

logger = logging.getLogger(__name__)

# 系统设置的深链 URL
_URL_ACCESSIBILITY = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
_URL_INPUT_MONITORING = "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
_URL_SECURITY = "x-apple.systempreferences:com.apple.preference.security?General"


def _run(cmd):
    """跑一条命令，返回 (返回码, 输出)。命令不存在也算失败。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def check_accessibility():
    """辅助功能权限是否已授予。"""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception as e:
        logger.debug(f"辅助功能检测失败: {e}")
        return False


def check_input_monitoring():
    """输入监听权限是否已授予。

    没有直接的公开 API，用「能否创建一个事件 tap」来间接判断：
    没权限时 CGEventTapCreate 返回 None。
    """
    try:
        from Quartz import (
            CGEventTapCreate,
            CFMachPortInvalidate,
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            kCGEventFlagsChanged,
        )
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            (1 << kCGEventFlagsChanged),
            lambda *args: None,
            None,
        )
        if tap:
            CFMachPortInvalidate(tap)
            return True
        return False
    except Exception as e:
        logger.debug(f"输入监听检测失败: {e}")
        return False


def check_developer_mode():
    """开发者模式是否开启 —— 置顶注入通道的前置条件。

    DevToolsSecurity 输出 "Developer mode is currently enabled." / "... disabled."
    需要管理员权限才能开启，所以只做检测和引导。
    """
    rc, out = _run(["/usr/sbin/DevToolsSecurity", "-status"])
    if rc != 0:
        # 路径因系统版本而异，退回 PATH 查找
        rc, out = _run(["DevToolsSecurity", "-status"])
    if rc != 0:
        return False
    return "enabled" in out.lower()


def check_clang():
    """是否装了 clang（Xcode 命令行工具）—— 编译置顶载荷需要。"""
    try:
        from shutil import which
        return which("clang") is not None
    except Exception:
        return False


def check_lldb():
    """是否有 lldb —— 注入通道需要。"""
    try:
        from shutil import which
        return which("lldb") is not None
    except Exception:
        return False


def open_url(url):
    """打开系统设置页面。"""
    rc, out = _run(["open", url])
    if rc != 0:
        logger.warning(f"打开系统设置失败: {out.strip()[:200]}")
        return False
    return True


def open_accessibility_settings():
    return open_url(_URL_ACCESSIBILITY)


def open_input_monitoring_settings():
    return open_url(_URL_INPUT_MONITORING)


def open_security_settings():
    return open_url(_URL_SECURITY)


def open_app_folder():
    """打开应用所在目录 —— 引导用户把 OptSnap 拖进权限列表。

    权限列表里添加的是「可执行文件本身」，直接展示它在哪比讲一堆步骤有用。
    """
    import os
    import sys

    target = None
    # 打包成 .app 时取 .app 的外层目录，开发模式取项目根
    bundle = os.environ.get("OPTSNAP_BUNDLE_PATH")
    if bundle and os.path.exists(bundle):
        target = os.path.dirname(bundle)
    elif getattr(sys, "frozen", False):
        target = os.path.dirname(sys.executable)
    else:
        # __file__ 在 src/optsnap/ 下，往上两级是项目根
        target = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    rc, out = _run(["open", target])
    return rc == 0


def snapshot():
    """一次性返回所有权限状态，供菜单渲染。

    返回 dict，键名直接对应菜单项含义，避免调用方再拼装。
    """
    return {
        "accessibility": check_accessibility(),
        "input_monitoring": check_input_monitoring(),
        "developer_mode": check_developer_mode(),
        "clang": check_clang(),
        "lldb": check_lldb(),
    }


def missing_for_pin(status=None, include_developer_mode=False):
    """置顶功能还缺哪些「硬性」前置条件，返回人类可读的列表。

    空列表表示置顶可用。

    注意：开发者模式**不在**默认缺失列表里。实测本机 DevToolsSecurity 显示 disabled，
    但 lldb 依然能附加到 Dock 并注入成功 —— 它只是常被建议开启，不是硬门槛。
    只有注入真的失败时，才把开发者模式作为排查项提出来（见 pin.py 的失败诊断）。
    """
    if status is None:
        status = snapshot()

    missing = []
    if not status["clang"]:
        missing.append("clang（Xcode 命令行工具）")
    if not status["lldb"]:
        missing.append("lldb")
    if not status["accessibility"]:
        missing.append("辅助功能权限")
    if include_developer_mode and not status["developer_mode"]:
        missing.append("开发者模式")
    return missing


def pin_troubleshooting_hint(status=None):
    """置顶注入失败时的排查建议，按可能性排序。"""
    if status is None:
        status = snapshot()

    hints = []
    if not status["clang"] or not status["lldb"]:
        hints.append("安装 Xcode 命令行工具：xcode-select --install")
    if not status["developer_mode"]:
        hints.append("开启开发者模式：sudo DevToolsSecurity -enable")
    hints.append("确认 Dock 正常运行：pgrep -x Dock")
    hints.append("重新启动 OptSnap 后重试")
    return hints
