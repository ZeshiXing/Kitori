"""Small adapters for the existing Tiger recognition and Luna display pipelines.

Audio capture, VAD, ASR inference, tokenization and ruby rendering stay upstream.
No audio or transcripts are persisted here. The status file contains metadata only.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import threading
import time
import wave


def load_config(root: Path) -> dict:
    config = json.loads((root / 'config/caption.json').read_text(encoding='utf-8-sig'))
    from jcaption.settings import local_config
    return local_config(config)


def tiger_wav_to_pcm(audio_data: bytes, sample_rate: int) -> bytes:
    """The finalized Tiger STT callback contains a WAV container, not raw PCM."""
    with wave.open(io.BytesIO(audio_data), 'rb') as wav:
        if (sample_rate != 16000 or wav.getframerate() != sample_rate or
                wav.getnchannels() != 1 or wav.getsampwidth() != 2 or
                wav.getcomptype() != 'NONE'):
            raise ValueError('Expected Tiger mono 16 kHz signed 16-bit WAV')
        return wav.readframes(wav.getnframes())


def make_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap mono signed 16-bit PCM for synthetic diagnostics."""
    if sample_rate != 16000 or len(pcm) % 2:
        raise ValueError('Expected mono 16 kHz signed 16-bit PCM')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


class LunaDisplay:
    def __init__(self, url: str, session=None):
        if session is None:
            import requests
            session = requests.Session()
            session.trust_env = False
        self.session, self.url = session, url.rstrip('/')
        self.last_identity = None

    def show(self, text: str, identity=None) -> bool:
        if not text.strip():
            return False
        # Deduplicate only the same recognition event, not a repeated spoken line.
        if identity is not None and identity == self.last_identity:
            return False
        response = self.session.get(self.url + '/api/textinput',
                                    params={'text': text}, timeout=2)
        response.raise_for_status()
        self.last_identity = identity
        return True


class CaptionPublisher:
    """Send versioned hypotheses to the independent local caption service."""
    def __init__(self, url, token):
        import requests
        self.url, self.token = url, token
        self.session = requests.Session()
        self.session.trust_env = False

    def publish(self, event):
        response = self.session.post(self.url + '/api/update', json=event,
                                     headers={'X-Caption-Token': self.token}, timeout=(0.2, 0.5))
        response.raise_for_status()
        return response.json()['accepted']


class StatusFile:
    def __init__(self, path: Path):
        self.path, self.state = path, {}
        self.lock = threading.Lock()

    def __call__(self, **fields):
        with self.lock:
            self.state.update(fields, updated_at=time.time())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + '.' + str(os.getpid()) + '.tmp')
            try:
                temporary.write_text(json.dumps(self.state, indent=2), encoding='utf-8')
                temporary.replace(self.path)
            except PermissionError:
                # Windows readers can briefly deny replacement. Status is
                # diagnostic: never block or fail the realtime caption callback.
                self.state['status_write_errors'] = self.state.get('status_write_errors', 0) + 1
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

