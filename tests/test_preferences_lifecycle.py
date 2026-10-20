"""Settings restart and application-wide shutdown UI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import QCoreApplication, QEvent
import shiboken6
from jcaption.tray import SessionTray
from jcaption.settings import write_json


class PreferencesLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        shiboken6.delete(cls.app)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        write_json(self.root/'config/caption.json',{'mode':'local','local_model':'tiny','language':'ja'})
        self.tray_patch=patch('jcaption.tray.QSystemTrayIcon')
        self.tray_patch.start()
        self.session_tray = SessionTray(self.root)

    def tearDown(self):
        self.session_tray.timer.stop()
        self.session_tray.menu.deleteLater()
        self.tray_patch.stop()
        self.session_tray.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.directory.cleanup()




    def test_windows_first_use_restores_restart_button_with_setup_instructions(self):
        dialog, process = self.restart_dialog()
        self.ready_restart(stage='windows_setup')
        dialog.poll_restart()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertIn('语言包', dialog.message.text())


    def test_tray_exit_requests_application_wide_shutdown(self):
        with patch('jcaption.tray.request_exit') as stop:
            self.session_tray.quit_application()
        stop.assert_called_once_with(self.root)
        self.session_tray.tray.hide.assert_called_once()

    def test_settings_exit_button_requests_application_wide_shutdown(self):
        from jcaption.preferences import Preferences
        from jcaption.settings import load_appearance
        dialog = Preferences(self.root,{'mode':'local','local_model':'tiny','language':'ja'},load_appearance(self.root),Mock(),Mock())
        try:
            dialog.show()
            button, = [b for b in dialog.findChildren(QPushButton) if b.text() == '退出字幕程序']
            with patch('jcaption.preferences.request_exit') as stop:
                button.click()
            stop.assert_called_once_with(self.root)
            self.assertFalse(dialog.isVisible())
        finally:
            dialog.close()
            dialog.deleteLater()

    def restart_dialog(self, code=0):
        from jcaption.preferences import Preferences
        from jcaption.settings import load_appearance
        dialog = Preferences(self.root, {'mode':'local','local_model':'tiny','language':'ja'}, load_appearance(self.root), Mock(), Mock())
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        process = Mock()
        process.poll.return_value = code
        ready=patch('jcaption.preferences.model_ready',return_value=True)
        ready.start()
        self.addCleanup(ready.stop)
        dialog.track_restart(process, 100)
        return dialog, process


    def ready_restart(self, started_at=101, updated_at=102, stage='listening'):
        write_json(self.root/'logs/processes.json', {'started_at':started_at})
        write_json(self.root/'logs/status.json', {'stage':stage,'backend':'local','updated_at':updated_at})

    def test_restart_success_restores_button_and_allows_another_apply(self):
        dialog, process = self.restart_dialog()
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.apply_button.text(), '正在重启字幕…')
        self.ready_restart()
        dialog.poll_restart()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.tabs.isEnabled())
        self.assertEqual(dialog.apply_button.text(), '应用并重启字幕')
        self.assertEqual(dialog.message.text(), '字幕已重启成功。')
        dialog.apply_button.click()
        dialog.apply.assert_called_once()

    def test_restart_does_not_accept_old_runtime_or_old_status(self):
        dialog, process = self.restart_dialog()
        for started, updated in [(99,102),(101,99)]:
            self.ready_restart(started, updated)
            dialog.poll_restart()
            self.assertFalse(dialog.apply_button.isEnabled())
        self.ready_restart(stage='plugin_ready')
        dialog.poll_restart()
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_restart_waits_for_launcher_even_if_status_is_ready(self):
        dialog, process = self.restart_dialog(code=None)
        self.ready_restart()
        dialog.poll_restart()
        self.assertFalse(dialog.apply_button.isEnabled())
        process.poll.return_value = 0
        dialog.poll_restart()
        self.assertTrue(dialog.apply_button.isEnabled())

    def test_restart_failure_restores_button_for_retry(self):
        dialog, process = self.restart_dialog(code=1)
        self.ready_restart()
        dialog.poll_restart()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.tabs.isEnabled())
        self.assertIn('失败',dialog.message.text())
        self.assertIsNone(dialog.restart)

    def test_restart_timeout_restores_button_for_retry(self):
        with patch('jcaption.preferences.time.monotonic',return_value=10):
            dialog, process = self.restart_dialog()
        with patch('jcaption.preferences.time.monotonic',return_value=190):
            dialog.poll_restart()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.tabs.isEnabled())
        self.assertIn('超时',dialog.message.text())
