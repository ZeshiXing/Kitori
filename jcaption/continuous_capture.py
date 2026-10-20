"""Continuous audio spans, with upstream Silero deciding only start/end.

WASAPI, resampling, loudness normalization and VAD inference remain in upstream
libraries. This module owns bounded buffering and latest-draft scheduling.
"""
from collections import deque
import threading
import time


class AudioMailbox:
    def __init__(self, capacity=8):
        self.items=deque();self.condition=threading.Condition();self.closed=False
        self.capacity=capacity;self.coalesced=0

    def put(self, uid, pcm, final):
        with self.condition:
            if self.closed:return
            if self.items and self.items[-1][0]==uid and not self.items[-1][2]:
                self.items[-1]=(uid,pcm,final);self.coalesced+=1
            else:
                if len(self.items)>=self.capacity:
                    raise OverflowError('ASR cannot keep up with completed utterances')
                self.items.append((uid,pcm,final))
            self.condition.notify()

    def get(self):
        with self.condition:
            self.condition.wait_for(lambda:self.items or self.closed)
            return self.items.popleft() if self.items else None

    def close(self):
        with self.condition:
            self.closed=True;self.items.clear();self.condition.notify_all()


class ContinuousSpans:
    """512-sample frames and official VAD events -> complete growing PCM spans."""
    def __init__(self, submit, interval=.75, first=.18, preroll=.6, limit=15):
        self.submit=submit;self.interval=interval;self.first=first
        self.preroll_bytes=int(preroll*32000);self.limit_bytes=int(limit*32000)
        self.ring=deque();self.ring_size=0;self.frames=[];self.size=0
        self.uid=0;self.active=False;self.since_start=0.;self.since_draft=0.;self.sent=False
        self.onsets=0;self.frames_kept=0;self.idle_frames=0

    def feed(self, pcm, event=None, continuing=False):
        if len(pcm)!=1024:raise ValueError('Silero capture requires 512 PCM16 samples')
        starting=bool(event and 'start' in event)
        if not self.active and (starting or continuing):
            self.frames=list(self.ring) if starting else []
            self.size=sum(map(len,self.frames));self.active=True
            self.since_start=self.since_draft=0.;self.sent=False;self.onsets+=1
        if self.active:
            # Keep every frame, including weak phonemes and intra-sentence gaps.
            self.frames.append(pcm);self.size+=len(pcm);self.frames_kept+=1
            self.since_start+=.032;self.since_draft+=.032
            final=bool(event and 'end' in event) or self.size>=self.limit_bytes
            hop=min(self.interval,.35) if self.since_start<1.6 else self.interval
            due=self.since_start>=self.first if not self.sent else self.since_draft>=hop
            if final or due:
                self.submit(self.uid,b''.join(self.frames),final)
                self.since_draft=0.;self.sent=True
            if final:
                self.uid+=1;self.frames=[];self.size=0;self.active=False
        else:self.idle_frames+=1
        self.ring.append(pcm);self.ring_size+=len(pcm)
        while self.ring_size>self.preroll_bytes and self.ring:
            self.ring_size-=len(self.ring.popleft())


class ContinuousCapture:
    def __init__(self, root, config, consume, status, ready):
        self.root,self.config,self.consume,self.status,self.ready=root,config,consume,status,ready
        self.stop_event=threading.Event();self.mailbox=AudioMailbox()
        self.spans=ContinuousSpans(self.mailbox.put,interval=config.get('local_stream_chunk_seconds',.75),
                                   limit=config.get('stream_window_seconds',15))
        self.reader=threading.Thread(target=self.read,daemon=True)
        self.worker=threading.Thread(target=self.infer,daemon=True)

    def start(self):
        self.worker.start();self.reader.start()

    def metrics(self):
        return {'pipeline':'continuous','onsets':self.spans.onsets,'frames_kept':self.spans.frames_kept,
                'idle_frames':self.spans.idle_frames,'coalesced_drafts':self.mailbox.coalesced,
                'first_draft_seconds':self.spans.first,'update_interval':self.spans.interval}

    def infer(self):
        while not self.stop_event.is_set():
            job=self.mailbox.get()
            if job is None:return
            try:self.consume(*job)
            except Exception:
                self.status(stage='local_error',local_error='本地识别失败，请检查模型与运行环境')

    def read(self):
        try:
            import numpy as np
            import pyaudiowpatch as pyaudio
            import audio_tools
            from .speech_boundary import TorchSpeechBoundary
            from .settings import capture_vad_threshold
            boundary=TorchSpeechBoundary(self.root)
            vad=boundary.iterator_class(boundary.model,threshold=capture_vad_threshold(self.config),
                sampling_rate=16000,min_silence_duration_ms=600,speech_pad_ms=120)
            def feed(pcm):
                event=vad(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768)
                self.spans.feed(pcm,event,vad.triggered)
            with pyaudio.PyAudio() as audio:
                device=audio.get_default_wasapi_loopback()
                rate=int(device['defaultSampleRate']);channels=int(device['maxInputChannels'])
                count=int(rate*.032)
                with audio.open(format=pyaudio.paInt16,channels=channels,rate=rate,input=True,
                                input_device_index=device['index'],frames_per_buffer=count) as stream:
                    self.ready()
                    next_idle=time.monotonic()+.064
                    pending=b''
                    while not self.stop_event.is_set():
                        if stream.get_read_available()>=count:
                            raw=stream.read(count,exception_on_overflow=False)
                            pending+=audio_tools.resample_audio(raw,rate,16000,target_channels=1,input_channels=channels).tobytes()
                            while len(pending)>=1024:
                                feed(pending[:1024]);pending=pending[1024:]
                            next_idle=time.monotonic()+.064
                        elif time.monotonic()>=next_idle:
                            # Idle WASAPI endpoints can stop callbacks completely.
                            # Feed real elapsed silence so the final is not held
                            # until the next sound; no audio is invented as speech.
                            feed(bytes(1024));next_idle+=.032
                        else:self.stop_event.wait(.002)
        except Exception as error:
            self.status(stage='source_error',source_note='Continuous audio capture failed: '+type(error).__name__)
            self.stop_event.set();self.mailbox.close()

    def close(self):
        self.stop_event.set();self.mailbox.close()
        for worker in (self.reader,self.worker):
            if worker.is_alive() and worker is not threading.current_thread():worker.join(timeout=4)
