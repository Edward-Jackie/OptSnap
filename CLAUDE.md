# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OptSnap is a macOS menu-bar utility (AltSnap-inspired) that lets you move/resize windows and adjust their
visibility by holding a modifier key (default: Option) and using the mouse — no need to grab a title bar or
edge. It's a PyObjC app: a `CGEventTap` intercepts global mouse/keyboard events, `AXUIElement` moves/resizes
windows, and either the `SkyLight` private framework or an `NSPanel` overlay handles dimming, depending on
macOS version. It only runs on macOS.

## Commands

```bash
uv sync                        # install dependencies
uv run python -m optsnap       # run in dev mode (menu bar app, foreground)
./optsnap.sh                   # convenience wrapper around the above
./build_app.sh                 # build build/OptSnap.app (manual bundling, NOT via setup.py/py2app)
open build/OptSnap.app         # run the packaged app
```

There is no linter or formatter configured (no ruff/flake8/mypy config) and no CI. `setup.py` declares a
py2app build but `build_app.sh` is the build path that's actually documented and used — don't assume
`python setup.py py2app` produces the shipped artifact.

### Tests

There's no pytest setup — `scripts/test_*.py` are standalone scripts, not a pytest suite. Run one directly:

```bash
uv run python scripts/test_actions.py
```

Each prints PASS/FAIL per test and exits non-zero on failure. Only **`scripts/test_actions.py`** is a pure
unit test (mocks `optsnap.window` calls, no side effects, safe to run headless/in CI-like conditions).

The rest are **manual/interactive scripts that touch real macOS state** — they require Accessibility/Input
Monitoring permissions already granted, a live desktop session, and in several cases either wait on real
mouse input for a fixed window or actually move/resize/dim whatever real window is under the cursor:
`test_alpha.py`, `test_diagnostic.py`, `test_event_tap.py`, `test_overlay.py`, `test_window_move.py`. Don't
run these expecting a quick deterministic result — they're for a human at the keyboard debugging the
Quartz/AX/SkyLight layer, not for automated verification.

## Required macOS permissions

The app needs two TCC permissions granted to whatever process runs it (Python/terminal in dev mode, or
`OptSnap.app` once packaged — granting one does not cover the other):
- **Accessibility** (`AXUIElement*`) — to move/resize other apps' windows.
- **Input Monitoring** — for the `CGEventTap` to see global mouse/keyboard events.

`OptSnapCore.check_permissions()` / `request_accessibility()` in `core.py` handle detection and prompting;
`__main__.py:main()` blocks at startup polling for both before starting the event loop.

## Architecture

### Event flow and state machine

Everything funnels through one `CGEventTap` owned by `OptSnapCore` (`core.py`), running on a dedicated
background thread (`run_in_thread()` → `CFRunLoopRun()`), separate from the `rumps` menu bar app on the main
thread. `OptSnapCore._event_callback` is a small state machine over `self.mode`: `idle → moving/resizing →
idle`, driven directly by raw `kCGEventLeftMouseDown/Dragged/Up` and `kCGEventRightMouseDown/Dragged/Up`
while the configured modifier is held. Scroll events adjust alpha directly from `idle` with no separate mode.
The toggle hotkey (default F8) is checked before anything else, even when the tap is otherwise disabled, so
it always works.

Cross-thread UI updates matter here: `OptSnapCore.toggle()` dispatches `on_state_change` onto
`AppKit.NSOperationQueue.mainQueue()` rather than calling it inline, because doing AppKit work directly on
the tap thread can stall it long enough for macOS to fire `kCGEventTapDisabledByTimeout` and kill the tap.
The tap also self-heals: a `CFRunLoopTimer` (`HEALTH_CHECK_INTERVAL`) checks `CGEventTapIsEnabled` and calls
`_recreate_tap()` if the tap was disabled (timeout or TCC revocation).

### Window I/O split: read via CGWindowList, write via AXUIElement

`window.py` deliberately separates *querying* window geometry from *setting* it:
- **Reads** (position, size, hit-testing at a point) go through `CGWindowListCopyWindowInfo` — considered
  more reliable than parsing `AXValue`.
- **Writes** (position, size) go through `AXUIElementSetAttributeValue`, since `CGWindowList` is read-only.
- Getting an `AXUIElementRef` for a window found via `CGWindowList` uses a PID-based lookup
  (`_get_ax_window_for_pid`) rather than the private `_AXUIElementGetWindow` API, because that private call
  is flaky across process relaunches. Note it falls back to "first window of the app" if it can't match by
  ID — apps with multiple windows can resolve to the wrong one.
- `_ax_retry()` retries once/backoff on `kAXErrorCannotComplete`, which AX APIs return transiently.

### Alpha/dimming has two independent implementations, chosen by macOS version

`actions.py:adjust_alpha()` branches on `platform.mac_ver()` major version:
- **macOS 15+**: `overlay.py` — a borderless, click-through `NSPanel` is positioned over the target window and
  its own alpha is raised to fake dimming, since `SLSSetWindowAlpha` no longer reliably affects other
  processes' windows on newer macOS. Overlays are tracked in a `window_id → NSPanel` dict and must be
  manipulated on the main thread (`_run_on_main`).
- **macOS 12–14**: `window.py` — the `SkyLight.framework` private API (`SLSSetWindowAlpha`/`SLSGetWindowAlpha`,
  loaded via `ctypes`) sets the real window alpha.

Both paths share a `_alpha_cache` (window_id → opacity) in `actions.py` so relative scroll deltas accumulate
correctly, and `reset_all_alpha()` (called on disable/quit) clears whichever mechanism is active.

### Dead code — don't extend or "fix" these

`src/optsnap/gui.py` and `src/optsnap/event_tap.py` are not imported anywhere in the codebase.
`__main__.py` has its own inline `OptSnapMenuApp` (not the one in `gui.py`), and the tap lifecycle actually
lives in `core.py` (not `event_tap.py`, despite that file's docstring claiming otherwise). Likewise,
`config.py`'s `MODIFIER_NAMES` / `TOGGLE_KEY_NAMES` / `MODIFIER_TO_NAME` exist only for the unused `gui.py`
— the live name/keycode mappings are the private `_MODIFIERS` / `_MODIFIER_NAMES` / `_TOGGLE_KEYCODES` /
`_TOGGLE_KEY_NAMES` defined in `core.py`. When changing modifier/toggle-key behavior, edit `core.py`, not
`config.py`'s display-name maps.

## Configuration

User-facing tunables live in `src/optsnap/config.py` (toggle keycode, modifier name, alpha step/min/max,
minimum window size, health-check interval) and are plain module-level constants — changing them requires
restarting OptSnap, there's no live-reload.
