"""窗口置顶 —— 通过 Dock 进程代理修改窗口层级。

macOS 15 起，SkyLight 的 SLSSetWindowLevel 对其它进程的窗口只返回成功但实际不生效
（进程归属校验）。本模块把一段原生载荷注入 Dock.app，由 Dock 用自己的 SLS 连接真正
修改层级。原理同 yabai 的 scripting-addition。

工作分三段：
1. 编译载荷（首次运行，结果缓存）
2. 注入载荷（lldb 附加 Dock，约 10-15 秒，放在后台做）
3. 下发命令（写命令文件 + 等回执，约 30ms）

对外只暴露 is_available / ensure_channel / set_pinned / toggle_pin 几个函数，
调用方不需要关心底层通道状态。
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

_NATIVE_DIR = os.path.join(os.path.dirname(__file__), "native")
_PAYLOAD_SRC = os.path.join(_NATIVE_DIR, "pin_payload.c")

CMD_FILE = "/tmp/optsnap_pin_cmd"
ACK_FILE = "/tmp/optsnap_pin_ack"
HEARTBEAT_FILE = "/tmp/optsnap_pin_heartbeat"

# 心跳超过这个秒数没刷新，认为通道已死（Dock 重启、载荷被卸载等）
HEARTBEAT_TIMEOUT = 5.0
# 命令往返超时
COMMAND_TIMEOUT = 1.0
# 注入超时：lldb 附加 + dlopen 实测 10-15 秒，留够余量
INJECT_TIMEOUT = 60

# 层级取值。kCGFloatingWindowLevel = 3，浮在普通窗口之上但低于菜单栏/程序坞，
# 是「置顶但不像系统弹窗那样霸道」的合适档位。
PIN_LEVEL_FLOATING = 3
PIN_LEVEL_NORMAL = 0

_lock = threading.Lock()
_channel_ready = False
_cmd_seq = int(time.time()) % 1000000
# window_id -> 当前是否置顶
_pinned_state = {}


def is_supported():
    """当前平台是否支持置顶功能。

    依赖 Dock 注入，只在 macOS 15+ 实测通过。更早版本可以用 SkyLight 的
    SLSSetWindowAlpha 类比路径，但层级 API 的跨进程行为未验证，先保守限制。
    """
    if platform.system() != "Darwin":
        return False
    try:
        major = int(platform.mac_ver()[0].split(".")[0])
    except (ValueError, IndexError):
        return False
    return major >= 15


def _dock_pid():
    out = subprocess.run(["pgrep", "-x", "Dock"], capture_output=True, text=True)
    pids = out.stdout.split()
    return int(pids[0]) if pids else None


def _heartbeat_alive():
    """心跳文件是否新鲜 —— 判断载荷是否还在 Dock 里跑着。"""
    try:
        if time.time() - os.path.getmtime(HEARTBEAT_FILE) > HEARTBEAT_TIMEOUT:
            return False
        # 写心跳的是 Dock 内的线程，pid 应该就是 Dock 的 pid
        with open(HEARTBEAT_FILE) as f:
            pid = int(f.read().strip())
        return pid == _dock_pid()
    except (OSError, ValueError):
        return False


def _build_payload():
    """编译载荷 dylib，返回路径；失败返回 None。

    编译产物放在临时目录：它是可再生的，没必要污染项目目录，也避免 .gitignore
    要额外维护。
    """
    out_dir = os.path.join(tempfile.gettempdir(), "optsnap_pin")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pin_payload.dylib")

    src_mtime = os.path.getmtime(_PAYLOAD_SRC)
    if os.path.exists(out_path) and os.path.getmtime(out_path) >= src_mtime:
        return out_path

    if not shutil.which("clang"):
        logger.error("置顶功能需要 clang（Xcode Command Line Tools），未找到")
        return None

    try:
        result = subprocess.run(
            ["clang", "-dynamiclib", "-O2", "-o", out_path, _PAYLOAD_SRC, "-lpthread"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"编译置顶载荷失败: {e}")
        return None

    if result.returncode != 0:
        logger.error(f"编译置顶载荷失败: {result.stderr.strip()[:400]}")
        return None

    return out_path


def _inject(payload_path):
    """把载荷 dlopen 进 Dock.app。耗时 10-15 秒，必须在后台线程调用。"""
    dock_pid = _dock_pid()
    if not dock_pid:
        logger.error("Dock 未运行，无法注入置顶载荷")
        return False

    # 每次复制成唯一文件名：dlopen 同一路径第二次不会重跑构造器，
    # 而我们需要构造器来启动监听线程。
    unique = os.path.join(
        tempfile.gettempdir(), f"optsnap_pin_{os.getpid()}_{int(time.time())}.dylib"
    )
    try:
        shutil.copy2(payload_path, unique)
    except OSError as e:
        logger.error(f"复制置顶载荷失败: {e}")
        return False

    # lldb 附加 Dock 是调试手段，需要 developer mode 开启。这不是产品级的正常路径，
    # 但对本地工具是可行的 —— 失败时降级为「置顶不可用」，不影响其它功能。
    lldb_cmd = [
        "lldb", "-b",
        "-o", f"process attach --pid {dock_pid}",
        "-o", f'expr (void*)dlopen("{unique}", 2)',
        "-o", "process detach",
        "-o", "quit",
    ]

    try:
        result = subprocess.run(
            lldb_cmd, capture_output=True, text=True, timeout=INJECT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        logger.error("注入置顶载荷超时")
        return False
    except OSError as e:
        logger.error(f"调用 lldb 失败（需要安装 Xcode Command Line Tools）: {e}")
        return False
    finally:
        try:
            os.unlink(unique)
        except OSError:
            pass

    combined = (result.stdout or "") + (result.stderr or "")
    if "error:" in combined:
        logger.error(f"注入置顶载荷失败: {combined.strip()[:400]}")
        return False

    return True


def ensure_channel(wait=True, timeout=20.0):
    """确保注入通道可用。已就绪则立即返回。

    Args:
        wait: 是否等待注入完成。False 时只做非阻塞检查/触发后台注入。
    """
    global _channel_ready

    if not is_supported():
        return False

    with _lock:
        if _heartbeat_alive():
            _channel_ready = True
            return True
        if not wait:
            # 交给后台线程慢慢注入，不阻塞调用方（通常是从菜单触发的）
            threading.Thread(target=ensure_channel, kwargs={"wait": True}, daemon=True).start()
            return False

    payload = _build_payload()
    if not payload:
        return False

    logger.info("正在注入置顶通道（约需 10-15 秒）…")
    started = time.time()
    if not _inject(payload):
        return False

    # 注入成功后等心跳出现，确认线程真的跑起来了
    while time.time() - started < timeout:
        if _heartbeat_alive():
            with _lock:
                _channel_ready = True
            logger.info(f"置顶通道就绪（耗时 {time.time() - started:.1f}s）")
            return True
        time.sleep(0.2)

    logger.error("置顶通道注入后未检测到心跳")
    return False


def _send_command(window_id, level):
    """下发一条改层级命令并等回执。返回 (成功, CGError)。

    调用方必须保证通道就绪（_heartbeat_alive）。
    """
    global _cmd_seq

    with _lock:
        _cmd_seq += 1
        seq = _cmd_seq

    try:
        tmp = CMD_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(f"{seq} {window_id} {level}\n")
        os.replace(tmp, CMD_FILE)
    except OSError as e:
        logger.error(f"写入置顶命令失败: {e}")
        return False, None

    deadline = time.time() + COMMAND_TIMEOUT
    while time.time() < deadline:
        try:
            with open(ACK_FILE) as f:
                parts = f.read().split()
            if len(parts) == 4 and int(parts[0]) == seq:
                err = int(parts[3])
                if err != 0:
                    logger.warning(f"置顶命令返回 CGError {err}（window={window_id}）")
                return err == 0, err
        except (OSError, ValueError):
            pass
        time.sleep(0.003)

    logger.warning(f"置顶命令超时（window={window_id}）")
    return False, None


def set_pinned(window_id, pinned):
    """设置/取消窗口置顶。返回是否成功。

    失败时不抛异常：置顶是增强功能，调用方（事件回调）不该因为它而中断。
    """
    if not is_supported() or window_id is None:
        return False

    if not _heartbeat_alive():
        logger.warning("置顶通道未就绪，忽略本次切换")
        return False

    level = PIN_LEVEL_FLOATING if pinned else PIN_LEVEL_NORMAL
    ok, err = _send_command(window_id, level)
    if ok:
        if pinned:
            _pinned_state[window_id] = True
        else:
            _pinned_state.pop(window_id, None)
        logger.info(f"窗口 {window_id} {'置顶' if pinned else '取消置顶'}")
    return ok


def toggle_pin(window_id):
    """切换窗口置顶状态，返回切换后的状态（None 表示失败）。"""
    if window_id is None:
        return None
    new_state = not _pinned_state.get(window_id, False)
    if set_pinned(window_id, new_state):
        return new_state
    return None


def is_pinned(window_id):
    return _pinned_state.get(window_id, False)


def pinned_window_at(x, y):
    """返回指针位置下「已置顶」的窗口 id，没有则 None。

    为什么需要单独判断：窗口被置顶后 layer 从 0 变成 3，而 window.get_window_at_point
    只认 layer==0 的窗口，会直接跳过它。不先查这里的话，第二次按快捷键就命中到下层
    的另一个窗口，导致「取消置顶」永远失效、还会误置顶别的窗口。
    """
    from optsnap import window as win

    for window_id in list(_pinned_state.keys()):
        geo = win.get_window_geometry(window_id)
        if not geo:
            continue
        gx, gy, gw, gh = geo
        if gx <= x <= gx + gw and gy <= y <= gy + gh:
            return window_id
    return None


def is_pinned_any():
    """是否有任何窗口处于置顶状态，供菜单决定「取消全部置顶」是否可点。"""
    return bool(_pinned_state)


def pinned_count():
    return len(_pinned_state)


def reset_all_pins():
    """取消所有置顶（禁用/退出时调用），避免窗口卡在浮动层。"""
    if not _pinned_state:
        return
    if not _heartbeat_alive():
        _pinned_state.clear()
        return
    for window_id in list(_pinned_state.keys()):
        _send_command(window_id, PIN_LEVEL_NORMAL)
    _pinned_state.clear()
    logger.info("已取消所有窗口置顶")


def channel_status():
    """返回 (是否支持, 通道是否就绪)，供菜单展示。"""
    return is_supported(), is_supported() and _heartbeat_alive()
