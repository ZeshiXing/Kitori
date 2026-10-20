import unittest
from unittest.mock import Mock
from jcaption.state import CaptionState, display_window, previous_reading_line


class CaptionDisplayTests(unittest.TestCase):
    def event(self, text, revision=1, uid=0, final=False):
        return dict(session_id='run', utterance_id=uid, revision=revision, final=final, text=text)

    def test_identical_hypotheses_and_final_do_not_extend_idle_display(self):
        clock = Mock(return_value=10)
        state = CaptionState('run', clock=clock)
        state.accept(self.event('今日は'))
        clock.return_value = 13
        state.accept(self.event('今日は', revision=2, final=True))
        shown = display_window(state.snapshot(), 4, now=14.01)
        self.assertEqual(shown['current']['text'], '')
        self.assertTrue(shown['current']['display_expired'])
        self.assertEqual(state.snapshot()['current']['text'], '今日は')

    def test_new_words_and_a_repeated_spoken_utterance_refresh_the_deadline(self):
        clock = Mock(return_value=10)
        state = CaptionState('run', clock=clock)
        state.accept(self.event('今日は'))
        clock.return_value = 13
        state.accept(self.event('今日は晴れ', revision=2, final=True))
        self.assertEqual(display_window(state.snapshot(), 4, now=15)['current']['text'], '今日は晴れ')
        clock.return_value = 20
        state.accept(self.event('今日は晴れ', uid=1))
        self.assertEqual(display_window(state.snapshot(), 4, now=22)['current']['text'], '今日は晴れ')

    def test_old_line_does_not_reappear_as_previous_after_a_silent_gap(self):
        clock = Mock(return_value=10)
        state = CaptionState('run', clock=clock)
        state.accept(self.event('古い字幕', final=True))
        clock.return_value = 20
        state.accept(self.event('新しい字幕', uid=1))
        snapshot = display_window(state.snapshot(), 4, now=20.1)
        self.assertIsNone(previous_reading_line(snapshot, 2, now=20.1))
        self.assertEqual(len(state.snapshot()['history']), 1)

    def test_disabled_timeout_and_media_clock_captions_are_not_expired(self):
        snapshot = dict(input_mode='live', current=dict(text='字幕', updated_monotonic=1), history=[])
        self.assertEqual(display_window(snapshot, 0, now=100)['current']['text'], '字幕')
        snapshot['input_mode'] = 'lookahead'
        self.assertEqual(display_window(snapshot, 4, now=100)['current']['text'], '字幕')

    def test_empty_capture_fragment_retains_recent_final_then_expires(self):
        clock = Mock(return_value=10)
        state = CaptionState('run', clock=clock)
        state.accept(self.event('直前の台詞', final=True))
        clock.return_value = 11
        state.accept(self.event('', uid=1, final=True))
        self.assertEqual(display_window(state.snapshot(), 4, now=11.1)['current']['text'], '直前の台詞')
        self.assertEqual(display_window(state.snapshot(), 4, now=14.1)['current']['text'], '')
        self.assertEqual(state.snapshot()['current']['phase'], 'cancelled')

    def test_empty_final_keeps_same_utterance_draft_without_confirming_it(self):
        clock=Mock(return_value=10)
        state=CaptionState('run',clock=clock)
        state.accept(self.event('短い返事'))
        state.apply_annotation(0,1,[dict(start=0,end=2,surface='短い',reading='みじかい')])
        clock.return_value=10.2
        state.accept(self.event('',revision=2,final=True))
        shown=display_window(state.snapshot(),4,now=10.3)
        self.assertEqual(shown['current']['text'],'短い返事')
        self.assertEqual(shown['current']['phase'],'draft')
        self.assertEqual(shown['current']['stable_text'],'')
        self.assertEqual(shown['current']['ruby'][0]['reading'],'みじかい')
        self.assertEqual(state.snapshot()['current']['phase'],'cancelled')
        self.assertEqual(display_window(state.snapshot(),4,now=14.01)['current']['text'],'')

    def test_empty_revisions_across_segments_keep_latest_draft_not_an_older_final(self):
        clock=Mock(return_value=10);state=CaptionState('run',clock=clock)
        state.accept(self.event('前の終稿',final=True))
        clock.return_value=11;state.accept(self.event('今の草稿',uid=1))
        for stamp,uid,revision,final in [(11.1,1,2,False),(11.2,1,3,True),(11.4,2,1,True)]:
            clock.return_value=stamp;state.accept(self.event('',uid=uid,revision=revision,final=final))
            shown=display_window(state.snapshot(),4,now=stamp+.01)
            self.assertEqual(shown['current']['text'],'今の草稿')
            self.assertEqual(shown['current']['content_updated_monotonic'],11)
        self.assertEqual(display_window(state.snapshot(),4,now=15.01)['current']['text'],'')
        clock.return_value=15.2;state.accept(self.event('新しい文字',uid=3))
        self.assertEqual(display_window(state.snapshot(),4,now=15.21)['current']['text'],'新しい文字')

    def test_lookahead_silence_never_replays_the_retained_live_line(self):
        snapshot=dict(input_mode='lookahead',current=dict(text='',phase='final'),history=[],
                      last_nonempty=dict(text='過去の音声',phase='draft'))
        self.assertEqual(display_window(snapshot,4,now=10)['current']['text'],'')
