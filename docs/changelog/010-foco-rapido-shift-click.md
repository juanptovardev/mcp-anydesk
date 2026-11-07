# 010 — Foco rápido y Shift+Clic con la ventana enfocada (v3.7.4)

## Motivo

El bucle del agente hace ~9 llamadas MCP por página del 5250. Cada una pasaba
por `focus_and_verify()`, que dormía el delay completo (**500 ms**) aunque la
ventana ya fuera la del foreground. Medido: **~4.5 s muertos por página**.

En paralelo, el `Shift+Clic` (mecánica aprobada por el operador para
seleccionar el bloque) fallaba de forma intermitente: a veces el remoto recibía
el clic **sin** Shift y sólo extendía la selección como un clic suelto.

## Qué se cambió

### `mcp_anydesk_server/window_manager.py`

`focus_and_verify()`:

```python
if win32gui.GetForegroundWindow() == active_hwnd:
    time.sleep(min(focus_delay_ms, 50) / 1000.0)
else:
    time.sleep(focus_delay_ms / 1000.0)
```

La ventana ya delante paga un respiro de 50 ms; si hay que traerla, mantiene
el delay completo (el remoto necesita ese tiempo para repintar).

### `mcp_anydesk_server/server.py`

`click_point()` con `shift=True` ahora llama `focus_and_verify()` **antes** de
bajar el modificador:

```python
if shift:
    try:
        focus_and_verify()
    except RuntimeError as exc:
        return {"status": "error", "note": f"Focus failed: {exc}"}
```

**Por qué:** AnyDesk entrega ratón y teclado por colas distintas. Si el
modificador baja antes de que la ventana esté delante, el remoto recibe el
clic sin Shift. Con `settle_ms` (v3.7.4 anterior) el problema se reducía pero
no desaparecía: faltaba el enfoque previo.

## Bugs corregidos

| Bug | Síntoma | Causa |
|---|---|---|
| Ritmo lento | ~20 s por página | delay de foco pagado en cada llamada |
| Shift+Clic intermitente | a veces seleccionaba sin extender | ventana no enfocada al bajar el modificador |

## Tests

`tests/test_focus_delay.py` (2 casos, win32 stubbeado, cero input real):

- Con la ventana ya delante, `focus_and_verify()` espera 50 ms.
- Con otra ventana delante, espera el delay completo (500 ms).

Total del repo: **25 tests OK**.

## Deuda

- `press_enter` (commit `4523768`) sigue **sin test unitario**.
- La version declarada estaba en 3.7.3 aunque el changelog 009 anunciaba
  3.7.1: las zonas horarias de versionado quedaron desfasadas. Este changelog
  fija 3.7.4 como version real de `__init__.py` y `pyproject.toml`.
