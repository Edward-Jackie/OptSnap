"""Test script: set focused window alpha to 0.5 via SkyLight."""

import sys
import time

from optsnap.window import (
    check_accessibility_permission,
    get_focused_window,
    set_window_alpha,
    get_window_alpha,
)


def main():
    print("OptSnap Window Alpha Test")
    print("=" * 40)

    if not check_accessibility_permission():
        print("Accessibility permission not granted.")
        print("Granting... (system dialog will appear)")
        from optsnap.window import request_accessibility_permission
        request_accessibility_permission()
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

    # Get current alpha
    current = get_window_alpha(window_id)
    print(f"Current alpha: {current:.2f}" if current is not None else "Current alpha: unknown")

    # Set to 0.5
    print("Setting alpha to 0.5...")
    err = set_window_alpha(window_id, 0.5)
    if err == 0:
        print("SUCCESS: set_window_alpha returned OK")
    else:
        print(f"WARNING: set_window_alpha returned error {err}")

    time.sleep(0.5)

    # Verify
    new_alpha = get_window_alpha(window_id)
    if new_alpha is not None:
        print(f"New alpha: {new_alpha:.2f}")
        if abs(new_alpha - 0.5) < 0.05:
            print("SUCCESS: Alpha verified at ~0.5")
        else:
            print(f"WARNING: Alpha is {new_alpha:.2f}, expected ~0.5")
    else:
        print("WARNING: Could not verify alpha (get_window_alpha returned None)")

    # Restore to 1.0 after 2 seconds
    print("Restoring alpha to 1.0 in 2s...")
    time.sleep(2)
    set_window_alpha(window_id, 1.0)
    print("Restored. Test complete.")


if __name__ == "__main__":
    main()
