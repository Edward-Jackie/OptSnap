# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OptSnap is a macOS menu-bar utility (AltSnap-inspired) that lets you move/resize windows and adjust their
visibility by holding a modifier key (default: Option) and using the mouse — no need to grab a title bar or
edge. It's a PyObjC app: a `CGEventTap` intercepts global mouse/keyboard events, `AXUIElement` moves/resizes
windows, and either the `SkyLight` private framework or an `NSPanel` overlay handles dimming, depending on
macOS version. It only runs on macOS.

## Commands

```bash
uv sync                        # install dependencies
uv run python -m optsnap       # run in dev mode (menu bar app, foreground)
./optsnap.sh                   # convenience wrapper around the above
./build_app.sh                 # build build/OptSnap.app (manual bundling, NOT via setup.py/py2app)
open build/OptSnap.app         # run the packaged app
```

There is no linter or formatter configured (no ruff/flake8/mypy config) and no CI. `setup.py` declares a
py2app build but `build_app.sh` is the build path that's actually documented and used — don't assume
`python setup.py py2app` produces the shipped artifact.

### Tests

There's no pytest setup — `scripts/test_*.py` are standalone scripts, not a pytest suite. Run one directly:

```bash
uv run python scripts/test_actions.py
```

Each prints PASS/FAIL per test and exits non-zero on failure. Only **`scripts/test_actions.py`** is a pure
unit test (mocks `optsnap.window` calls, no side effects, safe to run headless/in CI-like conditions).

The rest are **manual/interactive scripts that touch real macOS state** — they require Accessibility/Input
Monitoring permissions already granted, a live desktop session, and in several cases either wait on real
mouse input for a fixed window or actually move/resize/dim whatever real window is under the cursor:
`test_alpha.py`, `test_diagnostic.py`, `test_event_tap.py`, `test_overlay.py`, `test_window_move.py`. Don't
run these expecting a quick deterministic result — they're for a human at the keyboard debugging the
Quartz/AX/SkyLight layer, not for automated verification.

## Required macOS permissions

The app needs two TCC permissions granted to whatever process runs it (Python/terminal in dev mode, or
`OptSnap.app` once packaged — granting one does not cover the other):
- **Accessibility** (`AXUIElement*`) — to move/resize other apps' windows.
- **Input Monitoring** — for the `CGEventTap` to see global mouse/keyboard events.

`OptSnapCore.check_permissions()` / `request_accessibility()` in `core.py` handle detection and prompting;
`__main__.py:main()` blocks at startup polling for both before starting the event loop.

## Architecture

### Event flow and state machine

Everything funnels through one `CGEventTap` owned by `OptSnapCore` (`core.py`), running on a dedicated
background thread (`run_in_thread()` → `CFRunLoopRun()`), separate from the `rumps` menu bar app on the main
thread. `OptSnapCore._event_callback` is a small state machine over `self.mode`: `idle → moving/resizing →
idle`, driven directly by raw `kCGEventLeftMouseDown/Dragged/Up` and `kCGEventRightMouseDown/Dragged/Up`
while the configured modifier is held. Scroll events adjust alpha directly from `idle` with no separate mode.
The toggle hotkey (default F8) is checked before anything else, even when the tap is otherwise disabled, so
it always works.

Cross-thread UI updates matter here: `OptSnapCore.toggle()` dispatches `on_state_change` onto
`AppKit.NSOperationQueue.mainQueue()` rather than calling it inline, because doing AppKit work directly on
the tap thread can stall it long enough for macOS to fire `kCGEventTapDisabledByTimeout` and kill the tap.
The tap also self-heals: a `CFRunLoopTimer` (`HEALTH_CHECK_INTERVAL`) checks `CGEventTapIsEnabled` and calls
`_recreate_tap()` if the tap was disabled (timeout or TCC revocation).

### Window I/O split: read via CGWindowList, write via AXUIElement

`window.py` deliberately separates *querying* window geometry from *setting* it:
- **Reads** (position, size, hit-testing at a point) go through `CGWindowListCopyWindowInfo` — considered
  more reliable than parsing `AXValue`.
- **Writes** (position, size) go through `AXUIElementSetAttributeValue`, since `CGWindowList` is read-only.
- Getting an `AXUIElementRef` for a window found via `CGWindowList` uses a PID-based lookup
  (`_get_ax_window_for_pid`) rather than the private `_AXUIElementGetWindow` API, because that private call
  is flaky across process relaunches. Note it falls back to "first window of the app" if it can't match by
  ID — apps with multiple windows can resolve to the wrong one.
- `_ax_retry()` retries once/backoff on `kAXErrorCannotComplete`, which AX APIs return transiently.

### Alpha/dimming has two independent implementations, chosen by macOS version

`actions.py:adjust_alpha()` branches on `platform.mac_ver()` major version:
- **macOS 15+**: `overlay.py` — a borderless, click-through `NSPanel` is positioned over the target window and
  its own alpha is raised to fake dimming, since `SLSSetWindowAlpha` no longer reliably affects other
  processes' windows on newer macOS. Overlays are tracked in a `window_id → NSPanel` dict and must be
  manipulated on the main thread (`_run_on_main`).
- **macOS 12–14**: `window.py` — the `SkyLight.framework` private API (`SLSSetWindowAlpha`/`SLSGetWindowAlpha`,
  loaded via `ctypes`) sets the real window alpha.

Both paths share a `_alpha_cache` (window_id → opacity) in `actions.py` so relative scroll deltas accumulate
correctly, and `reset_all_alpha()` (called on disable/quit) clears whichever mechanism is active.

### Dead code — don't extend or "fix" these

`src/optsnap/gui.py` and `src/optsnap/event_tap.py` are not imported anywhere in the codebase.
`__main__.py` has its own inline `OptSnapMenuApp` (not the one in `gui.py`), and the tap lifecycle actually
lives in `core.py` (not `event_tap.py`, despite that file's docstring claiming otherwise). Likewise,
`config.py`'s `MODIFIER_NAMES` / `TOGGLE_KEY_NAMES` / `MODIFIER_TO_NAME` exist only for the unused `gui.py`
— the live name/keycode mappings are the private `_MODIFIERS` / `_MODIFIER_NAMES` / `_TOGGLE_KEYCODES` /
`_TOGGLE_KEY_NAMES` defined in `core.py`. When changing modifier/toggle-key behavior, edit `core.py`, not
`config.py`'s display-name maps.

## Configuration

User-facing tunables live in `src/optsnap/config.py` (toggle keycode, modifier name, alpha step/min/max,
minimum window size, health-check interval) and are plain module-level constants — changing them requires
restarting OptSnap, there's no live-reload.

## 窗口置顶（pin.py + native/pin_payload.c）

置顶走的是「注入 Dock 代理」路线，不是直接调用 SkyLight。要改这块之前先理解为什么：

| 调用方式 | 返回值 | 实际效果 |
| --- | --- | --- |
| `SLSSetWindowLevel` → 别的 App 的窗口 | CGError 0 | 层级**不变**（进程归属校验） |
| `SLSSetWindowLevel` → 自己的窗口 | CGError 0 | 层级真实改变 |
| 同一 API，注入 Dock 进程内执行 | CGError 0 | 层级**真实改变** |

所以直接调 API 是「假成功」，必须借 Dock 的进程身份。这和 macOS 15+ 降暗改用 NSPanel
覆盖层是同一类限制（见 `actions.py:_MACOS_MAJOR` 分支）。

### 通道机制

1. `pin.py:_build_payload()` 用 clang 编译 `native/pin_payload.c` 到临时目录（按 mtime 缓存）
2. `pin.py:_inject()` 用 `lldb` 附加 Dock，`dlopen` 载荷（~10-15s，必须在后台线程）
3. 载荷的构造器起轮询线程，每 30ms 读命令文件 `/tmp/optsnap_pin_cmd`
4. `pin.py:_send_command()` 写命令 → 等回执文件 `/tmp/optsnap_pin_ack`（~30ms）
5. 心跳文件 `/tmp/optsnap_pin_heartbeat` 超 5s 未刷新 = 通道已死

注入成功的判据是**心跳文件出现且其中的 pid 等于 Dock 的 pid**，不是 lldb 返回 0。

### 两个容易踩的坑

- **`dlopen` 同一路径不会重跑构造器**。每次注入必须复制成唯一文件名，否则载荷不会
  启动轮询线程，心跳永远不出现。
- **置顶后窗口 layer 不是 0，`window.get_window_at_point` 会跳过它**。所以
  `core.toggle_pin_under_cursor()` 必须先用 `pin.pinned_window_at()` 查已置顶窗口，
  否则第二次按快捷键会命中下层窗口，取消置顶永远失效。`test_pin.py` 里有对应回归测试。

### 权限引导

`permissions.py` 只做检测 + 跳转，不强行拦启动。`missing_for_pin()` 的默认缺失列表
**不含开发者模式**——实测本机 `DevToolsSecurity -status` 显示 disabled 时注入依然成功，
它是排查项不是硬门槛（`pin_troubleshooting_hint()` 里才提）。

## 置顶窗口的描边标记（border.py）

`border.py` 给每个置顶窗口叠一个无边框、点击穿透的 NSPanel，layer 只画一圈 1.5pt 边框。

### 层级选择（不要随意调高）

`BORDER_LEVEL = 4`，刚好比 `PIN_LEVEL_FLOATING = 3` 高一级。**不要**为了「更保险」把它
设到 20 以上：高于程序坞（20）或菜单栏（24）的浮层会盖住系统 UI，看起来像 bug。
`test_pin.py:test_border_level_above_pinned_window` 锁住了这个约束。

### 位置跟随

OptSnap 已经拦下了拖拽事件，但置顶窗口也可能被别的程序移动（动画、脚本、系统重排），
靠事件推断位置不可靠。所以用 `NSTimer` 按 60fps 整表刷新一次 `CGWindowList` —— 一次调用
拿全部窗口几何，比每个窗口单独查便宜得多。定时器只在有描边时运行，空闲时会停掉。

定时器必须加入 `NSRunLoopCommonModes`，否则菜单弹出、窗口拖动等 tracking 模式下不触发，
描边会明显滞后。

### 坐标换算

CG 全局坐标以**主屏左上角**为原点、y 向下；AppKit 以**主屏左下角**为原点、y 向上。
换算是 `ns_y = 主屏高度 - cg_y - 窗口高度`，对副屏同样成立（副屏的 x 为负，y 原样翻）。
`test_pin.py:test_border_coordinate_conversion` 覆盖了这个计算。

### 失败不能影响置顶

描边只是视觉标记。`pin.py:set_pinned()` 里描边调用包在 try/except 里，描边挂了
置顶本身仍然返回成功 —— 否则用户会遇到「明明置顶了却报失败」。

## 图标资源（scripts/make_icon.py / make_menubar_icon.py）

图标由脚本生成，不要手改 PNG。两套图标的规范完全不同，混用会出问题：

| 类型 | 规范 | 生成脚本 |
| --- | --- | --- |
| app 图标 | 1024 画布、圆角矩形主体、彩色、四周留白 9.8%、圆角占主体 22.4% | `make_icon.py` |
| 菜单栏图标 | 22pt（@1x/@2x/@3x）、**纯黑 + 透明背景的模板图** | `make_menubar_icon.py` |

app 图标的比例是从系统自带 `AppIcon.icns`（Calculator）实测反推出来的，不是猜的。

### 菜单栏图标的两个坑

1. **必须是纯黑 + 透明背景**。模板图只有 alpha 有意义，颜色由系统按明暗菜单栏决定。
   用彩色或不透明底图会导致深色菜单栏上显示成一坨方块。
2. **`rumps` 的 `icon` 参数只接受文件路径**，传 `NSImage` 会抛
   `TypeError: expected str, bytes or os.PathLike object, not NSImage`。模板模式用
   `template=True` 参数交给 rumps 处理，不要在外面自己 `setTemplate_`。

菜单栏图形选的是「单窗口 + 向上箭头」而不是像 app 图标那样三层叠放：22pt 下三层
会糊成一团（实测 stroke 挤在一起分不出层次）。

## 置顶的退出还原（pin.py:reset_all_pins / startup_cleanup，core.py:shutdown）

用户要求「退出 OptSnap 时把置顶的窗口全部还原」。做到这一点踩了四个坑，
每个都值得记住，否则改动这块很容易把它们重新引入：

### 坑 1：Python 的 signal 在 rumps 里完全无效

`rumps.App.run()` 最终调用 `AppHelper.runEventLoop()`，这是 Cocoa 的 C 语言级
事件循环，**Python 的信号处理器在里面永远得不到执行机会**。实测 `kill -TERM`
后进程既不退出、清理逻辑也不触发。

正确做法是挂 `NSApplicationWillTerminateNotification`（见 `_install_cocoa_terminate_hook`），
这是 AppKit 自己的退出钩子，菜单退出、Dock 右键退出、系统注销关机都会触发。
signal 那一套留着只对「不经过 rumps 的测试脚本」有用。

### 坑 2：不能只用「层级 != 0」找置顶窗口

系统 UI 的层级是特殊情况：桌面 `-2147483603`、程序坞 `-2147483624`、菜单栏 `24`。
按「不等于 0」判断会把它们也当置顶窗口去改，**直接破坏桌面和程序坞显示**（真实踩过，
最后靠重启 Finder/Dock 才恢复）。

`find_actually_pinned()` 的判据必须是 `PIN_LEVEL_NORMAL < level <= PIN_LEVEL_FLOATING`。

### 坑 3：命令序号会倒退，导致命令静默失效

载荷只执行 `seq > last_seq` 的命令（防重复）。如果本进程的序号比载荷记住的小，
命令会被当成「已处理」全部跳过 —— 没有任何报错，只是静默失效。

序号用时间戳取模初始化是错的（重启后可能比上次小）。现在的做法是：
`_cmd_seq` 用毫秒时间戳初始化，且**每次发命令前**读一次回执里的序号做下限对齐。
不能只在启动时对齐一次 —— 有多个进程共用通道时，谁写回执谁就把进度推高了。

### 坑 4：启动清扫会和用户操作抢窗口

进程被 SIGKILL 时任何清理代码都跑不了，所以要有「启动时清扫上次残留」的兜底。
但清扫在后台线程跑（注入要 10-15 秒），如果用户这时置顶了窗口，清扫会把它当残留清掉。

用 `_startup_lock` + `_startup_done` 做互斥：清扫期间 `set_pinned` 会阻塞等待。

### 退出路径汇总

| 场景 | 是否还原 | 机制 |
| --- | --- | --- |
| 菜单「退出 OptSnap」 | ✅ | `shutdown()` |
| 系统注销/关机 | ✅ | Cocoa 通知 |
| 未捕获异常 | ✅ | `atexit` |
| 进程被 SIGKILL | ❌ 无法（系统限制） | 下次启动的清扫兜底 |
| Dock 重启导致通道失效 | ⚠️ 跳过 | 窗口层级已随 Dock 复位，无需还原 |
