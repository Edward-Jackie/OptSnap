# CLAUDE.md

本文件给 AI 编码助手（Claude Code 等）和开发者看，记录架构决策与踩过的坑。
面向用户的使用说明在 [README.md](README.md)。

## 这是什么

OptSnap 是一个 macOS 菜单栏工具，灵感来自 AltSnap：按住修饰键（默认 Option）+ 鼠标，直接在窗口
任意位置拖动、缩放、调透明度，不需要去抓标题栏或边缘。另外支持把任意窗口钉在最上层——AltSnap
有这个功能，macOS 原生没有。

技术上是一个 PyObjC 应用：
- `CGEventTap` 拦截全局鼠标/键盘事件
- `AXUIElement` 移动/调整窗口
- `SkyLight` 私有框架或 `NSPanel` 覆盖层做窗口降暗（按 macOS 版本二选一）
- 注入 Dock 进程改窗口层级（置顶）

只在 macOS 上运行。

## 常用命令

```bash
uv sync                        # 安装依赖
uv run python -m optsnap       # 开发模式运行（菜单栏应用，前台）
./optsnap.sh                   # 上面那条的包装脚本
./build_app.sh                 # 打包成 build/OptSnap.app（手工打包，不走 setup.py/py2app）
open build/OptSnap.app         # 运行打包后的 app

# 重新生成图标
uv run --with pillow python scripts/make_icon.py /tmp/icon.iconset
uv run --with pillow python scripts/make_menubar_icon.py src/optsnap/resources
```

没有配置 linter / formatter（无 ruff/flake8/mypy），也没有 CI。`setup.py` 里虽然声明了 py2app
构建，但实际打包路径是 `build_app.sh`——不要假设 `python setup.py py2app` 能产出发布物。

### 测试

没有 pytest 配置，`scripts/test_*.py` 是独立脚本。直接跑：

```bash
uv run python scripts/test_actions.py
uv run python scripts/test_pin.py
```

每个脚本逐项打印 PASS/FAIL，失败时退出码非零。

只有 **`test_actions.py`** 和 **`test_pin.py`** 是纯单元测试：mock 掉系统调用，无副作用，
可以无脑跑。

其余是**手动调试脚本，会触碰真实 macOS 状态**——需要已授予辅助功能/输入监听权限、有活跃桌面会话，
有几个还会等待真实鼠标输入或真的去移动/缩放/降暗光标下的窗口：
`test_alpha.py`、`test_diagnostic.py`、`test_event_tap.py`、`test_overlay.py`、
`test_window_move.py`。不要指望它们给出快速确定的结果。

## 需要的 macOS 权限

应用需要对**运行它的那个进程**授予两项 TCC 权限（开发模式下是 Python/终端，打包后是
`OptSnap.app`——授给其中一个不会覆盖另一个）：

- **辅助功能**（`AXUIElement*`）——移动/调整其它应用的窗口
- **输入监听**——让 `CGEventTap` 能看到全局鼠标/键盘事件

`core.py` 的 `OptSnapCore.check_permissions()` / `request_accessibility()` 负责检测和弹窗；
`__main__.py:main()` 在启动时轮询等待两者就绪后才启动事件循环。

`permissions.py` 只做检测 + 跳转系统设置，**不强行拦启动**——缺权限时菜单里给引导，让用户自己处理。

## 架构

### 事件流与状态机

所有事件汇总到 `OptSnapCore`（`core.py`）持有的唯一一个 `CGEventTap`，跑在独立后台线程
（`run_in_thread()` → `CFRunLoopRun()`），与主线程的 `rumps` 菜单栏应用分离。

`OptSnapCore._event_callback` 是一个围绕 `self.mode` 的小状态机：`idle → moving/resizing → idle`，
由原始的 `kCGEventLeftMouseDown/Dragged/Up`、`kCGEventRightMouseDown/Dragged/Up` 驱动，前提是配置的
修饰键处于按下状态。滚轮事件直接从 `idle` 调整透明度，没有单独的“alpha”模式。

热键检查放在最前面，即使 tap 处于禁用状态：
- 全局开关（默认 F8）
- 置顶热键（默认 ⌥⇧P），组合键必须**精确匹配**修饰键掩码

跨线程 UI 更新要特别注意：`OptSnapCore.toggle()` 把 `on_state_change` 派发到
`AppKit.NSOperationQueue.mainQueue()` 而不是内联调用，因为在 tap 线程上直接做 AppKit 操作会卡住
回调，长到 macOS 触发 `kCGEventTapDisabledByTimeout` 把 tap 干掉。

tap 有自愈机制：`CFRunLoopTimer`（`HEALTH_CHECK_INTERVAL`）检查 `CGEventTapIsEnabled`，发现
被禁用（超时或 TCC 撤销）就调 `_recreate_tap()`。

### 窗口 I/O 分工：读用 CGWindowList，写用 AXUIElement

`window.py` 刻意把“查询窗口几何”和“设置窗口几何”分开：

- **读**（位置、尺寸、按坐标命中窗口）走 `CGWindowListCopyWindowInfo`——比解析 `AXValue` 可靠
- **写**（位置、尺寸）走 `AXUIElementSetAttributeValue`，因为 `CGWindowList` 是只读的
- 从 `CGWindowList` 找到窗口后拿 `AXUIElementRef`，用的是基于 PID 的查找（`_get_ax_window_for_pid`）
  而不是私有 API `_AXUIElementGetWindow`，因为后者跨进程重启时不可靠。注意它在匹配不到 ID 时
  会退化成“该应用的第一个窗口”——多窗口应用可能拿错窗口
- `_ax_retry()` 对 `kAXErrorCannotComplete` 做一次退避重试，AX API 会瞬时返回这个错误

### 降暗有两套独立实现，按 macOS 版本选择

`actions.py:adjust_alpha()` 按 `platform.mac_ver()` 的主版本号分支：

- **macOS 15+**：`overlay.py`——一个无边框、点击穿透的 `NSPanel` 叠在目标窗口上，抬高它自己的
  alpha 来伪造降暗。因为 `SLSSetWindowAlpha` 在新系统上对其它进程的窗口不再可靠生效（和置顶遇到
  的是同一个跨进程限制）。覆盖层存在 `window_id → NSPanel` 字典里，必须在主线程操作（`_run_on_main`）
- **macOS 12–14**：`window.py`——`SkyLight.framework` 私有 API（`SLSSetWindowAlpha`/`SLSGetWindowAlpha`，
  通过 `ctypes` 加载）设置真实窗口 alpha

两条路径共享 `actions.py` 里的 `_alpha_cache`（window_id → 不透明度），让相对的滚轮增量能正确累积；
`reset_all_alpha()`（禁用/退出时调用）负责清除当前生效的那种机制。

### 死代码——不要扩展或“修复”它们

`src/optsnap/gui.py` 和 `src/optsnap/event_tap.py` 在任何地方都没有被 import。
`__main__.py` 有自己内联的 `OptSnapMenuApp`（不是 `gui.py` 里那个），tap 的生命周期实际在 `core.py`
里（不是 `event_tap.py`，尽管那个文件的 docstring 声称如此）。同样，`config.py` 里的
`MODIFIER_NAMES` / `TOGGLE_KEY_NAMES` / `MODIFIER_TO_NAME` 只服务于未使用的 `gui.py`——
实际在用的名称/键码映射是 `core.py` 里的私有 `_MODIFIERS` / `_MODIFIER_NAMES` /
`_TOGGLE_KEYCODES` / `_TOGGLE_KEY_NAMES`。改修饰键/热键行为时改 `core.py`，不是 `config.py` 里
那几组显示名映射。

## 配置

面向用户的调参项都在 `src/optsnap/config.py`（开关热键、置顶热键、修饰键、透明度步长/上下限、
窗口最小尺寸、健康检查间隔、描边样式），全是模块级常量——改了要重启 OptSnap，没有热重载。

## 窗口置顶（pin.py + native/pin_payload.c）

置顶走的是“注入 Dock 代理”路线，不是直接调用 SkyLight。改这块之前先理解为什么：

| 调用方式 | 返回值 | 实际效果 |
| --- | --- | --- |
| `SLSSetWindowLevel` → 别的 App 的窗口 | CGError 0 | 层级**不变**（进程归属校验） |
| `SLSSetWindowLevel` → 自己的窗口 | CGError 0 | 层级真实改变 |
| 同一 API，注入 Dock 进程内执行 | CGError 0 | 层级**真实改变** |

所以直接调 API 是“假成功”，必须借 Dock 的进程身份。这和 macOS 15+ 降暗改用 NSPanel 覆盖层是
同一类限制（见 `actions.py:_MACOS_MAJOR` 分支）。

### 通道机制

1. `pin.py:_build_payload()` 用 clang 编译 `native/pin_payload.c` 到临时目录（按 mtime 缓存）
2. `pin.py:_inject()` 用 `lldb` 附加 Dock，`dlopen` 载荷（约 10-15s，必须在后台线程）
3. 载荷构造器起轮询线程，每 30ms 读命令文件 `/tmp/optsnap_pin_cmd`
4. `pin.py:_send_command()` 写命令 → 等回执文件 `/tmp/optsnap_pin_ack`（约 30ms）
5. 心跳文件 `/tmp/optsnap_pin_heartbeat` 超 5s 未刷新 = 通道已死

注入成功的判据是**心跳文件出现且其中的 pid 等于 Dock 的 pid**，不是 lldb 返回 0。

### 三个容易踩的坑

1. **`dlopen` 同一路径不会重跑构造器**。每次注入必须复制成唯一文件名，否则载荷不会启动轮询线程，
   心跳永远不出现。

2. **置顶后窗口 layer 不是 0，`window.get_window_at_point` 会跳过它**。所以
   `core.toggle_pin_under_cursor()` 必须先用 `pin.pinned_window_at()` 查已置顶窗口，否则第二次按
   快捷键会命中下层窗口，取消置顶永远失效。`test_pin.py` 有对应回归测试。

3. **命令序号会倒退会导致静默失效**，详见下面“退出还原”的坑 3。

### 权限引导

`permissions.py` 只做检测 + 跳转，不强行拦启动。`missing_for_pin()` 的默认缺失列表**不含开发者
模式**——实测本机 `DevToolsSecurity -status` 显示 disabled 时注入依然成功，它是排查项不是硬门槛
（`pin_troubleshooting_hint()` 里才提）。

## 置顶窗口的描边标记（border.py）

`border.py` 给每个置顶窗口叠一个无边框、点击穿透的 NSPanel，layer 只画一圈 1.5pt 边框。

### 层级选择（不要随意调高）

`BORDER_LEVEL = 4`，刚好比 `PIN_LEVEL_FLOATING = 3` 高一级。**不要**为了“更保险”把它设到 20 以上：
高于程序坞（20）或菜单栏（24）的浮层会盖住系统 UI，看起来像 bug。
`test_pin.py:test_border_level_above_pinned_window` 锁住了这个约束。

### 位置跟随

OptSnap 已经拦下了拖拽事件，但置顶窗口也可能被别的程序移动（动画、脚本、系统重排），靠事件推断
位置不可靠。所以用 `NSTimer` 按 60fps 整表刷新一次 `CGWindowList`——一次调用拿全部窗口几何，比每个
窗口单独查便宜得多。定时器只在有描边时运行，空闲时会停掉。

定时器必须加入 `NSRunLoopCommonModes`，否则菜单弹出、窗口拖动等 tracking 模式下不触发，描边会明显滞后。

### 坐标换算

CG 全局坐标以**主屏左上角**为原点、y 向下；AppKit 以**主屏左下角**为原点、y 向上。
换算是 `ns_y = 主屏高度 - cg_y - 窗口高度`，对副屏同样成立（副屏的 x 为负，y 原样翻）。
`test_pin.py:test_border_coordinate_conversion` 覆盖了这个计算。

### 失败不能影响置顶

描边只是视觉标记。`pin.py:set_pinned()` 里描边调用包在 try/except 里，描边挂了置顶本身仍然返回成功——
否则用户会遇到“明明置顶了却报失败”。

## 图标资源（scripts/make_icon.py / make_menubar_icon.py）

图标由脚本生成，不要手改 PNG。两套图标的规范完全不同，混用会出问题：

| 类型 | 规范 | 生成脚本 |
| --- | --- | --- |
| App 图标 | 1024 画布、圆角矩形主体、彩色、四周留白 9.8%、圆角占主体 22.4% | `make_icon.py` |
| 菜单栏图标 | 22pt（@1x/@2x/@3x）、**纯黑 + 透明背景的模板图** | `make_menubar_icon.py` |

App 图标的比例是从系统自带 `AppIcon.icns`（Calculator）实测反推出来的，不是猜的。

### 菜单栏图标的两个坑

1. **必须是纯黑 + 透明背景**。模板图只有 alpha 有意义，颜色由系统按明暗菜单栏决定。用彩色或不透明
   底图会导致深色菜单栏上显示成一坨方块。
2. **`rumps` 的 `icon` 参数只接受文件路径**，传 `NSImage` 会抛
   `TypeError: expected str, bytes or os.PathLike object, not NSImage`。模板模式用 `template=True`
   参数交给 rumps 处理，不要在外面自己 `setTemplate_`。

菜单栏图形选的是“单窗口 + 向上箭头”而不是像 App 图标那样三层叠放：22pt 下三层会糊成一团
（实测 stroke 挤在一起分不出层次）。

## 退出还原（pin.py:reset_all_pins / startup_cleanup，core.py:shutdown）

要求是“退出 OptSnap 时把置顶的窗口全部还原”。做到这一点踩了四个坑，每个都值得记住，否则改动这块
很容易把它们重新引入：

### 坑 1：Python 的 signal 在 rumps 里完全无效

`rumps.App.run()` 最终调用 `AppHelper.runEventLoop()`，这是 Cocoa 的 C 语言级事件循环，
**Python 的信号处理器在里面永远得不到执行机会**。实测 `kill -TERM` 后进程既不退出、清理逻辑也不触发。

正确做法是挂 `NSApplicationWillTerminateNotification`（见 `_install_cocoa_terminate_hook`），
这是 AppKit 自己的退出钩子，菜单退出、Dock 右键退出、系统注销关机都会触发。
signal 那一套留着只对“不经过 rumps 的测试脚本”有用。

### 坑 2：不能只用“层级 != 0”找置顶窗口

系统 UI 的层级是特殊情况：桌面 `-2147483603`、程序坞 `-2147483624`、菜单栏 `24`。
按“不等于 0”判断会把它们也当置顶窗口去改，**直接破坏桌面和程序坞显示**（真实踩过，最后靠重启
Finder/Dock 才恢复）。

`find_actually_pinned()` 的判据必须是 `PIN_LEVEL_NORMAL < level <= PIN_LEVEL_FLOATING`。

### 坑 3：命令序号会倒退，导致命令静默失效

载荷只执行 `seq > last_seq` 的命令（防重复）。如果本进程的序号比载荷记住的小，命令会被当成
“已处理”全部跳过——没有任何报错，只是静默失效。

序号用时间戳取模初始化是错的（重启后可能比上次小）。现在的做法是：`_cmd_seq` 用毫秒时间戳初始化，
且**每次发命令前**读一次回执里的序号做下限对齐。不能只在启动时对齐一次——有多个进程共用通道时，
谁写回执谁就把进度推高了。

### 坑 4：启动清扫会和用户操作抢窗口

进程被 SIGKILL 时任何清理代码都跑不了，所以要有“启动时清扫上次残留”的兜底。但清扫在后台线程跑
（注入要 10-15 秒），如果用户这时置顶了窗口，清扫会把它当残留清掉。

用 `_startup_lock` + `_startup_done` 做互斥：清扫期间 `set_pinned` 会阻塞等待。

### 退出路径汇总

| 场景 | 是否还原 | 机制 |
| --- | --- | --- |
| 菜单“退出 OptSnap” | ✅ | `shutdown()` |
| 系统注销/关机 | ✅ | Cocoa 通知 |
| 未捕获异常 | ✅ | `atexit` |
| 进程被 SIGKILL | ❌ 无法（系统限制） | 下次启动的清扫兜底 |
| Dock 重启导致通道失效 | ⚠️ 跳过 | 窗口层级已随 Dock 复位，无需还原 |

## 调研产物

`scripts/inject-poc/` 是确定“置顶能否实现”时留下的可行性验证，不是产品代码，不需要维护。
里面记录了完整的实测数据（哪种私有 API 跨进程有效、哪种是假成功）。要重新评估 macOS 新版本的
行为时，可以从那里开始。
