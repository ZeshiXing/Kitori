"""Native transport must deliver before EOF and must not replay growing buffers."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from jcaption.local_asr import AudioCppEngine, LivePCMStream, LocalASRError
from jcaption.local_models import (EXTRA_MODELS, MODELS, is_whisper, model_directory,
                                   validate_language, model_ready)
from jcaption.settings import write_json


class LocalModelsTests(unittest.TestCase):
    def server(self, incomplete=False):
        bodies = []
        first = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def do_POST(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                body = b''
                try:
                    while True:
                        size = int(self.rfile.readline().strip(), 16)
                        if not size:
                            self.rfile.readline()
                            break
                        block = self.rfile.read(size)
                        self.rfile.read(2)
                        body += block
                        if len(body) == len(block):
                            self.wfile.write(b'data: {"type":"transcript.text.delta","delta":"early"}\n\n')
                            self.wfile.flush()
                            first.set()
                    bodies.append(body)
                    if not incomplete:
                        self.wfile.write(b'data: {"type":"transcript.text.done","text":"complete"}\n\ndata: [DONE]\n\n')
                        self.wfile.flush()
                except (ConnectionError, ValueError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, bodies, first

    def test_full_duplex_real_http_returns_text_before_audio_finishes(self):
        server, bodies, first = self.server()
        stream = LivePCMStream('127.0.0.1', server.server_port, 'test', 'ja')
        self.addCleanup(stream.abort)
        stream.send(b'\x01\x00' * 8000)
        self.assertTrue(first.wait(2))
        self.assertTrue(stream.changed.wait(2))
        self.assertFalse(stream.done.is_set(), 'Server/client waited for EOF before text')
        self.assertEqual(stream.snapshot(), 'early')
        stream.send(b'\x02\x00' * 8000)
        self.assertEqual(stream.finish(), 'complete')
        self.assertEqual(bodies, [b'\x01\x00' * 8000 + b'\x02\x00' * 8000])

    def test_incomplete_stream_is_never_published_as_a_final(self):
        server, _, _ = self.server(incomplete=True)
        stream = LivePCMStream('127.0.0.1', server.server_port, 'test')
        self.addCleanup(stream.abort)
        stream.send(b'\x01\x00' * 1000)
        with self.assertRaises(LocalASRError):
            stream.finish()

    def engine(self, port):
        engine = AudioCppEngine.__new__(AudioCppEngine)
        engine.port, engine.language = port, 'ja'
        engine.family = 'voxtral_realtime'
        engine.stream, engine.previous_pcm = None, b''
        engine.utterance_key = None
        return engine

    def test_growing_snapshots_send_each_sample_once_and_next_utterance_resets(self):
        server, bodies, _ = self.server()
        engine = self.engine(server.server_port)
        a, b = b'\x01\x00' * 8000, b'\x02\x00' * 8000
        engine.transcribe(a, 16000, False)
        engine.transcribe(a, 16000, False)
        self.assertEqual(engine.transcribe(a + b, 16000, True), 'complete')
        self.assertEqual(engine.transcribe(b, 16000, True), 'complete')
        from jcaption.local_asr import VOXTRAL_FINAL_PADDING
        self.assertEqual(bodies, [a + b + VOXTRAL_FINAL_PADDING, b + VOXTRAL_FINAL_PADDING])

    def test_resampler_tail_changes_do_not_replay_old_audio(self):
        server, bodies, _ = self.server()
        engine = self.engine(server.server_port)
        a = b'\x01\x00' * 8000
        engine.transcribe(a, 16000, False)
        changed = a[:-128] + b'\x03\x00' * 64 + b'\x02\x00' * 8000
        engine.transcribe(changed, 16000, True)
        from jcaption.local_asr import VOXTRAL_FINAL_PADDING
        self.assertEqual(bodies, [a + b'\x02\x00' * 8000 + VOXTRAL_FINAL_PADDING])

    def test_stream_final_timeout_is_bounded(self):
        stream = LivePCMStream.__new__(LivePCMStream)
        stream.socket, stream.done, stream.abort = Mock(), threading.Event(), Mock()
        with self.assertRaises(LocalASRError):
            stream.finish(timeout=.01)
        stream.abort.assert_called_once()

    def test_reazon_short_capture_blip_does_not_reach_native_worker(self):
        from jcaption.local_asr import ReazonEngine
        engine=ReazonEngine.__new__(ReazonEngine)
        engine.process=Mock()
        self.assertEqual(engine.transcribe(bytes(1024),16000,True),'')
        engine.process.stdin.write.assert_not_called()

    def test_whisper_standard_profile_uses_upstream_decode_defaults(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from jcaption.local_asr import WhisperEngine
        model=Mock()
        model.transcribe.side_effect=lambda *a,**kw: ([], SimpleNamespace(language='ja'))
        factory=Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper':SimpleNamespace(WhisperModel=factory)}):
            engine=WhisperEngine('.',{'local_model':'large-v3','language':'ja','whisper_draft_beam':3,
                                     'whisper_standard_decode':True})
            engine.transcribe(bytes(16000),16000,False)
        kwargs=model.transcribe.call_args.kwargs
        self.assertEqual(kwargs['beam_size'],3)
        self.assertNotIn('temperature',kwargs)
        self.assertNotIn('condition_on_previous_text',kwargs)

    def test_capture_identity_tolerates_resampling_grid_changes_and_rejects_old_session(self):
        server, bodies, _ = self.server()
        engine = self.engine(server.server_port)
        a = b'\x01\x00' * 8000
        engine.set_utterance(('session-a', 1))
        engine.transcribe(a, 16000, False)
        # Resampling grid rounding changes samples throughout the old prefix.
        engine.transcribe(b'\x02\x00' * 16000, 16000, True)
        from jcaption.local_asr import VOXTRAL_FINAL_PADDING
        self.assertEqual(bodies, [a + b'\x02\x00' * 8000 + VOXTRAL_FINAL_PADDING])
        engine.set_utterance(('session-b', 0))
        engine.transcribe(b'\x03\x00' * 8000, 16000, True)
        self.assertEqual(bodies[-1], b'\x03\x00' * 8000 + VOXTRAL_FINAL_PADDING)

    def test_family_language_and_whisper_filter_scope(self):
        self.assertEqual(len(EXTRA_MODELS), 5)
        self.assertTrue(is_whisper('kotoba-v2'))
        self.assertTrue(is_whisper('large-v3-turbo'))
        for name in EXTRA_MODELS:
            validate_language(name, 'ja')
            validate_language(name, 'auto')
            self.assertEqual(is_whisper(name), name == 'kotoba-v2')
        for name in ('kotoba-v2', 'reazonspeech-k2'):
            with self.assertRaises(ValueError): validate_language(name, 'en')
        with self.assertRaises(ValueError): model_directory('.', '../escape')

    def test_incomplete_external_assets_and_missing_runtime_are_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'qwen3-asr-0.6b'
            self.assertFalse(model_ready(root, name))
            target = model_directory(root, name)
            target.mkdir(parents=True)
            entry = EXTRA_MODELS[name]
            write_json(target / 'installed.json', {key: f['sha256'] for key, f in entry['files'].items()})
            self.assertFalse(model_ready(root, name))


if __name__ == '__main__':
    unittest.main()
