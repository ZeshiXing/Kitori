import tempfile
from pathlib import Path
import unittest

from jcaption.lookahead import Lookahead, UnsupportedMedia, check_manifest
from jcaption.server import CaptionService


class LookaheadTests(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        self.file.close()
        self.now = 10.0
        self.ahead = Lookahead(clock=lambda: self.now)
        self.generation = self.ahead.open(self.file.name)

    def tearDown(self):
        Path(self.file.name).unlink()

    def cache(self, start=0, end=8):
        self.ahead.jobs.append({'generation': self.generation, 'job_id': 'first',
                                'start': start, 'end': end, 'pcm': ''})
        self.ahead.take_job()
        return self.ahead.complete(self.generation, 'first',
                                   [{'start': 3, 'end': 5, 'text': '未来の台詞'}], lambda _: [])

    def test_cached_future_line_is_not_shown_early(self):
        self.cache()
        self.ahead.set_clock(self.generation, 1, True)
        snapshot = self.ahead.snapshot()
        self.assertTrue(snapshot['covered'])
        self.assertIsNone(snapshot['cue'])
        self.ahead.set_clock(self.generation, 3.5, True)
        self.assertEqual(self.ahead.snapshot()['cue']['text'], '未来の台詞')

    def test_lead_includes_contiguous_adjacent_chunks(self):
        self.cache()
        self.ahead.coverage.append((8, 16))
        self.ahead.set_clock(self.generation, 3, True)
        self.assertEqual(self.ahead.snapshot()['lead_seconds'], 13)

    def test_stale_clock_disables_lookahead_instead_of_drifting(self):
        self.cache()
        self.ahead.set_clock(self.generation, 3, False)
        self.now += 3
        self.assertFalse(self.ahead.snapshot()['covered'])

    def test_rate_and_pause_use_media_clock(self):
        self.cache()
        self.ahead.set_clock(self.generation, 1, False, rate=2)
        self.now += 1
        self.assertEqual(self.ahead.snapshot()['position'], 3)
        self.ahead.set_clock(self.generation, 3, True)
        self.now += 1
        self.assertEqual(self.ahead.snapshot()['position'], 3)

    def test_old_source_job_cannot_populate_new_cache(self):
        self.ahead.jobs.append({'generation': self.generation, 'job_id': 'old', 'start': 0, 'end': 8, 'pcm': ''})
        self.ahead.take_job()
        self.ahead.open(self.file.name)
        self.assertFalse(self.ahead.complete(self.generation, 'old', [], lambda _: []))
        self.assertEqual(self.ahead.snapshot()['cached_ranges'], [])

    def test_seek_outside_coverage_immediately_uses_live_lane(self):
        self.cache()
        self.ahead.set_clock(self.generation, 30, False)
        self.assertFalse(self.ahead.snapshot()['covered'])

    def test_expired_job_gets_a_new_identity_and_late_result_is_rejected(self):
        self.ahead.jobs.append({'generation': self.generation, 'job_id': 'old', 'start': 0, 'end': 8, 'pcm': ''})
        self.ahead.take_job()
        self.now += 16
        retry = self.ahead.take_job()
        self.assertNotEqual(retry['job_id'], 'old')
        self.assertFalse(self.ahead.complete(self.generation, 'old', [], lambda _: []))
        self.now += 16
        self.assertIsNone(self.ahead.take_job())
        self.assertEqual(self.ahead.snapshot()['reason'], 'recognition_timeout')

    def test_protected_dash_and_hls_are_rejected(self):
        with self.assertRaises(UnsupportedMedia):
            check_manifest('<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><ContentProtection value="cenc"/></MPD>')
        with self.assertRaises(UnsupportedMedia):
            check_manifest('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="license"')
        check_manifest('<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"/>')

    def test_unsupported_source_does_not_replace_live_caption(self):
        service = CaptionService('test', 'token', port=0)
        try:
            service.state.accept({'session_id': 'test', 'utterance_id': 0, 'revision': 1,
                                  'text': '实时字幕', 'final': False})
            service.lookahead.status = 'unsupported'
            service.lookahead.reason = 'protected_media'
            snapshot = service.display_snapshot()
            self.assertEqual(snapshot['input_mode'], 'live')
            self.assertEqual(snapshot['current']['text'], '实时字幕')
        finally:
            service.http.server_close()


if __name__ == '__main__':
    unittest.main()
