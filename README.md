# OptSnap

macOS 平台类 AltSnap 窗口管理工具。按住修饰键即可拖拽移动、调整窗口大小。

## 功能

- **移动窗口**：按住修饰键 + 鼠标左键拖拽，移动任意窗口（无需点标题栏）
- **调整大小**：按住修饰键 + 鼠标右键拖拽，智能识别边缘/角落进行缩放
- **窗口降暗**：按住修饰键 + 滚轮滚动，实时调节窗口可见度（macOS 15+）
- **全局开关**：按激活键（F8）一键启用/禁用 OptSnap

## 系统要求

- macOS 12.0+（Monterey 或更高版本）
- Python 3.10+
- [uv](https://github.com/astral-sh/uv)（Python 包管理器）

## 安装与使用

### 1. 安装依赖

```bash
uv sync
```

### 2. 授予权限

OptSnap 需要两项 macOS 系统权限：

#### 辅助功能（Accessibility）— 窗口控制
首次运行时，macOS 会弹出系统对话框请求辅助功能权限。点击"允许"或手动前往：

**系统设置 → 隐私与安全性 → 辅助功能 → 开启 Python/终端**

#### 输入监听（Input Monitoring）— 全局事件捕获
首次运行时会在终端提示，请前往：

**系统设置 → 隐私与安全性 → 输入监听 → 点 + → 添加 Python.app 或你的终端应用**

授予权限后，OptSnap 会自动等待并检测到权限生效。

### 3. 运行

```bash
uv run python -m optsnap
```

运行后终端会显示 `[OptSnap] Running`，此时可以开始使用。

按 **F8** 键可切换启用/禁用状态。

按 **Ctrl+C** 终止程序。

## 配置

编辑 `src/optsnap/config.py` 即可自定义所有参数：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `TOGGLE_KEYCODE` | `100` (F8) | 全局激活键 keycode。可选：`107` (Scroll Lock)、`122` (F1)、`120` (F2)、`96` (F5)、`113` (Pause)、`114` (Insert) |
| `MODIFIER_NAME` | `"alternate"` | 修饰键名称。可选：`"alternate"` (Option)、`"control"` (Ctrl)、`"command"` (Cmd) |
| `ALPHA_STEP` | `0.05` | 每次滚轮调节透明度的步长 |
| `ALPHA_MIN` | `0.1` | 最小透明度（0.0 = 完全透明，1.0 = 完全不透明） |
| `ALPHA_MAX` | `1.0` | 最大透明度 |
| `MIN_WINDOW_WIDTH` | `100` | 窗口最小宽度 |
| `MIN_WINDOW_HEIGHT` | `50` | 窗口最小高度 |
| `HEALTH_CHECK_INTERVAL` | `2.0` | 事件监听健康检查间隔（秒） |

### 示例：把激活键改为 F1

```python
TOGGLE_KEYCODE = 122  # F1
```

> 默认激活键为 F8（keycode `100`）。

### 示例：把修饰键从 Option 改为 Ctrl

```python
MODIFIER_NAME = "control"
```

修改后重启 OptSnap 即可生效。

## 使用说明

| 操作 | 方式 |
|------|------|
| 移动窗口 | 按住 **Option** + 鼠标左键拖拽 |
| 调整大小 | 按住 **Option** + 鼠标右键拖拽（向右/下=放大，向左/上=缩小） |
| 降暗窗口 | 按住 **Option** + 向下滚轮（向上滚轮恢复） |
| 启用/禁用 | 按 **F8** 键 |

### 调整大小说明

右键拖拽时，窗口按鼠标移动方向直接调整宽高：
- 向右拖 → 宽度增加
- 向下拖 → 高度增加
- 向左拖 → 宽度减小
- 向上拖 → 高度减小

## 技术原理

1. **CGEventTap** — 在系统会话级别全局捕获鼠标和键盘事件
2. **CGWindowList** — 通过 CoreGraphics 查询窗口位置和尺寸（比 AX API 更稳定）
3. **AXUIElement** — 通过辅助功能 API 设置窗口位置和大小
4. **AXValueCreate** — 通过 pyobjc 的 AXValue 接口传递位置/尺寸值给 AX API
5. **SkyLight.framework** — 透明度功能预留接口（macOS 15+ 暂不可用）

## 常见问题

### 运行后没反应
1. 检查是否已授予 **辅助功能** 和 **输入监听** 两项权限
2. 授予权限后，如果程序已在运行，请重启 OptSnap
3. 终端查看日志输出，确认显示 `[OptSnap] Running`

### 某个窗口无法移动
- **全屏应用**：macOS 全屏模式下的窗口不受 AX API 控制
- **系统保护窗口**：Dock、菜单栏、登录界面等受 SIP 保护，无法操作
- **Electron 应用**（如 VSCode、Discord）：部分 Electron 应用需要开启增强辅助接口

### 降暗效果不生效
- macOS 15 (Sequoia) 上使用叠加层降暗方案，需要 OptSnap 以 GUI 模式运行（菜单栏图标可见）
- 全屏应用窗口可能无法被叠加层覆盖
- 按 **F8** 禁用 OptSnap 或退出程序时，所有降暗叠加层会自动移除
- macOS 12–14：通过 SkyLight 私有 API 实现真实透明度，极少数特殊窗口可能不支持

### 重置权限
如果权限配置混乱，可以重置后重新授予：

```bash
# 重置 Python 的所有权限
sudo tccutil reset All com.apple.python3
```

## 已知限制

- 不支持多显示器（MVP 版本）
- 全屏应用无法控制
- SIP 保护的窗口（Dock、菜单栏、登录界面）无法操作
- **窗口降暗**：macOS 15+ (Sequoia) 封锁了 SkyLight 跨进程 alpha API，改用叠加层降暗方案（需 GUI 模式）；macOS 12–14 支持真实透明度
- 权限是授予 Python 解释器的，更换 Python 版本后需重新授权
- 休眠唤醒后可能有短暂的事件丢失（健康检查会自动恢复）

## 项目结构

```
OptSnap/
├── pyproject.toml              # uv 项目配置，pyobjc 依赖
├── README.md                   # 本文档
├── src/optsnap/
│   ├── __init__.py
│   ├── __main__.py             # 入口：权限引导 + 事件循环 + 全局开关
│   ├── config.py               # 可配置参数（激活键、修饰键、透明度步长等）
│   ├── event_tap.py            # CGEventTap 常量
│   ├── window.py               # CGWindowList + AXUIElement + SkyLight 私有 API
│   └── actions.py              # 移动/缩放/透明度动作逻辑
└── scripts/
    ├── test_event_tap.py       # 事件捕获测试
    ├── test_window_move.py     # 窗口移动测试
    ├── test_alpha.py           # 透明度测试
    └── test_actions.py         # 动作逻辑单元测试
```
