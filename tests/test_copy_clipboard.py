"""Tests for copy_clipboard — Ctrl+C allowed ONLY through this path.

No real SendInput, no focus stealing: focus and key sends are stubbed.
Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_anydesk_server import keyboard_injector as ki

VK_CTRL = ki._VK_CODES["ctrl"]
VK_C = ki._VK_C


class TestCopyClipboard(unittest.TestCase):
    def setUp(self):
        self._orig_focus = ki.focus_and_verify
        self._orig_post = ki.verify_focus_post
        self._orig_send = ki._send_vk
        self.sent: list = []
        ki.focus_and_verify = lambda ms: None
        ki.verify_focus_post = lambda: None
        ki._send_vk = lambda vk, keyup=False: self.sent.append((vk, keyup))

    def tearDown(self):
        ki.focus_and_verify = self._orig_focus
        ki.verify_focus_post = self._orig_post
        ki._send_vk = self._orig_send

    def test_press_keys_still_refuses_ctrl_c(self):
        """The guard in press_keys must NOT be weakened by this feature."""
        result = ki.press_keys(["ctrl", "c"], key_delay_ms=30,
                               focus_delay_ms=0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["event_count"], 0)
        self.assertIn("Refused ctrl+c", result["note"])
        self.assertEqual(self.sent, [])

    def test_copy_clipboard_sends_exactly_ctrl_c(self):
        result = ki.copy_clipboard(key_delay_ms=30, focus_delay_ms=0)
        self.assertEqual(result["status"], "pressed")
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(
            self.sent,
            [(VK_CTRL, False), (VK_C, False), (VK_C, True), (VK_CTRL, True)],
        )

    def test_copy_clipboard_note_warns_clipboard_is_remote(self):
        result = ki.copy_clipboard(key_delay_ms=30, focus_delay_ms=0)
        self.assertIn("cannot be read", result["note"])

    def test_copy_clipboard_never_sends_enter(self):
        ki.copy_clipboard(key_delay_ms=30, focus_delay_ms=0)
        vk_enter = {0x0D, 0x0A}
        pressed = {vk for vk, _keyup in self.sent}
        self.assertFalse(pressed & vk_enter, "Enter must never be sent")

    def test_paste_clipboard_sends_exactly_ctrl_v(self):
        result = ki.paste_clipboard(key_delay_ms=30, focus_delay_ms=0)
        self.assertEqual(result["status"], "pressed")
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(
            self.sent,
            [(VK_CTRL, False), (ki._VK_V, False), (ki._VK_V, True),
             (VK_CTRL, True)],
        )

    def test_paste_sin_formato_sends_ctrl_shift_v(self):
        """Ctrl+Shift+V: modificadores en orden, liberados en orden inverso."""
        result = ki.paste_clipboard(key_delay_ms=30, focus_delay_ms=0, shift=True)
        self.assertEqual(result["status"], "pressed")
        self.assertEqual(result["event_count"], 6)
        self.assertEqual(
            self.sent,
            [(VK_CTRL, False), (ki._VK_SHIFT, False),
             (ki._VK_V, False), (ki._VK_V, True),
             (ki._VK_SHIFT, True), (VK_CTRL, True)],
        )

    def test_modifier_released_if_copy_fails_midway(self):
        """A stuck Ctrl on the operator's PC is unacceptable."""
        def boom(vk, keyup=False):
            if keyup:
                raise RuntimeError("simulated failure")
            self.sent.append((vk, keyup))

        ki._send_vk = boom
        result = ki.copy_clipboard(key_delay_ms=30, focus_delay_ms=0)
        self.assertEqual(result["status"], "error")

    def test_press_keys_cannot_type_letters(self):
        """Letters are absent from the map: press_keys cannot send text."""
        self.assertNotIn("c", ki._VK_CODES)
        result = ki.press_keys(["k"], key_delay_ms=30, focus_delay_ms=0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
