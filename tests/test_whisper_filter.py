"""Literal filtering never changes model decoding or adds confirmation waits."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from jcaption.whisper_filter import WhisperPhraseFilter, validate_blocklist


class WhisperFilterTests(unittest.TestCase):
    def test_disabled_is_identity_and_common_dialogue_is_preserved(self):
        text = 'ご視聴ありがとうございました。'
        self.assertEqual(WhisperPhraseFilter().apply(text), text)
        filter = WhisperPhraseFilter(True)
        for text in ('ありがとう。', 'はい、はい。', 'ご視聴について話す。', '私は学校へ行きます。'):
            self.assertEqual(filter.apply(text), text)

    def test_phrase_can_span_whitespace_and_case_but_is_not_a_regex(self):
        filter = WhisperPhraseFilter(True, ['Thank you for watching', '[noise]'])
        self.assertEqual(filter.apply('THANK YOU\nFOR WATCHING!'), '')
        self.assertEqual(filter.apply('noise'), 'noise')
        self.assertEqual(filter.apply('[noise]'), '')

    def test_partial_removal_keeps_other_text_and_empty_list_disables_matches(self):
        filter = WhisperPhraseFilter(True, ['架空の字幕'])
        self.assertEqual(filter.apply('前半。架空の字幕 後半。'), '前半。 後半。')
        self.assertEqual(WhisperPhraseFilter(True, []).apply('架空の字幕'), '架空の字幕')
        self.assertEqual(filter.apply('架空の字幕。'), '')

    def test_timed_filter_crosses_word_boundaries_and_preserves_media_times(self):
        words = [SimpleNamespace(word='前半。',start=0,end=1),
                 SimpleNamespace(word='架空の',start=1,end=2),
                 SimpleNamespace(word='字幕',start=2,end=3),
                 SimpleNamespace(word='後半。',start=3,end=4)]
        filter = WhisperPhraseFilter(True, ['架空の字幕'])
        self.assertEqual(filter.words(words), [{'word':'前半。','start':0,'end':1},
                                             {'word':'後半。','start':3,'end':4}])
        self.assertEqual(filter.words(words[1:3]), [])

    def test_invalid_or_unbounded_lists_are_rejected(self):
        for value in ('term', [''], ['a\nb'], ['x'*201], ['term']*201, [None]):
            with self.assertRaises(ValueError): validate_blocklist(value)
        self.assertEqual(validate_blocklist([' a ', 'a']), ['a'])

    def test_plugin_filters_both_phases_clears_blocked_text_and_leaves_api_alone(self):
        path = Path(__file__).resolve().parents[1]/'plugins/japanese_caption.py'
        spec = importlib.util.spec_from_file_location('caption_filter_test_plugin',path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'Plugins':SimpleNamespace(Base=object)}):
            spec.loader.exec_module(module)
        plugin = module.JapaneseCaptionPlugin()
        plugin.is_enabled = Mock(return_value=True)
        plugin.phrase_filter = WhisperPhraseFilter(True, ['架空の字幕'])
        plugin.publisher, plugin.status = Mock(), Mock()
        plugin.detected_language = 'ja'
        result = {'caption_session':'test','caption_utterance':0,'caption_revision':1,
                  'caption_backend':'local','asr_seconds':.1,'audio_seconds':1}
        for final in (False, True):
            plugin.emit_caption('架空の字幕。',result,final)
            self.assertEqual(plugin.publisher.publish.call_args.args[0]['text'], '')
            self.assertEqual(plugin.publisher.publish.call_args.args[0]['final'], final)
        plugin.emit_caption('架空の字幕',{**result,'caption_backend':'openai'},True)
        self.assertEqual(plugin.publisher.publish.call_args.args[0]['text'], '架空の字幕')
