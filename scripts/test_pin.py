"""置顶逻辑单元测试 —— 用 mock 隔离 Dock 注入，不触碰真实系统状态。

只测纯逻辑：层级选择、命令序号递增、状态记录、失败降级。
真实的注入与层级修改需要人工验证（见 scripts/inject-poc/README.md）。
"""

import sys
from unittest.mock import patch, MagicMock


def test_is_supported_version_gate():
    """低于 macOS 15 时判定为不支持。"""
    from optsnap import pin

    with patch('optsnap.pin.platform.mac_ver', return_value=('14.5', ('', '', ''), '')):
        assert pin.is_supported() is False

    with patch('optsnap.pin.platform.mac_ver', return_value=('15.2', ('', '', ''), '')):
        assert pin.is_supported() is True

    print("  is_supported 版本门槛: PASS")


def test_is_supported_non_darwin():
    """非 macOS 平台判定为不支持。"""
    from optsnap import pin

    with patch('optsnap.pin.platform.system', return_value='Linux'):
        assert pin.is_supported() is False

    print("  is_supported 非 macOS: PASS")


def test_set_pinned_rejects_when_channel_dead():
    """通道没心跳时 set_pinned 返回 False，而不是抛异常。"""
    from optsnap import pin

    with patch('optsnap.pin._heartbeat_alive', return_value=False):
        assert pin.set_pinned(1234, True) is False

    print("  set_pinned 通道未就绪降级: PASS")


def test_set_pinned_level_mapping():
    """置顶走浮动层，取消走普通层。"""
    from optsnap import pin

    pin._pinned_state = {}
    sent = []

    with patch('optsnap.pin._heartbeat_alive', return_value=True), \
         patch('optsnap.pin._send_command', side_effect=lambda wid, lv: (sent.append((wid, lv)) or (True, 0))):

        assert pin.set_pinned(5678, True) is True
        assert sent[-1] == (5678, pin.PIN_LEVEL_FLOATING)

        assert pin.set_pinned(5678, False) is True
        assert sent[-1] == (5678, pin.PIN_LEVEL_NORMAL)

    print("  set_pinned 层级映射: PASS")


def test_pinned_state_tracking():
    """置顶/取消时 _pinned_state 同步更新。"""
    from optsnap import pin

    pin._pinned_state = {}

    with patch('optsnap.pin._heartbeat_alive', return_value=True), \
         patch('optsnap.pin._send_command', return_value=(True, 0)):

        pin.set_pinned(111, True)
        assert pin.is_pinned(111) is True
        assert pin.is_pinned_any() is True
        assert pin.pinned_count() == 1

        pin.set_pinned(111, False)
        assert pin.is_pinned(111) is False
        assert pin.is_pinned_any() is False
        assert pin.pinned_count() == 0

    print("  pinned 状态跟踪: PASS")


def test_toggle_pin_roundtrip():
    """toggle 在两次调用间正确翻转状态。"""
    from optsnap import pin

    pin._pinned_state = {}

    with patch('optsnap.pin._heartbeat_alive', return_value=True), \
         patch('optsnap.pin._send_command', return_value=(True, 0)):

        assert pin.toggle_pin(222) is True
        assert pin.toggle_pin(222) is False
        assert pin.toggle_pin(222) is True

    print("  toggle_pin 翻转: PASS")


def test_toggle_pin_none_window():
    """window_id 为 None 时安全返回 None。"""
    from optsnap import pin

    assert pin.toggle_pin(None) is None

    print("  toggle_pin 空窗口: PASS")


def test_send_command_writes_and_reads_ack():
    """下发命令时写入的序号递增，且能正确匹配回执。"""
    from optsnap import pin
    import tempfile
    import os
    import threading
    import time

    pin._cmd_seq = 100

    with tempfile.TemporaryDirectory() as d:
        cmd = os.path.join(d, "cmd")
        ack = os.path.join(d, "ack")

        with patch('optsnap.pin.CMD_FILE', cmd), \
             patch('optsnap.pin.ACK_FILE', ack), \
             patch('optsnap.pin.COMMAND_TIMEOUT', 2.0):

            written = []

            # 模拟载荷：看到命令文件就写回执
            def fake_payload():
                seen = 0
                while len(written) < 2:
                    try:
                        with open(cmd) as f:
                            parts = f.read().split()
                        if len(parts) == 3 and int(parts[0]) > seen:
                            seen = int(parts[0])
                            written.append((seen, int(parts[1]), int(parts[2])))
                            with open(ack, "w") as af:
                                af.write(f"{parts[0]} {parts[1]} {parts[2]} 0\n")
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.005)

            t = threading.Thread(target=fake_payload, daemon=True)
            t.start()
            time.sleep(0.05)

            ok1, err1 = pin._send_command(333, pin.PIN_LEVEL_FLOATING)
            ok2, err2 = pin._send_command(333, pin.PIN_LEVEL_NORMAL)

            assert ok1 is True and err1 == 0
            assert ok2 is True and err2 == 0
            # 两次下发都真实写盘，且序号递增
            assert len(written) == 2
            assert written[1][0] > written[0][0]
            assert written[0][2] == pin.PIN_LEVEL_FLOATING
            assert written[1][2] == pin.PIN_LEVEL_NORMAL

    print("  send_command 下发与回执匹配: PASS")


def test_reset_all_pins_clears_state():
    """reset_all_pins 清空状态，且对每个置顶窗口下发还原命令。"""
    from optsnap import pin

    pin._pinned_state = {1: True, 2: True}
    calls = []

    with patch('optsnap.pin._heartbeat_alive', return_value=True), \
         patch('optsnap.pin._send_command', side_effect=lambda wid, lv: (calls.append((wid, lv)) or (True, 0))):

        pin.reset_all_pins()

    assert sorted(w for w, _ in calls) == [1, 2]
    assert all(lv == pin.PIN_LEVEL_NORMAL for _, lv in calls)
    assert pin.pinned_count() == 0

    print("  reset_all_pins: PASS")


def test_reset_all_pins_noop_when_empty():
    """没有置顶窗口时不发任何命令。"""
    from optsnap import pin

    pin._pinned_state = {}
    with patch('optsnap.pin._send_command') as mock_send:
        pin.reset_all_pins()
        mock_send.assert_not_called()

    print("  reset_all_pins 空态跳过: PASS")


def test_pinned_window_at_finds_pinned_window():
    """置顶后的窗口 layer 不是 0，get_window_at_point 会跳过它，
    所以必须先用 pinned_window_at 命中，否则第二次按快捷键无法取消置顶。"""
    from optsnap import pin

    pin._pinned_state = {777: True}

    with patch('optsnap.window.get_window_geometry', return_value=(100, 100, 400, 300)):
        # 指针在窗口范围内
        assert pin.pinned_window_at(200, 200) == 777
        # 指针在窗口外
        assert pin.pinned_window_at(50, 50) is None
        # 边界
        assert pin.pinned_window_at(100, 100) == 777
        assert pin.pinned_window_at(500, 400) == 777

    # 没有置顶窗口时不命中
    pin._pinned_state = {}
    with patch('optsnap.window.get_window_geometry', return_value=(100, 100, 400, 300)):
        assert pin.pinned_window_at(200, 200) is None

    print("  pinned_window_at 命中: PASS")


def test_toggle_sequence_pin_then_unpin():
    """完整快捷键序列：第一次置顶，第二次取消，不应误伤下层窗口。"""
    from optsnap.core import OptSnapCore
    from optsnap import pin

    pin._pinned_state = {}
    core = OptSnapCore()

    with patch('optsnap.pin._heartbeat_alive', return_value=True), \
         patch('optsnap.pin._send_command', return_value=(True, 0)), \
         patch('optsnap.window.get_window_geometry', return_value=(100, 100, 400, 300)), \
         patch('optsnap.window.get_window_at_point', return_value=(888, MagicMock(), {})), \
         patch('Quartz.CGEventCreate', return_value=MagicMock()), \
         patch('Quartz.CGEventGetLocation', return_value=type('P', (), {'x': 200, 'y': 200})()):

        # 第一次：指针下无已置顶窗口 → 置顶普通窗口 888
        assert core.toggle_pin_under_cursor() is True
        assert pin.is_pinned(888) is True

        # 第二次：指针下已有置顶窗口 888 → 取消它，而不是去置顶下层窗口
        assert core.toggle_pin_under_cursor() is False
        assert pin.is_pinned(888) is False

    print("  快捷键置顶/取消序列: PASS")


def test_permissions_missing_for_pin():
    """置顶缺失项判断：命令行工具和权限才是硬门槛，开发者模式不算。"""
    from optsnap import permissions

    full = {"accessibility": True, "input_monitoring": True,
            "developer_mode": False, "clang": True, "lldb": True}
    assert permissions.missing_for_pin(full) == []

    no_clang = dict(full, clang=False)
    assert "clang（Xcode 命令行工具）" in permissions.missing_for_pin(no_clang)

    no_ax = dict(full, accessibility=False)
    assert "辅助功能权限" in permissions.missing_for_pin(no_ax)

    # 开发者模式默认不进缺失列表
    assert "开发者模式" not in permissions.missing_for_pin(full)
    assert "开发者模式" in permissions.missing_for_pin(full, include_developer_mode=True)

    print("  permissions 缺失项判断: PASS")


def main():
    print("OptSnap 置顶逻辑测试")
    print("=" * 40)

    failed = 0
    tests = [
        test_is_supported_version_gate,
        test_is_supported_non_darwin,
        test_set_pinned_rejects_when_channel_dead,
        test_set_pinned_level_mapping,
        test_pinned_state_tracking,
        test_toggle_pin_roundtrip,
        test_toggle_pin_none_window,
        test_send_command_writes_and_reads_ack,
        test_reset_all_pins_clears_state,
        test_reset_all_pins_noop_when_empty,
        test_pinned_window_at_finds_pinned_window,
        test_toggle_sequence_pin_then_unpin,
        test_permissions_missing_for_pin,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  {test.__name__}: FAIL — {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    if failed == 0:
        print(f"SUCCESS: All {len(tests)} tests passed")
        sys.exit(0)
    else:
        print(f"FAILURE: {failed}/{len(tests)} tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
