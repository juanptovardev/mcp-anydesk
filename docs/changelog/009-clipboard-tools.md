# 009 — Clipboard tools (copy_clipboard / paste_clipboard) v3.7.1

## Motivo

El flujo de trabajo del operador en el 5250 termina con:

```
Shift + 7 abajo + 72 derecha + 14 abajo  ->  Ctrl+C  ->  Alt+Tab  ->  Ctrl+V
```

`press_keys` no puede hacer Ctrl+C (lo rechaza por diseño) y tampoco Ctrl+V
(las letras no existen en `_VK_CODES`, así que `press_keys` nunca puede
teclear texto). Sin esas dos combinaciones el pegado es imposible.

## Qué se añadió

Dos tools nuevas, separadas de `press_keys` a propósito:

| Tool | Qué envía | Para qué |
|---|---|---|
| `copy_clipboard()` | Ctrl down, C down, C up, Ctrl up | copiar un bloque a portapapeles |
| `paste_clipboard()` | Ctrl down, V down, V up, Ctrl up | pegar el bloque |

Ambas comparten `_clipboard_combo(vk_key, tecla, ...)`.

## Por qué no se relajó la regla de press_keys

`press_keys(["ctrl","c"])` sigue devolviendo `status=error`. La regla nació
porque Ctrl+C en una consola es una señal de interrupción, no un copiar.
Para no debilitarla, el copiado vive en una tool con nombre explícito
(`copy_clipboard`), documentada como "GUI only, nunca para parar procesos".
Hay un test (`test_press_keys_still_refuses_ctrl_c`) que falla si alguien
reabre el atajo por la puerta de atrás.

`_VK_C = 0x43` y `_VK_V = 0x56` viven fuera de `_VK_CODES` para que
`press_keys` siga sin poder enviar letras.

## Límites declarados

- El portapapeles está en la máquina **remota**: este server no puede leerlo.
  La única prueba de que el copiado funcionó es pegar y mirar la captura.
- AnyDesk puede no reenviar Ctrl+C programático. La primera corrida en vivo
  lo decide; si no pega nada, la respuesta es "no se reenvía", no "reintentar".

## Tests

`tests/test_copy_clipboard.py` (6 casos, `_send_vk` y el foco stubbeados,
cero input real):

- `press_keys(["ctrl","c"])` sigue rechazado, 0 eventos.
- `copy_clipboard()` = exactamente 4 eventos en orden Ctrl↓ C↓ C↑ Ctrl↑.
- `paste_clipboard()` = exactamente 4 eventos con VK_V.
- La nota avisa de que el portapapeles es remoto.
- Nunca se envía Enter.
- Si falla a mitad, el Ctrl se libera (no queda modificador pegado).

Total del repo: **19 tests OK**. Smoke stdio: **24 tools**, `get_version` 3.7.1.
