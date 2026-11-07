"""Keyboard injection via SendInput for AnyDesk.

Simple flow: focus_and_verify -> type each char via _send_char -> verify_focus_post.

All characters are sent via KEYEVENTF_UNICODE (wVk=0, wScan=Unicode codepoint).
This is completely layout-independent — works regardless of the local keyboard
layout (EN-US, ES-PE, etc.). No VkKeyScanW mapping needed for character injection.

Special keys (Tab, F-keys, numpad +, Alt+Tab, ...) are sent via press_keys()
using wVk + scancode. Whether AnyDesk forwards them is verified empirically
(T0 spike) — some combos may be intercepted locally or dropped remotely.

Ctrl+C (send_cancel) cannot be sent programmatically through AnyDesk —
it focuses the window so the operator can press Ctrl+C manually.

Enter is NEVER sent by any function in this module — enforced in code.
"""

from __future__ import annotations

import logging
import time

from .command_templates import wrap_command, wrap_command_base64
from .config import (
    CANCEL_FOCUS_DELAY_MS,
    DEFAULT_FOCUS_DELAY_MS,
    DEFAULT_KEYSTROKE_DELAY_MS,
    MIN_KEYSTROKE_DELAY_MS,
)
from .win32_input import (
    INPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_EXTENDEDKEY,
    KEYEVENTF_KEYUP,
    KEYEVENTF_SCANCODE,
    KEYEVENTF_UNICODE,
    MAPVK_VK_TO_VSC,
    MapVirtualKeyW,
    send_inputs,
)
from .window_manager import focus_and_verify, get_pinned_hwnd, verify_focus_post

log = logging.getLogger(__name__)

def _send_char(char: str) -> None:
    """Send a single character via KEYEVENTF_UNICODE (layout-independent).

    Uses wVk=0, wScan=<unicode codepoint>, dwFlags=KEYEVENTF_UNICODE.
    This sends the character directly by its Unicode value, bypassing
    the local keyboard layout entirely. Works regardless of whether
    the local machine has EN-US, ES-PE, or any other layout active.

    Args:
        char: Single character to type.

    Raises:
        RuntimeError: If SendInput fails.
    """
    code = ord(char)
    inputs = (INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki.wVk = 0
    inputs[0].ii.ki.wScan = code
    inputs[0].ii.ki.dwFlags = KEYEVENTF_UNICODE
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ii.ki.wVk = 0
    inputs[1].ii.ki.wScan = code
    inputs[1].ii.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

    try:
        send_inputs(inputs)
    except RuntimeError as exc:
        raise RuntimeError(
            f"SendInput UNICODE failed for {char!r} (U+{code:04X}). {exc}"
        ) from exc


def _check_quote_balance(text: str) -> str | None:
    """Check for unbalanced quotes that would leave PS in >> continuation.

    Removes PS-escaped quote pairs ('' and `") before counting, so
    intentionally escaped quotes don't trigger false positives.

    Returns an error message if unbalanced, None if OK.
    """
    cleaned = text.replace("''", "").replace('`"', "")

    single = cleaned.count("'")
    double = cleaned.count('"')

    issues: list[str] = []
    if single % 2 != 0:
        issues.append("single quotes (')")
    if double % 2 != 0:
        issues.append('double quotes (")')

    if issues:
        return (
            f"Unbalanced {' and '.join(issues)} detected. "
            "PowerShell will enter >> continuation mode, requiring "
            "Ctrl+C to recover. Fix quote pairing before injecting."
        )
    return None


# ---------------------------------------------------------------------------
# Special keys (press_keys, v3.6.0 — T0 spike)
# ---------------------------------------------------------------------------

_VK_CODES: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,  # VK_MENU
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "add": 0x6B,  # numpad +
    "subtract": 0x6D,  # numpad -
    "multiply": 0x6A,  # numpad *
    "divide": 0x6F,  # numpad /
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

_MODIFIERS = ("shift", "ctrl", "alt")

# VKs that require KEYEVENTF_EXTENDEDKEY (arrows, navigation, numpad /).
_EXTENDED_VK = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    0x2D, 0x2E, 0x6F,
}

# Refused in code: the hard rule "never press Enter" is enforced here,
# not left to the caller's discipline.
_REFUSED_KEYS = ("enter", "return", "\n", "\r")

# Used only by copy_clipboard()/paste_clipboard(): letters are not in _VK_CODES on purpose,
# so Ctrl+C cannot be reached through press_keys.
_VK_CONTROL = 0x11
_VK_SHIFT = 0x10
_VK_C = 0x43
_VK_V = 0x56
_VK_RETURN = 0x0D


def _send_vk(vk: int, keyup: bool = False) -> None:
    """Send one virtual-key event via wVk + scancode.

    Args:
        vk: Virtual-key code (e.g. 0x09 for Tab).
        keyup: If True, send key-release; otherwise key-press.

    Raises:
        RuntimeError: If SendInput fails.
    """
    scan = MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE
    if vk in _EXTENDED_VK:
        flags |= KEYEVENTF_EXTENDEDKEY
    if keyup:
        flags |= KEYEVENTF_KEYUP
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki.wVk = vk
    inputs[0].ii.ki.wScan = scan
    inputs[0].ii.ki.dwFlags = flags

    try:
        send_inputs(inputs)
    except RuntimeError as exc:
        raise RuntimeError(
            f"SendInput VK failed for vk=0x{vk:02X} "
            f"({'keyup' if keyup else 'keydown'}). {exc}"
        ) from exc


def press_keys(
    keys: list[str],
    key_delay_ms: int = 60,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
) -> dict:
    """Focus the pinned AnyDesk window and press special keys.

    Modifiers (shift/ctrl/alt) are held while the remaining keys are
    tapped, then released — so ["shift", "f4"] sends Shift+F4 and
    ["alt", "tab"] sends Alt+Tab.

    Hard refusals (enforced in code, not by convention):
    - Enter/Return/newline: NEVER sent. The operator presses Enter manually.
    - Ctrl+C: refused — AnyDesk renders programmatic Ctrl+C as literal
      text instead of a console interrupt. Use send_cancel() so the
      operator presses it physically.

    Whether AnyDesk forwards a given key is verified empirically (T0
    spike): some combos may be intercepted locally or dropped remotely.
    Always verify the effect with capture_screenshot/read_from_anydesk.

    Args:
        keys: Key names (case-insensitive). Supported: tab, shift, ctrl,
            alt, escape/esc, space, backspace, pageup, pagedown, end,
            home, left, up, right, down, insert, delete, add (numpad +),
            subtract, multiply, divide, f1..f12.
        key_delay_ms: Delay between key events (ms). Floor: 30ms.
        focus_delay_ms: Delay after focusing window before pressing (ms).

    Returns:
        Dict with status, keys_pressed, event_count, elapsed_ms, and note.
    """
    names = [str(k).strip().lower() for k in keys]

    if not names:
        return {
            "status": "error",
            "keys_pressed": [],
            "event_count": 0,
            "elapsed_ms": 0,
            "note": "Empty key list. Nothing pressed.",
        }

    refused = [k for k in names if k in _REFUSED_KEYS]
    if refused:
        return {
            "status": "error",
            "keys_pressed": [],
            "event_count": 0,
            "elapsed_ms": 0,
            "note": (
                f"Refused {refused}: Enter is NEVER sent programmatically. "
                "The operator presses Enter manually after verifying."
            ),
        }

    if "ctrl" in names and "c" in names:
        return {
            "status": "error",
            "keys_pressed": [],
            "event_count": 0,
            "elapsed_ms": 0,
            "note": (
                "Refused ctrl+c: AnyDesk renders programmatic Ctrl+C as "
                "literal text, not a console interrupt. Use send_cancel() "
                "so the operator presses it physically."
            ),
        }

    unknown = [k for k in names if k not in _VK_CODES]
    if unknown:
        return {
            "status": "error",
            "keys_pressed": [],
            "event_count": 0,
            "elapsed_ms": 0,
            "note": (
                f"Unknown key names: {unknown}. "
                f"Supported: {sorted(_VK_CODES)}."
            ),
        }

    mods = [k for k in names if k in _MODIFIERS]
    taps = [k for k in names if k not in _MODIFIERS]

    key_delay_ms = max(key_delay_ms, MIN_KEYSTROKE_DELAY_MS)
    delay_s = key_delay_ms / 1000.0

    # 1. Focus
    try:
        focus_and_verify(focus_delay_ms)
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": names,
            "event_count": 0,
            "elapsed_ms": 0,
            "note": str(exc),
        }

    # 2. Press: modifiers down -> tap each key -> modifiers up (reversed)
    events = 0
    held = list(mods)
    start = time.perf_counter()
    try:
        for m in mods:
            _send_vk(_VK_CODES[m], keyup=False)
            events += 1
            time.sleep(delay_s)
        for t in taps:
            _send_vk(_VK_CODES[t], keyup=False)
            events += 1
            time.sleep(delay_s)
            _send_vk(_VK_CODES[t], keyup=True)
            events += 1
            time.sleep(delay_s)
        for m in reversed(mods):
            _send_vk(_VK_CODES[m], keyup=True)
            events += 1
            time.sleep(delay_s)
        held.clear()
    except RuntimeError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "error",
            "keys_pressed": names,
            "event_count": events,
            "elapsed_ms": elapsed_ms,
            "note": f"Press failed after {events} events: {exc}",
        }
    finally:
        # Never leave a modifier held on the operator's machine if the
        # sequence above failed midway (held is empty on success).
        for m in reversed(held):
            try:
                _send_vk(_VK_CODES[m], keyup=True)
            except RuntimeError:
                pass
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # 3. Post-verify focus
    try:
        verify_focus_post()
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": names,
            "event_count": events,
            "elapsed_ms": elapsed_ms,
            "note": f"Focus drifted: {exc}",
        }

    return {
        "status": "pressed",
        "keys_pressed": names,
        "event_count": events,
        "elapsed_ms": elapsed_ms,
        "note": (
            "Keys sent. Effect NOT verified — confirm visually with "
            "capture_screenshot or read_from_anydesk before proceeding."
        ),
    }


def _clipboard_combo(
    vk_key: int,
    tecla: str,
    key_delay_ms: int = 60,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
    shift: bool = False,
) -> dict:
    """Send Ctrl(+Shift)+<tecla> as a CLIPBOARD operation, GUI only.

    shift=True is Ctrl+Shift+V ("paste without formatting" in Sheets/Chrome).

    press_keys() refuses ctrl+c on purpose: in a console it is an interrupt
    signal. This function exists only for GUI clipboard work (5250 emulator
    block <-> remote clipboard) and is a separate, explicitly named capability
    so the refusal in press_keys stays intact.

    Implemented standalone, not via press_keys: letters are deliberately
    absent from _VK_CODES (press_keys cannot type text), so the VK for the
    letter key is used directly here.

    HARD LIMITS (measured, do not paper over):
    - The clipboard lives on the REMOTE machine: this code cannot read it.
      The only proof that the copy worked is pasting somewhere and looking.
    - AnyDesk may not forward programmatic Ctrl+C at all; the first live run
      decides. If nothing pastes, the answer is "not forwarded", not "retry".

    Returns:
        Dict with status, keys_pressed, event_count, elapsed_ms, note.
    """
    delay_s = max(key_delay_ms, MIN_KEYSTROKE_DELAY_MS) / 1000.0
    etiqueta = f"ctrl+shift+{tecla}" if shift else f"ctrl+{tecla}"
    try:
        focus_and_verify(focus_delay_ms)
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": etiqueta.split("+"),
            "event_count": 0,
            "elapsed_ms": 0,
            "note": str(exc),
        }

    mods = [_VK_CONTROL] + ([_VK_SHIFT] if shift else [])
    events = 0
    held: list[int] = []
    start = time.perf_counter()
    try:
        for vk in mods:
            _send_vk(vk, keyup=False)
            events += 1
            held.append(vk)
            time.sleep(delay_s)
        _send_vk(vk_key, keyup=False)
        events += 1
        time.sleep(delay_s)
        _send_vk(vk_key, keyup=True)
        events += 1
        time.sleep(delay_s)
        for vk in reversed(mods):
            _send_vk(vk, keyup=True)
            events += 1
            held.remove(vk)
        time.sleep(delay_s)
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": etiqueta.split("+"),
            "event_count": events,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "note": f"Copy failed after {events} events: {exc}",
        }
    finally:
        # Un modificador pegado en la maquina del operador es inaceptable.
        for vk in reversed(held):
            try:
                _send_vk(vk, keyup=True)
            except RuntimeError:
                pass

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    try:
        verify_focus_post()
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": etiqueta.split("+"),
            "event_count": events,
            "elapsed_ms": elapsed_ms,
            "note": f"Focus drifted: {exc}",
        }

    return {
        "status": "pressed",
        "keys_pressed": etiqueta.split("+"),
        "event_count": events,
        "elapsed_ms": elapsed_ms,
        "note": (
            f"{etiqueta.upper()} sent to the pinned window as a CLIPBOARD "
            "operation. The remote clipboard cannot be read from here: the "
            "only proof is the visible effect after the paste, verified with "
            "a capture."
        ),
    }


def copy_clipboard(
    key_delay_ms: int = 60,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
) -> dict:
    """Ctrl+C as a CLIPBOARD copy (GUI apps only, v3.7.2).

    Separate from press_keys on purpose: there Ctrl+C is refused, because in
    a console it is an interrupt. Never use this to stop a process.

    AnyDesk may not forward programmatic Ctrl+C at all: the first live run
    decides. If nothing pastes, the answer is "not forwarded", not "retry".
    """
    return _clipboard_combo(_VK_C, "c", key_delay_ms, focus_delay_ms)


def paste_clipboard(
    key_delay_ms: int = 60,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
    shift: bool = False,
) -> dict:
    """Ctrl(+Shift)+V as a CLIPBOARD paste (GUI apps only, v3.7.2).

    shift=True sends Ctrl+Shift+V, which in Chrome/Sheets is "paste without
    formatting": the block lands as values instead of being re-interpreted.

    Letters are not in _VK_CODES, so press_keys cannot send Ctrl+V either;
    this is the only path. Verify the result visually: a paste into a
    spreadsheet can land in the wrong cell.
    """
    return _clipboard_combo(_VK_V, "v", key_delay_ms, focus_delay_ms, shift)


def press_enter(
    key_delay_ms: int = 60,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
) -> dict:
    """Send Enter (v3.8.0). Separate capability, press_keys still refuses it.

    press_keys() refuses Enter on purpose: in the operator's daily work an
    accidental Enter submits a form. This function exists for the ONE case
    that needs it explicitly (an IBM i login screen, a dialog accept), is
    named after the risk, and is audited as "press:enter (submit)".

    Caller responsibility: verify the screen BEFORE calling. Enter is a
    commit, not a keystroke.
    """
    delay_s = max(key_delay_ms, MIN_KEYSTROKE_DELAY_MS) / 1000.0
    start = time.perf_counter()
    try:
        focus_and_verify(focus_delay_ms)
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": ["enter"],
            "event_count": 0,
            "elapsed_ms": 0,
            "note": str(exc),
        }
    try:
        _send_vk(_VK_RETURN, keyup=False)
        time.sleep(delay_s)
        _send_vk(_VK_RETURN, keyup=True)
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": ["enter"],
            "event_count": 0,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "note": str(exc),
        }
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    try:
        verify_focus_post()
    except RuntimeError as exc:
        return {
            "status": "error",
            "keys_pressed": ["enter"],
            "event_count": 2,
            "elapsed_ms": elapsed_ms,
            "note": f"Focus drifted: {exc}",
        }
    return {
        "status": "pressed",
        "keys_pressed": ["enter"],
        "event_count": 2,
        "elapsed_ms": elapsed_ms,
        "note": "Enter sent. Effect NOT verified - capture the screen next.",
    }


def write_to_anydesk(
    command: str,
    keystroke_delay_ms: int = DEFAULT_KEYSTROKE_DELAY_MS,
    focus_delay_ms: int = DEFAULT_FOCUS_DELAY_MS,
    wrap: bool = True,
    base64_output: bool = False,
    force_dangerous: bool = False,
    sanitizer_available: bool = True,
) -> dict:
    """Focus the pinned AnyDesk window and inject text character by character.

    Simple flow: focus -> type each char with delay -> verify focus.

    Args:
        command: Text to inject. Must NOT contain newlines.
        keystroke_delay_ms: Delay between each character (ms). Floor: 30ms.
        focus_delay_ms: Delay after focusing window before typing (ms).
        wrap: If True, auto-wrap with sanitizer check before injecting.
        base64_output: If True, use base64 wrapper instead of standard.
            Only effective when wrap=True.
        force_dangerous: Unused — kept for API compatibility.

    Returns:
        Dict with status, char_count, original_command, wrapped,
        elapsed_ms, and note.
    """
    original_command = command

    if base64_output and not wrap:
        return {
            "status": "error",
            "char_count": 0,
            "original_command": original_command,
            "wrapped": False,
            "elapsed_ms": 0,
            "note": (
                "base64_output=True requires wrap=True. Base64 encoding "
                "is applied via the command wrapper — it cannot work "
                "without wrapping. Set wrap=True or remove base64_output."
            ),
        }

    if any(ch in command for ch in ("\n", "\r")):
        return {
            "status": "error",
            "char_count": 0,
            "original_command": original_command,
            "wrapped": False,
            "elapsed_ms": 0,
            "note": (
                "Multi-line input rejected. Commands containing newlines "
                "must be split into separate steps. Remove all \\n and \\r "
                "characters."
            ),
        }

    command = command.replace("\n", "").replace("\r", "")
    command = command.replace("`n", "").replace("`r", "")

    if not command:
        return {
            "status": "error",
            "char_count": 0,
            "original_command": original_command,
            "wrapped": False,
            "elapsed_ms": 0,
            "note": "Empty command after sanitization.",
        }

    was_wrapped = False
    if wrap:
        if base64_output:
            command = wrap_command_base64(command, sanitizer_available=sanitizer_available)
        else:
            command = wrap_command(command)
        was_wrapped = True

    quote_error = _check_quote_balance(command)
    if quote_error:
        return {
            "status": "error",
            "char_count": len(command),
            "original_command": original_command,
            "wrapped": was_wrapped,
            "elapsed_ms": 0,
            "note": quote_error,
        }

    keystroke_delay_ms = max(keystroke_delay_ms, MIN_KEYSTROKE_DELAY_MS)
    delay_s = keystroke_delay_ms / 1000.0

    # 1. Focus
    try:
        focus_and_verify(focus_delay_ms)
    except RuntimeError as exc:
        return {
            "status": "error",
            "char_count": 0,
            "original_command": original_command,
            "wrapped": was_wrapped,
            "elapsed_ms": 0,
            "note": str(exc),
        }

    # 2. Inject character by character (KEYEVENTF_UNICODE — layout-independent)
    start = time.perf_counter()
    chars_injected = 0
    try:
        for char in command:
            _send_char(char)
            chars_injected += 1
            time.sleep(delay_s)
    except RuntimeError as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "error",
            "char_count": len(command),
            "original_command": original_command,
            "wrapped": was_wrapped,
            "elapsed_ms": elapsed_ms,
            "note": (
                f"Injection failed after {chars_injected}/{len(command)} chars: {exc}"
            ),
        }
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # 3. Post-verify focus
    try:
        verify_focus_post()
    except RuntimeError as exc:
        return {
            "status": "error",
            "char_count": len(command),
            "original_command": original_command,
            "wrapped": was_wrapped,
            "elapsed_ms": elapsed_ms,
            "note": f"Focus drifted: {exc}",
        }

    return {
        "status": "injected",
        "char_count": len(command),
        "original_command": original_command,
        "wrapped": was_wrapped,
        "elapsed_ms": elapsed_ms,
        "note": "Enter NOT pressed — awaiting operator confirmation",
    }


def send_cancel() -> dict:
    """Request the operator to press Ctrl+C on the remote console.

    AnyDesk does NOT forward programmatic Ctrl+C (SendInput) as a real
    console interrupt signal — it renders it as literal text. Only a
    physical Ctrl+C from the operator's keyboard generates the
    CTRL_C_EVENT that stops running processes.

    This tool focuses the AnyDesk window so the operator can immediately
    press Ctrl+C without needing to click on it first.

    Returns:
        Dict with status and instructions for the operator.
    """
    hwnd = get_pinned_hwnd()
    if hwnd is None:
        return {
            "status": "error",
            "note": "No AnyDesk window pinned. Use select_anydesk_window first.",
        }

    try:
        focus_and_verify(CANCEL_FOCUS_DELAY_MS)
    except RuntimeError as exc:
        return {"status": "error", "note": str(exc)}

    return {
        "status": "awaiting_operator",
        "note": (
            "AnyDesk window focused. OPERATOR: press Ctrl+C NOW to cancel "
            "the running command. Programmatic Ctrl+C cannot interrupt "
            "processes through AnyDesk — only physical keyboard input works."
        ),
    }
def hold_modifier(name: str, down: bool) -> None:
    """Hold or release one modifier key, for shift+click style gestures.

    press_keys() holds a modifier only for the duration of one call, so it
    cannot express "keep shift down while something else happens". This is the
    primitive for that, and callers MUST release in a finally block: a stuck
    modifier on the operator's machine is unacceptable.

    Args:
        name: "shift", "ctrl" or "alt".
        down: True presses, False releases.

    Raises:
        RuntimeError: Unknown modifier or SendInput failure.
    """
    if name not in ("shift", "ctrl", "alt"):
        raise RuntimeError(f"Unknown modifier {name!r}. Use shift, ctrl or alt.")
    _send_vk(_VK_CODES[name], keyup=not down)