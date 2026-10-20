import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import shiboken6
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent, QProcess

from jcaption.local_models import EXTRA_MODELS
from jcaption.preferences import Preferences
from jcaption.settings import load_appearance, write_json


class ModelPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        shiboken6.delete(cls.app)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        config = {'mode':'local', 'local_model':'tiny', 'language':'ja'}
        write_json(self.root / 'config/caption.json', config)
        self.apply = Mock()
        self.dialog = Preferences(self.root, config, load_appearance(self.root), Mock(), self.apply)

    def tearDown(self):
        self.dialog.runtime_timer.stop()
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.directory.cleanup()

    def choose(self, name):
        self.dialog.model.setCurrentIndex(self.dialog.model.findData(name))

    def test_all_models_are_selectable_and_filter_is_only_for_whisper_family(self):
        for name in EXTRA_MODELS:
            self.choose(name)
            self.assertEqual(self.dialog.values()['local_model'], name)
            self.assertEqual(self.dialog.whisper_filter_row.isHidden(), name != 'kotoba-v2')
            self.assertEqual(self.dialog.native_backend.isHidden(), name not in
                             ('qwen3-asr-0.6b','qwen3-asr-1.7b','voxtral-realtime'))
        self.choose('reazonspeech-k2')
        self.dialog.language.setCurrentIndex(self.dialog.language.findData('en'))
        self.dialog.apply_clicked()
        self.assertIn('只支持日语', self.dialog.message.text())
        self.apply.assert_not_called()
        self.assertIsNone(self.dialog.download)

    def test_switching_models_preserves_custom_filter_and_native_settings(self):
        self.dialog.whisper_phrases = ['ご視聴', '架空字幕']
        self.dialog.whisper_filter.setChecked(True)
        self.dialog.native_backend.setCurrentIndex(self.dialog.native_backend.findData('cuda'))
        self.dialog.native_device.setValue(1)
        for name in ('kotoba-v2', 'qwen3-asr-1.7b', 'reazonspeech-k2', 'kotoba-v2'):
            self.choose(name)
        values = self.dialog.values()
        self.assertTrue(values['whisper_blocklist_enabled'])
        self.assertEqual(values['whisper_blocklist'], ['ご視聴', '架空字幕'])
        self.assertEqual(values['local_native_backend'], 'cuda')
        self.assertEqual(values['local_native_device'], 1)

    def test_windows_source_applies_without_model_download_and_preserves_model(self):
        self.dialog.source.setCurrentIndex(self.dialog.source.findData('windows_livecaptions'))
        self.assertFalse(self.dialog.model.isEnabled())
        self.assertTrue(self.dialog.tabs.isTabEnabled(1))
        self.dialog.apply_clicked()
        self.apply.assert_called_once()
        self.assertIsNone(self.dialog.download)
        values = self.apply.call_args.args[0]
        self.assertEqual(values['recognition_source'], 'windows_livecaptions')
        self.assertEqual(values['local_model'], 'tiny')
        self.dialog.source.setCurrentIndex(self.dialog.source.findData('models'))
        self.assertTrue(self.dialog.model.isEnabled())

    def test_whisper_quality_is_preserved_when_switching_families(self):
        self.dialog.whisper_quality.setCurrentIndex(self.dialog.whisper_quality.findData(3))
        self.dialog.whisper_standard.setChecked(True)
        self.choose('qwen3-asr-1.7b')
        self.assertTrue(self.dialog.whisper_quality.isHidden())
        self.choose('large-v3')
        self.assertFalse(self.dialog.whisper_quality.isHidden())
        self.assertEqual(self.dialog.values()['whisper_draft_beam'], 3)
        self.assertTrue(self.dialog.values()['whisper_standard_decode'])

    def test_unapplied_recognition_can_be_discarded_without_reverting_instant_styles(self):
        before = self.dialog.values()
        self.dialog.language.setCurrentIndex(self.dialog.language.findData('en'))
        self.dialog.whisper_phrases = ['custom']
        self.dialog.update_pending()
        self.assertFalse(self.dialog.pending_notice.isHidden())
        self.assertTrue(self.dialog.discard_button.isEnabled())
        self.dialog.appearance['font_size'] = 45
        self.dialog.discard_button.click()
        self.assertEqual(self.dialog.values(), before)
        self.assertTrue(self.dialog.pending_notice.isHidden())
        self.assertEqual(self.dialog.appearance['font_size'], 45)
        self.apply.assert_not_called()

    def test_close_and_escape_discard_pending_edits(self):
        before = self.dialog.values()
        for close in (self.dialog.close, self.dialog.reject):
            self.dialog.show()
            self.choose('large-v3')
            close()
            self.assertFalse(self.dialog.isVisible())
            self.assertEqual(self.dialog.values(), before)
        self.apply.assert_not_called()

    def test_windows_uses_furigana_language_and_hides_native_device_controls(self):
        self.choose('qwen3-asr-1.7b')
        self.dialog.source.setCurrentIndex(self.dialog.source.findData('windows_livecaptions'))
        self.assertEqual(self.dialog.language_label.text(), '注音语言')
        self.assertTrue(self.dialog.native_backend.isHidden())
        self.dialog.source.setCurrentIndex(self.dialog.source.findData('models'))
        self.assertEqual(self.dialog.language_label.text(), '识别语言')
        self.assertFalse(self.dialog.native_backend.isHidden())

    def test_style_controls_follow_active_output_not_unapplied_selection(self):
        config = {'display_mode': 'luna', 'local_model': 'tiny'}
        write_json(self.root/'config/caption.json', config)
        self.dialog.refresh_runtime_status()
        self.assertFalse(self.dialog.font.isEnabled())
        self.assertFalse(self.dialog.opacity.isEnabled())
        self.assertTrue(self.dialog.max_lines.isEnabled())
        self.assertTrue(self.dialog.color_buttons['stable_color'].isEnabled())
        self.dialog.output.setCurrentIndex(self.dialog.output.findData('both'))
        self.dialog.refresh_runtime_status()
        self.assertFalse(self.dialog.font.isEnabled())
        config['display_mode'] = 'both'
        write_json(self.root/'config/caption.json', config)
        self.dialog.refresh_runtime_status()
        self.assertTrue(self.dialog.font.isEnabled())
        self.dialog.shadow.setChecked(False)
        self.assertFalse(self.dialog.shadow_blur.isEnabled())
        self.assertFalse(self.dialog.color_buttons['shadow_color'].isEnabled())

    def fake_download(self):
        process = Mock()
        process.processId.return_value = 0
        self.dialog.download = process
        self.dialog.pending = self.dialog.values()
        return process

    def test_cancelled_download_never_applies_even_if_finished_successfully(self):
        process = self.fake_download()
        process.waitForFinished.side_effect = lambda *_: self.dialog.download_finished(0)
        with patch('jcaption.preferences.model_ready', return_value=True):
            self.dialog.stop_download()
            self.dialog.download_finished(0)  # duplicate late completion
        self.apply.assert_not_called()
        self.assertIsNone(self.dialog.download)
        self.assertTrue(self.dialog.tabs.isEnabled())
        self.assertTrue(self.dialog.apply_button.isEnabled())

    def test_close_cancels_download_and_double_apply_does_not_start_another(self):
        self.dialog.show()
        process = self.fake_download()
        self.dialog.apply_clicked()
        self.apply.assert_not_called()
        self.assertIs(self.dialog.download, process)
        self.dialog.close()
        process.kill.assert_called_once()
        self.assertIsNone(self.dialog.download)
        self.apply.assert_not_called()

    def test_successful_download_applies_once_and_failure_keeps_pending_choices(self):
        self.choose('large-v3')
        self.fake_download()
        with patch('jcaption.preferences.model_ready', return_value=True):
            self.dialog.download_finished(0)
            self.dialog.download_finished(0)
        self.apply.assert_called_once_with(self.dialog.values())
        self.apply.reset_mock()
        self.fake_download()
        self.dialog.download_finished(1)
        self.apply.assert_not_called()
        self.assertEqual(self.dialog.model.currentData(), 'large-v3')
        self.assertFalse(self.dialog.pending_notice.isHidden())

    def test_runtime_does_not_report_stopped_or_loading_model_as_listening(self):
        for stage, expected in [('stopped', '字幕未运行'), ('loading_local_model', '正在加载本地模型'),
                                ('listening', '本地实时识别')]:
            write_json(self.root/'logs/status.json', {'stage': stage})
            self.dialog.refresh_runtime_status()
            self.assertIn(expected, self.dialog.runtime.text())
        write_json(self.root/'config/caption.json', {'recognition_source': 'windows_livecaptions'})
        write_json(self.root/'logs/status.json', {'stage': 'source_error', 'source_note': 'reader failed'})
        self.dialog.refresh_runtime_status()
        self.assertEqual(self.dialog.runtime.text(), 'reader failed')

    def real_download(self):
        process = QProcess(self.dialog)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.dialog.pending = self.dialog.values()
        self.dialog.buffer = b''
        self.dialog.download = process
        process.readyReadStandardOutput.connect(self.dialog.download_output)
        process.finished.connect(self.dialog.download_finished)
        process.errorOccurred.connect(self.dialog.download_error)
        return process

    def test_actual_qprocess_cancellation_releases_controls_without_applying(self):
        process = self.real_download()
        process.start(sys.executable, ['-c', 'import time; time.sleep(10)'])
        self.assertTrue(process.waitForStarted(3000))
        self.dialog.tabs.setEnabled(False)
        self.dialog.apply_button.setEnabled(False)
        self.dialog.stop_download()
        self.app.processEvents()
        self.assertIsNone(self.dialog.download)
        self.assertTrue(self.dialog.tabs.isEnabled())
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.apply.assert_not_called()

    def test_actual_qprocess_start_failure_recovers_controls_and_can_retry(self):
        process = self.real_download()
        self.dialog.tabs.setEnabled(False)
        self.dialog.apply_button.setEnabled(False)
        process.start(str(self.root/'nonexistent-python.exe'), [])
        self.assertFalse(process.waitForStarted(3000))
        self.app.processEvents()
        self.assertIsNone(self.dialog.download)
        self.assertTrue(self.dialog.tabs.isEnabled())
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.apply.assert_not_called()
