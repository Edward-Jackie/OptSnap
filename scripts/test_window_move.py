"""Test script: move focused window 10px right via AXUIElement."""

import sys

from optsnap.window import (
    check_accessibility_permission,
    request_accessibility_permission,
    get_focused_window,
    get_window_position,
    get_window_size,
    set_window_position,
)


def main():
    print("OptSnap Window Move Test")
    print("=" * 40)

    if not check_accessibility_permission():
        print("Accessibility permission not granted.")
        print("Granting... (system dialog will appear)")
        request_accessibility_permission()
        import time
        time.sleep(2)
        if not check_accessibility_permission():
            print("ERROR: Accessibility permission still not granted.")
            sys.exit(1)

    print("Accessibility: OK")

    window_id, ax_ref = get_focused_window()
    if window_id is None:
        print("ERROR: Could not get focused window")
        sys.exit(1)

    print(f"Focused window: id={window_id}")

    pos = get_window_position(ax_ref)
    size = get_window_size(ax_ref)

    if pos is None:
        print("ERROR: Could not get window position")
        sys.exit(1)

    print(f"Current position: ({pos[0]:.0f}, {pos[1]:.0f})")
    if size:
        print(f"Size: ({size[0]:.0f}, {size[1]:.0f})")

    new_x = pos[0] + 10
    new_y = pos[1]
    print(f"Moving to: ({new_x:.0f}, {new_y:.0f})")

    set_window_position(ax_ref, new_x, new_y)

    import time
    time.sleep(0.5)

    new_pos = get_window_position(ax_ref)
    if new_pos and abs(new_pos[0] - new_x) < 2:
        print("SUCCESS: Window moved 10px right")
        sys.exit(0)
    else:
        print(f"FAILURE: Window did not move as expected. New pos: {new_pos}")
        sys.exit(1)


if __name__ == "__main__":
    main()
