# 006 — press_keys (teclas especiales, T0) — v3.6.0

- Rama: `refactor/v3-limpio`
- Fecha: 2026-10-26
- Objetivo: desbloquear el flujo IBM-matriz (Tab, `+` numérico, F10, Shift+F4, Alt+Tab), imposible con `write_to_anydesk` (solo UNICODE, sin teclas especiales).

## Cambios por archivo

- `mcp_anydesk_server/win32_input.py`: constante `KEYEVENTF_EXTENDEDKEY = 0x0001` (flechas, navegación, numpad `/` la exigen).
- `mcp_anydesk_server/keyboard_injector.py`:
  - `press_keys(keys, key_delay_ms=60, focus_delay_ms=500)` — modificadores (shift/ctrl/alt) held mientras las demás teclean, luego release en reversa.
  - `_send_vk()` — wVk + scancode vía `MapVirtualKeyW`, flag EXTENDED donde aplica.
  - Rechazos en código: Enter/Return/newline (regla dura) y Ctrl+C (remite a `send_cancel`).
  - Mapa de 30 nombres: tab, shift, ctrl, alt, esc, space, backspace, pageup/down, end, home, flechas, insert, delete, add/subtract/multiply/divide (numpad), f1–f12.
- `mcp_anydesk_server/server.py`: tool `press_keys` registrado en bloque `write_capable`, con auditoría en sesión (`press:...`).
- `mcp_anydesk_server/__init__.py`: versión 3.5.1 → 3.6.0.

## Bugs encontrados durante implementación

- `c` no existe como nombre de tecla: el rechazo de ctrl+c quedaba inalcanzable tras el chequeo de nombres desconocidos. Fix: chequeo ctrl+c ANTES del chequeo unknown.

## Verificación

- `python -c "import mcp_anydesk_server.server"` limpio.
- `python test_mcp_smoke.py` → 19 tools (18 + press_keys), sin regresión.
- Pruebas vivas T0 pendientes de aprobación del operador (Alt+Tab con advertencia: AnyDesk puede retenerlo local).

## Deuda / pendiente

- Efecto real de cada tecla por verificar en vivo (T0a–T0c seguro; `add` y Shift+F4 en contexto IBM).
- ~~`docs/testing/TEST_PROMPT.md` y `docs/SYSTEM_PROMPT.md` aún no mencionan `press_keys`.~~ Resuelto en 007.
