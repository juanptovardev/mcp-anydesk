"""AnyDesk window enumeration, selection, and focus management.

v3.4 changes:
- _click_window_center(hwnd): click the center of the window after focus so
  AnyDesk receives input without requiring the user to place the cursor.
- focus_and_verify() calls _click_window_center() when FOCUS_CLICK_ENABLED.

v3 changes (N4):
- Named sessions dict: multiple windows can be pinned simultaneously.
- pin_session(hwnd, name): pin with a human-readable label.
- switch_session(name): change the active session by name.
- list_sessions(): enumerate all named sessions.
- get_pinned_hwnd() now returns the active named session's hwnd, with
  fallback to the legacy single-pin var for backward compatibility.
"""

from __future__ import annotations

import ctypes
import time

import win32api  # type: ignore[import-untyped]
import win32con  # type: ignore[import-untyped]
import win32gui  # type: ignore[import-untyped]
import win32process  # type: ignore[import-untyped]

from .config import DEFAULT_FOCUS_DELAY_MS, FOCUS_CLICK_DELAY_MS, FOCUS_CLICK_ENABLED
from .win32_input import (
    INPUT,
    INPUT_MOUSE,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    SM_CXSCREEN,
    SM_CYSCREEN,
    GetSystemMetrics,
    send_inputs,
)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_pinned_hwnd: int | None = None                  # Legacy single-pin (v1/v2 compat)
_sessions: dict[str, dict] = {}                  # name -> {"hwnd": int, "title": str}
_active_session: str | None = None               # Currently active named session


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------
def enumerate_anydesk_windows() -> list[tuple[int, str, str]]:
    """Find all visible windows whose class or title contains 'AnyDesk'.

    Returns:
        List of (hwnd, title, class_name) tuples.
    """
    windows: list[tuple[int, str, str]] = []

    def _callback(hwnd: int, _extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)
        is_anydesk_class = "anydesk" in class_name.lower()
        import re
        is_anydesk_title = bool(re.search(r'(?<![_\w])AnyDesk(?![_\w])', title))
        if is_anydesk_class or is_anydesk_title:
            windows.append((hwnd, title, class_name))

    win32gui.EnumWindows(_callback, None)
    return windows


# ---------------------------------------------------------------------------
# Selection / pinning
# ---------------------------------------------------------------------------
def select_window(hwnd: int) -> dict:
    """Pin a specific window handle for the session.

    Args:
        hwnd: The window handle to pin.

    Returns:
        Status dict with pinned hwnd and title.

    Raises:
        ValueError: If the hwnd is not a valid visible window.
    """
    global _pinned_hwnd

    if not win32gui.IsWindow(hwnd):
        raise ValueError(f"hwnd {hwnd} is not a valid window.")
    if not win32gui.IsWindowVisible(hwnd):
        raise ValueError(f"hwnd {hwnd} is not visible.")

    title = win32gui.GetWindowText(hwnd)
    _pinned_hwnd = hwnd
    return {"status": "pinned", "hwnd": hwnd, "title": title}


def get_active_hwnd() -> int | None:
    """Return the hwnd for the currently active session.

    Checks named sessions first; falls back to the legacy single-pin var.
    """
    if _active_session and _active_session in _sessions:
        return _sessions[_active_session]["hwnd"]
    return _pinned_hwnd


def get_pinned_hwnd() -> int | None:
    """Return the currently active hwnd, or None if nothing is pinned.

    Backward-compatible wrapper around get_active_hwnd().
    """
    return get_active_hwnd()


def pin_session(hwnd: int, name: str) -> dict:
    """Pin a window with a human-readable name (N4).

    Multiple windows can be pinned simultaneously under different names.
    The newly pinned window becomes the active session.

    Args:
        hwnd: Window handle to pin.
        name: Human-readable label (e.g., "DC01", "HyperV-Host").

    Returns:
        Status dict with name, hwnd, and title.
    """
    global _active_session, _pinned_hwnd

    if not win32gui.IsWindow(hwnd):
        return {"status": "error", "note": f"hwnd {hwnd} is not a valid window."}
    if not win32gui.IsWindowVisible(hwnd):
        return {"status": "error", "note": f"hwnd {hwnd} is not visible."}

    title = win32gui.GetWindowText(hwnd)
    _sessions[name] = {"hwnd": hwnd, "title": title}
    _active_session = name
    _pinned_hwnd = hwnd  # Keep legacy var in sync
    return {"status": "pinned", "name": name, "hwnd": hwnd, "title": title}


def switch_session(name: str) -> dict:
    """Switch the active session to a previously pinned named window (N4).

    Args:
        name: Name of a previously pinned session.

    Returns:
        Status dict with name, hwnd, and title, or error if not found.
    """
    global _active_session, _pinned_hwnd

    if name not in _sessions:
        available = list(_sessions.keys())
        return {
            "status": "error",
            "note": f"Session '{name}' not found. Available: {available}",
        }

    _active_session = name
    _pinned_hwnd = _sessions[name]["hwnd"]  # Keep legacy var in sync
    return {"status": "switched", "name": name, **_sessions[name]}


def list_sessions() -> list[dict]:
    """Return all named sessions with their hwnd, title, and active status.

    Returns:
        List of session dicts (name, hwnd, title, active).
    """
    return [
        {
            "name": name,
            "hwnd": info["hwnd"],
            "title": info["title"],
            "active": name == _active_session,
        }
        for name, info in _sessions.items()
    ]


# ---------------------------------------------------------------------------
# Focus management
# ---------------------------------------------------------------------------

_FOCUS_CLICK_OVERRIDE: bool | None = None


def set_focus_click(enabled: bool | None) -> bool | None:
    """Override the auto-click-on-focus behaviour for this process.

    GUI flows (5250 terminals, spreadsheets) must NOT have the cursor moved
    on every injection: clicking the window centre lands in the middle of
    the remote screen and destroys the field the operator selected.

    Args:
        enabled: True to force the click, False to disable it, None to fall
            back to config.FOCUS_CLICK_ENABLED.

    Returns:
        The stored override (None when back to the config default).
    """
    global _FOCUS_CLICK_OVERRIDE
    _FOCUS_CLICK_OVERRIDE = enabled
    return _FOCUS_CLICK_OVERRIDE


def focus_click_enabled() -> bool:
    """Effective auto-click setting: override wins over the config default."""
    if _FOCUS_CLICK_OVERRIDE is None:
        return FOCUS_CLICK_ENABLED
    return _FOCUS_CLICK_OVERRIDE


def get_window_geometry(hwnd: int) -> dict:
    """Return window/client geometry and DPI context used for click math.

    Args:
        hwnd: Window handle.

    Returns:
        Dict with window_rect, client size and screen origin, caption
        offset, screen size, the effective focus-click setting and the
        remote viewport child (when present).
    """
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    cr = win32gui.GetClientRect(hwnd)
    origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))
    client_w, client_h = cr[2] - cr[0], cr[3] - cr[1]

    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "window_rect": {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left,
            "height": bottom - top,
        },
        "client": {
            "width": client_w,
            "height": client_h,
            "screen_x": origin_x,
            "screen_y": origin_y,
        },
        "caption_offset": {"x": origin_x - left, "y": origin_y - top},
        "screen": {
            "width": GetSystemMetrics(SM_CXSCREEN),
            "height": GetSystemMetrics(SM_CYSCREEN),
        },
        "viewport": find_viewport(hwnd),
        "focus_click_enabled": focus_click_enabled(),
    }


VIEWPORT_CLASS_PREFIX = "gui.tabbar_panel"


def find_viewport(hwnd: int) -> dict | None:
    """Locate the child window that renders the remote screen.

    The AnyDesk control window has its own toolbar (~104px tall at the top),
    so root-client coordinates are NOT remote coordinates. The remote image
    lives in a child window; clicking inside it is what reaches the remote
    desktop.

    Args:
        hwnd: Root AnyDesk window handle.

    Returns:
        Dict with hwnd, offset (relative to the root client), width and
        height, or None when no viewport child is found.
    """
    found: list[int] = []

    def callback(child: int, _extra: object) -> bool:
        try:
            cls = win32gui.GetClassName(child)
        except Exception:
            return True
        if cls.startswith(VIEWPORT_CLASS_PREFIX):
            found.append(child)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, callback, None)
    except Exception:
        return None
    if not found:
        return None

    def area(h: int) -> int:
        r = win32gui.GetClientRect(h)
        return max(0, r[2] - r[0]) * max(0, r[3] - r[1])

    child = max(found, key=area)
    cr = win32gui.GetClientRect(child)
    width, height = cr[2] - cr[0], cr[3] - cr[1]
    if width <= 0 or height <= 0:
        return None

    cx, cy = win32gui.ClientToScreen(child, (0, 0))
    rx, ry = win32gui.ClientToScreen(hwnd, (0, 0))
    return {
        "hwnd": child,
        "offset": {"x": cx - rx, "y": cy - ry},
        "width": width,
        "height": height,
    }


def click_client_point(
    hwnd: int,
    x: int,
    y: int,
    button: str = "left",
    double: bool = False,
) -> dict:
    """Click a point expressed in window-client coordinates.

    Client coordinates are what a 1:1 capture of the window uses, so OCR
    boxes and element boxes can be passed straight through. Coordinates are
    translated to screen space with ClientToScreen (caption/border safe) and
    normalised to the 0-65535 MOUSEEVENTF_ABSOLUTE space.

    Args:
        hwnd: Window handle.
        x: Client X in pixels.
        y: Client Y in pixels.
        button: "left", "right" or "middle".
        double: Send two down/up pairs.

    Returns:
        Dict with status, target client/screen points and note.
    """
    flags = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }
    if button not in flags:
        return {
            "status": "error",
            "note": f"Unknown button {button!r}. Use left, right or middle.",
        }

    cr = win32gui.GetClientRect(hwnd)
    client_w, client_h = cr[2] - cr[0], cr[3] - cr[1]
    if not (0 <= x < client_w and 0 <= y < client_h):
        return {
            "status": "error",
            "note": f"({x},{y}) is outside the client area {client_w}x{client_h}.",
        }

    origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))
    screen_x, screen_y = origin_x + x, origin_y + y

    screen_w = GetSystemMetrics(SM_CXSCREEN)
    screen_h = GetSystemMetrics(SM_CYSCREEN)
    if screen_w <= 1 or screen_h <= 1:
        return {"status": "error", "note": "Screen metrics unavailable."}

    nx = (screen_x * 65535) // (screen_w - 1)
    ny = (screen_y * 65535) // (screen_h - 1)

    down_flag, up_flag = flags[button]
    presses = 2 if double else 1
    events = 1 + presses * 2
    inputs = (INPUT * events)()

    inputs[0].type = INPUT_MOUSE
    inputs[0].ii.mi.dx = nx
    inputs[0].ii.mi.dy = ny
    inputs[0].ii.mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE

    idx = 1
    for _ in range(presses):
        for flag in (down_flag, up_flag):
            inputs[idx].type = INPUT_MOUSE
            inputs[idx].ii.mi.dx = nx
            inputs[idx].ii.mi.dy = ny
            inputs[idx].ii.mi.dwFlags = (
                MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | flag
            )
            idx += 1

    try:
        send_inputs(inputs)
    except RuntimeError as exc:
        return {"status": "error", "note": f"Click failed: {exc}"}

    return {
        "status": "clicked",
        "button": button,
        "presses": presses,
        "client": {"x": x, "y": y, "width": client_w, "height": client_h},
        "screen": {"x": screen_x, "y": screen_y},
        "note": "Click sent. Effect NOT verified — capture and confirm.",
    }


def _click_window_center(hwnd: int) -> None:
    """Send a left-click to the center of the window via SendInput.

    This ensures AnyDesk receives keyboard input after SetForegroundWindow
    without requiring the user to manually place the cursor first.

    Args:
        hwnd: Window handle to click.
    """
    try:
        cr = win32gui.GetClientRect(hwnd)
        click_client_point(hwnd, (cr[2] - cr[0]) // 2, (cr[3] - cr[1]) // 2)
    except Exception:
        return  # Non-fatal — skip click if geometry unavailable


def focus_and_verify(focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS) -> None:
    """Bring the pinned window to the foreground and verify focus.

    Uses AttachThreadInput to bypass Windows' foreground lock restriction,
    which prevents background processes from stealing focus.

    If FOCUS_CLICK_ENABLED, also clicks the center of the window after the
    focus delay so AnyDesk receives keyboard input without requiring the
    user to place the cursor manually.

    Raises:
        RuntimeError: If no window is pinned or focus verification fails.
    """
    active_hwnd = get_active_hwnd()
    if active_hwnd is None:
        raise RuntimeError(
            "No AnyDesk window pinned. Use select_anydesk_window first."
        )

    if not win32gui.IsWindow(active_hwnd):
        raise RuntimeError(
            f"Pinned hwnd {active_hwnd} is no longer valid. "
            "The AnyDesk session may have been closed."
        )

    # Get foreground window's thread
    fg_hwnd = win32gui.GetForegroundWindow()
    fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
    our_thread = win32api.GetCurrentThreadId()

    attached = False
    try:
        if fg_thread != our_thread:
            ctypes.windll.user32.AttachThreadInput(our_thread, fg_thread, True)
            attached = True

        if win32gui.IsIconic(active_hwnd):
            win32gui.ShowWindow(active_hwnd, win32con.SW_RESTORE)

        win32gui.BringWindowToTop(active_hwnd)
        win32gui.SetForegroundWindow(active_hwnd)

    finally:
        if attached:
            ctypes.windll.user32.AttachThreadInput(our_thread, fg_thread, False)

    # Ventana ya en primer plano: no se paga el delay completo en cada llamada
    # (medido: 500 ms x 9 llamadas = ~4.5 s muertos por pagina). Respiro minimo.
    if win32gui.GetForegroundWindow() == active_hwnd:
        time.sleep(min(focus_delay_ms, 50) / 1000.0)
    else:
        time.sleep(focus_delay_ms / 1000.0)

    # Auto-click window center so AnyDesk accepts keyboard input
    if focus_click_enabled():
        _click_window_center(active_hwnd)
        if FOCUS_CLICK_DELAY_MS > 0:
            time.sleep(FOCUS_CLICK_DELAY_MS / 1000.0)

    foreground = win32gui.GetForegroundWindow()
    if foreground != active_hwnd:
        raise RuntimeError(
            "Focus lost, injection aborted. "
            f"Expected hwnd {active_hwnd}, got {foreground}."
        )


def verify_focus_post() -> None:
    """Post-injection focus verification.

    Raises:
        RuntimeError: If focus has drifted away from the active window.
    """
    active_hwnd = get_active_hwnd()
    if active_hwnd is None:
        return

    foreground = win32gui.GetForegroundWindow()
    if foreground != active_hwnd:
        raise RuntimeError(
            "Focus drifted during injection. "
            f"Expected hwnd {active_hwnd}, got {foreground}. "
            "Keystrokes may have been sent to the wrong window."
        )
