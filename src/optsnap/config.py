"""OptSnap 配置 —— 修改这些值来定制行为。"""

# ── 全局开关热键 ─────────────────────────────────────────────────────────
# 按下该键切换 OptSnap 启用/禁用。
TOGGLE_KEYCODE = 100  # F8（默认）

# ── 置顶热键 ─────────────────────────────────────────────────────────────
# 切换「鼠标指针下窗口」的置顶状态。
#
# 用组合键而不是单按功能键：不少 Mac 键盘处于「媒体键」模式，F9 这类键按下发出的是
# 媒体键事件（NSSystemDefined），不是 keyDown，单键热键会失效。组合键走 keyDown
# 通道，不受这个模式影响。
PIN_HOTKEY_KEYCODE = 35   # P
PIN_HOTKEY_MODIFIERS = ["alternate", "shift"]   # Option + Shift + P

# ── 修饰键 ───────────────────────────────────────────────────────────────
MODIFIER_NAME = "alternate"  # alternate / control / command 之一

# ── 透明度 ───────────────────────────────────────────────────────────────
ALPHA_STEP = 0.05   # 每格滚轮的透明度变化量
ALPHA_MIN = 0.1     # 最低不透明度（0.0 = 完全透明）
ALPHA_MAX = 1.0     # 最高不透明度（完全不透明）

# ── 窗口尺寸下限 ─────────────────────────────────────────────────────────
MIN_WINDOW_WIDTH = 100
MIN_WINDOW_HEIGHT = 50

# ── 事件监听 ─────────────────────────────────────────────────────────────
HEALTH_CHECK_INTERVAL = 2.0   # 事件 tap 健康检查间隔（秒）

# ── 置顶层级 ─────────────────────────────────────────────────────────────
# kCGFloatingWindowLevel = 3：浮在普通窗口之上，但仍低于菜单栏和程序坞。
# 比它更高的层级会显得像系统弹窗，交互上容易挡住输入焦点。
PIN_LEVEL_FLOATING = 3
PIN_LEVEL_NORMAL = 0

# ── 置顶窗口的描边标记 ───────────────────────────────────────────────────
# 置顶后给窗口画一圈细边，否则多个窗口叠在一起时分不清哪个真的生效了。
BORDER_WIDTH = 1.5          # 线宽（pt）。太粗会像选中框，1.5 在 Retina 上刚好可见
BORDER_CORNER_RADIUS = 8.0  # 圆角，贴合 macOS 窗口的圆角视觉
BORDER_COLOR = (0.20, 0.60, 1.0, 0.9)   # 系统蓝，与 macOS 强调色一致
# 描边面板的层级：只要比置顶窗口（3）高一级就够，不需要冲到很高的层级。
# 用 4 而不是 20+ 是有意的 —— 高于程序坞（20）或菜单栏（24）的浮层会盖住系统 UI，
# 看起来像 bug。4 既能压住置顶窗口，又始终待在系统 UI 之下。
BORDER_LEVEL = 4
# 位置跟随的刷新间隔（秒）。拖拽系统窗口时描边要跟得上，16ms≈60fps 开销可忽略
# （整表只调一次 CGWindowList）。
BORDER_REFRESH_INTERVAL = 1.0 / 60.0

# ── GUI 用的常量映射 ─────────────────────────────────────────────────────
MODIFIER_NAMES = {
    "alternate": "Option",
    "control": "Ctrl",
    "command": "Cmd",
}

TOGGLE_KEYCODES = [100, 122, 120, 99, 107, 113, 114]
TOGGLE_KEY_NAMES = {100: "F8", 122: "F1", 120: "F2", 99: "F5", 107: "Scroll Lock", 113: "Pause", 114: "Insert"}

# 置顶热键的可选组合。都是「修饰键 + 字母」，避免功能键的媒体键模式问题。
PIN_HOTKEYS = [
    (35, ["alternate", "shift"], "⌥⇧P"),
    (35, ["alternate", "control"], "⌥⌃P"),
    (36, ["alternate", "shift"], "⌥⇧O"),
    (17, ["alternate", "shift"], "⌥⇧T"),
    (15, ["alternate", "shift"], "⌥⇧R"),
]

# 反向映射
MODIFIER_TO_NAME = {v: k for k, v in MODIFIER_NAMES.items()}  # 未使用，保留以备查
TOGGLE_KEYCODE_TO_NAME = TOGGLE_KEY_NAMES
