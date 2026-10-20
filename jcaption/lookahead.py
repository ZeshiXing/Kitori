"""Bounded decode-ahead jobs and a media-clock caption cache.

Media codecs stay in FFmpeg; protected manifests are explicitly unsupported.
The ordinary live lane is independent and never waits for this worker.
"""
import base64
from collections import deque
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlparse
import uuid
import xml.etree.ElementTree as ET


class UnsupportedMedia(Exception):
    pass


def check_manifest(text):
    stripped = text.lstrip()
    if stripped.startswith('#EXTM3U'):
        if any(line.startswith('#EXT-X-KEY:') and 'METHOD=NONE' not in line
               for line in text.splitlines()):
            raise UnsupportedMedia('protected_media')
    elif '<MPD' in text:
        root = ET.fromstring(text)
        if any(element.tag.rsplit('}', 1)[-1] == 'ContentProtection' for element in root.iter()):
            raise UnsupportedMedia('protected_media')


class Lookahead:
    def __init__(self, ffmpeg_bin='', clock=time.monotonic, decoder=None, enabled=True):
        self.enabled = enabled
        self.ffmpeg = str(Path(ffmpeg_bin) / 'ffmpeg.exe') if ffmpeg_bin else 'ffmpeg'
        self.clock, self.decoder = clock, decoder or self._decode
        self.lock = threading.RLock()
        self.generation = None
        self.source = None
        self.position = 0.0
        self.rate, self.paused, self.clock_at = 1.0, True, None
        self.status = 'unavailable'
        self.reason = None
        self.jobs = deque(maxlen=1)
        self.inflight = None
        self.coverage = []
        self.cues = []
        self.events = deque(maxlen=64)
        self.sequence = 0
        self.eof_at = None
        self.running = True
        self.worker = threading.Thread(target=self._work, daemon=True)

    def start(self):
        self.worker.start()

    def open(self, source):
        if not isinstance(source, str) or len(source) > 4000:
            raise ValueError('Invalid media source')
        parsed = urlparse(source)
        if parsed.scheme not in ('http', 'https') and not Path(source).is_file():
            raise ValueError('Media file does not exist')
        with self.lock:
            self.generation = uuid.uuid4().hex
            self.source = source
            self.position, self.paused, self.clock_at = 0.0, True, None
            self.status, self.reason = ('probing', None) if self.enabled else ('unsupported', 'live_source_only')
            self.jobs.clear()
            self.inflight = None
            self.coverage.clear()
            self.cues.clear()
            self.events.clear()
            self.eof_at = None
            self.sequence += 1
            return self.generation

    def set_clock(self, generation, position, paused, rate=1.0):
        if not (0 <= position < 1000000 and 0 < rate <= 8):
            raise ValueError('Invalid media clock')
        with self.lock:
            if generation != self.generation:
                return False
            self.position, self.paused, self.rate = position, bool(paused), rate
            self.clock_at = self.clock()
            self.sequence += 1
            return True

    def _position(self):
        if self.clock_at is None or self.paused:
            return self.position
        return self.position + max(0, self.clock() - self.clock_at) * self.rate

    def _probe(self, source):
        if source.startswith(('http://', 'https://')):
            import requests
            # No browser cookies, license credentials or decryption keys.
            with requests.get(source, stream=True, timeout=(3, 5)) as response:
                response.raise_for_status()
                first = next(response.iter_content(65536), b'')
                if first.lstrip().startswith((b'<?xml', b'<MPD', b'#EXTM3U')):
                    data = first + response.raw.read(1024 * 1024)
                    check_manifest(data.decode('utf-8-sig'))
        elif source.lower().endswith(('.mpd', '.m3u8')):
            check_manifest(Path(source).read_text(encoding='utf-8-sig'))

    def _decode(self, source, start, duration):
        command = [self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin']
        if source.startswith(('http://', 'https://')):
            command += ['-rw_timeout', '5000000']
        command += ['-ss', str(start), '-i', source, '-t', str(duration),
                    '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1']
        result = subprocess.run(command, capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise UnsupportedMedia('decode_failed')
        return result.stdout

    def _work(self):
        probed = None
        while self.running:
            time.sleep(0.1)
            with self.lock:
                generation, source = self.generation, self.source
                if not source or self.status in ('unsupported', 'error'):
                    continue
            try:
                if generation != probed:
                    self._probe(source)
                    probed = generation
                with self.lock:
                    if generation != self.generation or self.jobs or self.inflight:
                        continue
                    position = self._position()
                    # Align chunks to a stable grid; seek uses the new nearest
                    # uncovered chunk. Cache never advances the visible clock.
                    start = int(position // 8) * 8
                    while any(a <= start < b for a, b in self.coverage):
                        start += 8
                    if start > position + 24:
                        continue
                    if self.eof_at is not None and start >= self.eof_at:
                        continue
                pcm = self.decoder(source, start, 8)
                with self.lock:
                    if generation != self.generation:
                        continue
                    if not pcm:
                        self.status = 'eof'
                        self.eof_at = start
                        continue
                    self.jobs.append({'generation': generation, 'job_id': uuid.uuid4().hex,
                                      'start': start, 'end': start + len(pcm) / 32000,
                                      'pcm': base64.b64encode(pcm).decode('ascii')})
                    self.status = 'decoding'
            except Exception as error:
                with self.lock:
                    if generation == self.generation:
                        self.status = 'unsupported' if isinstance(error, UnsupportedMedia) else 'error'
                        self.reason = str(error) if isinstance(error, UnsupportedMedia) else type(error).__name__
                        self.sequence += 1

    def take_job(self):
        with self.lock:
            if self.inflight and self.clock() - self.inflight.get('issued_at', self.clock()) > 15:
                expired = self.inflight
                self.inflight = None
                if expired.get('attempt', 0) >= 1:
                    self.status, self.reason = 'error', 'recognition_timeout'
                    return None
                self.jobs.append({**expired, 'job_id': uuid.uuid4().hex, 'attempt': 1})
            if not self.jobs or self.inflight:
                return None
            self.inflight = self.jobs.popleft()
            self.inflight['issued_at'] = self.clock()
            return dict(self.inflight)

    def complete(self, generation, job_id, segments, annotate):
        with self.lock:
            job = self.inflight
            if not job or generation != self.generation or job_id != job['job_id']:
                return False
            for index, segment in enumerate(segments):
                text = segment['text'].strip()
                if text:
                    self.cues.append({'start': job['start'] + max(0, segment['start']),
                                      'end': min(job['end'], job['start'] + segment['end']),
                                      'text': text, 'ruby': annotate(text),
                                      'identity': f'{job_id}:{index}'})
            self.coverage.append((job['start'], job['end']))
            self.events.append({'start': job['start'], 'end': job['end'],
                                'player_position': self._position(), 'paused': self.paused,
                                'wall_time': time.time()})
            self.inflight = None
            position = self._position()
            self.coverage = [(a, b) for a, b in self.coverage if b >= position - 8][-8:]
            self.cues = [c for c in self.cues if c['end'] >= position - 8][-80:]
            self.status = 'ready'
            self.sequence += 1
            return True

    def snapshot(self):
        with self.lock:
            position = self._position()
            clock_valid = self.clock_at is not None and self.clock() - self.clock_at <= 2
            covered = clock_valid and any(a <= position < b for a, b in self.coverage)
            cue = next((dict(c) for c in reversed(self.cues) if c['start'] <= position < c['end']), None)
            reachable = position
            for start, end in sorted(self.coverage):
                if start <= reachable + 0.001 and end >= position:
                    reachable = max(reachable, end)
            return {'generation': self.generation, 'status': self.status, 'reason': self.reason,
                    'position': position, 'clock_valid': clock_valid, 'covered': covered,
                    'paused': self.paused, 'cached_ranges': list(self.coverage),
                    'cache_events': list(self.events),
                    'lead_seconds': max(0, reachable - position),
                    'cue': cue if covered else None, 'sequence': self.sequence}

    def close(self):
        self.running = False
        if self.worker.is_alive():
            self.worker.join(timeout=1)
