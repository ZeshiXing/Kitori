"""Optional display isolation, stale receipts and reversible user-HTML install."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import threading
import time
import requests
from jcaption.luna import LunaView, prepare_extension, BEGIN
from jcaption.settings import read_json, write_json
from jcaption.server import CaptionService


class ExtensionTests(unittest.TestCase):
    def test_idempotent_install_and_removal_preserve_other_user_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            luna = root / 'luna'
            config = luna / 'userconfig/config.json'
            original = {'rendertext_using':'textbrowser', 'useextrahtml':False, 'other':'keep'}
            write_json(config, original)
            html = luna / 'userconfig/extrahtml.html'
            html.write_text('<style>/* user */</style>', encoding='utf-8')
            self.assertTrue(prepare_extension(root, luna, check=True))
            self.assertEqual(read_json(config), original)
            prepare_extension(root, luna)
            self.assertFalse(prepare_extension(root, luna, check=True))
            self.assertEqual(html.read_text(encoding='utf-8').count(BEGIN), 1)
            html.write_text(html.read_text(encoding='utf-8') + '<p>later</p>', encoding='utf-8')
            prepare_extension(root, luna)
            prepare_extension(root, luna, disable=True)
            self.assertEqual(read_json(config), original)
            self.assertEqual(html.read_text(encoding='utf-8'), '<style>/* user */</style><p>later</p>')

    def test_removal_does_not_undo_user_setting_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'luna/userconfig/config.json'
            write_json(config, {'rendertext_using':'textbrowser'})
            prepare_extension(root, root / 'luna')
            updated = read_json(config)
            updated['isshowhira'] = False
            write_json(config, updated)
            prepare_extension(root, root / 'luna', disable=True)
            self.assertFalse(read_json(config)['isshowhira'])

    def test_reenable_captures_the_current_user_preferences_for_later_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'luna/userconfig/config.json'
            write_json(config, {'rendertext_using':'textbrowser'})
            prepare_extension(root, root / 'luna')
            prepare_extension(root, root / 'luna', disable=True)
            write_json(config, {'rendertext_using':'webview','useextrahtml':True})
            prepare_extension(root, root / 'luna')
            prepare_extension(root, root / 'luna', disable=True)
            self.assertTrue(read_json(config)['useextrahtml'])
            self.assertEqual(read_json(config)['rendertext_using'], 'webview')

    def test_connected_extension_sends_only_final_then_falls_back_after_disconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            view = LunaView(directory, 'view')
            view.last_poll, view.paint = time.monotonic(), {'revision':1}
            session = Mock()
            delivered = threading.Event()
            session.get.side_effect = lambda *args, **kwargs: (delivered.set() or Mock())
            service = CaptionService('sink-test','publish',port=0,luna_url='http://127.0.0.1:23733',luna_view=view)
            def update(identity, revision, text, final=False):
                service.state.accept({'session_id':'sink-test','utterance_id':identity,
                                      'revision':revision,'text':text,'final':final})
            with patch('requests.Session', return_value=session):
                service.start()
                try:
                    update(0,1,'今日は')
                    update(0,2,'今日は学校')
                    self.assertFalse(delivered.wait(0.25))
                    update(0,3,'今日は学校です。',True)
                    self.assertTrue(delivered.wait(1))
                    self.assertEqual(session.get.call_args.kwargs['params']['text'],'今日は学校です。')
                    delivered.clear()
                    view.last_poll = 0
                    update(1,1,'明日は')
                    update(1,2,'明日は映画')
                    self.assertTrue(delivered.wait(1))
                    self.assertEqual(session.get.call_args.kwargs['params']['text'],'明日は')
                finally:
                    service.close()


class LunaServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.view = LunaView(self.directory.name, 'display-capability')
        self.service = CaptionService('luna-test', 'publish-capability', port=0, luna_view=self.view)
        self.service.start()
        self.url = f'http://127.0.0.1:{self.service.port}'
        self.client = requests.Session()
        self.client.trust_env = False
        self.headers = {'Origin':'null', 'X-Caption-View':'display-capability'}

    def tearDown(self):
        self.client.close()
        self.service.close()
        self.directory.cleanup()

    def test_file_view_cors_does_not_authorize_publishing(self):
        self.assertEqual(self.client.get(self.url + '/api/luna/state', headers={'Origin':'null'}, timeout=2).status_code, 403)
        response = self.client.get(self.url + '/api/luna/state', headers=self.headers, timeout=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'null')
        self.assertNotIn('history', response.json())
        self.assertEqual(self.client.get(self.url + '/api/luna/state',
                         headers={**self.headers, 'Origin':'https://example.org'}, timeout=2).status_code, 403)
        self.assertEqual(self.client.post(self.url + '/api/update', json={}, headers=self.headers, timeout=2).status_code, 403)
        self.assertEqual(self.client.get(self.url + '/api/state', headers=self.headers, timeout=2).status_code, 403)

    def test_old_paint_receipt_cannot_replace_latest(self):
        event = {'session_id':'luna-test','utterance_id':0,'revision':1,'text':'今日は','final':False}
        self.service.state.accept(event)
        receipt = {'session_id':'luna-test','utterance_id':0,'revision':1,
                   'stable_characters':0,'draft_characters':3,'ruby_count':1}
        self.client.get(self.url + '/api/luna/state', headers=self.headers, timeout=2)
        self.assertEqual(self.client.post(self.url + '/api/luna/paint', json=receipt,
                         headers=self.headers, timeout=2).status_code, 200)
        self.assertTrue(self.view.connected)
        self.service.state.accept({**event,'revision':2,'text':'今日は学校'})
        self.assertEqual(self.client.post(self.url + '/api/luna/paint', json=receipt,
                         headers=self.headers, timeout=2).status_code, 400)
        self.assertNotIn('text', self.view.paint)

    def test_preflight_is_limited_to_display_routes(self):
        headers = {'Origin':'null','Access-Control-Request-Headers':'X-Caption-View'}
        self.assertEqual(self.client.options(self.url + '/api/luna/state', headers=headers, timeout=2).status_code, 204)
        self.assertEqual(self.client.options(self.url + '/api/update', headers=headers, timeout=2).status_code, 403)

    def test_luna_view_retains_previous_line_but_never_delays_new_draft(self):
        event = {'session_id':'luna-test','utterance_id':0,'revision':1,'text':'前の台詞','final':True}
        self.service.state.accept(event)
        self.service.state.accept({**event,'utterance_id':1,'text':'次の台詞','final':False})
        response = self.client.get(self.url + '/api/luna/state', headers=self.headers, timeout=2).json()
        self.assertEqual(response['previous']['text'],'前の台詞')
        self.assertEqual(response['current']['text'],'次の台詞')
        self.assertNotIn('history',response)
        write_json(Path(self.directory.name)/'config/overlay.json',{'previous_caption_seconds':0})
        response = self.client.get(self.url + '/api/luna/state', headers=self.headers, timeout=2).json()
        self.assertIsNone(response['previous'])
