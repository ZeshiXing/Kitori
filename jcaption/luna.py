"""Optional Luna user extension. Never patches the upstream program files."""
import json
from pathlib import Path
import secrets
import time

from .settings import read_json, write_json, load_appearance
from .state import previous_reading_line

BEGIN = '<!-- Japanese Caption Assistant: begin -->'
END = '<!-- Japanese Caption Assistant: end -->'


def strip_extension(html):
    if BEGIN not in html:
        return html
    start = html.index(BEGIN)
    end = html.find(END, start)
    if end < 0:
        raise ValueError('Incomplete caption extension; restore extrahtml.html before configuring')
    return html[:start] + html[end + len(END):]


def prepare_extension(root, luna_dir, disable=False, check=False):
    root, luna_dir = Path(root), Path(luna_dir)
    config_path = luna_dir / 'userconfig/config.json'
    config = read_json(config_path)
    if not config:
        raise ValueError('Luna user configuration is missing')
    html_path = luna_dir / 'userconfig/extrahtml.html'
    html = html_path.read_text(encoding='utf-8-sig') if html_path.exists() else ''
    state_path = root / 'config/luna-view.json'
    state = read_json(state_path)
    managed = state.get('luna_dir') == str(luna_dir.resolve())
    if disable:
        if not managed:
            return False
        wanted = strip_extension(html)
        for key, original in state['original'].items():
            if config.get(key) == state['applied'][key]:
                if original['present']:
                    config[key] = original['value']
                else:
                    config.pop(key, None)
        if not check:
            html_path.write_text(wanted, encoding='utf-8')
            write_json(config_path, config)
            state['enabled'] = False
            write_json(state_path, state)
        return html != wanted
    applied = {'rendertext_using': 'webview', 'useextrahtml': True,
               'isshowrawtext': True, 'isshowhira': True}
    if not managed or state.get('enabled') is False:
        state = {'luna_dir': str(luna_dir.resolve()), 'view_token': secrets.token_urlsafe(32),
                 'original': {key: {'present': key in config, 'value': config.get(key)} for key in applied},
                 'applied': applied}
    state['enabled'] = True
    style = config.get('rendertext_using_internal', {}).get('webview', 'normal')
    boot = {'url': 'http://127.0.0.1:' + str(read_json(root / 'config/caption.json').get('caption_port', 8766)),
            'token': state['view_token'], 'style': style,
            'styleargs': config.get('rendertext', {}).get('webview', {}).get(style, {}).get('args', {})}
    # No remote assets, transcript, API credential or write-capability is embedded.
    script = (Path(__file__).with_name('web').joinpath('layout.js').read_text(encoding='utf-8') + '\n' +
              Path(__file__).with_name('web').joinpath('luna.js').read_text(encoding='utf-8'))
    block = BEGIN + '\n<script>\n(() => {\nconst boot = ' + json.dumps(boot, ensure_ascii=True).replace('<', '\\u003c')
    block += ';\n' + script + '\n})();\n</script>\n' + END
    # Replace in place, preserving any existing user HTML outside our markers.
    if BEGIN in html:
        start = html.index(BEGIN)
        finish = html.find(END, start)
        if finish < 0:
            raise ValueError('Incomplete caption extension')
        wanted = html[:start] + block + html[finish + len(END):]
    else:
        wanted = html + block
    changed = wanted != html or any(config.get(k) != v for k, v in applied.items())
    if not check:
        write_json(state_path, state)
        if changed:
            html_path.write_text(wanted, encoding='utf-8')
            config.update(applied)
            write_json(config_path, config)
    return changed


class LunaView:
    """A separate display capability accepts only reads and bounded paint receipts."""
    def __init__(self, root, token):
        self.root, self.token = Path(root), token
        self.last_poll = 0
        self.paint = None

    @property
    def connected(self):
        return self.paint is not None and time.monotonic() - self.last_poll < 2

    def payload(self, snapshot):
        self.last_poll = time.monotonic()
        appearance = load_appearance(self.root)
        return {'session_id': snapshot['session_id'], 'sequence': snapshot['sequence'],
                'current': snapshot['current'],
                'previous': previous_reading_line(snapshot, appearance['previous_caption_seconds']),
                'max_caption_lines': appearance['max_caption_lines'],
                'colors': {key: appearance[key] for key in ('stable_color', 'draft_color')}}

    def receipt(self, value, snapshot):
        fields = ('revision', 'stable_characters', 'draft_characters', 'ruby_count')
        current = snapshot['current']
        if (not isinstance(value, dict) or value.get('session_id') != snapshot['session_id'] or not current or
                any(type(value.get(key)) is not int or not 0 <= value[key] <= 8000 for key in fields) or
                value.get('utterance_id') != current['utterance_id'] or value['revision'] != current['revision']):
            raise ValueError('Invalid paint receipt')
        self.paint = {key: value[key] for key in ('session_id', 'utterance_id', *fields)}
        previous = value.get('previous_characters', 0)
        if type(previous) is int and 0 <= previous <= 8000:
            self.paint['previous_characters'] = previous
        for key in ('visible_rows', 'visible_characters', 'trimmed_characters', 'preserved_native_clears'):
            number = value.get(key)
            if type(number) is int and 0 <= number <= 8000:
                self.paint[key] = number

