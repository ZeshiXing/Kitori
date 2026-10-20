"""Audio consumed, stale identities and boundary correctness, not UI mocks."""
import unittest

from jcaption.rolling_asr import Recognition, RollingRecognizer, Word
from jcaption.speech_boundary import gap_cut


def audio(seconds, value=1000):
    return int(value).to_bytes(2, 'little', signed=True)*int(seconds*16000)


class RollingASRTests(unittest.TestCase):
    def test_empty_prefix_decode_never_discards_speech_at_a_vad_cut(self):
        calls=[]
        def decode(pcm,*_):
            calls.append(pcm)
            return Recognition('' if len(calls)==1 else '句首保留')
        stream=RollingRecognizer(decode,speech_boundary=lambda *_:3*32000)
        pcm=audio(6)
        self.assertEqual(stream.transcribe(pcm,16000,False),'句首保留')
        self.assertEqual(calls[-1],pcm)
        self.assertEqual(stream.offset,0)
        self.assertEqual(stream.totals['empty_prefix_cuts_rejected'],1)

    def test_speech_boundary_splits_music_gap_without_discarding_any_pcm(self):
        calls = []
        # Simulate learned speech endpoints, not a fake quiet waveform: the
        # entire PCM is nonzero, including background sound in the pause.
        def decode(pcm,rate,final):
            calls.append(pcm)
            return Recognition('前句' if len(calls)==1 else '次句')
        boundary=lambda pcm,rate:gap_cut([{'start':0,'end':32000},
                                         {'start':38400,'end':80000}],len(pcm)//2,rate)
        stream=RollingRecognizer(decode,speech_boundary=boundary)
        pcm=audio(5.5)
        self.assertEqual(stream.transcribe(pcm,16000,False),'前句次句')
        self.assertEqual(b''.join(calls),pcm)
        self.assertEqual(stream.totals['speech_pause_trims'],1)

    def test_unavailable_boundary_or_invalid_cut_keeps_whole_audio(self):
        calls=[]
        def decode(pcm,*_):
            calls.append(len(pcm))
            return Recognition('正文')
        stream=RollingRecognizer(decode,speech_boundary=lambda *_:3)
        self.assertEqual(stream.transcribe(audio(6),16000,False),'正文')
        self.assertEqual(calls,[6*32000])
        self.assertEqual(stream.offset,0)
        self.assertEqual(stream.totals['boundary_errors'],1)

    def test_identical_audio_and_same_quality_final_reuse_one_decode(self):
        calls = []
        def decode(pcm, rate, final):
            calls.append((len(pcm), final))
            return Recognition('はい')
        stream = RollingRecognizer(decode)
        stream.set_utterance(('session', 0))
        for final in (False, False, True, True):
            self.assertEqual(stream.transcribe(audio(1), 16000, final), 'はい')
        self.assertEqual(len(calls), 1)
        self.assertEqual(stream.totals['duplicate_hits'], 3)
        stream.set_utterance(('session', 1))
        self.assertEqual(stream.transcribe(audio(1), 16000, True), 'はい')
        self.assertEqual(len(calls), 2, 'Identical spoken lines are separate utterances')

    def test_changed_audio_same_length_is_not_cached_and_quality_final_still_runs(self):
        calls = []
        def decode(pcm, rate, final):
            calls.append(final)
            return Recognition('正確' if final else '草稿')
        stream = RollingRecognizer(decode, final_changes_decode=True)
        stream.transcribe(audio(1), 16000, False)
        stream.transcribe(audio(1, 2000), 16000, False)
        self.assertEqual(stream.transcribe(audio(1, 2000), 16000, True), '正確')
        stream.transcribe(audio(1, 2000), 16000, True)
        self.assertEqual(calls, [False, False, True])

    def test_confirmed_timestamp_prefix_leaves_only_tail_and_final_never_replays_prefix(self):
        calls = []
        def decode(pcm, rate, final):
            calls.append(len(pcm)/32000)
            if len(calls) <= 2:
                return Recognition('今日は。日本語', (
                    Word(0, 1, '今日'), Word(1, 3, 'は。'), Word(3, 4, '日本'), Word(4, 4.8, '語')))
            # Offset is 2.8 sec; the first word is retained left context.
            return Recognition('は。日本語を学ぶ', (
                Word(0, .25, 'は。'), Word(.3, 1.2, '日本'), Word(1.2, 2.0, '語'),
                Word(2.0, 2.5, 'を'), Word(2.5, 3.0, '学ぶ')))
        stream = RollingRecognizer(decode, timestamps=True)
        self.assertEqual(stream.transcribe(audio(4.9), 16000, False), '今日は。日本語')
        self.assertEqual(stream.transcribe(audio(5), 16000, False), '今日は。日本語')
        self.assertAlmostEqual(stream.offset/32000, 2.8)
        self.assertEqual(stream.transcribe(audio(6), 16000, True), '今日は。日本語を学ぶ')
        self.assertAlmostEqual(calls[-1], 3.2)
        self.assertEqual(stream.totals['timestamp_trims'], 1)

    def test_conflicting_or_unreliable_word_alignment_cannot_seal_audio(self):
        results = iter([
            Recognition('今日です', (Word(0, 2, '今日'), Word(2, 3, 'です'))),
            Recognition('明日です', (Word(0, 2, '明日'), Word(2, 3, 'です'))),
            Recognition('明日です', (Word(0, float('nan'), '明日'),)),
        ])
        stream = RollingRecognizer(lambda *_: next(results), timestamps=True)
        stream.transcribe(audio(4.5), 16000, False)
        self.assertEqual(stream.transcribe(audio(5.5), 16000, False), '明日です')
        self.assertEqual(stream.transcribe(audio(6), 16000, False), '明日です')
        self.assertEqual(stream.offset, 0)

    def test_repeated_word_after_committed_time_is_real_new_speech(self):
        stream = RollingRecognizer(lambda *_: None, timestamps=True)
        stream.committed = 'はい'
        stream.committed_end = 2
        stream.offset = int(1.8*32000)
        words = stream.uncommitted_words((Word(0, .3, 'はい'), Word(.4, .8, 'はい')),16000,32000)
        self.assertEqual([w.text for w in words], ['はい'])
        self.assertGreater(words[0].start, stream.committed_end)

    def test_fast_particle_within_timestamp_tolerance_is_not_dropped(self):
        stream = RollingRecognizer(lambda *_: None, timestamps=True)
        stream.committed = '計算'
        stream.committed_end = 2
        stream.offset = int(1.8*32000)
        words = stream.uncommitted_words((Word(.18,.24,'せ'),Word(.24,.5,'ず')),16000,32000)
        self.assertEqual(''.join(w.text for w in words),'せず')

    def test_agreed_subwords_without_sentence_boundary_never_force_an_audio_cut(self):
        result = Recognition('計算せず', (Word(0,1,'計算'),Word(1,2,'せ'),Word(2,3,'ず')))
        stream = RollingRecognizer(lambda *_: result, timestamps=True)
        stream.transcribe(audio(5),16000,False)
        stream.transcribe(audio(6),16000,False)
        self.assertEqual(stream.offset,0)
        self.assertEqual(stream.committed,'')

    def test_unpunctuated_japanese_can_trim_at_an_agreed_timestamp_pause(self):
        result = Recognition('そうです次です', (Word(0,1,'そう'),Word(1,2,'です'),
                                            Word(2.4,3,'次'),Word(3,4.8,'です')))
        stream = RollingRecognizer(lambda *_: result,timestamps=True)
        stream.transcribe(audio(4.9),16000,False)
        stream.transcribe(audio(5.5),16000,False)
        self.assertEqual(stream.committed,'そうです')
        self.assertAlmostEqual(stream.offset/32000,1.8)

    def test_missing_speech_detector_keeps_even_quiet_audio_instead_of_guessing(self):
        calls = []
        def decode(pcm, rate, final):
            calls.append(pcm)
            return Recognition('前の句後の句')
        stream = RollingRecognizer(decode)
        pcm = audio(3) + audio(.4, 0) + audio(2)
        self.assertEqual(stream.transcribe(pcm,16000,False), '前の句後の句')
        self.assertEqual(stream.offset, 0)
        self.assertEqual(calls, [pcm])

    def test_final_decodes_remaining_audio_once_without_a_new_cut(self):
        calls, scans = [], []
        def decode(pcm,rate,final):
            calls.append((pcm, final))
            return Recognition('前句' if len(calls)==1 else '次句')
        def boundary(pcm,rate):
            scans.append(pcm)
            return 3*32000
        stream=RollingRecognizer(decode, speech_boundary=boundary, final_changes_decode=True)
        stream.transcribe(audio(6),16000,False)
        self.assertEqual(len(scans),1)
        before=len(calls)
        pcm=audio(9)
        self.assertEqual(stream.transcribe(pcm,16000,True),'前句次句')
        self.assertEqual(len(scans),1)
        self.assertEqual(calls[before:],[(pcm[3*32000:],True)])

    def test_final_without_prior_draft_preserves_whole_utterance(self):
        calls=[]
        def forbidden_scan(*_):
            self.fail('A final needs no new audio cut')
        def decode(pcm,rate,final):
            calls.append((pcm,final))
            return Recognition('首尾保留')
        stream=RollingRecognizer(decode,speech_boundary=forbidden_scan)
        pcm=audio(8)
        self.assertEqual(stream.transcribe(pcm,16000,True),'首尾保留')
        self.assertEqual(calls,[(pcm,True)])

    def test_text_only_no_silence_keeps_context_instead_of_guessing_word_boundary(self):
        calls = []
        def decode(pcm, rate, final):
            calls.append(len(pcm))
            return Recognition('長い台詞')
        stream = RollingRecognizer(decode)
        stream.transcribe(audio(8),16000,False)
        self.assertEqual(stream.offset, 0)
        self.assertEqual(calls, [8*32000])

    def test_new_session_and_shorter_capture_reset_old_prefix(self):
        stream = RollingRecognizer(lambda *_: Recognition('新しい声'))
        stream.set_utterance(('a', 0))
        stream.transcribe(audio(2),16000,False)
        stream.committed = '古い声'
        self.assertEqual(stream.transcribe(audio(1),16000,True), '新しい声')
        stream.committed = '古い声'
        stream.set_utterance(('b', 0))
        self.assertEqual(stream.transcribe(audio(1),16000,True), '新しい声')


if __name__ == '__main__':
    unittest.main()
