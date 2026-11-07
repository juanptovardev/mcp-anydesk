"""focus_and_verify: el delay de foco solo se paga si hay que traer la ventana.

Sin ventana real y sin eventos al OS: se stubea todo lo de win32.
Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_anydesk_server import window_manager as wm

PINNED = 198526


class FocusDelayTest(unittest.TestCase):
    """El delay completo (500 ms) se pagaba en cada llamada MCP."""

    def _correr(self, foreground_inicial):
        self.sleeps = []
        estado = {"fg": foreground_inicial}

        def fake_sleep(segundos):
            self.sleeps.append(segundos)
            # Tras el enfoque, la ventana pineada queda delante.
            estado["fg"] = PINNED

        parches = [
            patch.object(wm, "get_active_hwnd", lambda: PINNED),
            patch.object(wm.win32gui, "IsWindow", lambda h: True),
            patch.object(wm.win32gui, "GetForegroundWindow", lambda: estado["fg"]),
            patch.object(wm.win32gui, "IsIconic", lambda h: False),
            patch.object(wm.win32gui, "BringWindowToTop", lambda h: None),
            patch.object(wm.win32gui, "SetForegroundWindow", lambda h: None),
            patch.object(wm.win32process, "GetWindowThreadProcessId", lambda h: (1, 2)),
            patch.object(wm.win32api, "GetCurrentThreadId", lambda: 1),
            patch.object(wm, "focus_click_enabled", lambda: False),
            patch.object(wm.time, "sleep", fake_sleep),
        ]
        for p in parches:
            p.start()
        try:
            wm.focus_and_verify()
        finally:
            for p in reversed(parches):
                p.stop()
        return self.sleeps

    def test_ventana_ya_delante_usa_respiro_minimo(self):
        sleeps = self._correr(PINNED)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.05, places=3)

    def test_otra_ventana_delante_paga_el_delay_completo(self):
        sleeps = self._correr(999999)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
