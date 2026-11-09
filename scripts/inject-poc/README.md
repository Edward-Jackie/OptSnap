# 窗口置顶注入 PoC

验证 macOS 上「把任意第三方窗口钉在最上层」（AltSnap 的 always-on-top）能否实现。

## 结论

**能实现，但必须借系统进程。** 直接调用 SkyLight 私有 API 无效，注入到 Dock.app 后有效。

## 实测数据（macOS 15.2 / Intel i7）

| 调用方式 | 返回值 | 实际 effect |
|---|---|---|
| `SLSSetWindowLevel` 直连（本进程 → 他人窗口） | CGError 0（假成功） | layer 恒为 0，栈序不变 |
| `SLSSetWindowLevel` 直连（本进程 → 自有窗口） | CGError 0 | layer 0→3→8 真实生效 |
| `CGSSetWindowLevel` 跨进程 | CGError 0 | 无变化 |
| `SLSSetWindowSubLevel` 跨进程 | CGError -1 | 无变化 |
| `SLSOrderWindow` 跨进程 | CGError 1000 | 无变化 |
| `SLSTransactionSetWindowLevel` 事务提交 | 失败 | 无变化 |
| `SLSSetWindowAlpha` 跨进程 | CGError 0（假成功） | alpha 读回仍 1.0 |
| AX `AXRaise` | kAXErrorSuccess | 仅在目标 App 同前台时有效 |
| **`SLSSetWindowLevel` 注入 Dock.app 后执行** | **CGError 0** | **layer 0→3→8 真实生效** |

关键对照实验（层级设为 -1 沉底）：

```
[baseline layer=0]      栈位=28  上方普通窗口=0   下方普通窗口=12
[降到 layer=-1]         栈位=40  上方普通窗口=12  下方普通窗口=0    ← 沉到所有普通窗口之下
[升到 layer=3]          栈位=28  上方普通窗口=0   下方普通窗口=12   ← 浮到最上
```

设置了 layer 之后，窗口的层叠顺序真实改变。有两个独立的读取路径可以验证：
`CGWindowListCopyWindowInfo` 的 `kCGWindowLayer`，以及 `SLSWindowIteratorGetLevel`。

## 用法

```bash
./poc_inject.sh <window_id> [level]    # level 默认 3，0 表示取消置顶
```

首次运行会自动 `clang -dynamiclib` 编译载荷。查找 window_id：

```bash
python3 -c "
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
for i in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
    b = i.get('kCGWindowBounds', {})
    if b.get('Width',0) > 500:
        print(i['kCGWindowNumber'], i.get('kCGWindowOwnerName'), i.get('kCGWindowLayer'))
"
```

## 原理

- `window.c` 编译成 dylib，构造器读 `/tmp/topmost_target.txt`（格式 `wid level`），在 Dock 进程内调用 `SLSSetWindowLevel`，结果写 `/tmp/topmost_result.txt`。
- 每次注入把 dylib 复制成唯一文件名：`dlopen` 同一路径第二次不会重跑构造器。
- 参数走文件而非函数调用：lldb 的 `expr` 在 Dock 进程内内联 `dlsym` + 调用会 `EXC_BAD_ACCESS`，走构造器最稳。

## 集成到 OptSnap 的现实障碍

1. **不能依赖 lldb**。PoC 用 `lldb -b` 附加 Dock，这是调试手段，不是产品形态。yabai 的做法是自带 `payload` 二进制 + Mach 端口注入 + 常驻 socket 通道，工程量大得多。
2. **`task_for_pid` 拿不到 port**。本机实测：对 Dock、Finder、以及自己 fork 的子进程都返回 `KERN_FAILURE(5)`。yabai 能注入是因为它的二进制带相应 entitlement 并以 root 运行。
3. **`sudo` 需要密码**，当前会话无法自动化。
4. **每次 macOS 大版本升级都可能失效**，需要跟进 SkyLight 私有 API 变化。

## 已知坑

- **截图不可用**：当前终端没有「屏幕录制」权限，`screencapture` 输出全黑（平均亮度 2.74/255）。本 PoC 的所有验证走的是 WindowServer 元数据（layer 字段 + 栈序），不依赖截图。
- **`SLSSetWindowSubLevel`** 即使注入后仍返回 -1，跨进程改 sublevel 不可行；但只改 level 已足够实现置顶。
- **lldb 持久变量不可用**（`expr $h = ...` 报 undeclared identifier），必须内联写全。
