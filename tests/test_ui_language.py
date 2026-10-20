"""Actual Qt controls: live language switches preserve pending recognition edits."""
import ast
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel
from jcaption.i18n import CATALOG, translate, load_ui_language, save_ui_language
from jcaption.preferences import Preferences
from jcaption.settings import read_json, write_json, load_appearance


class PanelLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        shiboken6.delete(cls.app)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = {'mode':'api', 'local_model':'large-v3', 'language':'ja', 'display_mode':'luna',
                       'api_key_file':'never-read.env'}
        write_json(self.root/'config/caption.json', self.config)
        self.apply = Mock()
        self.appearance = Mock()
        self.dialog = self.create_dialog()

    def create_dialog(self):
        dialog = Preferences(self.root, self.config, load_appearance(self.root), self.appearance, self.apply)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog.runtime_timer.stop)
        return dialog

    def tearDown(self):
        self.doCleanups()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.directory.cleanup()

    def choose(self, code):
        self.dialog.interface_language.setCurrentIndex(self.dialog.interface_language.findData(code))

    def test_live_switch_roundtrip_keeps_pending_values_and_stt_language(self):
        self.dialog.model.setCurrentIndex(self.dialog.model.findData('qwen3-asr-1.7b'))
        self.dialog.whisper_phrases = ['ご視聴', 'custom phrase']
        self.dialog.native_device.setValue(2)
        self.dialog.tabs.setCurrentIndex(2)
        pending = self.dialog.values()
        before = (self.root/'config/caption.json').read_bytes()
        for code, title, tabs in [('en','Caption settings',['Recognition & language','Display','Text']),
                                 ('ja','字幕設定',['認識と言語','表示','文字']),
                                 ('zh','字幕设置',['识别与语言','显示','文字'])]:
            self.choose(code)
            self.assertEqual(self.dialog.windowTitle(), 'Kitori — ' + title)
            self.assertEqual([self.dialog.tabs.tabText(i) for i in range(3)], tabs)
            self.assertEqual(self.dialog.values(), pending)
            self.assertEqual(self.dialog.tabs.currentIndex(), 2)
            self.assertEqual(load_ui_language(self.root), code)
            self.assertEqual(self.dialog.language.currentData(), 'ja')
            self.assertEqual((self.root/'config/caption.json').read_bytes(), before)
            self.assertEqual([self.dialog.interface_language.itemText(i) for i in range(3)],
                             ['中文','日本語','English'])
        self.apply.assert_not_called()
        self.appearance.assert_not_called()

    def test_saved_language_reopens_and_runtime_messages_stay_localized(self):
        self.choose('en')
        other = self.create_dialog()
        self.assertEqual(other.windowTitle(),'Kitori — Caption settings')
        write_json(self.root/'logs/status.json', {'stage':'local_error',
            'local_error':'本地模型加载失败，请检查模型与运行环境'})
        other.refresh_runtime_status()
        self.assertEqual(other.runtime.text(),'Local model failed to load. Check the model and runtime')
        self.assertEqual(other.source.itemText(0),'Local model')
        self.assertEqual(other.source.itemData(1),'windows_livecaptions')
        self.assertEqual(other.tabs.count(),3)
        self.assertFalse(hasattr(other,'provider'))
        self.assertFalse(hasattr(other,'mode'))
        self.assertFalse(any(key.startswith('api_') for key in other.values()))

    def test_switch_during_restart_keeps_disabled_button_and_localizes_result(self):
        process = Mock()
        process.poll.return_value = None
        self.dialog.track_restart(process,100)
        self.choose('en')
        self.assertFalse(self.dialog.apply_button.isEnabled())
        self.assertEqual(self.dialog.apply_button.text(),'Restarting captions…')
        process.poll.return_value = 1
        self.dialog.poll_restart()
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertIn('Caption restart failed.',self.dialog.message.text())

    def test_download_status_switch_keeps_process_and_progress(self):
        self.dialog.download = Mock()
        self.dialog.pending = self.dialog.values()
        self.dialog.buffer = b''
        self.dialog.download.readAllStandardOutput.return_value = b'{"downloaded_MB":3,"total_MB":10}\n'
        self.dialog.download_output()
        process = self.dialog.download
        self.choose('en')
        self.assertIn('Preparing Whisper large-v3: downloaded 3 MB / 10 MB', self.dialog.message.text())
        self.assertIs(self.dialog.download, process)
        self.assertEqual(self.dialog.progress.value(),3)
        self.dialog.download = None

    def test_invalid_or_unwritable_ui_language_does_not_corrupt_settings(self):
        write_json(self.root/'config/ui.json',{'language':'invalid','other':123})
        self.assertEqual(load_ui_language(self.root),'zh')
        with self.assertRaises(ValueError): save_ui_language(self.root,'fr')
        with patch('jcaption.i18n.write_json',side_effect=PermissionError('locked')):
            self.choose('en')
        self.assertEqual(self.dialog.interface_language.currentData(),'zh')
        self.assertEqual(self.dialog.ui_language,'zh')
        self.assertEqual(read_json(self.root/'config/ui.json')['other'],123)

    def test_all_static_panel_labels_have_complete_translations(self):
        import jcaption.preferences
        tree = ast.parse(Path(jcaption.preferences.__file__).read_text(encoding='utf-8'))
        labels = [node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == 'tr' and node.args and isinstance(node.args[0],ast.Constant)
                  and isinstance(node.args[0].value,str)]
        for source in labels:
            self.assertIn(source, CATALOG, repr(source))
        for source, row in CATALOG.items():
            self.assertEqual(set(row), {'ja','en'})
            for language, value in row.items():
                self.assertTrue(value)
                self.assertEqual(set(re.findall(r'\{(\w+)\}',source)),
                                 set(re.findall(r'\{(\w+)\}',value)))
                self.assertEqual(translate(source,language),value)
                self.assertEqual(translate(value,'zh',source_language=language),source)
