"""Persistence, local-only migration and incomplete model protection."""
import json
from pathlib import Path
import tempfile
import unittest

from jcaption.settings import (load_appearance, read_json, write_json, model_installed,
                               recognition_language, save_recognition, local_config)


class SettingsTests(unittest.TestCase):
    def test_capture_sensitivity_is_bounded_and_independent_of_decode_settings(self):
        from jcaption.settings import capture_vad_threshold
        self.assertEqual(capture_vad_threshold({'capture_vad_threshold':.25}),.25)
        self.assertEqual(capture_vad_threshold({'capture_vad_threshold':.4,'whisper_draft_beam':5}),.4)
        for value in (0,1,True,'0.25',float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                capture_vad_threshold({'capture_vad_threshold':value})

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'config/caption.json'
        write_json(self.path, {'local_model': 'large-v3-turbo', 'api_key_file': 'existing.env',
                               'mode': 'local', 'display_mode': 'both', 'device': 'cuda'})

    def test_incomplete_model_cannot_replace_working_configuration(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_recognition(self.root, {'local_model':'tiny', 'language':'ja'})
        with self.assertRaises(ValueError):
            save_recognition(self.root, {'local_model':'../anything', 'language':'ja'})
        self.assertEqual(before, self.path.read_bytes())

    def test_complete_model_can_be_selected_without_losing_other_preferences(self):
        directory = self.root / 'apps/TigerBackend/audioWhisper/.cache/whisper/tiny-ct2-fp16'
        directory.mkdir(parents=True)
        (directory / 'model.bin').write_bytes(b'model')
        self.assertFalse(model_installed(self.root, 'tiny'))
        catalog = read_json(Path(__file__).resolve().parents[1] / 'jcaption/model_catalog.json')
        for filename in catalog['tiny']['file_checksums']:
            (directory / filename).write_bytes(b'fixture')
        save_recognition(self.root, {'local_model':'tiny', 'language':'ja'})
        config = read_json(self.path)
        self.assertEqual(config, {'local_model': 'tiny', 'language':'ja',
                                  'mode': 'local', 'display_mode': 'both', 'device': 'cuda',
                                  'luna_output_enabled':True})

    def test_interrupted_validation_is_not_treated_as_installed(self):
        directory = self.root / 'apps/TigerBackend/audioWhisper/.cache/whisper/tiny-ct2-fp16'
        directory.mkdir(parents=True)
        catalog = read_json(Path(__file__).resolve().parents[1] / 'jcaption/model_catalog.json')
        for filename in catalog['tiny']['file_checksums']:
            (directory / filename).write_bytes(b'fixture')
        (directory / '.caption-download-incomplete').touch()
        self.assertFalse(model_installed(self.root, 'tiny'))
        with self.assertRaises(ValueError):
            save_recognition(self.root, {'local_model':'tiny', 'language':'ja'})

    def test_appearance_roundtrip_and_malformed_values_do_not_break_startup(self):
        path = self.root / 'config/overlay.json'
        write_json(path, {'background_opacity': 0, 'font_size': 36})
        self.assertEqual(load_appearance(self.root)['background_opacity'], 0)
        self.assertEqual(load_appearance(self.root)['font_size'], 36)
        write_json(path, {'background_opacity': 'bad', 'font_size': 999})
        self.assertEqual(load_appearance(self.root)['background_opacity'], 85)
        self.assertEqual(load_appearance(self.root)['font_size'], 64)
        path.write_text('[123]', encoding='utf-8')
        self.assertEqual(load_appearance(self.root)['background_opacity'], 85)
        path.write_text('{broken', encoding='utf-8')
        self.assertEqual(load_appearance(self.root)['background_opacity'], 85)

    def test_auto_language_is_not_sent_to_whisper_as_literal(self):
        self.assertIsNone(recognition_language({'language':'auto'}))
        self.assertEqual(recognition_language({'language':'ja'}),'ja')

    def test_retired_cloud_configuration_migrates_without_reading_key_file(self):
        from unittest.mock import patch
        original=read_json(self.path)
        write_json(self.path,{**original,'mode':'api','language':'ja','api_url':'https://example.com/asr',
                             'api_model':'legacy','minimax_stream_response':True})
        with patch('jcaption.settings.model_ready',return_value=True):
            result=save_recognition(self.root,{'language':'auto','display_mode':'luna'})
        self.assertEqual(result['mode'],'local')
        self.assertEqual(result['language'],'auto')
        self.assertTrue(result['luna_output_enabled'])
        self.assertEqual(result['device'],'cuda')
        self.assertFalse(any(key.startswith('api_') for key in result))
        self.assertNotIn('minimax_stream_response',result)

    def test_display_and_local_preferences_roundtrip(self):
        from unittest.mock import patch
        with patch('jcaption.settings.model_ready',return_value=True):
            for output in ('luna','both','overlay'):
                result=save_recognition(self.root,{'language':'ja','display_mode':output,
                    'whisper_blocklist_enabled':True,'whisper_blocklist':[' 架空の字幕 ','架空の字幕'],
                    'local_model':'qwen3-asr-1.7b','local_native_backend':'cuda',
                    'local_native_device':1,'local_stream_chunk_seconds':.75})
                self.assertEqual(result['luna_output_enabled'],output!='overlay')
                self.assertEqual(result['whisper_blocklist'],['架空の字幕'])
                self.assertEqual(result['local_native_device'],1)
                self.assertEqual(result['local_stream_chunk_seconds'],.75)

    def test_invalid_preferences_never_partially_replace_working_config(self):
        from unittest.mock import patch
        before=self.path.read_bytes()
        with patch('jcaption.settings.model_ready',return_value=True):
            for invalid in ({'mode':'api'}, {'mode':'auto'}, {'api_provider':'openai'},
                {'api_key_file':'secret.txt'}, {'language':'invented'},
                {'whisper_blocklist_enabled':'yes'}, {'whisper_blocklist':['']},
                {'local_native_backend':'invented'}, {'local_native_device':True},
                {'local_native_device':16}, {'local_stream_chunk_seconds':float('nan')},
                {'local_stream_chunk_seconds':.1}):
                with self.assertRaises(ValueError):
                    save_recognition(self.root,{'language':'ja',**invalid})
                self.assertEqual(self.path.read_bytes(),before)
