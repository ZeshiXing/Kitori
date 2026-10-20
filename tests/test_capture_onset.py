"""Capture-time onset preservation and first-draft timing, without ASR mocks."""
from types import SimpleNamespace
import unittest

from jcaption.capture_onset import CaptureOnsetGuard


class Processor:
    recorded_sample_rate=48000
    default_sample_rate=16000
    input_channel_num=2
    start_rec_on_volume_threshold=False
    previous_audio_chunk=None
    intermediate_time_start=0
    def __init__(self):self.frames=[]


class CaptureOnsetTests(unittest.TestCase):


    def test_brief_speech_can_submit_a_draft_before_the_voice_ends(self):
        now=[100.0];p=Processor();g=CaptureOnsetGuard(clock=lambda:now[0])
        g.before_callback(p);g.before_start(p);p.frames=[b'speech'];p.start_rec_on_volume_threshold=True
        # A 250 ms reply used to end before the first 450 ms draft deadline.
        now[0]+=.19;g.before_callback(p)
        self.assertGreater(now[0]-p.intermediate_time_start,g.interval)
        self.assertLess(now[0]-100,.25)
        self.assertEqual(g.metrics()['first_draft_seconds'],.18)

    def test_early_draft_refresh_is_shifted_once_then_normal_cadence_returns(self):
        now=[100.0];p=Processor();g=CaptureOnsetGuard(clock=lambda:now[0])
        g.before_callback(p);g.before_start(p);p.frames=[b'speech'];p.start_rec_on_volume_threshold=True
        p.intermediate_time_start=100.45;now[0]=100.47
        g.before_callback(p)
        self.assertAlmostEqual(p.intermediate_time_start,100.05)
        now[0]=100.5;g.before_callback(p)
        self.assertAlmostEqual(p.intermediate_time_start,100.05)
        now[0]=102;p.intermediate_time_start=101.95;g.before_callback(p)
        self.assertEqual(p.intermediate_time_start,101.95)

    def test_stereo_preroll_is_bounded_and_prepended_exactly_once(self):
        p=Processor();g=CaptureOnsetGuard(clock=lambda:100)
        chunks=[]
        for i in range(30):
            chunk=bytes([i])*6144 # 32 ms stereo at 48 kHz.
            chunks.append(chunk);p.previous_audio_chunk=chunk
            g.before_callback(p)
        g.before_start(p)
        self.assertEqual(b''.join(p.frames),b''.join(chunks[-18:]))
        self.assertIsNone(p.previous_audio_chunk)
        p.start_rec_on_volume_threshold=True
        g.before_start(p)
        self.assertEqual(len(p.frames),18)
        self.assertAlmostEqual(g.metrics()['last_preroll_seconds'],.576)

    def test_idle_clock_cannot_submit_immediate_tiny_onset(self):
        now=[100.0];p=Processor()
        g=CaptureOnsetGuard(interval=.75,first_draft=.45,clock=lambda:now[0])
        for gap in (1,6,60):
            now[0]+=gap;g.before_callback(p)
            self.assertAlmostEqual(now[0]-p.intermediate_time_start,.3)
            self.assertLess(now[0]-p.intermediate_time_start,.75)
        p.start_rec_on_volume_threshold=True;p.frames=[b'speech']
        old=p.intermediate_time_start;now[0]+=.2;g.before_callback(p)
        self.assertEqual(p.intermediate_time_start,old)
        self.assertAlmostEqual(now[0]-old,.5)

    def test_music_kept_recording_flag_after_flush_rearms_preroll_and_first_deadline(self):
        now=[100.0];p=Processor();g=CaptureOnsetGuard(clock=lambda:now[0])
        p.start_rec_on_volume_threshold=True;p.frames=[]
        g.before_callback(p)
        self.assertFalse(p.start_rec_on_volume_threshold)
        chunks=[]
        for index in range(20):
            chunk=bytes([index])*6144;chunks.append(chunk)
            p.previous_audio_chunk=chunk;now[0]+=.032;g.before_callback(p)
        g.before_start(p)
        self.assertEqual(b''.join(p.frames),b''.join(chunks[-18:]))
        self.assertAlmostEqual(now[0]-p.intermediate_time_start,.75-.18)
        self.assertEqual(g.metrics()['onsets'],1)

    def test_same_callback_flush_and_new_speech_restarts_timer_without_old_flag_blocking(self):
        now=[100.0];p=Processor();g=CaptureOnsetGuard(clock=lambda:now[0])
        p.start_rec_on_volume_threshold=True;p.intermediate_time_start=100
        g.before_start(p)
        self.assertAlmostEqual(now[0]-p.intermediate_time_start,.75-.18)
        self.assertEqual(g.metrics()['onsets'],1)
        p.frames=[b'new speech'];g.before_start(p)
        self.assertEqual(g.metrics()['onsets'],1)

    def test_sources_and_repeated_silence_restarts_do_not_share_preroll(self):
        a,b=Processor(),Processor();g=CaptureOnsetGuard()
        a.previous_audio_chunk=b'a'*6144;b.previous_audio_chunk=b'b'*6144
        g.before_callback(a);g.before_callback(b);g.before_start(a);g.before_start(b)
        self.assertEqual(a.frames,[b'a'*6144]);self.assertEqual(b.frames,[b'b'*6144])
        a.start_rec_on_volume_threshold=True;g.before_callback(a)
        a.start_rec_on_volume_threshold=False;a.frames=[];a.previous_audio_chunk=b'c'*6144
        g.before_callback(a);g.before_start(a)
        self.assertEqual(a.frames,[b'c'*6144])

    def test_disabled_guard_and_host_speaker_carry_are_preserved(self):
        p=Processor();g=CaptureOnsetGuard(enabled=lambda:False)
        p.previous_audio_chunk=b'x'*6144
        g.before_callback(p);g.before_start(p)
        self.assertEqual(p.frames,[]);self.assertEqual(p.intermediate_time_start,0)
        g.enabled=lambda:True;g.before_callback(p)
        p.frames=[b'speaker-carry'];g.before_start(p)
        self.assertEqual(p.frames,[b'speaker-carry'])

    def test_only_supported_callback_registry_is_used(self):
        g=CaptureOnsetGuard()
        self.assertFalse(g.install(SimpleNamespace()))
        registry={'before_callback_called_func':[],'before_recording_starts_callback_func':[]}
        self.assertTrue(g.install(SimpleNamespace(MAIN_APP_BEFORE_CALLBACK_FUNC_LISTS=registry)))
        self.assertTrue(g.install(SimpleNamespace(MAIN_APP_BEFORE_CALLBACK_FUNC_LISTS=registry)))
        self.assertEqual(registry['before_callback_called_func'],[g.before_callback])
        self.assertEqual(registry['before_recording_starts_callback_func'],[g.before_start])
