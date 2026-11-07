# 007 — Review round press_keys (fixes + tests)

- Rama: `refactor/v3-limpio`
- Fecha: 2026-10-26
- Origen: code review NEEDS_REVISION sobre 006 (1 blocker, 1 major, 4 minors).

## Fixes

- **Blocker** `keyboard_injector.py`: `["c"]` suelto llegaba a `_VK_CODES["c"]` → `KeyError` no capturado (con `["alt","c"]` dejaba Alt trabado). Gates reordenados (ctrl+c antes de unknown) y eliminado el carve-out `k != "c"`.
- **Major** `keyboard_injector.py`: `finally` libera modificadores pendientes (`held`) si la secuencia falla a mitad. En happy path `held` queda vacío: sin keyups duplicados (lo verifica el test).
- **Minor** `server.py`: auditoría usa las teclas de entrada (`press:tab+f4`), no el resultado (los rechazos ya no guardan `press:` vacío).
- **Minor** `server.py`: docstring de la tool trae la lista completa de teclas (el LLM solo ve el docstring).
- **Minor** `RONDA_PRUEBAS.md`: 18 → 19 tools.
- **Minor** `docs/testing/TEST_PROMPT.md` (TEST 12, fecha, versión, X/12) y `docs/SYSTEM_PROMPT.md` (tool en lista + regla 15) actualizados. Deuda de 006 cerrada.

## Simplificación (over-engineering check del review)

- `_send_char` y `_send_vk` delegan en `send_inputs()` (win32_input, antes muerto), preservando contexto en el error (`... from exc`). Imports muertos fuera (`ctypes`, `SIZEOF_INPUT`, `_SendInput`).

## Tests

- Nuevo `tests/test_press_keys_validation.py` (stdlib unittest, fakes sin SendInput real): 8 rechazos sin excepción + secuencia shift+f4 exacta + liberación de shift en fallo simulado. 3/3 OK.
- `python test_mcp_smoke.py` → 19 tools, v3.6.0, sin regresión.
