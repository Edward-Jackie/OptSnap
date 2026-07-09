# OptSnap

OptSnap 是一个 macOS 窗口管理工具，灵感来自 AltSnap。它让你不用移动鼠标去找窗口标题栏或边缘，只要按住指定修饰键，就可以直接拖动窗口、调整窗口大小，或通过滚轮调节窗口可见度。

默认操作方式是 **Option + 鼠标**，默认全局开关是 **F8**。所有快捷键都可以在配置文件里调整。

## 主要功能

### 快速移动窗口

按住 **Option**，在任意窗口区域按下鼠标左键并拖动，即可移动窗口。

适合这些场景：

- 窗口标题栏太远，不想移动鼠标到顶部
- 小窗口、浮窗、工具窗口需要快速整理位置
- 多个应用窗口堆叠时，需要快速把目标窗口拖出来

### 快速调整窗口大小

按住 **Option**，在窗口上按下鼠标右键并拖动，即可调整窗口宽高。

调整规则：

- 向右拖动：增加窗口宽度
- 向左拖动：减小窗口宽度
- 向下拖动：增加窗口高度
- 向上拖动：减小窗口高度

OptSnap 会限制窗口最小尺寸，避免把窗口缩到不可用。

### 调节窗口可见度

按住 **Option**，在窗口上滚动鼠标滚轮，即可调节窗口可见度。

- 向下滚动：降低窗口可见度
- 向上滚动：恢复窗口可见度
- 禁用或退出 OptSnap 时，会自动恢复或移除降暗效果

在 macOS 15 及以上版本，OptSnap 使用覆盖层实现窗口降暗；在 macOS 12 到 14 上，会优先使用 SkyLight 私有 API 调节真实透明度。

### 全局启用和禁用

按 **F8** 可以随时启用或禁用 OptSnap。

禁用后：

- 不再拦截鼠标拖拽和滚轮操作
- 已应用的窗口降暗效果会被清理
- 再次按 F8 可以恢复启用

### 菜单栏控制

OptSnap 以 macOS 菜单栏应用运行。菜单栏图标中可以查看当前状态，并切换：

- 启用 / 禁用
- 修饰键
- 激活键

## 系统要求

- macOS 12.0 或更高版本
- Python 3.10 或更高版本
- [uv](https://github.com/astral-sh/uv)

## 安装

进入项目目录后安装依赖：

```bash
uv sync
```

## 授权

OptSnap 需要两个 macOS 系统权限。

### 辅助功能

用于移动和调整其他应用窗口。

路径：

```text
系统设置 -> 隐私与安全性 -> 辅助功能
```

把运行 OptSnap 的 Python、终端应用，或打包后的 OptSnap.app 加进去并启用。

### 输入监听

用于捕获全局鼠标、滚轮和键盘事件。

路径：

```text
系统设置 -> 隐私与安全性 -> 输入监听
```

把运行 OptSnap 的 Python、终端应用，或打包后的 OptSnap.app 加进去并启用。

如果权限刚刚授予但没有生效，请退出 OptSnap 后重新启动。

## 使用方法

### 开发模式运行

```bash
uv run python -m optsnap
```

启动后，菜单栏会出现 OptSnap 图标。保持这个进程运行即可使用窗口拖拽功能。

停止运行：

```bash
Ctrl+C
```

### 使用启动脚本

项目里提供了 `optsnap.sh`：

```bash
./optsnap.sh
```

也可以把它放到 PATH 中，例如改名为 `optsnap` 后从任意位置启动。

### 打包成 macOS App

生成 `OptSnap.app`：

```bash
./build_app.sh
```

运行：

```bash
open build/OptSnap.app
```

如果使用打包后的 App，需要在 macOS 权限设置中给 `OptSnap.app` 授权，而不是只给终端或 Python 授权。

## 常用操作

| 操作 | 默认方式 |
| --- | --- |
| 移动窗口 | 按住 **Option** + 鼠标左键拖动 |
| 调整窗口大小 | 按住 **Option** + 鼠标右键拖动 |
| 降低窗口可见度 | 按住 **Option** + 向下滚轮 |
| 恢复窗口可见度 | 按住 **Option** + 向上滚轮 |
| 启用 / 禁用 OptSnap | 按 **F8** |
| 退出 OptSnap | 菜单栏退出，或终端中按 **Ctrl+C** |

## 配置

编辑配置文件：

```text
src/optsnap/config.py
```

可调整的主要配置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `TOGGLE_KEYCODE` | `100` | 全局启用 / 禁用按键，默认 F8 |
| `MODIFIER_NAME` | `"alternate"` | 操作修饰键，默认 Option |
| `ALPHA_STEP` | `0.05` | 每次滚轮调节可见度的步长 |
| `ALPHA_MIN` | `0.1` | 最低可见度 |
| `ALPHA_MAX` | `1.0` | 最高可见度 |
| `MIN_WINDOW_WIDTH` | `100` | 窗口最小宽度 |
| `MIN_WINDOW_HEIGHT` | `50` | 窗口最小高度 |
| `HEALTH_CHECK_INTERVAL` | `2.0` | 事件监听健康检查间隔，单位秒 |

把修饰键改为 Ctrl：

```python
MODIFIER_NAME = "control"
```

把全局开关改为 F1：

```python
TOGGLE_KEYCODE = 122
```

修改配置后需要重启 OptSnap。

## 技术说明

OptSnap 主要使用以下 macOS 能力：

1. `CGEventTap`：全局捕获鼠标、滚轮和键盘事件
2. `CGWindowList`：查询屏幕窗口位置、尺寸和窗口 ID
3. `AXUIElement`：通过辅助功能 API 移动和调整窗口大小
4. `SkyLight.framework`：在部分系统版本上调节窗口透明度
5. `NSPanel`：在 macOS 15 及以上版本用覆盖层实现窗口降暗

## 常见问题

### 启动后没有反应

检查以下项目：

1. 是否已经授予辅助功能权限
2. 是否已经授予输入监听权限
3. 授权对象是否正确，例如正在运行的是终端、Python，还是 `OptSnap.app`
4. 授权后是否重新启动过 OptSnap

### F8 没有切换状态

通常是输入监听权限未生效。请在系统设置里重新确认权限，然后退出并重新启动 OptSnap。

### 某些窗口无法移动

常见原因：

- 应用处于 macOS 全屏模式
- 窗口属于 Dock、菜单栏、登录界面等系统保护区域
- 某些 Electron 或特殊应用没有暴露完整辅助功能接口

### 降暗效果不生效

请确认：

- OptSnap 正在以 GUI / 菜单栏模式运行
- 目标窗口不是全屏窗口
- 已授予辅助功能和输入监听权限

## 已知限制

- 全屏应用窗口无法控制
- Dock、菜单栏、登录界面等系统保护窗口无法控制
- 多显示器场景仍需要进一步完善
- macOS 15 及以上版本使用覆盖层降暗，不是修改目标窗口真实透明度
- 更换 Python 版本、终端应用或 App 包后，可能需要重新授权

## 项目结构

```text
OptSnap/
├── pyproject.toml
├── README.md
├── build_app.sh
├── optsnap.sh
├── src/optsnap/
│   ├── __main__.py
│   ├── actions.py
│   ├── config.py
│   ├── core.py
│   ├── event_tap.py
│   ├── gui.py
│   ├── overlay.py
│   └── window.py
└── scripts/
    ├── test_actions.py
    ├── test_alpha.py
    ├── test_diagnostic.py
    ├── test_event_tap.py
    ├── test_overlay.py
    └── test_window_move.py
```
