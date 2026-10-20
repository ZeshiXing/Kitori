"""Behavior at revision, annotation and session boundaries."""
import unittest

from jcaption.annotation import JapaneseAnnotator
from jcaption.state import CaptionState, previous_reading_line


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.state = CaptionState('run-1')

    def event(self, text, revision=1, identity=0, final=False, session='run-1'):
        return {'session_id': session, 'utterance_id': identity,
                'revision': revision, 'text': text, 'final': final}

    def test_draft_is_visible_before_final_and_agreement_commits_prefix(self):
        self.state.accept(self.event('今日は'))
        first = self.state.snapshot()['current']
        self.assertEqual(first['text'], '今日は')
        self.assertEqual(first['phase'], 'draft')
        self.assertEqual(first['stable_text'], '')
        self.state.accept(self.event('今日は日本語', revision=2))
        second = self.state.snapshot()['current']
        self.assertEqual(second['stable_text'], '今日は')
        self.assertEqual(second['draft_text'], '日本語')

    def test_late_draft_and_duplicate_final_cannot_overwrite_final(self):
        self.state.accept(self.event('今日は', revision=2, final=True))
        self.assertFalse(self.state.accept(self.event('今日', revision=1)))
        self.assertFalse(self.state.accept(self.event('明日', revision=3)))
        self.assertEqual(self.state.snapshot()['current']['text'], '今日は')

    def test_previous_utterance_result_cannot_replace_new_speech(self):
        self.state.accept(self.event('はい', final=True))
        self.state.accept(self.event('次の話', identity=1))
        self.assertFalse(self.state.accept(self.event('遅い結果', revision=20, final=True)))
        self.assertEqual(self.state.snapshot()['current']['text'], '次の話')

    def test_repeat_spoken_lines_have_distinct_identities(self):
        self.state.accept(self.event('はい', final=True))
        self.state.accept(self.event('はい', identity=1, final=True))
        self.assertEqual(len(self.state.snapshot()['history']), 1)
        self.assertEqual(self.state.metrics()['final_updates'], 2)

    def test_annotation_for_old_text_is_discarded(self):
        self.state.accept(self.event('今日'))
        self.state.accept(self.event('明日', revision=2))
        self.assertFalse(self.state.apply_annotation(0, 1, [{'start': 0, 'end': 2,
                                                           'surface': '今日', 'reading': 'きょう'}]))
        self.assertEqual(self.state.snapshot()['current']['ruby'], [])

    def test_committed_reading_is_frozen_until_explicit_final_correction(self):
        self.state.accept(self.event('今日'))
        self.state.accept(self.event('今日は', revision=2))
        span = {'start': 0, 'end': 2, 'surface': '今日', 'reading': 'きょう'}
        self.state.apply_annotation(0, 2, [span])
        self.state.accept(self.event('今日は日本語', revision=3))
        self.state.apply_annotation(0, 3, [{**span, 'reading': 'こんにち'}])
        self.assertEqual(self.state.snapshot()['current']['ruby'][0]['reading'], 'きょう')
        self.state.accept(self.event('明日は日本語', revision=4, final=True))
        self.assertTrue(self.state.snapshot()['current']['correction'])

    def test_conflicting_draft_stays_visible_without_waiting_for_final(self):
        self.state.accept(self.event('今日'))
        self.state.accept(self.event('今日は', revision=2))
        self.state.accept(self.event('明日は学校', revision=3))
        self.assertEqual(self.state.snapshot()['current']['text'], '明日は学校')
        self.assertEqual(self.state.snapshot()['current']['stable_text'], '')
        self.assertTrue(self.state.snapshot()['current']['pending_correction'])
        self.state.accept(self.event('明日は学校に行く', revision=4))
        self.assertEqual(self.state.snapshot()['current']['stable_text'], '明日は学校')

    def test_changed_prefix_drops_only_changed_readings(self):
        self.state.accept(self.event('今日は学校'))
        self.state.accept(self.event('今日は学校です', revision=2))
        self.state.apply_annotation(0,2,[{'start':0,'end':2,'surface':'今日','reading':'きょう'},
                                       {'start':3,'end':5,'surface':'学校','reading':'がっこう'}])
        self.state.accept(self.event('今日は映画を見ます', revision=3))
        self.assertEqual(self.state.snapshot()['current']['stable_text'], '今日は')
        self.assertEqual(self.state.snapshot()['current']['text'], '今日は映画を見ます')
        self.assertEqual(list(self.state.frozen_readings.values()), ['きょう'])
        self.assertFalse(self.state.apply_annotation(0,2,[]))

    def test_previous_final_is_retained_without_delaying_next_draft(self):
        now = [10.0]
        state = CaptionState('run-1',clock=lambda:now[0])
        state.accept(self.event('前の台詞',final=True))
        now[0] += .34
        state.accept(self.event('次の台詞',identity=1))
        snapshot = state.snapshot()
        self.assertEqual(snapshot['current']['text'],'次の台詞')
        self.assertEqual(previous_reading_line(snapshot,4,now[0])['text'],'前の台詞')
        now[0] += 3
        state.accept(self.event('次の台詞を話す',revision=2,identity=1))
        self.assertIsNotNone(previous_reading_line(state.snapshot(),4,now[0]))
        now[0] += 1.01
        self.assertIsNone(previous_reading_line(state.snapshot(),4,now[0]))
        self.assertEqual(state.snapshot()['current']['text'],'次の台詞を話す')
        self.assertIsNone(previous_reading_line(snapshot,0,10.34))
        self.assertIsNone(previous_reading_line({**snapshot,'input_mode':'lookahead'},4,10.34))

    def test_old_run_cannot_inject_results_after_restart(self):
        with self.assertRaises(ValueError):
            self.state.accept(self.event('古い結果', session='run-0'))

    def test_detected_language_is_retained_for_the_annotation_worker(self):
        event = {**self.event('中文内容', final=True), 'language': 'zh'}
        self.state.accept(event)
        self.assertEqual(self.state.snapshot()['current']['language'], 'zh')

    def test_history_and_telemetry_are_bounded_and_metrics_have_no_text(self):
        for identity in range(300):
            self.state.accept(self.event('字幕', identity=identity, final=True))
        self.assertEqual(len(self.state.snapshot()['history']), 5)
        metrics = self.state.metrics()
        self.assertEqual(len(metrics['observations']), 256)
        self.assertNotIn('text', repr(metrics))

    def test_japanese_boundaries_and_surrogate_characters(self):
        annotator = JapaneseAnnotator()
        text = '😀今日は字幕を見る'
        tokens = annotator.tokens(text)
        for token in tokens:
            self.assertEqual(text[token['start']:token['end']], token['surface'])
        today = next(token for token in tokens if token['surface'] == '今日')
        self.assertEqual(today['reading'], 'きょう')
        self.assertEqual(annotator.safe_commit_end('日本語', 1), 0)


class ServiceTests(unittest.TestCase):
    def test_non_japanese_caption_does_not_get_japanese_readings(self):
        self.assertEqual(self.service.caption_tokens('中文内容', 'zh'), [])
        self.assertTrue(any(token['reading'] for token in self.service.caption_tokens('今日は', 'ja')))

    @classmethod
    def setUpClass(cls):
        import requests
        from jcaption.server import CaptionService
        cls.service = CaptionService('http-run', 'test-token', port=0)
        cls.service.start()
        cls.url = f'http://127.0.0.1:{cls.service.port}'
        cls.client = requests.Session()
        cls.client.trust_env = False

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.service.close()

    def test_only_authenticated_local_adapter_can_publish(self):
        event = {'session_id': 'http-run', 'utterance_id': 0, 'revision': 1,
                 'text': '日本語', 'final': False}
        self.assertEqual(self.client.post(self.url + '/api/update', json=event, timeout=2).status_code, 403)
        self.assertEqual(self.client.post(self.url + '/api/update', json=event,
                         headers={'X-Caption-Token': 'test-token', 'Origin': 'https://example.org'},
                         timeout=2).status_code, 403)
        response = self.client.post(self.url + '/api/update', json=event,
                                   headers={'X-Caption-Token': 'test-token'}, timeout=2)
        self.assertTrue(response.json()['accepted'])
        state = self.client.get(self.url + '/api/state', timeout=2).json()
        self.assertEqual(state['current']['phase'], 'draft')

    def test_new_view_receives_a_snapshot_without_waiting_for_next_audio(self):
        with self.client.get(self.url + '/events', stream=True, timeout=2) as response:
            line = next(response.iter_lines(chunk_size=1))
            self.assertTrue(line.startswith(b'data: '))
            self.assertIn(b'http-run', line)


if __name__ == '__main__':
    unittest.main()
