"""Test script: validate action logic with mocked window calls."""

import sys
from unittest.mock import patch, MagicMock

from optsnap.config import MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT


def test_move_action():
    """Test MoveAction delta math."""
    from optsnap.actions import MoveAction

    ax_ref = MagicMock()
    bounds = {'x': 100, 'y': 200, 'w': 300, 'h': 400}

    action = MoveAction(1234, ax_ref, 500, 600, bounds)
    assert action.start_win_x == 100
    assert action.start_win_y == 200

    with patch('optsnap.actions.win.set_window_position') as mock_set:
        action.update(550, 630)
        mock_set.assert_called_once()
        args = mock_set.call_args[0]
        assert args[1] == 150
        assert args[2] == 230

    print("  MoveAction: PASS")


def test_move_action_fallback():
    """Test MoveAction falls back to win.get_window_position when no bounds."""
    from optsnap.actions import MoveAction

    ax_ref = MagicMock()

    with patch('optsnap.actions.win.get_window_position', return_value=(50, 75)):
        action = MoveAction(1234, ax_ref, 100, 100)
        assert action.start_win_x == 50
        assert action.start_win_y == 75

    print("  MoveAction fallback: PASS")


def test_resize_action_simple():
    """Test ResizeAction: drag adjusts size from bottom-right."""
    from optsnap.actions import ResizeAction

    ax_ref = MagicMock()
    bounds = {'x': 100, 'y': 100, 'w': 200, 'h': 100}

    action = ResizeAction(1234, ax_ref, 300, 200, bounds)
    assert action.start_win_w == 200
    assert action.start_win_h == 100

    with patch('optsnap.actions.win.set_window_size') as mock_size:
        action.update(350, 230)
        mock_size.assert_called_once()
        args = mock_size.call_args[0]
        assert args[1] == 250  # 200 + 50
        assert args[2] == 130  # 100 + 30

    print("  ResizeAction simple: PASS")


def test_resize_action_minimum_size():
    """Test ResizeAction enforces minimum size."""
    from optsnap.actions import ResizeAction

    ax_ref = MagicMock()
    bounds = {'x': 100, 'y': 100, 'w': 200, 'h': 100}

    action = ResizeAction(1234, ax_ref, 300, 200, bounds)

    with patch('optsnap.actions.win.set_window_size') as mock_size:
        # Drag -150px left (would make width 50, below min)
        action.update(150, 200)
        mock_size.assert_called_once()
        args = mock_size.call_args[0]
        assert args[1] >= MIN_WINDOW_WIDTH

    print("  ResizeAction minimum size: PASS")


def test_alpha_action_clamping():
    """Test AlphaAction clamping at 0.1 and 1.0."""
    from optsnap import actions

    actions._alpha_cache = {}

    with patch('optsnap.actions._MACOS_MAJOR', 14), \
         patch('optsnap.actions.win.get_window_alpha', return_value=0.5), \
         patch('optsnap.actions.win.set_window_alpha') as mock_set:

        for _ in range(10):
            actions.adjust_alpha(1234, 1.0)

        last_call = mock_set.call_args[0]
        assert last_call[1] <= 1.0

        actions._alpha_cache[1234] = 0.15
        actions.adjust_alpha(1234, -1.0)
        call_args = mock_set.call_args[0]
        assert call_args[1] >= 0.1

    print("  AlphaAction clamping: PASS")


def main():
    print("OptSnap Action Logic Tests")
    print("=" * 40)

    failed = 0
    tests = [
        test_move_action,
        test_move_action_fallback,
        test_resize_action_simple,
        test_resize_action_minimum_size,
        test_alpha_action_clamping,
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
