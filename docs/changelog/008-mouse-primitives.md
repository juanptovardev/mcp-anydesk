# 008 — Primitivas de ratón + causa raíz del fallo PILOTO-01

- Rama: `refactor/v3-limpio`
- Fecha: 2026-10-26
- Origen: T-IBM-02. El piloto 01 inyectó texto pero no aterrizó en `Calle`.

## Causa raíz del fallo PILOTO-01

`focus_and_verify()` ejecutaba `_click_window_center()` en **cada** foco
(`FOCUS_CLICK_ENABLED=True`). Cada `write_to_anydesk`, `press_keys` o
`capture_screenshot` movía primero el cursor remoto al centro de la pantalla y
luego escribía ahí. Nada llegaba a `Calle`; IBM respondía
`El campo requiere caracteres numericos`.

La hipótesis anterior ("el operador dejó el cursor fuera del campo") era
incorrecta.

## Cambios

- `window_manager.py`
  - `set_focus_click(enabled)` / `focus_click_enabled()`: override por proceso
    sobre `FOCUS_CLICK_ENABLED` (None = default de config).
  - `get_window_geometry(hwnd)`: window_rect, client, caption_offset, screen,
    viewport y el estado efectivo de focus-click.
  - `find_viewport(hwnd)`: localiza el hijo `gui.tabbar_panel*` que dibuja la
    pantalla remota y devuelve su hwnd, offset relativo al cliente raíz y tamaño
    (medido en vivo: 1022x471 en offset 1,104).
  - `click_client_point(hwnd,x,y,button,double)`: coords de cliente → pantalla
    con `ClientToScreen`, normalización `*65535//(size-1)` (corrige el off-by-one
    del código anterior), un solo `send_inputs` con `[MOVE,(DOWN,UP)*n]`.
  - `_click_window_center` ahora delega en `click_client_point`.
- `win32_input.py`: constantes `MOUSEEVENTF_RIGHTDOWN/UP`, `MIDDLEDOWN/UP`.
- `server.py`: tools nuevas `geometry`, `set_focus_click_mode`, `click_point`.
  `click_point` recibe **coordenadas del viewport remoto**, no de la ventana:
  el área cliente raíz incluye la barra de AnyDesk.

## Medido en vivo

- Ventana `Oficina - AnyDesk` hwnd 198526, cliente 1024x576 en pantalla (171,96).
- Viewport hijo hwnd 393712, 1022x471 en offset (1,104). 576-104=472 ≈ 471.
- `PrintWindow(PW_RENDERFULLCONTENT)` sobre el viewport devuelve la pantalla
  remota a 1:1 incluso con la ventana tapada; `mss` sobre la región devuelve lo
  que haya encima (mi propio terminal), así que no sirve con la ventana oculta.
- El screenshot del MCP (cap 640px) sale de la ventana raíz: 1024→640 = factor
  1.6, y arrastra la barra. No usar sus píxeles para clics.

## Tests

`tests/test_window_manager_click.py` (7 casos nuevos, 12 total OK): rechazo
fuera de rango sin enviar eventos, botón inválido, conversión cliente→pantalla y
normalización, doble clic (5 eventos), flags de botón derecho, override de
focus-click, geometría, detección de viewport (elige el hijo más grande, offset
correcto, None si no hay).
