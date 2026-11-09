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
# 命令序号。载荷那边会记住「已处理的最大序号」，只执行更大的序号，避免重复执行。
#
# 关键：**必须单调递增且比上次运行大**。用时间戳取模初始化是错的 —— 重启后算出的
# 序号可能比载荷记住的小（实测踩到：载荷 last_seq=205780，新进程从 205767 开始，
# 所有命令都被当成「已处理」跳过，置顶和还原全部静默失效）。
# 用毫秒时间戳做起点，正常情况下每次重启都会更大。
_cmd_seq = int(time.time() * 1000)
# window_id -> 当前是否置顶
_pinned_state = {}

# 启动清扫用的互斥锁 + 完成标记。
# 清扫是后台线程跑的（注入要 10-15 秒），如果不等它完成就让用户操作，
# 会出现「用户刚置顶的窗口被清扫逻辑当成遗留残留清掉」的问题。
_startup_lock = threading.Lock()
_startup_done = False


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
            # 通道就绪后立刻对齐序号：载荷可能比本进程活得久，记着更大的序号，
            # 不同步的话后面所有命令都会被它当成「已处理」跳过。
            _sync_cmd_seq()
            logger.info(f"置顶通道就绪（耗时 {time.time() - started:.1f}s）")
            return True
        time.sleep(0.2)

    logger.error("置顶通道注入后未检测到心跳")
    return False


def _sync_cmd_seq():
    """把 _cmd_seq 抬到「比载荷已处理的序号更大」的位置。

    载荷进程可能比本进程活得久（Dock 不重启时，注入的线程一直在跑），它记着上次
    处理过的最大序号。如果本进程重启后序号从头开始，载荷会把新命令全部当成
    「已处理」跳过 —— 表现就是置顶和还原静默失效（实测踩过）。

    这里读回执文件里的序号做下限，保证新序号一定更大。
    """
    global _cmd_seq

    used = 0
    for path in (ACK_FILE, CMD_FILE):
        try:
            with open(path) as f:
                parts = f.read().split()
            if parts:
                used = max(used, int(parts[0]))
        except (OSError, ValueError):
            pass

    with _lock:
        if used >= _cmd_seq:
            _cmd_seq = used
            logger.debug(f"命令序号已同步到载荷当前进度: {used}")


def _send_command(window_id, level):
    """下发一条改层级命令并等回执。返回 (成功, CGError)。

    调用方必须保证通道就绪（_heartbeat_alive）。
    """
    global _cmd_seq

    with _lock:
        # 每次发命令前先对齐载荷进度：读回执里最后处理过的序号作为下限。
        #
        # 为什么必须每次查而不是只在启动时查一次：可能有多个进程同时用这个通道
        # （比如主程序 + 调试脚本），各自维护自己的计数器。谁写回执谁就把进度推高了，
        # 另一个进程的计数器可能落后 —— 落后时载荷会把它发的命令当成「已处理」跳过，
        # 表现是命令静默失效（实测踩过：退出还原命令全部超时，窗口停在浮层）。
        used = 0
        try:
            with open(ACK_FILE) as f:
                parts = f.read().split()
            if parts:
                used = int(parts[0])
        except (OSError, ValueError):
            pass

        if used >= _cmd_seq:
            _cmd_seq = used
            logger.debug(f"命令序号对齐到载荷进度: {used}")

        # 用「毫秒时间戳」和「自增」取较大者。两个进程同时发命令时，
        # 各自读到同一个回执号会算出相同序号，用时间戳能进一步降低撞号概率；
        # 即使撞了，载荷按 `seq > last_seq` 判断，后到的会被丢弃 —— 不会互相破坏。
        _cmd_seq = max(_cmd_seq + 1, int(time.time() * 1000))
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

    # 等启动清扫结束再动手。清扫要处理「上次崩溃留下的置顶窗口」，
    # 如果这时用户抢先置顶了一个窗口，清扫会把它当成残留一起还原掉。
    global _startup_done
    if not _startup_done:
        with _startup_lock:
            pass  # 拿到锁即表示清扫已完成（或已跳过）

    level = PIN_LEVEL_FLOATING if pinned else PIN_LEVEL_NORMAL
    ok, err = _send_command(window_id, level)
    if ok:
        if pinned:
            _pinned_state[window_id] = True
        else:
            _pinned_state.pop(window_id, None)
        # 描边只是视觉标记：即使它失败了，置顶本身也是成功的，所以不参与返回值
        try:
            from optsnap import border
            border.set_border(window_id, pinned)
        except Exception as e:
            logger.debug(f"更新置顶描边失败 (window={window_id}): {e}")
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


def find_actually_pinned():
    """扫描系统里真实处于置顶层级的所有应用窗口。

    这是退出还原的兜底手段。光靠 _pinned_state 不够：程序异常退出、Dock 重启导致
    状态丢失、或用户手动改过层级时，内存状态会和实际不一致。以窗口层级为准最可靠。

    判断范围刻意收紧到 (PIN_LEVEL_NORMAL, PIN_LEVEL_FLOATING]，**不能**宽泛地用
    「不等于 0」—— 系统 UI 的层级是负的特殊值（桌面 -2147483603、程序坞
    -2147483624），菜单栏是 24、程序坞是 20，误改这些会破坏系统界面。
    """
    import os
    from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

    own_pid = os.getpid()
    found = []
    try:
        for info in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
            if info.get('kCGWindowOwnerPID') == own_pid:
                continue
            level = info.get('kCGWindowLayer', 0)
            if PIN_LEVEL_NORMAL < level <= PIN_LEVEL_FLOATING:
                found.append(info.get('kCGWindowNumber'))
    except Exception as e:
        logger.debug(f"扫描置顶窗口失败: {e}")
    return found


def pinned_count():
    return len(_pinned_state)


def reset_all_pins(verify=True):
    """取消所有置顶（禁用/退出时调用），避免窗口卡在浮动层。

    清理范围取两个来源的并集，缺一不可：
    - 内存里的 _pinned_state：记录我们主动置顶过的窗口
    - find_actually_pinned()：扫描系统里真实处于浮层级的窗口，兜住状态丢失的情况

    verify=True 时在还原后再扫一遍，把漏掉的补一次。退出流程用这个，宁可多试一轮。

    返回是否全部还原干净（True/False），调用方可以据此决定是否记录警告。
    """
    targets = set(_pinned_state.keys())
    targets |= set(find_actually_pinned())

    if not targets:
        _pinned_state.clear()
        _clear_borders()
        return True

    logger.info(f"正在还原 {len(targets)} 个窗口的置顶状态")

    if not _heartbeat_alive():
        # 通道已死（Dock 重启等），发命令没用。清掉内存状态和描边即可 ——
        # 窗口层级此时通常已随 Dock 重启重置，不需要也无法恢复。
        logger.warning("置顶通道不可用，跳过层级还原（窗口层级会随 Dock 重启复位）")
        _pinned_state.clear()
        _clear_borders()
        return True

    for window_id in targets:
        _send_command(window_id, PIN_LEVEL_NORMAL)

    _pinned_state.clear()
    _clear_borders()

    if verify:
        # 再扫一次，补掉可能漏掉/失败的。只补一轮：某些窗口（全屏、系统保护窗口）
        # 的层级本来就改不动，无限重试只会拖慢退出流程，不如明确报出来。
        leftover = find_actually_pinned()
        if leftover:
            logger.info(f"复查发现 {len(leftover)} 个窗口仍在浮层，补一次还原")
            for window_id in leftover:
                _send_command(window_id, PIN_LEVEL_NORMAL)
            leftover = find_actually_pinned()

        if leftover:
            logger.warning(
                f"仍有 {len(leftover)} 个窗口未能还原: {leftover}"
                "（可能是全屏或系统保护窗口，无法修改层级）"
            )
            return False

    logger.info("已还原所有窗口置顶状态")
    return True


def startup_cleanup(timeout=60):
    """启动时清扫上次异常退出留下的置顶窗口。

    进程被 SIGKILL 时任何 Python 清理代码都跑不了（操作系统层面的限制），
    所以这是唯一的兜底手段。靠扫描窗口层级而不是内存状态 —— 崩溃后状态已经丢了。

    关键点：清扫必须在用户能操作之前完成，否则会把用户刚置顶的窗口也清掉。
    这里用 _startup_lock 和 set_pinned 互斥，并且清扫期间 set_pinned 会等待。
    """
    global _startup_done

    try:
        if not ensure_channel(wait=True, timeout=timeout):
            logger.debug("启动清扫跳过：置顶通道不可用")
            with _startup_lock:
                _startup_done = True
            return

        # 清扫期间挡住新的置顶操作，避免「刚置顶就被清掉」
        with _startup_lock:
            leftover = find_actually_pinned()
            if leftover:
                logger.info(f"发现 {len(leftover)} 个上次遗留的置顶窗口，正在还原")
                for window_id in leftover:
                    _send_command(window_id, PIN_LEVEL_NORMAL)
                _pinned_state.clear()
                _clear_borders()
            _startup_done = True
    except Exception as e:
        logger.warning(f"启动清扫失败: {e}")
        with _startup_lock:
            _startup_done = True


def _clear_borders():
    """清掉所有描边。描边失败不能影响置顶状态的清理。"""
    try:
        from optsnap import border
        border.remove_all_borders()
    except Exception as e:
        logger.debug(f"清除置顶描边失败: {e}")


def channel_status():
    """返回 (是否支持, 通道是否就绪)，供菜单展示。"""
    return is_supported(), is_supported() and _heartbeat_alive()
