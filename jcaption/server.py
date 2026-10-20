"""Loopback-only caption view. Transcripts live in bounded process memory."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading

from .annotation import JapaneseAnnotator
from .state import CaptionState, display_window
from .lookahead import Lookahead

WEB = Path(__file__).with_name('web')


class CaptionService:
    def __init__(self, session_id, token, port=8766, luna_url=None, ffmpeg_bin='', language='ja', luna_view=None,
                 lookahead_enabled=True, appearance_provider=None):
        self.appearance_provider = appearance_provider or (lambda: {})
        self.token, self.port = token, port
        self.annotator = JapaneseAnnotator()
        self.language = language
        self.state = CaptionState(session_id, boundary=self.annotator.safe_commit_end)
        self.running = threading.Event()
        self.running.set()
        self.luna_url = luna_url
        self.luna_view = luna_view
        self.lookahead = Lookahead(ffmpeg_bin, enabled=lookahead_enabled)
        self.on_shutdown = None
        self.backend_ready = False
        self.luna_deliveries = 0
        self.sink_worker = threading.Thread(target=self._luna_output, daemon=True)
        self.worker = threading.Thread(target=self._annotate, daemon=True)
        self.http = ThreadingHTTPServer(('127.0.0.1', port), self._handler())
        self.port = self.http.server_address[1]
        self.http.daemon_threads = True

    def _annotate(self):
        seen = None
        while self.running.is_set():
            snapshot = self.state.snapshot()
            current = snapshot['current']
            identity = ((current['utterance_id'], current['revision']) if current else None)
            if identity is None or identity == seen:
                self.state.wait(snapshot['sequence'], timeout=0.25)
                continue
            seen = identity
            try:
                spans = self.caption_tokens(current['text'], current.get('language', self.language))
                # A slow reading for an old draft must not overwrite a new one.
                if not self.state.apply_annotation(*identity, spans):
                    continue
            except Exception:
                # Failure of an optional sink must not stop transcription.
                continue

    def _luna_output(self):
        import requests
        session = requests.Session()
        session.trust_env = False
        previous = None
        while self.running.is_set() and self.luna_url:
            current = self.display_snapshot()['current']
            # The extension paints every hypothesis directly. Only completed
            # sentences enter Luna history/translation. Without it, keep the
            # ordinary stable-text API adapter as a fallback.
            extended = self.luna_view and self.luna_view.connected
            if current and current['stable_text'] and (not extended or current['phase'] == 'final'):
                identity = (current.get('input_mode', 'live'), current['utterance_id'], current['stable_text'])
                if identity != previous:
                    try:
                        session.get(self.luna_url.rstrip('/') + '/api/textinput',
                                    params={'text': current['stable_text']}, timeout=(0.2, 0.3)).raise_for_status()
                        previous = identity
                        self.luna_deliveries += 1
                    except requests.RequestException:
                        pass
            threading.Event().wait(0.1)
        session.close()

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass  # Do not write requested text, tokens or captions to logs.

            def _local_request(self):
                allowed_hosts = {f'127.0.0.1:{service.port}', f'localhost:{service.port}'}
                allowed_origins = {'http://' + host for host in allowed_hosts}
                return (self.headers.get('Host') in allowed_hosts and
                        self.headers.get('Origin', next(iter(allowed_origins))) in allowed_origins)

            def _luna_request(self):
                # file:// WebView2 has the opaque "null" origin. This dedicated
                # capability does not authorize publishing, shutdown or audio.
                view = service.luna_view
                return (view is not None and
                        self.headers.get('Host') in (f'127.0.0.1:{service.port}', f'localhost:{service.port}') and
                        self.headers.get('Origin') in (None, 'null') and
                        secrets.compare_digest(self.headers.get('X-Caption-View', ''), view.token))

            def _luna_cors(self):
                if self.path in ('/api/luna/state', '/api/luna/paint') and self.headers.get('Origin') == 'null':
                    self.send_header('Access-Control-Allow-Origin', 'null')
                    self.send_header('Vary', 'Origin')

            def do_OPTIONS(self):
                if (service.luna_view is None or self.path not in ('/api/luna/state', '/api/luna/paint') or
                        self.headers.get('Origin') != 'null' or
                        self.headers.get('Host') not in (f'127.0.0.1:{service.port}', f'localhost:{service.port}')):
                    return self._reply(403, {'error': 'forbidden'})
                self.send_response(204)
                self._luna_cors()
                self.send_header('Access-Control-Allow-Headers', 'X-Caption-View, Content-Type')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Max-Age', '600')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def _reply(self, code, data, mime='application/json; charset=utf-8'):
                if not isinstance(data, bytes):
                    data = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self._luna_cors()
                if code >= 400:
                    # Rejected POST bodies are not consumed. Close the stream
                    # so their bytes cannot be parsed as another HTTP request.
                    self.send_header('Connection', 'close')
                    self.close_connection = True
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == '/api/luna/state':
                    if not self._luna_request():
                        return self._reply(403, {'error': 'forbidden'})
                    return self._reply(200, service.luna_view.payload(service.display_snapshot()))
                if not self._local_request():
                    return self._reply(403, {'error': 'local_only'})
                if self.path == '/api/state':
                    return self._reply(200, service.display_snapshot())
                if self.path == '/api/lookahead/job':
                    if not secrets.compare_digest(self.headers.get('X-Caption-Token', ''), service.token):
                        return self._reply(403, {'error': 'forbidden'})
                    return self._reply(200, service.lookahead.take_job())
                if self.path == '/api/metrics':
                    return self._reply(200, service.state.metrics())
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if self.path in files:
                    filename, mime = files[self.path]
                    return self._reply(200, (WEB / filename).read_bytes(), mime)
                if self.path != '/events':
                    return self._reply(404, {'error': 'not_found'})
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                sequence = -1
                try:
                    while service.running.is_set():
                        snapshot = service.state.wait(sequence, timeout=1)
                        if snapshot['sequence'] == sequence:
                            self.wfile.write(b': keepalive\n\n')
                        else:
                            self.wfile.write(('data: ' + json.dumps(snapshot, ensure_ascii=False) + '\n\n').encode('utf-8'))
                            sequence = snapshot['sequence']
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def do_POST(self):
                if self.path == '/api/luna/paint':
                    if not self._luna_request():
                        return self._reply(403, {'error': 'forbidden'})
                    try:
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 2048:
                            raise ValueError('size')
                        service.luna_view.receipt(json.loads(self.rfile.read(size)), service.display_snapshot())
                    except (ValueError, TypeError):
                        return self._reply(400, {'error': 'invalid_receipt'})
                    return self._reply(200, {'accepted': True})
                if not self._local_request() or not secrets.compare_digest(
                        self.headers.get('X-Caption-Token', ''), service.token):
                    return self._reply(403, {'error': 'forbidden'})
                if self.path not in ('/api/update', '/api/lookahead/open', '/api/lookahead/result', '/api/clock', '/api/shutdown'):
                    return self._reply(404, {'error': 'not_found'})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 65536:
                        return self._reply(413, {'error': 'invalid_size'})
                    event = json.loads(self.rfile.read(size))
                    if not isinstance(event, dict):
                        raise ValueError('object required')
                    if self.path == '/api/lookahead/open':
                        return self._reply(200, {'generation': service.lookahead.open(event['source'])})
                    if self.path == '/api/clock':
                        accepted = service.lookahead.set_clock(event['generation'], float(event['position']),
                                                               event['paused'], float(event.get('rate', 1)))
                    elif self.path == '/api/lookahead/result':
                        accepted = service.lookahead.complete(event['generation'], event['job_id'],
                                                              event['segments'], lambda text: service.caption_tokens(
                                                                  text, event.get('language', service.language)))
                    elif self.path == '/api/shutdown':
                        if service.on_shutdown:
                            threading.Thread(target=service.on_shutdown, daemon=True).start()
                        accepted = True
                    else:
                        accepted = service.state.accept(event)
                    return self._reply(200, {'accepted': accepted})
                except (ValueError, TypeError, KeyError):
                    return self._reply(400, {'error': 'invalid_update'})

        return Handler

    def caption_tokens(self, text, language):
        return self.annotator.tokens(text) if language == 'ja' else []

    def start(self):
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.worker.start()
        self.lookahead.start()
        self.sink_worker.start()

    def display_snapshot(self):
        snapshot = self.state.snapshot()
        snapshot['backend_ready'] = self.backend_ready
        snapshot['luna_output'] = {'enabled': bool(self.luna_url), 'deliveries': self.luna_deliveries,
                                   'stream_connected': bool(self.luna_view and self.luna_view.connected),
                                   'paint': self.luna_view.paint if self.luna_view else None}
        ahead = self.lookahead.snapshot()
        snapshot['lookahead'] = {k: v for k, v in ahead.items() if k != 'cue'}
        if ahead['covered']:
            cue = ahead['cue']
            text = cue['text'] if cue else ''
            snapshot['current'] = {
                'session_id': snapshot['session_id'], 'utterance_id': cue['identity'] if cue else 'silence',
                'revision': 1, 'phase': 'final', 'text': text, 'stable_text': text, 'draft_text': '',
                'ruby': [{**span, 'stable': True} for span in cue['ruby']] if cue else [],
                'backend': 'local', 'input_mode': 'lookahead',
                'media_start_ms': cue['start'] * 1000 if cue else None,
                'media_end_ms': cue['end'] * 1000 if cue else None, 'timing_quality': 'approximate',
            }
            snapshot['input_mode'] = 'lookahead'
        appearance = self.appearance_provider()
        snapshot = display_window(snapshot, appearance.get('caption_idle_seconds', 0))
        snapshot['display'] = {'max_caption_lines': appearance.get('max_caption_lines', 2)}
        return snapshot

    def close(self):
        self.running.clear()
        self.lookahead.close()
        with self.state.condition:
            self.state.condition.notify_all()
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(timeout=1)
