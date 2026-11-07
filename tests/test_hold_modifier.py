"""hold_modifier: primitiva para shift+clic (sin input real)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_anydesk_server import keyboard_injector as ki  # noqa: E402


class TestHoldModifier(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._patch = patch.object(
            ki, "_send_vk", side_effect=lambda vk, keyup=False: self.sent.append((vk, keyup))
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_shift_down_then_up(self):
        ki.hold_modifier("shift", True)
        ki.hold_modifier("shift", False)
        self.assertEqual(self.sent, [(ki._VK_CODES["shift"], False),
                                     (ki._VK_CODES["shift"], True)])

    def test_ctrl_y_alt_tambien(self):
        ki.hold_modifier("ctrl", True)
        ki.hold_modifier("alt", False)
        self.assertEqual(self.sent, [(ki._VK_CODES["ctrl"], False),
                                     (ki._VK_CODES["alt"], True)])

    def test_modificador_desconocido_falla(self):
        with self.assertRaises(RuntimeError):
            ki.hold_modifier("windows", True)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
