"""Inject synthetic display text into real Luna; no audio/ASR accuracy claim."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jcaption.server import CaptionService
from jcaption.luna import LunaView
from jcaption.settings import read_json, load_appearance, write_json

ROOT = Path(__file__).resolve().parents[2]
config = read_json(ROOT/'config/caption.json')
view = LunaView(ROOT, read_json(ROOT/'config/luna-view.json')['view_token'])
service = CaptionService('display-layout-check', 'diagnostic-only', port=config.get('caption_port',8766),
                         luna_view=view, appearance_provider=lambda: load_appearance(ROOT))
service.start()
try:
    text = '今日は日本語の字幕と振り仮名を表示しながら長い台詞を二行以内に収めます。' * 5
    service.state.accept(dict(session_id='display-layout-check',utterance_id=0,revision=1,final=False,text=text))
    deadline = time.monotonic()+12
    initial = None
    while time.monotonic()<deadline:
        paint = view.paint or {}
        if paint.get('revision')==1 and paint.get('trimmed_characters',0)>0 and paint.get('ruby_count',0)>0:
            initial = dict(paint);break
        time.sleep(.1)
    if not initial or initial['visible_rows'] > 2:
        raise SystemExit('Real Luna did not paint a two-line annotated suffix')
    deadline=time.monotonic()+8
    cleared=None
    while time.monotonic()<deadline:
        paint=view.paint or {}
        if paint.get('visible_characters')==0 and paint.get('visible_rows')==0:
            cleared=dict(paint);break
        time.sleep(.1)
    if not cleared:
        raise SystemExit('Real Luna did not clear after the configured idle timeout')
    report={'source':'synthetic injected text, real Luna WebView', 'two_line_paint':initial,
            'idle_cleared_paint':cleared,'settings':{k:load_appearance(ROOT)[k] for k in ('max_caption_lines','caption_idle_seconds')}}
    write_json(ROOT/'logs/display-layout-check.json',report)
    print(json.dumps(report),flush=True)
finally:
    service.close()
