"""Event Tap constants and helpers.

Core tap lifecycle (create/stop/recreate) lives in __main__.py.
This module provides constants that need to be shared across modules.
"""

from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventTapIsEnabled,
    CFMachPortCreateRunLoopSource,
    CFMachPortInvalidate,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    CFRunLoopTimerCreate,
    CFRunLoopAddTimer,
    CFRunLoopRemoveTimer,
    CFRunLoopTimerInvalidate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    kCGEventTapDisabledByTimeout,
    kCFRunLoopDefaultMode,
)

try:
    from Quartz import kCGEventTapDisabledByTCC
except ImportError:
    kCGEventTapDisabledByTCC = 14
