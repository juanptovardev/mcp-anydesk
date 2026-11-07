"""Click math + focus-click override tests. No real input, no window needed.

Stubs win32gui geometry and send_inputs so nothing is sent to the OS.
Run: python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_anydesk_server import window_manager as wm

CLIENT_W, CLIENT_H = 1024, 576
ORIGIN = (171, 96)
SCREEN_W, SCREEN_H = 1366, 768


class ClickMathTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._patches = [
            patch.object(wm, "send_inputs", lambda arr: self.sent.append(arr)),
            patch.object(
                wm, "GetSystemMetrics",
                lambda idx: SCREEN_W if idx == wm.SM_CXSCREEN else SCREEN_H,
            ),
            patch.object(
                wm.win32gui, "GetClientRect",
                lambda hwnd: (0, 0, CLIENT_W, CLIENT_H),
            ),
            patch.object(
                wm.win32gui, "ClientToScreen",
                lambda hwnd, pt: (ORIGIN[0] + pt[0], ORIGIN[1] + pt[1]),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        wm.set_focus_click(None)

    def test_out_of_bounds_rejected_and_silent(self):
        for x, y in ((-1, 10), (10, -1), (CLIENT_W, 10), (10, CLIENT_H)):
            with self.subTest(x=x, y=y):
                result = wm.click_client_point(1, x, y)
                self.assertEqual(result["status"], "error")
        self.assertEqual(self.sent, [], "no click must be sent when rejected")

    def test_unknown_button_rejected(self):
        result = wm.click_client_point(1, 5, 5, button="wheel")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.sent, [])

    def test_client_to_screen_and_normalisation(self):
        result = wm.click_client_point(1, 10, 20)
        self.assertEqual(result["status"], "clicked")
        self.assertEqual(result["screen"], {"x": 181, "y": 116})

        arr = self.sent[0]
        self.assertEqual(len(arr), 3)  # move + down + up
        # correct normalisation divides by (size - 1), not size
        self.assertEqual(arr[1].ii.mi.dx, (181 * 65535) // (SCREEN_W - 1))
        self.assertEqual(arr[1].ii.mi.dy, (116 * 65535) // (SCREEN_H - 1))

    def test_double_click_event_count_and_flags(self):
        result = wm.click_client_point(1, 1, 1, double=True)
        self.assertEqual(result["presses"], 2)
        arr = self.sent[0]
        self.assertEqual(len(arr), 5)
        down, up = wm.MOUSEEVENTF_LEFTDOWN, wm.MOUSEEVENTF_LEFTUP
        self.assertEqual(arr[1].ii.mi.dwFlags, wm.MOUSEEVENTF_ABSOLUTE | wm.MOUSEEVENTF_MOVE | down)
        self.assertEqual(arr[2].ii.mi.dwFlags, wm.MOUSEEVENTF_ABSOLUTE | wm.MOUSEEVENTF_MOVE | up)
        self.assertEqual(arr[4].ii.mi.dwFlags, wm.MOUSEEVENTF_ABSOLUTE | wm.MOUSEEVENTF_MOVE | up)

    def test_right_button_uses_right_flags(self):
        wm.click_client_point(1, 2, 3, button="right")
        arr = self.sent[0]
        self.assertEqual(arr[1].ii.mi.dwFlags & wm.MOUSEEVENTF_RIGHTDOWN, wm.MOUSEEVENTF_RIGHTDOWN)


class FocusClickOverrideTest(unittest.TestCase):
    def tearDown(self):
        wm.set_focus_click(None)

    def test_override_wins_over_config(self):
        default = wm.focus_click_enabled()
        self.assertEqual(wm.set_focus_click(False), False)
        self.assertFalse(wm.focus_click_enabled())
        self.assertEqual(wm.set_focus_click(None), None)
        self.assertEqual(wm.focus_click_enabled(), default)

    def test_geometry_reports_effective_setting(self):
        wm.set_focus_click(False)
        with patch.object(wm.win32gui, "GetWindowRect", lambda h: (171, 96, 1195, 672)), \
             patch.object(wm.win32gui, "GetClientRect", lambda h: (0, 0, CLIENT_W, CLIENT_H)), \
             patch.object(wm.win32gui, "ClientToScreen", lambda h, pt: ORIGIN), \
             patch.object(wm.win32gui, "GetWindowText", lambda h: "Oficina - AnyDesk"), \
             patch.object(wm, "GetSystemMetrics",
                          lambda idx: SCREEN_W if idx == wm.SM_CXSCREEN else SCREEN_H):
            info = wm.get_window_geometry(198526)
        self.assertFalse(info["focus_click_enabled"])
        self.assertEqual(info["client"]["width"], CLIENT_W)
        self.assertEqual(info["caption_offset"], {"x": 0, "y": 0})


class ViewportDetectionTest(unittest.TestCase):
    """The remote screen is a child window; the root client includes the toolbar."""

    def test_largest_viewport_child_is_selected(self):
        children = {2164540: ("SysTabControl32", (0, 0, 720, 25)),
                    67584: ("basic_button#9\n", (0, 0, 0, 0)),
                    393712: ("gui.tabbar_panel#46\n", (0, 0, 1022, 471))}

        def fake_enum(hwnd, cb, extra):
            for child in children:
                cb(child, extra)
            return True

        def fake_screen(hwnd, pt):
            # root client origin (171,96); viewport child at +1,+104
            if hwnd == 198526:
                return (171 + pt[0], 96 + pt[1])
            return (172 + pt[0], 200 + pt[1])

        with patch.object(wm.win32gui, "EnumChildWindows", fake_enum), \
             patch.object(wm.win32gui, "GetClassName",
                          lambda h: children[h][0]), \
             patch.object(wm.win32gui, "GetClientRect",
                          lambda h: children[h][1]), \
             patch.object(wm.win32gui, "ClientToScreen", fake_screen):
            viewport = wm.find_viewport(198526)

        self.assertIsNotNone(viewport)
        self.assertEqual(viewport["hwnd"], 393712)
        self.assertEqual(viewport["width"], 1022)
        self.assertEqual(viewport["height"], 471)
        self.assertEqual(viewport["offset"], {"x": 1, "y": 104})

    def test_no_viewport_returns_none(self):
        with patch.object(wm.win32gui, "EnumChildWindows", lambda h, cb, e: True):
            self.assertIsNone(wm.find_viewport(198526))


if __name__ == "__main__":
    unittest.main()
