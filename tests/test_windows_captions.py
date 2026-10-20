import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from jcaption.windows_captions import SnapshotStream
from jcaption.settings import read_json, write_json, save_recognition


class WindowsSnapshotTests(unittest.TestCase):
    def stream(self):
        stream = SnapshotStream('session', 'ja')
        self.assertEqual(stream.update('', 0), [])
        return stream

    def test_partial_rewrite_and_idle_commit_do_not_wait_for_sentence(self):
        stream = self.stream()
        first = stream.update('ごめん', .12)
        revised = stream.update('間違って', .24)
        self.assertFalse(first[0]['final'])
        self.assertEqual(first[0]['utterance_id'], revised[0]['utterance_id'])
        self.assertEqual(revised[0]['text'], '間違って')
        self.assertEqual(stream.update('間違って', 1.1), [])
        final = stream.update('間違って', 1.3)
        self.assertTrue(final[0]['final'])
        self.assertEqual(stream.update('間違って', 2.5), [])
        following = stream.update('間違ってごめん', 3)
        self.assertEqual(following[0]['text'], 'ごめん')
        self.assertEqual(following[0]['utterance_id'], 1)

    def test_multiple_completed_sentences_and_tail_are_not_dropped(self):
        stream = self.stream()
        events = stream.update('今日は晴れ。元気？次は', .1)
        self.assertEqual([e['text'] for e in events], ['今日は晴れ。', '元気？', '次は'])
        self.assertEqual([e['final'] for e in events], [True, True, False])
        events = stream.update('今日は晴れ。元気？次は学校', .3)
        self.assertEqual([e['text'] for e in events], ['次は学校'])

    def test_rolling_window_keeps_active_sentence_and_no_replay(self):
        stream = self.stream()
        stream.update('昨日は晴れ。今日は', .1)
        events = stream.update('今日は雨です', .3)
        self.assertEqual([e['text'] for e in events], ['今日は雨です'])
        self.assertFalse(events[0]['final'])

    def test_attach_ignores_stale_captions_and_window_clear_flushes_tail(self):
        stream = SnapshotStream('session', 'ja')
        self.assertEqual(stream.update('前の字幕です。', 0), [])
        self.assertEqual(stream.update('前の字幕です。新しい\n字幕', .1)[0]['text'], '新しい字幕')
        events = stream.update('', .2)
        self.assertEqual([e['text'] for e in events], ['新しい字幕'])
        self.assertTrue(events[0]['final'])
        self.assertEqual(stream.update('次です', .3)[0]['text'], '次です')

    def test_windows_source_does_not_require_installed_local_model_and_discards_retired_cloud(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = dict(mode='local', language='en', local_model='kotoba-v2',
                          api_provider='openai', api_url='https://example.com/v1/audio/transcriptions',
                          api_model='saved-api', api_key_env='MY_SAVED_KEY')
            write_json(root / 'config/caption.json', config)
            with patch('jcaption.settings.model_ready', return_value=False):
                saved = save_recognition(root, {'recognition_source': 'windows_livecaptions'})
                self.assertNotIn('api_model', saved)
                self.assertEqual(saved['local_model'], 'kotoba-v2')
                self.assertEqual(saved['mode'], 'local')
                with self.assertRaises(ValueError):
                    save_recognition(root, {'recognition_source': 'models'})
            self.assertEqual(read_json(root / 'config/caption.json')['recognition_source'], 'windows_livecaptions')

    def test_windows_input_cannot_queue_lookahead_jobs_or_delay_playback(self):
        from jcaption.lookahead import Lookahead
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / 'audio.wav'
            media.touch()
            ahead = Lookahead(enabled=False)
            ahead.open(str(media))
            snapshot = ahead.snapshot()
            self.assertEqual(snapshot['status'], 'unsupported')
            self.assertEqual(snapshot['reason'], 'live_source_only')
            self.assertIsNone(ahead.take_job())

    def test_late_punctuation_does_not_replace_committed_words(self):
        stream = self.stream()
        stream.update('大前さんらしいね', .1)
        self.assertTrue(stream.update('大前さんらしいね', 1.3)[0]['final'])
        self.assertEqual(stream.update('大前さんらしいね。', 1.6), [])
        self.assertEqual(stream.update('大前さんらしいね。', 3), [])
        self.assertEqual(stream.update('大前さんらしいね。次だよ', 4)[0]['text'], '次だよ')

    def test_late_separator_in_batch_does_not_emit_a_punctuation_caption(self):
        stream = self.stream()
        stream.update('最初', .1)
        stream.update('最初', 1.3)
        events = stream.update('最初。次の文。', 1.6)
        self.assertEqual([e['text'] for e in events], ['次の文。'])


if __name__ == '__main__':
    unittest.main()
