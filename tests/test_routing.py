"""Local audio and display routing boundaries."""
import unittest
from unittest.mock import Mock
from caption_bridge import LunaDisplay, make_wav, tiger_wav_to_pcm

class RoutingTests(unittest.TestCase):
    def test_draft_and_final_use_local_engine_and_advance_utterance_identity(self):
        import importlib.util
        import sys
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        source = Path(__file__).resolve().parents[1] / 'plugins/japanese_caption.py'
        with patch.dict(sys.modules, {'Plugins':SimpleNamespace(Base=object)}):
            spec = importlib.util.spec_from_file_location('local_caption_routing_test',source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        plugin = module.JapaneseCaptionPlugin()
        plugin.is_enabled = Mock(return_value=True)
        plugin.transcribe_local = Mock(side_effect=['短い','短い台詞','はい'])
        plugin.status = Mock()
        plugin.session_id, plugin.utterance_id, plugin.revision = 'session',0,0
        plugin.detected_language = 'ja'
        wav = make_wav(b'\1\0'*8000,16000)
        draft = plugin.stt_processing(wav,16000,False)
        final = plugin.stt_processing(wav,16000,True)
        next_draft = plugin.stt_processing(wav,16000,False)
        self.assertEqual(plugin.transcribe_local.call_count,3)
        self.assertEqual(plugin.transcribe_local.call_args.args,(b'\1\0'*8000,16000))
        self.assertEqual([r['caption_revision'] for r in (draft,final,next_draft)],[1,2,1])
        self.assertEqual([r['caption_utterance'] for r in (draft,final,next_draft)],[0,0,1])
        self.assertTrue(final['final'])
        self.assertFalse(draft['final'])
        self.assertTrue(all(r['caption_backend']=='local' and r['streaming'] for r in (draft,final,next_draft)))

    def test_status_sharing_violation_never_breaks_caption_delivery(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from caption_bridge import StatusFile
        from jcaption.settings import read_json
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'status.json'
            status = StatusFile(path)
            with patch.object(Path,'replace',side_effect=PermissionError('Windows sharing violation')):
                status(stage='caption_displayed')
            status(revision=2)
            self.assertEqual(read_json(path)['status_write_errors'],1)
            self.assertEqual(read_json(path)['revision'],2)

    def test_repeated_words_from_distinct_events_are_not_lost(self):
        session = Mock()
        display = LunaDisplay('http://127.0.0.1:23733', session)
        self.assertTrue(display.show('はい', identity=1))
        self.assertFalse(display.show('はい', identity=1))
        self.assertTrue(display.show('はい', identity=2))
        self.assertEqual(session.get.call_count, 2)

    def test_audio_has_valid_wav_header(self):
        import io, wave
        with wave.open(io.BytesIO(make_wav(b'\0\0' * 16000, 16000))) as audio:
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnframes(), 16000)
            self.assertEqual(audio.getnchannels(), 1)

    def test_tiger_container_is_removed_before_routing(self):
        pcm = b'\x01\x02\x03\x04' * 160
        wrapped = make_wav(pcm, 16000)
        extracted = tiger_wav_to_pcm(wrapped, 16000)
        self.assertEqual(extracted, pcm)
        self.assertEqual(make_wav(extracted, 16000), wrapped)
        with self.assertRaises(ValueError):
            tiger_wav_to_pcm(wrapped, 48000)

