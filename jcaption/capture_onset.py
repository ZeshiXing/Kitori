"""Protect onset audio through Tiger's supported recording callback registry.

Keep raw pre-trigger frames in their original rate/channels. Inference and
codecs stay in the upstream host; no monkeypatch or signed-file modification.
"""
from collections import deque
import threading
import time
from weakref import WeakKeyDictionary


class CaptureOnsetGuard:
    def __init__(self, interval=.75, preroll=.6, first_draft=.18,
                 clock=time.time, enabled=lambda:True):
        self.interval, self.preroll, self.first_draft = interval, preroll, first_draft
        self.clock, self.enabled = clock, enabled
        self.states = WeakKeyDictionary()
        self.active = WeakKeyDictionary()
        self.lock = threading.RLock()
        self.onsets, self.last_preroll_seconds = 0, 0.0
        self.empty_segment_rearms = 0

    def install(self, recording):
        registry = getattr(recording,'MAIN_APP_BEFORE_CALLBACK_FUNC_LISTS',{})
        names = ('before_callback_called_func','before_recording_starts_callback_func')
        if not all(isinstance(registry.get(name),list) for name in names):
            return False
        if self.before_callback not in registry[names[0]]:
            registry[names[0]].append(self.before_callback)
        if self.before_start not in registry[names[1]]:
            registry[names[1]].append(self.before_start)
        return True

    @staticmethod
    def byte_rate(processor):
        rate = processor.recorded_sample_rate or processor.default_sample_rate
        channels = processor.input_channel_num or 1
        return int(rate)*int(channels)*2

    def before_callback(self, processor):
        if not self.enabled():
            with self.lock:
                self.states.pop(processor,None)
                self.active.pop(processor,None)

            return
        with self.lock:
            # The host flushes frames after a VAD pause, but background music
            # can keep its energy-based recording flag set. An empty segment
            # needs a new onset, even when that old flag did not turn off.
            if processor.start_rec_on_volume_threshold and not processor.frames:
                processor.start_rec_on_volume_threshold = False
                self.empty_segment_rearms += 1
            if processor.start_rec_on_volume_threshold:
                self.states.pop(processor,None)
                active = self.active.get(processor)
                if active and self.clock()-active[0]<1.6:
                    stamp = processor.intermediate_time_start
                    if stamp>active[1]:
                        # After the first draft, briefly refresh the small tail
                        # faster so the opening phrase need not wait a full hop.
                        stamp -= max(0,self.interval-min(self.interval,.35))
                        processor.intermediate_time_start = stamp
                        active[1] = stamp
                else:
                    self.active.pop(processor,None)
                return
            self.active.pop(processor,None)
            chunks,size = self.states.setdefault(processor,[deque(),0])
            previous = processor.previous_audio_chunk
            if previous:
                chunks.append(bytes(previous))
                size += len(previous)
            limit = int(self.byte_rate(processor)*self.preroll)
            # Whole source frames are retained; do not cut a stereo sample.
            while size>limit and chunks:
                size -= len(chunks.popleft())
            self.states[processor][1] = size
            # Idle time is not speech time. Prevent the old idle timer from
            # immediately submitting a 32 ms onset to the decoder.
            first = min(self.interval,self.first_draft)
            processor.intermediate_time_start = self.clock()-max(0,self.interval-first)

    def before_start(self, processor):
        if not self.enabled():
            return
        with self.lock:
            chunks,size = self.states.pop(processor,[(),0])
            if processor.frames:
                return  # A host-owned speaker-split carry must remain intact.
            # A flush and the next speech frame may happen in the same host
            # callback, before before_callback can observe the empty segment.
            first = min(self.interval,self.first_draft)
            processor.intermediate_time_start = self.clock()-max(0,self.interval-first)
            self.active[processor] = [self.clock(),processor.intermediate_time_start]
            processor.frames.extend(chunks)
            if chunks:
                processor.previous_audio_chunk = None  # Already in our ring.
            self.onsets += 1
            self.last_preroll_seconds = size/self.byte_rate(processor)

    def metrics(self):
        with self.lock:
            return {'onsets':self.onsets,'last_preroll_seconds':round(self.last_preroll_seconds,4),
                    'empty_segment_rearms':self.empty_segment_rearms,
                    'first_draft_seconds':min(self.interval,self.first_draft)}
