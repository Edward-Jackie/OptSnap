"""Diagnostic: test window operations step by step."""

import time
from Quartz import (
    CGEventTapCreate, CGEventTapEnable, CGEventGetType, CGEventGetLocation, CGEventGetFlags,
    CGEventGetIntegerValueField,
    CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent, CFRunLoopRunInMode,
    CFRunLoopStop,
    kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
    kCFRunLoopDefaultMode,
    kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGEventLeftMouseDragged,
    kCGEventRightMouseDown, kCGEventRightMouseUp, kCGEventRightMouseDragged,
    kCGEventScrollWheel, kCGEventFlagsChanged, kCGEventKeyDown,
    kCGEventFlagMaskAlternate, kCGKeyboardEventKeycode,
    CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
    kCGScrollWheelEventDeltaAxis1,
)

from optsnap import window as win
from optsnap.actions import MoveAction, ResizeAction, adjust_alpha

print("=" * 50)
print("Window Operations Diagnostic")
print("=" * 50)

# Step 1: Test get_window_at_point
print("\n[1] Testing get_window_at_point...")
info = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
print(f"  On-screen windows found: {len(info)}")

# Count layer 0 windows
normal = [w for w in info if w.get('kCGWindowLayer', 0) == 0]
print(f"  Normal windows (layer 0): {len(normal)}")

for w in normal[:3]:
    print(f"    pid={w.get('kCGWindowOwnerPID')}, title='{w.get('kCGWindowName')}', layer={w.get('kCGWindowLayer')}")

# Step 2: Test window geometry
print("\n[2] Testing window geometry lookup...")
first_win = None
for w in normal:
    wid = w.get('kCGWindowNumber')
    bounds = w.get('kCGWindowBounds', {})
    if bounds and hasattr(bounds, 'get'):
        print(f"  Window {wid}: bounds={bounds}")
        first_win = wid
        break

if first_win:
    geo = win.get_window_geometry(first_win)
    print(f"  get_window_geometry({first_win}) = {geo}")

# Step 3: Test alpha
print("\n[3] Testing SkyLight alpha API...")
if first_win:
    alpha = win.get_window_alpha(first_win)
    print(f"  get_window_alpha({first_win}) = {alpha}")
    err = win.set_window_alpha(first_win, 0.7)
    print(f"  set_window_alpha({first_win}, 0.7) returned: {err}")
    time.sleep(0.3)
    alpha2 = win.get_window_alpha(first_win)
    print(f"  get_window_alpha after set = {alpha2}")
    # Restore
    win.set_window_alpha(first_win, 1.0)

# Step 4: Test AX set position
print("\n[4] Testing AX position set...")
if first_win:
    _, ax_ref = win.get_window_at_point(100, 100)  # dummy
    # Use a known window
    for w in normal:
        wid = w.get('kCGWindowNumber')
        _, ax_ref = win.get_window_at_point(
            float(w.get('kCGWindowBounds', {}).get('X', 0)) + 50,
            float(w.get('kCGWindowBounds', {}).get('Y', 0)) + 50,
        )
        if ax_ref:
            print(f"  Got AX ref for window {wid}: {ax_ref}")
            pos = win.get_window_position(wid)
            print(f"  Position: {pos}")
            print(f"  Trying set_window_position +20px...")
            win.set_window_position(ax_ref, pos[0] + 20, pos[1])
            time.sleep(0.3)
            new_pos = win.get_window_position(wid)
            print(f"  After set: {new_pos}")
            # Restore
            win.set_window_position(ax_ref, pos[0], pos[1])
            break
        else:
            print(f"  No AX ref for window {wid} (pid={w.get('kCGWindowOwnerPID')})")

# Step 5: Interactive test
print("\n[5] Interactive test — holding Option and clicking...")
print("    Click on a window while holding Option.")
print("    Test runs for 8 seconds.")
print()

events = 0
actions_taken = 0

def callback(proxy, event_type, event, refcon):
    global events, actions_taken
    flags = CGEventGetFlags(event)
    modifier_held = bool(flags & kCGEventFlagMaskAlternate)
    raw_type = CGEventGetType(event)
    loc = CGEventGetLocation(event)

    if modifier_held and raw_type in (kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventScrollWheel):
        events += 1
        type_name = "LEFT" if raw_type == kCGEventLeftMouseDown else ("RIGHT" if raw_type == kCGEventRightMouseDragged else "SCROLL")
        print(f"  [{type_name}] Option+{type_name} at ({loc.x:.0f}, {loc.y:.0f})")

        wid, ax_ref = win.get_window_at_point(loc.x, loc.y)
        print(f"    -> window_id={wid}, ax_ref={ax_ref}")

        if wid:
            geo = win.get_window_geometry(wid)
            print(f"    -> geometry={geo}")

            if ax_ref:
                if raw_type == kCGEventLeftMouseDown:
                    print(f"    -> Trying MoveAction...")
                    action = MoveAction(wid, ax_ref, loc.x, loc.y)
                    print(f"    -> MoveAction created: start=({action.start_win_x:.0f}, {action.start_win_y:.0f})")
                    actions_taken += 1
                elif raw_type == kCGEventRightMouseDown:
                    print(f"    -> Trying ResizeAction...")
                    action = ResizeAction(wid, ax_ref, loc.x, loc.y)
                    print(f"    -> ResizeAction created: edge={action.edge}")
                    actions_taken += 1
                elif raw_type == kCGEventScrollWheel:
                    delta = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
                    print(f"    -> Trying adjust_alpha(delta={delta})...")
                    new_alpha = adjust_alpha(wid, delta)
                    print(f"    -> adjust_alpha returned: {new_alpha}")
                    actions_taken += 1
            else:
                print(f"    -> NO AX ref — can't manipulate window!")
        else:
            print(f"    -> NO window found at this point")

    return event

mask = (
    (1 << kCGEventLeftMouseDown) | (1 << kCGEventLeftMouseUp) | (1 << kCGEventLeftMouseDragged) |
    (1 << kCGEventRightMouseDown) | (1 << kCGEventRightMouseUp) | (1 << kCGEventRightMouseDragged) |
    (1 << kCGEventScrollWheel) | (1 << kCGEventFlagsChanged) |
    (1 << kCGEventKeyDown) | (1 << kCGEventKeyUp)
)

tap = CGEventTapCreate(
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    mask,
    callback,
    None,
)

if not tap:
    print("ERROR: CGEventTap creation FAILED!")
    exit(1)

source = CFMachPortCreateRunLoopSource(None, tap, 0)
CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopDefaultMode)
CGEventTapEnable(tap, True)

start = time.time()
while time.time() - start < 8:
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.5, False)

print()
print("=" * 50)
print(f"Modifier+mouse events: {events}")
print(f"Actions attempted: {actions_taken}")
if events == 0:
    print("ISSUE: No Option+mouse events received")
elif actions_taken == 0:
    print("ISSUE: Events received but no actions attempted (window not found or no AX ref)")
else:
    print("SUCCESS: All operations working!")
