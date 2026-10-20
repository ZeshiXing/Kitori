"""Real Luna WebView paint receipts; injected text, not an ASR benchmark.

Stop caption recognition first; Luna remains open. --hold allows a screenshot
and native dictionary check of the mixed-color draft.
"""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jcaption.server import CaptionService
from jcaption.luna import LunaView
from jcaption.settings import read_json, load_appearance

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hold', type=float, default=0)
args = parser.parse_args()
view_config = read_json(ROOT / 'config/luna-view.json')
config = read_json(ROOT / 'config/caption.json')
service = CaptionService('luna-output-check', 'diagnostic-token', port=config.get('caption_port',8766),
                         luna_url=config['luna_url'], luna_view=LunaView(ROOT,view_config['view_token']))
service.start()
def update(text, revision, final=False, identity=0):
    service.state.accept({'session_id':'luna-output-check','utterance_id':identity,
                          'revision':revision,'text':text,'final':final})
def wait_paint(revision, mixed=False, identity=0, previous=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        paint = service.luna_view.paint
        if (paint and paint['utterance_id'] == identity and paint['revision'] == revision and paint['ruby_count'] and
                (previous is None or bool(paint.get('previous_characters')) == previous) and
                (not mixed or paint['stable_characters'] and paint['draft_characters'])):
            return dict(paint)
        time.sleep(0.1)
    raise SystemExit('Luna did not acknowledge the expected ruby/streaming paint')
try:
    update('明日は学校で友達と',1)
    first = wait_paint(1)
    update('明日は学校で友達と映画を見ます。',2)
    draft = wait_paint(2, mixed=True)
    print(json.dumps({'draft_painted':draft,'hold_seconds':args.hold}),flush=True)
    time.sleep(max(0,args.hold))
    update('明日は図書館で友達と映画を見ます。',3)
    correction = wait_paint(3)
    if service.state.snapshot()['current']['text'] != '明日は図書館で友達と映画を見ます。':
        raise SystemExit('Conflicting draft was frozen until final')
    update('明日は図書館で友達と映画を見ます。',4,True)
    final = wait_paint(4)
    deadline = time.monotonic() + 5
    while not service.luna_deliveries and time.monotonic() < deadline:
        time.sleep(0.1)
    retention = load_appearance(ROOT)['previous_caption_seconds']
    update('次の台詞もすぐに表示します。',1,identity=1)
    next_draft = wait_paint(1,identity=1,previous=retention > 0)
    expired = wait_paint(1,identity=1,previous=False)
    result = {'source':'injected display diagnostic, not ASR','first_draft':first,
              'mixed_draft':draft,'conflicting_draft':correction,'final':final,
              'next_draft':next_draft,'expired_previous':expired,
              'retention_seconds':retention,'final_api_deliveries':service.luna_deliveries}
    (ROOT / 'logs/luna-output-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    if not service.luna_deliveries:
        raise SystemExit('Final sentence did not reach Luna API')
finally:
    service.close()
