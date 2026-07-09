"""Test script: verify CGEventTap captures Option+mouse events."""

import sys
import time

from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventGetType,
    CGEventGetLocation,
    CGEventGetFlags,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRunInMode,
    kCFRunLoopDefaultMode,
    kCFAllocatorDefault,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionListenOnly,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGEventLeftMouseDragged,
    kCGEventRightMouseDown,
    kCGEventRightMouseDragged,
    kCGEventScrollWheel,
    kCGEventFlagsChanged,
    kCGEventFlagMaskAlternate,
)

MODIFIER_MASK = kCGEventFlagMaskAlternate

events_captured = 0


def callback(proxy, event_type, event, refcon):
    global events_captured
    flags = CGEventGetFlags(event)
    modifier_held = bool(flags & MODIFIER_MASK)

    if modifier_held:
        loc = CGEventGetLocation(event)
        raw_type = CGEventGetType(event)
        type_names = {
            kCGEventLeftMouseDown: "LEFT_DOWN",
            kCGEventLeftMouseDragged: "LEFT_DRAG",
            kCGEventLeftMouseUp: "LEFT_UP",
            kCGEventRightMouseDown: "RIGHT_DOWN",
            kCGEventRightMouseDragged: "RIGHT_DRAG",
            kCGEventScrollWheel: "SCROLL",
            kCGEventFlagsChanged: "FLAGS_CHANGED",
        }
        name = type_names.get(raw_type, f"UNKNOWN({raw_type})")
        print(f"  Option+{name} at ({loc.x:.0f}, {loc.y:.0f})")
        events_captured += 1

    return event


def main():
    global events_captured

    print("OptSnap Event Tap Test")
    print("=" * 40)
    print(f"Modifier mask: {MODIFIER_MASK} ({'Option' if MODIFIER_MASK == kCGEventFlagMaskAlternate else 'Ctrl'})")
    print()
    print("Hold Option and click/drag/scroll anywhere...")
    print("Test runs for 15 seconds.")
    print()

    mask = (
        (1 << kCGEventLeftMouseDown)
        | (1 << kCGEventLeftMouseUp)
        | (1 << kCGEventLeftMouseDragged)
        | (1 << kCGEventRightMouseDown)
        | (1 << kCGEventRightMouseDragged)
        | (1 << kCGEventScrollWheel)
        | (1 << kCGEventFlagsChanged)
    )

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        mask,
        callback,
        None,
    )

    if not tap:
        print("ERROR: Failed to create event tap.")
        print("  Check Input Monitoring permission:")
        print("  System Settings → Privacy & Security → Input Monitoring")
        sys.exit(1)

    source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopDefaultMode)
    CGEventTapEnable(tap, True)

    print("Event tap active.\n")

    # Run for 15 seconds in 1-second intervals
    start = time.time()
    try:
        while time.time() - start < 15:
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1.0, False)
    except KeyboardInterrupt:
        pass

    from Quartz import CFMachPortInvalidate
    CFMachPortInvalidate(tap)

    print()
    print("=" * 40)
    if events_captured > 0:
        print(f"SUCCESS: Captured {events_captured} Option+mouse events")
        sys.exit(0)
    else:
        print("FAILURE: No Option+mouse events captured")
        print("  Make sure you're holding the Option key while clicking/dragging")
        sys.exit(1)


if __name__ == "__main__":
    main()
