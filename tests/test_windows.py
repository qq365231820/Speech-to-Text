import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from voiceinput import win32
from voiceinput.hotkeys import Hooks
from voiceinput.offline import LocalBackend

class WindowsTests(unittest.TestCase):
    def test_input_structure_size(self):
        self.assertEqual(ctypes.sizeof(win32.Input),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

    def test_unicode_input_without_clipboard(self):
        with patch("voiceinput.win32.focus",return_value=(1,2)),patch("voiceinput.win32.modifiers_down",return_value=False),patch.object(win32.user,"SendInput",return_value=6) as send:
            win32.type_text("洛😀",(1,2))
            self.assertEqual(send.call_args.args[0],6)
            self.assertEqual(send.call_args.args[1][0].u.ki.scan,ord("洛"))

    def test_focus_change_refuses_input(self):
        with patch("voiceinput.win32.focus",return_value=(3,4)),patch.object(win32.user,"SendInput") as send:
            with self.assertRaises(RuntimeError): win32.type_text("不能输入",(1,2))
            send.assert_not_called()

    def test_modifiers_refuse_input(self):
        with patch("voiceinput.win32.focus",return_value=(1,2)),patch("voiceinput.win32.modifiers_down",return_value=True),patch.object(win32.user,"SendInput") as send:
            with self.assertRaises(RuntimeError): win32.type_text("不能输入",(1,2))
            send.assert_not_called()

    def test_native_keyboard_filter_suppresses_main_only(self):
        events=[]
        with patch("pynput.keyboard.Listener") as keyboard,patch("pynput.mouse.Listener"):
            hooks=Hooks("ctrl+alt+v",events.append)
            handler=keyboard.call_args.kwargs["win32_event_filter"]
            handler(0x100,SimpleNamespace(vkCode=0xa2))
            handler(0x104,SimpleNamespace(vkCode=0xa4))
            handler(0x100,SimpleNamespace(vkCode=ord("V")))
            handler(0x100,SimpleNamespace(vkCode=ord("V")))
            handler(0x101,SimpleNamespace(vkCode=ord("V")))
            self.assertEqual(events,[True,False])
            self.assertEqual(keyboard.return_value.suppress_event.call_count,3)

    def test_native_mouse_side_button(self):
        events=[]
        with patch("pynput.keyboard.Listener"),patch("pynput.mouse.Listener") as mouse:
            Hooks("mouse_x1",events.append)
            handler=mouse.call_args.kwargs["win32_event_filter"]
            handler(0x20b,SimpleNamespace(mouseData=1<<16))
            handler(0x20c,SimpleNamespace(mouseData=1<<16))
            self.assertEqual(events,[True,False])
            self.assertEqual(mouse.return_value.suppress_event.call_count,2)

    def test_both_ctrl_keys(self):
        events=[]
        with patch("pynput.keyboard.Listener") as keyboard,patch("pynput.mouse.Listener"):
            Hooks("ctrl+v",events.append)
            handler=keyboard.call_args.kwargs["win32_event_filter"]
            for vk in (0xa2,0xa3,ord("V")):handler(0x100,SimpleNamespace(vkCode=vk))
            handler(0x101,SimpleNamespace(vkCode=0xa2))
            self.assertEqual(events,[True])
            handler(0x101,SimpleNamespace(vkCode=0xa3))
            self.assertEqual(events,[True,False])

    def test_idle_unloads_child(self):
        local=LocalBackend()
        process=Mock()
        process.is_alive.return_value=False
        local.process=process
        local.pipe=Mock()
        local.last_used=0
        local.unload_idle(60)
        process.terminate.assert_called_once()
        process.close.assert_called_once()
        self.assertIsNone(local.process)

    def test_idle_does_not_unload_busy_child(self):
        local=LocalBackend()
        local.process=Mock()
        local.lock.acquire()
        try:local.unload_idle(0)
        finally:local.lock.release()
        local.process.terminate.assert_not_called()

if __name__=="__main__": unittest.main()
