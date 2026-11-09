"""OptSnap 配置 —— 修改这些值来定制行为。"""

# ── 全局开关热键 ─────────────────────────────────────────────────────────
# 按下该键切换 OptSnap 启用/禁用。
TOGGLE_KEYCODE = 100  # F8（默认）

# ── 置顶热键 ─────────────────────────────────────────────────────────────
# 按下该键切换「鼠标指针下窗口」的置顶状态。
# 需要辅助功能权限 + 开发者模式（首次使用会引导开启）。
PIN_KEYCODE = 101  # F9（默认）

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

# ── GUI 用的常量映射 ─────────────────────────────────────────────────────
MODIFIER_NAMES = {
    "alternate": "Option",
    "control": "Ctrl",
    "command": "Cmd",
}

TOGGLE_KEYCODES = [100, 122, 120, 99, 107, 113, 114]
TOGGLE_KEY_NAMES = {100: "F8", 122: "F1", 120: "F2", 99: "F5", 107: "Scroll Lock", 113: "Pause", 114: "Insert"}

# 置顶热键可选值。避开 TOGGLE_KEYCODES 里已用的键，免得两个功能抢同一个键。
PIN_KEYCODES = [101, 109, 97, 98, 103, 111]
PIN_KEY_NAMES = {101: "F9", 109: "F10", 97: "F6", 98: "F7", 103: "F11", 111: "F12"}

# 反向映射
MODIFIER_TO_NAME = {v: k for k, v in MODIFIER_NAMES.items()}  # 未使用，保留以备查
TOGGLE_KEYCODE_TO_NAME = TOGGLE_KEY_NAMES
PIN_KEYCODE_TO_NAME = PIN_KEY_NAMES
