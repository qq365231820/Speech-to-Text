import unittest
from unittest.mock import patch
from types import SimpleNamespace
from voiceinput.hotkeys import CaptureState,CaptureHooks,key_from_vk

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.state=CaptureState(lambda value,error:self.events.append((value,error)))

    def test_function_key(self):
        self.state.feed(119,"f8",True)
        self.assertFalse(self.events)
        self.state.feed(119,"f8",False)
        self.assertEqual(self.events,[("f8","")])

    def test_combo_commits_after_all_released(self):
        for physical,name in ((1,"ctrl"),(2,"alt"),(3,"v")):
            self.state.feed(physical,name,True)
        self.state.feed(3,"v",False)
        self.state.feed(1,"ctrl",False)
        self.assertFalse(self.events)
        self.state.feed(2,"alt",False)
        self.assertEqual(self.events,[("ctrl+alt+v","")])

    def test_mouse_combo(self):
        self.state.feed(1,"ctrl",True)
        self.state.feed("mouse_x1","mouse_x1",True)
        self.state.feed("mouse_x1","mouse_x1",False)
        self.state.feed(1,"ctrl",False)
        self.assertEqual(self.events,[("ctrl+mouse_x1","")])

    def test_invalid_plain_letter(self):
        self.state.feed(65,"a",True)
        self.state.feed(65,"a",False)
        self.assertIsNone(self.events[0][0])
        self.assertIn("Ctrl",self.events[0][1])

    def test_escape_cancels(self):
        self.state.feed(27,"esc",True)
        self.state.feed(27,"esc",False)
        self.assertEqual(self.events,[(None,"已取消快捷键录制")])

    def test_modifier_alone_keeps_waiting(self):
        self.state.feed(1,"ctrl",True)
        self.state.feed(1,"ctrl",False)
        self.assertFalse(self.events)

    def test_repeat_and_late_events(self):
        for _ in range(10):self.state.feed(119,"f8",True)
        self.state.feed(119,"f8",False)
        self.state.feed(120,"f9",True)
        self.state.feed(120,"f9",False)
        self.assertEqual(self.events,[("f8","")])

    def test_native_capture_does_not_start_voice_hooks(self):
        with patch("pynput.keyboard.Listener") as keyboard,patch("pynput.mouse.Listener") as mouse:
            capture=CaptureHooks(lambda v,e:self.events.append((v,e)))
            handler=keyboard.call_args.kwargs["win32_event_filter"]
            handler(0x100,SimpleNamespace(vkCode=119))
            handler(0x101,SimpleNamespace(vkCode=119))
            self.assertEqual(self.events,[("f8","")])
            self.assertEqual(keyboard.return_value.suppress_event.call_count,2)
            capture.stop()
            keyboard.return_value.stop.assert_called_once()
            mouse.return_value.stop.assert_called_once()

    def test_vk_translation(self):
        self.assertEqual(key_from_vk(0xa3),"ctrl")
        self.assertEqual(key_from_vk(119),"f8")
        self.assertEqual(key_from_vk(0x41),"a")
        self.assertEqual(key_from_vk(0x3a),"unsupported")

if __name__=="__main__":unittest.main()
