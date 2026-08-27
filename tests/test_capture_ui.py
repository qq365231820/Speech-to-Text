import queue
import unittest
from unittest.mock import Mock,patch
from voiceinput.app import App

class CaptureUiTests(unittest.TestCase):
    def app(self):
        app=App.__new__(App)
        app.capture_hooks=None
        app.session=None
        app.pending=[]
        app.capture_generation=0
        app.hooks=Mock()
        app.escape_hook=Mock()
        app.events=queue.Queue()
        app.capture_button=Mock()
        app.status=Mock()
        app.vars={"hotkey":Mock()}
        app.install_hooks=Mock()
        app.closing=False
        return app

    def test_begin_suspends_voice_and_escape_hooks(self):
        app=self.app()
        with patch("voiceinput.app.win32.focus",return_value=(1,2)),patch("voiceinput.app.CaptureHooks") as hooks:
            app.begin_capture()
            app.hooks.stop.assert_called_once()
            app.escape_hook.stop.assert_called_once()
            hooks.return_value.start.assert_called_once()
            callback=hooks.call_args.args[0]
            callback("ctrl+v","")
            self.assertEqual(app.events.get_nowait(),("captured",(1,"ctrl+v","")))
            self.assertIsNone(app.session)

    def test_success_sets_pending_field_only(self):
        app=self.app()
        hook=app.capture_hooks=Mock()
        app.finish_capture("mouse_x1")
        hook.stop.assert_called_once()
        app.vars["hotkey"].set.assert_called_once_with("mouse_x1")
        app.install_hooks.assert_called_once()
        self.assertIsNone(app.capture_hooks)

    def test_cancel_keeps_existing_shortcut(self):
        app=self.app()
        app.capture_hooks=Mock()
        app.finish_capture(None,"cancel")
        app.vars["hotkey"].set.assert_not_called()
        app.install_hooks.assert_called_once()

    def test_recording_blocks_capture(self):
        app=self.app()
        app.session=Mock()
        app.begin_capture()
        app.hooks.stop.assert_not_called()
        self.assertIsNone(app.capture_hooks)

    def test_capture_blocks_voice_start(self):
        app=self.app()
        app.capture_hooks=Mock()
        with patch("voiceinput.app.Session") as session:
            app.hotkey(True,(1,2))
            session.assert_not_called()

if __name__=="__main__":unittest.main()
