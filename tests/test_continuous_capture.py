"""Continuous sample preservation and bounded ASR scheduling contracts."""
import threading
import unittest
from jcaption.continuous_capture import ContinuousSpans, AudioMailbox


class ContinuousCaptureTests(unittest.TestCase):
    def test_all_interior_low_confidence_frames_survive_and_preroll_is_once(self):
        jobs=[];spans=ContinuousSpans(lambda *job:jobs.append(job))
        lead=[bytes([i])*1024 for i in range(25)]
        for frame in lead:spans.feed(frame)
        voice=[b'v'*1024,bytes(1024),b'q'*1024,bytes(1024),b'w'*1024]
        for i,frame in enumerate(voice):spans.feed(frame,{'start':0} if i==0 else None,True)
        spans.feed(bytes(1024),{'end':1})
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0],(0,b''.join(lead[-18:]+voice+[bytes(1024)]),True))

    def test_draft_deadline_is_audio_time_and_idle_never_generates_subtitles(self):
        jobs=[];spans=ContinuousSpans(lambda *job:jobs.append(job))
        for _ in range(2000):spans.feed(bytes(1024))
        self.assertEqual(jobs,[])
        for i in range(5):spans.feed(b'v'*1024,{'start':0} if i==0 else None,True)
        self.assertEqual(jobs,[])
        spans.feed(b'v'*1024,None,True)
        self.assertEqual(len(jobs),1)
        self.assertFalse(jobs[0][2])
        self.assertAlmostEqual(spans.since_start,.192)

    def test_a_short_reply_final_contains_whole_voice_and_silence_tail(self):
        jobs=[];spans=ContinuousSpans(lambda *job:jobs.append(job))
        voice=[b'a'*1024,b'b'*1024,b'c'*1024]
        for i,frame in enumerate(voice):spans.feed(frame,{'start':0} if i==0 else None,True)
        for _ in range(18):spans.feed(bytes(1024),None,True)
        spans.feed(bytes(1024),{'end':1},False)
        self.assertTrue(jobs[-1][2])
        self.assertEqual(jobs[-1][1],b''.join(voice)+bytes(19*1024))
        self.assertEqual(jobs[-1][0],0)

    def test_forced_window_split_does_not_replay_previous_audio(self):
        jobs=[];spans=ContinuousSpans(lambda *job:jobs.append(job),preroll=0,limit=.32)
        frames=[bytes([i])*1024 for i in range(25)]
        for i,frame in enumerate(frames):
            spans.feed(frame,{'start':0} if i==0 else ({'end':1} if i==24 else None),i!=24)
        finals=[j for j in jobs if j[2]]
        self.assertEqual([j[0] for j in finals],[0,1,2])
        self.assertEqual(b''.join(j[1] for j in finals),b''.join(frames))

    def test_mailbox_coalesces_obsolete_drafts_but_never_completed_short_replies(self):
        mailbox=AudioMailbox()
        mailbox.put(0,b'a',False);mailbox.put(0,b'ab',False);mailbox.put(0,b'abc',True)
        mailbox.put(1,b'next',False);mailbox.put(1,b'next!',True)
        self.assertEqual(mailbox.get(),(0,b'abc',True))
        self.assertEqual(mailbox.get(),(1,b'next!',True))
        self.assertEqual(mailbox.coalesced,3)
        mailbox.close();self.assertIsNone(mailbox.get())

    def test_backpressure_and_shutdown_are_explicit_and_bounded(self):
        mailbox=AudioMailbox(capacity=2)
        mailbox.put(0,b'a',True);mailbox.put(1,b'b',True)
        with self.assertRaises(OverflowError):mailbox.put(2,b'c',True)
        self.assertEqual(mailbox.get(),(0,b'a',True))
        self.assertEqual(mailbox.get(),(1,b'b',True))
        done=threading.Event()
        worker=threading.Thread(target=lambda:(mailbox.get(),done.set()))
        worker.start();mailbox.close()
        self.assertTrue(done.wait(1));worker.join(1)
