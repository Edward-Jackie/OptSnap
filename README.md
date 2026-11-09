# OptSnap

OptSnap 是一个 macOS 窗口管理工具，灵感来自 AltSnap。不用去找窗口标题栏或边缘：按住修饰键，直接在窗口任意位置拖动、缩放，或用滚轮调节可见度。

还可以把任意窗口钉在最上层——这一项 AltSnap 有、macOS 原生没有。

默认 **Option + 鼠标**操作，**F8** 全局开关，**⌥⇧P** 置顶。所有键位都能在配置里改。

## 功能一览

| 操作 | 默认方式 |
| --- | --- |
| 移动窗口 | 按住 **Option** + 鼠标左键拖动 |
| 调整窗口大小 | 按住 **Option** + 鼠标右键拖动 |
| 降低窗口可见度 | 按住 **Option** + 向下滚轮 |
| 恢复窗口可见度 | 按住 **Option** + 向上滚轮 |
| 置顶 / 取消置顶指针下的窗口 | 按 **⌥⇧P** |
| 启用 / 禁用 OptSnap | 按 **F8** |
| 退出 OptSnap | 菜单栏退出，或终端中按 **Ctrl+C** |

## 主要功能

### 快速移动窗口

按住 **Option**，在任意窗口区域按下鼠标左键并拖动，即可移动窗口。

适合这些场景：

- 窗口标题栏太远，不想移动鼠标到顶部
- 小窗口、浮窗、工具窗口需要快速整理位置
- 多个应用窗口堆叠时，需要快速把目标窗口拖出来

### 快速调整窗口大小

按住 **Option**，在窗口上按下鼠标右键并拖动，即可调整窗口宽高。

- 向右拖动：增加宽度
- 向左拖动：减小宽度
- 向下拖动：增加高度
- 向上拖动：减小高度

OptSnap 会限制窗口最小尺寸，避免把窗口缩到不可用。

### 调节窗口可见度

按住 **Option**，在窗口上滚动鼠标滚轮。

- 向下滚动：降低可见度
- 向上滚动：恢复可见度

在 macOS 15 及以上版本，OptSnap 使用覆盖层实现窗口降暗；macOS 12 到 14 上优先使用 SkyLight 私有 API 调节真实透明度。

### 窗口置顶

**把鼠标指针移到目标窗口上**，按 **⌥⇧P**（Option + Shift + P），这个窗口就会钉在最上层。

- 再按一次：取消置顶
- 菜单栏「取消全部置顶」：一次性还原所有置顶窗口
- 置顶热键可在菜单里轮换：`⌥⇧P` / `⌥⌃P` / `⌥⇧O` / `⌥⇧T` / `⌥⇧R`

**置顶的窗口会显示一圈细蓝边**，一眼能看出哪些窗口生效了。蓝边跟随窗口移动；窗口最小化或切到其它桌面时，蓝边自动隐藏。

几个要点：

- 热键作用于**鼠标指针所在的那个窗口**，不是当前激活的窗口
- 置顶和「启用 / 禁用」是并列功能：即使 OptSnap 处于禁用状态，热键依然可用
- **退出 OptSnap 时会自动还原所有置顶窗口**，不会留下卡在浮层的窗口

> **为什么用组合键而不是单按 F9**：不少 Mac 键盘处于「媒体键」模式，按 F9 发出的是媒体键事件（`NSSystemDefined`）而非标准 keyDown，单键热键收不到。组合键走正常的 keyDown 通道，不受该模式影响。

实现上，OptSnap 会把一小段原生载荷注入 Dock 进程，由 Dock 代为调用 SkyLight 私有 API。原因见[技术说明](#为什么置顶要借-dock-进程)。

> **前置条件**：置顶需要 macOS 15+ 和 Xcode 命令行工具。首次使用会花 10-15 秒建立通道，之后每次切换约 30-70 毫秒。这一步失败不影响其它功能，菜单栏会显示缺什么、并给出可直接点击的处理入口。

### 全局启用和禁用

按 **F8** 随时启用或禁用 OptSnap。禁用后：

- 不再拦截鼠标拖拽和滚轮
- 已应用的降暗效果被清理
- 已置顶的窗口被还原

### 菜单栏

OptSnap 以菜单栏应用运行。点开图标可以看到：

- 当前启用状态
- 「切换启用/禁用」
- 修饰键、激活键
- 「置顶指针下的窗口」、置顶热键、置顶状态
- 「取消全部置顶」
- 权限状态区

权限缺失时，对应菜单项可以直接点击跳到系统设置；缺 Xcode 命令行工具时有安装入口。

## 系统要求

- macOS 12.0 或更高版本（置顶功能需 macOS 15+）
- Python 3.10 或更高版本
- [uv](https://github.com/astral-sh/uv)
- Xcode 命令行工具（仅置顶功能需要）

## 安装

```bash
uv sync
```

## 授权

OptSnap 需要两个系统权限。

### 辅助功能

用于移动、调整其它应用窗口。

```text
系统设置 → 隐私与安全性 → 辅助功能
```

把运行 OptSnap 的 Python、终端应用，或打包后的 `OptSnap.app` 加进去并启用。

### 输入监听

用于捕获全局鼠标、滚轮和键盘事件。

```text
系统设置 → 隐私与安全性 → 输入监听
```

把同样的程序加进去并启用。

如果刚授权但没生效，退出 OptSnap 重新启动。更换 Python 版本、终端应用或 App 包之后，可能需要重新授权。

## 使用方法

### 开发模式

```bash
uv run python -m optsnap
```

菜单栏出现图标后即可使用。停止：`Ctrl+C`。

### 启动脚本

```bash
./optsnap.sh
```

也可以把它放进 PATH，改名 `optsnap` 后从任意位置启动。

### 打包成 App

```bash
./build_app.sh
open build/OptSnap.app
```

使用打包后的 App 时，需要在系统权限里给 `OptSnap.app` 授权，而不是只给终端或 Python。

## 配置

编辑 `src/optsnap/config.py`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `TOGGLE_KEYCODE` | `100` | 全局启用 / 禁用按键，默认 F8 |
| `PIN_HOTKEY_KEYCODE` | `35` | 置顶热键的字母键码，默认 P |
| `PIN_HOTKEY_MODIFIERS` | `["alternate", "shift"]` | 置顶热键的修饰键组合 |
| `MODIFIER_NAME` | `"alternate"` | 拖拽操作修饰键，默认 Option |
| `ALPHA_STEP` | `0.05` | 每次滚轮调节可见度的步长 |
| `ALPHA_MIN` | `0.1` | 最低可见度 |
| `ALPHA_MAX` | `1.0` | 最高可见度 |
| `MIN_WINDOW_WIDTH` | `100` | 窗口最小宽度 |
| `MIN_WINDOW_HEIGHT` | `50` | 窗口最小高度 |
| `HEALTH_CHECK_INTERVAL` | `2.0` | 事件监听健康检查间隔（秒） |
| `PIN_LEVEL_FLOATING` | `3` | 置顶时使用的窗口层级 |
| `BORDER_WIDTH` | `1.5` | 置顶标记的描边线宽 |
| `BORDER_COLOR` | `(0.20, 0.60, 1.0, 0.9)` | 置顶标记的描边颜色 |
| `BORDER_LEVEL` | `4` | 描边面板层级，需高于置顶层级 |
| `BORDER_REFRESH_INTERVAL` | `1/60` | 描边跟随窗口的刷新间隔（秒） |

改几个常见项：

```python
# 修饰键改为 Ctrl
MODIFIER_NAME = "control"

# 全局开关改为 F1
TOGGLE_KEYCODE = 122

# 置顶热键改为 ⌥⌃P
PIN_HOTKEY_MODIFIERS = ["alternate", "control"]

# 描边更粗更显眼
BORDER_WIDTH = 2.5
```

修改后需要重启 OptSnap（没有热重载）。

## 技术说明

OptSnap 用到的 macOS 能力：

1. `CGEventTap` —— 全局捕获鼠标、滚轮、键盘事件
2. `CGWindowList` —— 查询窗口位置、尺寸、窗口 ID
3. `AXUIElement` —— 通过辅助功能 API 移动 / 调整窗口
4. `SkyLight.framework` —— 部分系统版本上调节窗口透明度
5. `NSPanel` —— macOS 15+ 用覆盖层实现降暗，以及置顶窗口的描边
6. 注入 Dock 进程 —— 由 Dock 代为修改窗口层级（置顶）

### 为什么置顶要借 Dock 进程

`SLSSetWindowLevel` 是 SkyLight 里改窗口层级的私有 API。从 macOS 15 开始，对**其它进程**的窗口调用它会返回成功（`CGError 0`），但层级实际不变——底层加了进程归属校验。

实测对照（macOS 15.2）：

| 调用方式 | 返回值 | 实际效果 |
| --- | --- | --- |
| `SLSSetWindowLevel` → 别的 App 的窗口 | 0（假成功） | 层级不变 |
| `SLSSetWindowLevel` → 自己的窗口 | 0 | 层级真实改变 |
| `SLSSetWindowAlpha` → 别的 App 的窗口 | 0（假成功） | alpha 读回仍是 1.0 |
| `CGSSetWindowLevel` / `SLSOrderWindow` / `SLSSetWindowSubLevel` | 0 / 1000 / -1 | 全部无效 |
| **注入 Dock 后调用 `SLSSetWindowLevel`** | 0 | **层级真实改变** |

Dock 是系统进程，用它自己的 SLS 连接就能改。yabai 的 `scripting-addition` 用的是同一原理。

验证方式是看窗口栈序：把层级设为 `-1`，窗口沉到所有普通窗口之下；设回 `3`，又浮到最上层。两条独立读取路径（`CGWindowListCopyWindowInfo` 的 layer 字段和 `SLSWindowIteratorGetLevel`）读数一致。

### 置顶通道的生命周期

1. 启动时后台编译载荷（`src/optsnap/native/pin_payload.c` → dylib，缓存到临时目录）
2. 后台用 `lldb` 附加 Dock，`dlopen` 载荷，约 10-15 秒
3. 载荷构造器启动轮询线程，每 30ms 检查命令文件，同时刷新心跳文件
4. 每次切换置顶：写命令文件 → 等回执，约 30ms

心跳文件超过 5 秒未刷新，就认为通道已死（例如 Dock 重启过），下次触发时重新注入。

### 退出还原

| 场景 | 是否还原 | 机制 |
| --- | --- | --- |
| 菜单「退出 OptSnap」 | ✅ | `core.shutdown()` |
| 系统注销 / 关机 | ✅ | Cocoa 退出通知 |
| 程序异常 | ✅ | `atexit` 兜底 |
| 进程被 `SIGKILL` | ❌ 系统限制 | 下次启动时自动清扫 |
| Dock 重启导致通道失效 | ⚠️ 跳过 | 窗口层级已随 Dock 复位 |

还原时会同时参考「内存里记录的置顶窗口」和「扫描系统里真实处于浮层的窗口」，后者用于兜住状态丢失的情况。判断范围严格限制在 `0 < 层级 ≤ 3`，避免误改系统 UI（桌面是 `-2147483603`、程序坞是 `-2147483624`、菜单栏是 `24`）。

### 图标

图标由脚本生成，不手改 PNG：

- `scripts/make_icon.py` —— App 图标，1024 画布、四周留白 9.8%、圆角占主体 22.4%，比例取自系统自带图标实测
- `scripts/make_menubar_icon.py` —— 菜单栏图标，22pt（@1x/@2x/@3x），纯黑 + 透明背景的模板图

## 常见问题

### 启动后没有反应

1. 是否已授予辅助功能权限
2. 是否已授予输入监听权限
3. 授权对象是否正确（终端、Python，还是 `OptSnap.app`）
4. 授权后是否重启过 OptSnap

### F8 没有切换状态

通常是输入监听权限未生效。重新确认权限后退出并重启 OptSnap。

### 某些窗口无法移动

- 应用处于 macOS 全屏模式
- 窗口属于 Dock、菜单栏、登录界面等系统保护区域
- 某些 Electron 应用没有暴露完整辅助功能接口

### 降暗效果不生效

- 确认 OptSnap 以 GUI / 菜单栏模式运行
- 目标窗口不是全屏窗口
- 已授予辅助功能和输入监听权限

### 按 ⌥⇧P 没有置顶反应

先在菜单栏看「置顶状态」：

- **不支持（需 macOS 15+）** —— 系统版本太低
- **通道未就绪** —— 注入还没完成或失败了，菜单底部会显示缺什么

常见原因：

1. 没装 Xcode 命令行工具（菜单里有安装入口）
2. Dock 刚重启过，通道失效 —— 重启 OptSnap 重新注入
3. 系统安全策略变化导致 lldb 无法附加 Dock

> `DevToolsSecurity -status` 显示 disabled 时依然可以注入成功，它只是排查项，不是硬门槛。实测这台机器上就是 disabled 状态但注入正常。

### 置顶后分不清哪些窗口生效了

看窗口边缘有没有细蓝边。如果蓝边没出现，说明置顶没成功——回到上一条检查通道状态。

### 置顶的窗口找不到了

如果窗口被拖到屏幕外或其它工作空间，它会保持置顶但看不见。菜单栏点「取消全部置顶」还原。

## 已知限制

- 全屏应用窗口无法控制，也无法置顶
- Dock、菜单栏、登录界面等系统保护窗口无法控制
- 多显示器场景未充分验证
- macOS 15+ 用覆盖层降暗，不是修改目标窗口真实透明度
- 置顶需要 macOS 15+，每次 macOS 大版本升级后可能需要重新验证
- 置顶通道依赖 lldb 附加 Dock，是调试通道而非公开 API，系统安全策略收紧时可能失效
- 进程被 `SIGKILL` 时无法还原置顶，靠下次启动清扫

## 项目结构

```text
OptSnap/
├── README.md
├── CLAUDE.md                    # 架构说明与踩坑记录（给 AI / 开发者看）
├── build_app.sh                 # 打包成 .app
├── optsnap.sh                   # 开发模式启动脚本
├── pyproject.toml
├── setup.py
├── assets/
│   └── icon.icns                # App 图标（脚本生成）
├── src/optsnap/
│   ├── __main__.py              # 菜单栏入口、权限引导、退出钩子
│   ├── core.py                  # 事件 tap、状态机、shutdown
│   ├── actions.py               # 移动 / 缩放 / 透明度动作
│   ├── window.py                # 窗口查询与几何操作
│   ├── overlay.py               # macOS 15+ 降暗覆盖层
│   ├── pin.py                   # 置顶（通道管理、状态、还原）
│   ├── border.py                # 置顶窗口的描边标记
│   ├── permissions.py           # 权限检测与跳转引导
│   ├── config.py                # 全部可调参数
│   ├── event_tap.py             # 【未使用】历史遗留
│   ├── gui.py                   # 【未使用】历史遗留
│   ├── native/
│   │   └── pin_payload.c        # 注入 Dock 的原生载荷
│   └── resources/
│       ├── menubar_icon.png     # 菜单栏模板图（@1x/@2x/@3x）
│       ├── menubar_icon@2x.png
│       └── menubar_icon@3x.png
└── scripts/
    ├── make_icon.py             # 生成 App 图标
    ├── make_menubar_icon.py     # 生成菜单栏图标
    ├── test_actions.py          # 动作逻辑单元测试（纯 mock，可无副作用运行）
    ├── test_pin.py              # 置顶逻辑单元测试（27 项）
    ├── test_alpha.py            # 手动调试脚本
    ├── test_diagnostic.py       # 手动调试脚本
    ├── test_event_tap.py        # 手动调试脚本
    ├── test_overlay.py          # 手动调试脚本
    ├── test_window_move.py      # 手动调试脚本
    └── inject-poc/              # 注入方案可行性验证（调研产物）
```

### 测试说明

没有 pytest 配置，`scripts/test_*.py` 是独立脚本，直接运行：

```bash
uv run python scripts/test_actions.py
uv run python scripts/test_pin.py
```

只有 `test_actions.py` 和 `test_pin.py` 是纯单元测试（mock 掉系统调用，无副作用）。
其余是手动调试脚本，需要真实权限和桌面环境，会触碰真实窗口——不要指望它们给出快速确定的结果。

## 许可

个人项目，仅供自用参考。
