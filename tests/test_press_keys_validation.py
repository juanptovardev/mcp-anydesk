"""Validation tests for press_keys — no real SendInput, no focus stealing.

Stubs focus_and_verify, verify_focus_post and _send_vk so the tests run
anywhere (CI, headless) without touching the operator's keyboard.
Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_anydesk_server import keyboard_injector as ki


class TestPressKeysValidation(unittest.TestCase):
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

    def test_rejections_never_raise(self):
        """Every invalid input returns status=error — never an exception."""
        for keys in (
            ["c"], ["c", "tab"], ["alt", "c"], ["enter"], ["return"],
            ["ctrl", "c"], ["banana"], [],
        ):
            with self.subTest(keys=keys):
                try:
                    result = ki.press_keys(keys, key_delay_ms=30,
                                           focus_delay_ms=0)
                except Exception as exc:  # noqa: BLE001 — must not happen
                    self.fail(f"{keys} raised {type(exc).__name__}: {exc}")
                self.assertEqual(result["status"], "error")
        self.assertEqual(self.sent, [], "no key event on rejection paths")

    def test_happy_path_sequence(self):
        result = ki.press_keys(["shift", "f4"], key_delay_ms=30,
                               focus_delay_ms=0)
        self.assertEqual(result["status"], "pressed")
        # shift down -> f4 down/up -> shift up
        self.assertEqual(self.sent, [
            (0x10, False), (0x73, False), (0x73, True), (0x10, True),
        ])

    def test_modifier_released_on_mid_sequence_failure(self):
        """A stuck Ctrl/Alt/Shift on the operator's PC is unacceptable."""
        calls = []

        def flaky(vk, keyup=False):
            calls.append((vk, keyup))
            if len(calls) == 2:
                raise RuntimeError("simulated SendInput failure")

        ki._send_vk = flaky
        result = ki.press_keys(["shift", "tab"], key_delay_ms=30,
                               focus_delay_ms=0)
        self.assertEqual(result["status"], "error")
        # finally block must release shift even though tab failed
        self.assertIn((0x10, True), calls)


if __name__ == "__main__":
    unittest.main()
