"""Adapters only: faster-whisper, sherpa-onnx worker, and native audio.cpp."""
import atexit
import base64
import http.client
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.parse import urlencode

from .local_models import backend_for, model_directory, runtime_executable, validate_language
from .settings import recognition_language, write_json


class LocalASRError(RuntimeError):
    pass


# The pinned Voxtral port's live EOF does not right-pad/flush its decoder.
# Match its offline delay+buffer padding: (6+1+10)*80 ms, plus one 80 ms grid.
VOXTRAL_FINAL_PADDING = bytes(16000 * 2 * 144 // 100)


def hidden_process():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


class WhisperEngine:
    def __init__(self, root, config):
        from faster_whisper import WhisperModel
        self.language = recognition_language(config)
        self.last_language = self.language or 'ja'
        self.draft_beam = config.get('whisper_draft_beam', 1)
        self.standard_decode = config.get('whisper_standard_decode', False)
        self.final_changes_decode = self.draft_beam < 3
        self.word_timestamps = True
        self.model = WhisperModel(str(model_directory(root, config['local_model'])),
                                  device=config.get('device', 'cuda'),
                                  compute_type=config.get('compute_type', 'float16'), cpu_threads=4,
                                  local_files_only=True)
        import numpy as np
        segments, _ = self.model.transcribe(np.zeros(16000, dtype=np.float32), language=self.language,
                                            beam_size=1, condition_on_previous_text=False)
        list(segments)
        self.speech_boundary = None
        try:
            from .speech_boundary import TorchSpeechBoundary
            self.speech_boundary = TorchSpeechBoundary(root)
            self.speech_boundary(bytes(32000),16000)
            self.word_timestamps = False
        except (ImportError, OSError, RuntimeError):
            pass  # Older portable runtimes retain conservative timestamp cuts.

    def transcribe(self, pcm, rate, final=True):
        return self.decode_window(pcm, rate, final).text

    def decode_window(self, pcm, rate, final=True):
        import numpy as np
        from .rolling_asr import Recognition, Word
        options = {} if self.standard_decode else {'condition_on_previous_text':False, 'temperature':0}
        if self.standard_decode and getattr(self, 'context_prompt', ''):
            options['initial_prompt'] = self.context_prompt
        segments, info = self.model.transcribe(np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768,
                                               language=self.language, task='transcribe',
                                               beam_size=max(3, self.draft_beam) if final else self.draft_beam,
                                               vad_filter=False,
                                               word_timestamps=getattr(self, 'align_current_window', True), **options)
        self.last_language = info.language
        segments = list(segments)
        words = tuple(Word(word.start, word.end, word.word)
                      for segment in segments for word in (getattr(segment, 'words', None) or ()))
        text = ''.join(segment.text for segment in segments).strip()
        # Some no-speech/edge segments have text but no word alignment. Do not
        # discard that text or trim it using the remaining segments' timestamps.
        if ''.join(w.text for w in words).strip() != text:
            words = ()
        return Recognition(text, words)

    def close(self):
        pass


class ReazonEngine:
    """Keep sherpa's native dependencies outside Tiger's signed frozen runtime."""
    def __init__(self, root, config):
        import queue
        self.last_language = 'ja'
        self.process = subprocess.Popen(
            [str(Path(root) / '.venv/Scripts/python.exe'), str(Path(root) / 'scripts/reazon_worker.py'),
             '--model-dir', str(model_directory(root, config['local_model']))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1, **hidden_process())
        self.replies = queue.Queue()
        def read():
            for line in self.process.stdout:
                try:
                    self.replies.put(json.loads(line))
                except ValueError:
                    continue
            self.replies.put({'error':'worker_exited'})
        threading.Thread(target=read, daemon=True).start()
        atexit.register(self.close)
        if self.receive(45).get('ready') is not True:
            self.close()
            raise LocalASRError('ReazonSpeech 加载失败')

    def receive(self, timeout):
        import queue
        try:
            result = self.replies.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise LocalASRError('ReazonSpeech 响应超时') from None
        if result.get('error'):
            self.close()
            raise LocalASRError('ReazonSpeech 运行失败，请重新准备运行环境')
        return result

    def transcribe(self, pcm, rate, final=True):
        if rate != 16000:
            raise LocalASRError('本地模型需要 16 kHz 音频')
        if len(pcm) < 3840:
            return ''  # Sub-120 ms VAD fragments cannot safely form model features.
        self.process.stdin.write(json.dumps({'pcm':base64.b64encode(pcm).decode('ascii')}) + '\n')
        self.process.stdin.flush()
        return self.receive(10)['text']

    def close(self):
        stop_process(self.process)

    def decode_window(self, pcm, rate, final=True):
        from .rolling_asr import Recognition
        return Recognition(self.transcribe(pcm, rate, final))


class LivePCMStream:
    """Full duplex HTTP/1.1: send raw chunks while a separate reader consumes SSE.

    requests' ordinary upload path is intentionally not used here: it sends the
    request body before reading response events, defeating capture-time output.
    """
    def __init__(self, host, port, model, language=None):
        self.text, self.error, self.final_received = '', None, False
        self.done, self.changed = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.connection = http.client.HTTPConnection(host, port, timeout=15)
        query = {'model':model, 'sample_rate':16000, 'channels':1, 'sample_format':'s16le'}
        if language:
            query['language'] = language
        self.connection.putrequest('POST', '/v1/audio/transcriptions/live?' + urlencode(query))
        self.connection.putheader('Content-Type', 'application/octet-stream')
        self.connection.putheader('Transfer-Encoding', 'chunked')
        self.connection.endheaders()
        # Keep the sending socket even if HTTPResponse detaches a close-marked connection.
        self.socket = self.connection.sock
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        response = None
        try:
            response = self.connection.getresponse()
            if response.status != 200:
                raise LocalASRError('本地流式接口拒绝请求（HTTP %d）' % response.status)
            while True:
                line = response.readline(1024 * 1024)
                if not line:
                    break
                if not line.startswith(b'data:'):
                    continue
                data = line[5:].strip()
                if data == b'[DONE]':
                    break
                event = json.loads(data)
                kind = event.get('type')
                with self.lock:
                    if kind == 'transcript.text.delta':
                        self.text += event.get('delta', '')
                    elif kind == 'transcript.text.partial':
                        self.text = event['text']
                    elif kind == 'transcript.text.done':
                        self.text = event['text']
                        self.final_received = True
                    elif kind == 'error' or 'error' in event:
                        raise LocalASRError('本地流式模型返回错误')
                    if len(self.text) > 8000:
                        raise LocalASRError('本地流式结果超过限制')
                self.changed.set()
            if not self.final_received:
                raise LocalASRError('本地音频流中断，未收到确认结果')
        except Exception as error:
            # Never include backend response bodies or captured speech in logs.
            self.error = error if isinstance(error, LocalASRError) else LocalASRError('本地音频流连接失败')
        finally:
            if response is not None:
                response.close()
            self.done.set()
            self.changed.set()

    def send(self, pcm):
        if self.error:
            raise self.error
        # Bound individual transport frames; no on-disk audio or extra collection delay.
        for offset in range(0, len(pcm), 16000):
            block = pcm[offset:offset + 16000]
            self.socket.sendall(('%x\r\n' % len(block)).encode('ascii') + block + b'\r\n')

    def snapshot(self):
        if self.error:
            raise self.error
        with self.lock:
            return self.text.strip()

    def finish(self, timeout=5):
        self.socket.sendall(b'0\r\n\r\n')
        if not self.done.wait(timeout):
            self.abort()
            raise LocalASRError('本地流式识别跟不上音频，请选择更小模型或更快设备')
        result = self.snapshot()
        self.connection.close()
        return result

    def abort(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()
        self.thread.join(timeout=1)


class AudioCppEngine:
    def __init__(self, root, config):
        import requests
        self.root, self.config = Path(root), config
        self.language = recognition_language(config)
        self.last_language = self.language or 'ja'
        self.stream, self.previous_pcm = None, b''
        self.utterance_key = None
        self.client = requests.Session()
        self.client.trust_env = False
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.base_url = f'http://127.0.0.1:{self.port}'
        family = backend_for(config['local_model'])
        self.family = family
        executable = runtime_executable(root, config.get('local_native_backend', 'vulkan'))
        selected_backend = config.get('local_native_backend', 'vulkan')
        device = config.get('local_native_device', -1)
        if device == -1:
            devices = subprocess.run([str(executable), '--backend', selected_backend, '--list-devices'],
                                     capture_output=True, text=True, encoding='utf-8', errors='replace',
                                     timeout=15, **hidden_process())
            # Prefer a discrete GPU on hybrid laptops; API ordering often lists
            # the integrated Intel device first. Explicit indices remain available.
            candidates = re.findall(r'^' + re.escape(selected_backend) + r':(\d+) .*\[GPU\]',
                                    devices.stdout, re.MULTILINE | re.IGNORECASE)
            device = int(candidates[0]) if candidates else 0
        self.device_index = device
        model_path = next(model_directory(root, config['local_model']).glob('*.gguf'))
        options = {} if family == 'qwen3_asr' else {'voxtral_realtime.stream_batch_tokens':4}
        profile = {'host':'127.0.0.1', 'port':self.port,
                   'backend':selected_backend, 'device':device, 'threads':4,
                   'lazy_load':False, 'max_loaded_models':1, 'busy_timeout_ms':5000,
                   'log_request_body':False,
                   'models':[{'id':'caption-local', 'family':family, 'path':str(model_path),
                              'task':'asr', 'mode':'offline' if family == 'qwen3_asr' else 'streaming', 'session_options':options,
                              'default_request_options':({'audio_chunk_seconds':30}
                                                         if family == 'qwen3_asr' else {})}]}
        profile_path = self.root / 'logs/local-asr-server.json'
        write_json(profile_path, profile)
        with (self.root / 'logs/local-asr.stderr.log').open('w', encoding='utf-8') as errors:
            self.process = subprocess.Popen(
                [str(executable),
                 '--config', str(profile_path), '--no-ui'],
                stdout=subprocess.DEVNULL, stderr=errors, **hidden_process())
        atexit.register(self.close)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise LocalASRError('audio.cpp 启动失败，请检查运行环境或切换推理设备')
            try:
                response = self.client.get(self.base_url + '/health', timeout=.5)
                if response.ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(.1)
        self.close()
        raise LocalASRError('本地模型加载超时')

    def transcribe(self, pcm, rate, final=True):
        if rate != 16000 or len(pcm) % 2:
            raise LocalASRError('本地流式模型需要 16 kHz 单声道 PCM')
        if self.family == 'qwen3_asr':
            # This pinned native port buffers its live Qwen result until EOF.
            # Re-decode a growing window instead of pretending it is incremental,
            # or cutting Japanese into independent half-second recognitions.
            from caption_bridge import make_wav
            fields = {'model':'caption-local'}
            if self.language:
                fields['language'] = self.language
            try:
                with self.client.post(self.base_url + '/v1/audio/transcriptions', data=fields,
                                      files={'file':('window.wav', make_wav(pcm, rate), 'audio/wav')},
                                      timeout=(1, 5)) as response:
                    response.raise_for_status()
                    result = response.json()
                if not isinstance(result.get('text'), str):
                    raise LocalASRError('本地模型返回无效结果')
                return result['text'].strip()
            except Exception:
                raise LocalASRError('Qwen 本地识别失败或跟不上音频，请选择更小模型或更快设备') from None
        # Tiger supplies cumulative buffers. Feed only new samples, never replay
        # the preceding hypothesis' audio into a stateful model.
        # Independent resampling of growing prefixes can change the last few
        # filter taps. Ignore only that tiny boundary, not changes in the body.
        stable = self.previous_pcm[:-256] if len(self.previous_pcm) > 256 else self.previous_pcm
        if self.stream and (len(pcm) < len(self.previous_pcm) or
                            getattr(self, 'utterance_key', None) is None and not pcm.startswith(stable)):
            self.stream.abort()
            self.stream, self.previous_pcm = None, b''
        if self.stream is None:
            self.stream = LivePCMStream('127.0.0.1', self.port, 'caption-local', self.language)
        try:
            self.stream.send(pcm[len(self.previous_pcm):])
            self.previous_pcm = pcm
            if final:
                # Supply right context now; do not wait for another 1.44 seconds
                # of actual sound. Otherwise short utterances and tail words vanish.
                self.stream.send(VOXTRAL_FINAL_PADDING)
                return self.stream.finish()
            return self.stream.snapshot()
        except Exception:
            self.stream.abort()
            self.stream, self.previous_pcm = None, b''
            raise
        finally:
            if final:
                self.stream, self.previous_pcm = None, b''

    def set_utterance(self, key):
        # Capture-host resampling uses a length-rounded grid: even the *body*
        # of a growing PCM prefix can differ by a few int16 units. The host's
        # utterance identity is authoritative; byte equality is only a fallback
        # for callers that cannot supply one.
        if key != self.utterance_key:
            if self.stream:
                self.stream.abort()
            self.stream, self.previous_pcm = None, b''
            self.utterance_key = key

    def decode_window(self, pcm, rate, final=True):
        from .rolling_asr import Recognition
        return Recognition(self.transcribe(pcm, rate, final))

    def close(self):
        if self.stream:
            self.stream.abort()
            self.stream = None
        stop_process(self.process)
        self.client.close()


def create_local_engine(root, config):
    validate_language(config['local_model'], config.get('language', 'auto'))
    kind = backend_for(config['local_model'])
    cls = WhisperEngine if kind == 'whisper' else ReazonEngine if kind == 'reazon' else AudioCppEngine
    engine = cls(root, config)
    if kind != 'voxtral_realtime':
        if kind != 'whisper':
            try:
                from .speech_boundary import SherpaSpeechBoundary
                engine.speech_boundary = SherpaSpeechBoundary(root)
            except (ImportError, OSError, RuntimeError):
                pass
        from .rolling_asr import WindowedEngine
        return WindowedEngine(engine)
    return engine
