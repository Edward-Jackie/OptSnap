#!/bin/bash
# 置顶注入 PoC：把载荷 dlopen 进 Dock.app，在 Dock 进程内改目标窗口层级。
#
# 背景：macOS 15 起 SkyLight 的 SLSSetWindowLevel / SLSSetWindowAlpha 对其它进程的窗口
# 只返回成功但实际不生效（进程归属校验）。Dock 是系统进程，用它自己的 SLS 连接就能改。
# yabai 的 scripting-addition 用的是同一原理，只是它自己维护注入通道。
#
# 前置：lldb 可附加到 Dock（本机实测通过）。
# 用法：./poc_inject.sh <window_id> [level]      level 默认 3（浮动层），0 = 还原
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DYLIB="$SCRIPT_DIR/topmost_payload.dylib"
WID="${1:?用法: ./poc_inject.sh <window_id> [level]}"
LEVEL="${2:-3}"
RESULT_FILE="/tmp/topmost_result.txt"

# 载荷缺失时自动编译
if [ ! -f "$SRC_DYLIB" ]; then
  echo "▶ 编译载荷…"
  clang -dynamiclib -o "$SRC_DYLIB" "$SCRIPT_DIR/topmost_payload.c" || exit 1
fi

DOCK_PID=$(pgrep -x Dock | head -1)
[ -z "$DOCK_PID" ] && { echo "❌ Dock 未运行"; exit 1; }

# 每次复制成唯一文件名：dlopen 同一路径第二次不会重跑构造器
PAYLOAD="/tmp/optsnap_payload_$$_$(date +%s).dylib"
cp "$SRC_DYLIB" "$PAYLOAD"

rm -f "$RESULT_FILE"
echo "$WID $LEVEL" > /tmp/topmost_target.txt

perl -e 'alarm 60; exec @ARGV' lldb -b \
  -o "process attach --pid $DOCK_PID" \
  -o "expr (void*)dlopen(\"$PAYLOAD\", 2)" \
  -o "process detach" \
  -o "quit" 2>&1 | grep -E "error:" | head -3

if [ -f "$RESULT_FILE" ]; then
  echo "▶ $(cat "$RESULT_FILE")"
else
  echo "▶ 注入未产生结果"
fi
rm -f "$PAYLOAD"
