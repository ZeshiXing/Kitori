# Japanese caption bridge: Tiger ASR -> LunaTranslator furigana overlay.
# Version: 0.3.0
import os
from pathlib import Path
import sys
import time
import uuid
import threading

import Plugins


class JapaneseCaptionPlugin(Plugins.Base):
    def init(self):
        if getattr(self,'capture',None):self.on_disable()
        self.shutting_down=False
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(line_buffering=True)
        self.init_plugin_settings({
            'description': {'type': 'label', 'label': 'Japanese captions + furigana',
                            'value': 'Configure mode in config/caption.json; restart to apply.'},
        })
        self.root = Path(os.environ['JP_CAPTION_ROOT'])
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        from caption_bridge import (load_config, LunaDisplay,
                                    StatusFile, CaptionPublisher)
        self.config = load_config(self.root)
        from jcaption.whisper_filter import WhisperPhraseFilter
        from jcaption.local_models import is_whisper
        filter_config = {**self.config, 'whisper_blocklist_enabled':
                         self.config.get('whisper_blocklist_enabled', False) and is_whisper(self.config['local_model'])}
        self.phrase_filter = WhisperPhraseFilter.from_config(filter_config)
        from jcaption.settings import recognition_language
        self.language = recognition_language(self.config)
        self.detected_language = self.language or 'ja'
        self.status = StatusFile(self.root / 'logs/status.json')
        self.display = LunaDisplay(self.config['luna_url'])
        self.local_engine = None
        self.session_id = os.environ.get('JP_CAPTION_SESSION', uuid.uuid4().hex)
        self.utterance_id, self.revision = 0, 0
        self.local_final_cache = None
        self.recognition_final = False
        self.model_lock = threading.RLock()
        self.live_waiting = threading.Event()
        self.publisher = (CaptionPublisher(os.environ['JP_CAPTION_URL'], os.environ['JP_CAPTION_TOKEN'])
                          if os.environ.get('JP_CAPTION_URL') else None)
        self.capture = None
        if os.environ.get('JP_CAPTION_CONTINUOUS') == '1':
            from jcaption.continuous_capture import ContinuousCapture
            self.ensure_local_engine()
            def ready():
                self.status(stage='listening',backend='local',mode='local',streaming=True,
                            capture_pipeline='continuous')
                print('JP_CAPTION_CAPTURE_READY',flush=True)
            self.capture=ContinuousCapture(self.root,self.config,self.consume_continuous,self.status,ready)
            self.capture.start()
            if self.publisher:threading.Thread(target=self.lookahead_worker,daemon=True).start()
            return
        from jcaption.capture_onset import CaptureOnsetGuard
        import audio_processing_recording
        if not hasattr(self,'capture_guard'):
            self.capture_guard = CaptureOnsetGuard(enabled=lambda:self.is_enabled(False))
        self.capture_guard.interval = self.config.get('local_stream_chunk_seconds',.5)
        capture_guard_installed = self.capture_guard.install(audio_processing_recording)
        # Query the host's bundled audio SDK; never substitute the microphone.
        import pyaudiowpatch as pyaudio
        import json
        with pyaudio.PyAudio() as audio:
            loopback = audio.get_default_wasapi_loopback()
        (self.root / 'logs/audio-device.json').write_text(
            json.dumps(loopback, ensure_ascii=True, indent=2), encoding='utf-8')
        self.status(stage='plugin_ready', mode=self.config['mode'], backend='loading',
                    capture_guard_installed=capture_guard_installed,
                    language=self.config['language'], streaming=True)
        # The real upstream plugin-host check should not initialize GPU models.
        if not os.environ.get('WT_PLUGIN_HOST'):
            self.ensure_local_engine()
            if self.publisher:
                threading.Thread(target=self.lookahead_worker, daemon=True).start()

    def ensure_local_engine(self):
        if self.local_engine is None:
            from jcaption.local_asr import create_local_engine
            from jcaption.local_models import backend_for, EXTRA_MODELS
            name = self.config['local_model']
            self.status(stage='loading_local_model', local_model=name)
            try:
                self.local_engine = create_local_engine(self.root, self.config)
            except Exception:
                self.status(stage='local_error', backend='none', local_error='本地模型加载失败，请检查模型与运行环境')
                raise
            self.status(local_model=name, local_backend=backend_for(name),
                        local_streaming=EXTRA_MODELS.get(name, {}).get('streaming', 'windowed'),
                        lookahead_supported=backend_for(name) == 'whisper')

    def consume_continuous(self, uid, pcm, final):
        if not self.is_enabled(False) or self.shutting_down:return
        if self.utterance_id!=uid:self.utterance_id,self.revision=uid,0
        from jcaption.local_models import backend_for
        # Preserve the existing host's loudness normalization for offline
        # engines; stateful Voxtral must receive unchanged growing PCM.
        if backend_for(self.config['local_model'])!='voxtral_realtime' and len(pcm)>=12800:
            import audio_tools
            import numpy as np
            if self._settings.GetOption('normalize_enabled'):
                values=audio_tools.convert_audio_datatype_to_float(np.frombuffer(pcm,dtype='<i2'))
                values,_=audio_tools.normalize_audio_lufs(values,16000,
                    self._settings.GetOption('normalize_lower_threshold'),self._settings.GetOption('normalize_upper_threshold'),
                    self._settings.GetOption('normalize_gain_factor'),verbose=False)
                pcm=audio_tools.convert_audio_datatype_to_integer(values,np.int16).tobytes()
        from caption_bridge import make_wav
        self.status(capture_onset=self.capture.metrics())
        result=self.stt_processing(make_wav(pcm,16000),16000,final)
        if result:self.emit_caption(result['text'],result,final)

    def on_disable(self):
        self.shutting_down=True
        if getattr(self,'capture',None):self.capture.close()
        if getattr(self,'local_engine',None):
            with self.model_lock:self.local_engine.close()

    def transcribe_local(self, pcm, sample_rate):
        cached = getattr(self, 'local_final_cache', None)
        if self.recognition_final and cached and cached[0] == pcm:
            return cached[1]
        self.ensure_local_engine()
        self.live_waiting.set()
        with self.model_lock:
            self.live_waiting.clear()
            try:
                if hasattr(self.local_engine, 'set_utterance'):
                    self.local_engine.set_utterance((self.session_id, self.utterance_id))
                text = self.local_engine.transcribe(pcm, sample_rate, self.recognition_final)
                self.detected_language = self.local_engine.last_language
                if hasattr(self.local_engine, 'inference_stats'):
                    self.status(local_inference=self.local_engine.inference_stats())
                if self.recognition_final:
                    self.local_final_cache = (pcm, text)
                return text
            except Exception:
                self.status(stage='local_error', local_error='本地识别失败，请检查推理设备或重新启动字幕')
                return ''

    def lookahead_worker(self):
        # Other adapters keep live streaming immediately. They do not fabricate
        # word timestamps or hold a live model session for optional lookahead.
        from jcaption.local_models import backend_for
        if backend_for(self.config['local_model']) != 'whisper':
            return
        import base64
        import numpy as np
        import requests
        session = requests.Session()
        session.trust_env = False
        headers = {'X-Caption-Token': os.environ['JP_CAPTION_TOKEN']}
        url = os.environ['JP_CAPTION_URL']
        while self.is_enabled(False) and not self.shutting_down:
            time.sleep(0.2)
            if self.live_waiting.is_set():
                continue
            try:
                job = session.get(url + '/api/lookahead/job', headers=headers, timeout=(0.2, 1)).json()
                if not job:
                    continue
                pcm = base64.b64decode(job['pcm'], validate=True)
                audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
                # Short jobs bound the time a live update can wait for the GPU.
                with self.model_lock:
                    decoding = ({} if self.config.get('whisper_standard_decode', False) else
                                {'condition_on_previous_text':False, 'temperature':0})
                    segments, info = self.local_engine.model.transcribe(
                        audio, language=self.language, task='transcribe',
                        beam_size=max(3,self.config.get('whisper_draft_beam',1)), vad_filter=False,
                        word_timestamps=True, **decoding)
                    rows = []
                    for segment in segments:
                        if not segment.words:
                            text = self.phrase_filter.apply(segment.text)
                            if text:
                                rows.append({'text': text, 'start': segment.start, 'end': segment.end})
                            continue
                        phrase, begin, end = '', None, None
                        for word in self.phrase_filter.words(segment.words):
                            begin = word['start'] if begin is None else begin
                            phrase += word['word']
                            end = word['end']
                            if len(phrase) >= 26 or phrase.rstrip().endswith(('。', '！', '？', '!', '?')):
                                rows.append({'text': phrase, 'start': begin, 'end': end})
                                phrase, begin = '', None
                        if phrase:
                            rows.append({'text': phrase, 'start': begin, 'end': end})
                session.post(url + '/api/lookahead/result', headers=headers,
                             json={'generation': job['generation'], 'job_id': job['job_id'], 'segments': rows,
                                   'language': info.language},
                             timeout=(0.2, 1)).raise_for_status()
            except Exception:
                # Live recognition remains usable when optional lookahead fails.
                continue

    def stt_processing(self, audio_data, sample_rate, final_audio):
        if not self.is_enabled(False):
            return None
        if not isinstance(audio_data, bytes):
            audio_data = bytes(audio_data)
        from caption_bridge import tiger_wav_to_pcm
        pcm = tiger_wav_to_pcm(audio_data, sample_rate)
        if hasattr(self,'capture_guard'):
            self.status(capture_onset=self.capture_guard.metrics())
        self.recognition_final = final_audio
        self.local_final_cache = None
        started = time.perf_counter()
        text = self.transcribe_local(pcm, sample_rate)
        elapsed = time.perf_counter() - started
        self.revision += 1
        result = {'text': text, 'type': 'transcript', 'language': self.detected_language,
                  'streaming': True, 'stream_id': f'{self.session_id}:{self.utterance_id}',
                  'stream_revision': self.revision, 'final': bool(final_audio),
                  'caption_session': self.session_id, 'caption_utterance': self.utterance_id,
                  'caption_revision': self.revision, 'asr_seconds': elapsed,
                  'audio_seconds': len(pcm) / (sample_rate * 2),
                  'caption_backend': 'local'}
        if final_audio:
            self.utterance_id += 1
            self.revision = 0
        if not text and not final_audio:
            return None
        return result

    def stt(self, text, result_obj):
        self.emit_caption(text, result_obj, True)

    def stt_intermediate(self, text, result_obj):
        self.emit_caption(text, result_obj, False)

    def emit_caption(self, text, result_obj, final):
        if not self.is_enabled(False) or getattr(self,'shutting_down',False):
            return
        try:
            if result_obj.get('caption_backend', 'local') == 'local':
                text = self.phrase_filter.apply(text)
            if self.publisher:
                self.publisher.publish({
                    'session_id': result_obj['caption_session'],
                    'utterance_id': result_obj['caption_utterance'],
                    'revision': result_obj['caption_revision'], 'final': final,
                    'text': text, 'backend': result_obj['caption_backend'],
                    'language': result_obj.get('language', self.detected_language),
                    'asr_seconds': result_obj['asr_seconds'], 'audio_seconds': result_obj['audio_seconds']})
            else:
                # Supported plugin-host diagnostic / optional legacy output.
                self.display.show(text)
            self.status(stage='caption_displayed', backend=result_obj.get('caption_backend', 'local'),
                caption_characters=len(text), last_caption_at=time.time(),
                caption_phase='final' if final else 'draft',
                utterance_id=result_obj.get('caption_utterance'),
                revision=result_obj.get('caption_revision'))
        except Exception as error:
            self.status(stage='display_error', error_type=type(error).__name__)
