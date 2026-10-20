"""Actual browser-playback trials; browser control stays with the UI tool/user.

Only counts/timings are saved. Small transcript samples are printed for this
explicit debugging session, not persisted into the metadata report.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jcaption.local_models import MODELS
from jcaption.settings import read_json, write_json
from jcaption.state import common_prefix_length

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model', choices=(*MODELS,'windows_livecaptions'))
parser.add_argument('--seconds', type=float, default=45)
parser.add_argument('--interval', type=float, default=.5)
parser.add_argument('--draft-beam', type=int, choices=(1,3,5), default=1)
parser.add_argument('--standard-decode', action='store_true')
parser.add_argument('--tag', default='')
parser.add_argument('--attach', action='store_true',help='Observe current ready backend without changing settings or reloading')
parser.add_argument('--mark', action='store_true')
parser.add_argument('--wall-time', type=float)
parser.add_argument('--media-start', type=float)
args=parser.parse_args()
if args.mark:
    active=read_json(ROOT/'logs/anime-trial-active.json')
    write_json(ROOT/'work/anime-trial-play.json', {'trial_id':active['trial_id'],
        'play_wall_time':args.wall_time,'media_start':args.media_start})
    print(json.dumps({'marked':active['model']}),flush=True)
    raise SystemExit(0)
if not args.model: parser.error('--model is required')
config=read_json(ROOT/'config/caption.json')
if args.attach and (config.get('local_model')!=args.model or config.get('mode')!='local'):
    raise SystemExit('Current backend does not match the requested local model')
if not args.attach:
    config.update(recognition_source='windows_livecaptions' if args.model=='windows_livecaptions' else 'models',
              mode='local', local_native_backend='cuda', local_stream_chunk_seconds=args.interval,
              whisper_draft_beam=args.draft_beam)
    config['whisper_standard_decode']=args.standard_decode
    if args.model!='windows_livecaptions':config['local_model']=args.model
    write_json(ROOT/'config/caption.json',config)
else:
    args.interval=config.get('local_stream_chunk_seconds',.5)
    args.draft_beam=config.get('whisper_draft_beam',1)
    args.standard_decode=config.get('whisper_standard_decode',False)
trial_id=uuid.uuid4().hex
started=time.time()
if not args.attach:
    with (ROOT/'logs/anime-trial-launch.log').open('w',encoding='utf-8') as launch_log:
        launched=subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'scripts/launch.ps1'),
                            '-Mode','local','-Display','luna'],cwd=ROOT,stdout=launch_log,stderr=launch_log,
                           timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    if launched.returncode:raise SystemExit('Trial launch failed; see launcher/runtime logs')
client=requests.Session();client.trust_env=False
deadline=time.monotonic()+180
while time.monotonic()<deadline:
    status=read_json(ROOT/'logs/status.json')
    if status.get('updated_at',0)>=started and status.get('stage') in ('local_error','source_error'):
        raise SystemExit('Trial backend reported an error')
    try:
        state=client.get('http://127.0.0.1:8766/api/state',timeout=1).json()
        if state.get('backend_ready'):break
    except requests.RequestException:pass
    time.sleep(.2)
else:raise SystemExit('Trial backend readiness timeout')
write_json(ROOT/'logs/anime-trial-active.json',{'trial_id':trial_id,'model':args.model,'state':'ready'})
print(json.dumps({'model':args.model,'trial_id':trial_id,'ready':True}),flush=True)
deadline=time.monotonic()+180
while time.monotonic()<deadline:
    marker=read_json(ROOT/'work/anime-trial-play.json')
    if marker.get('trial_id')==trial_id:break
    time.sleep(.05)
else:raise SystemExit('No browser playback marker arrived')
play=marker['play_wall_time']
deadline=play+args.seconds
events=[];seen=set();metrics={};last_by_uid={};samples=[];paints=[];paint_seen=set();errors=0
idle_seen=False
while time.time()<deadline:
    try:
        state=client.get('http://127.0.0.1:8766/api/state',timeout=1).json()
        current=state.get('current') or {}
        idle_seen=idle_seen or current.get('display_expired',False)
        identity=(current.get('utterance_id'),current.get('revision'))
        if current and identity not in seen and not current.get('display_expired'):
            seen.add(identity)
            prior=last_by_uid.get(identity[0])
            rewritten=len(prior['text'])-common_prefix_length(prior['text'],current['text']) if prior else 0
            event={'t':time.time()-play,'id':identity[0],'phase':current['phase'],'text':current['text'],
                   'rewritten':rewritten,'stable':len(current['stable_text'])}
            last_by_uid[identity[0]]=event;events.append(event)
            if current['phase']=='final' and current['text'] and len(samples)<7:samples.append(current['text'][:90])
        paint=state.get('luna_output',{}).get('paint') or {}
        paint_key=(paint.get('utterance_id'),paint.get('revision'),paint.get('visible_characters'),paint.get('ruby_count'))
        if paint and paint_key not in paint_seen:
            paints.append(paint);paint_seen.add(paint_key)
        for row in client.get('http://127.0.0.1:8766/api/metrics',timeout=1).json()['observations']:
            if row['wall_time']>=play:metrics[(row['utterance_id'],row['revision'])]=row
    except requests.RequestException:errors+=1
    time.sleep(.06)
rows=list(metrics.values());asr=[r['asr_seconds'] for r in rows if r.get('asr_seconds') is not None]
drafts=[r for r in rows if r['phase']=='draft' and r['characters']]
def percentile(values,p):
    return sorted(values)[min(len(values)-1,int((len(values)-1)*p))] if values else None
report={'model':args.model,'source':'actual d-anime-store playback, desktop audio',
    'media_start':marker['media_start'],'play_wall_time':play,'observed_seconds':args.seconds,
    'configured_update_interval':args.interval,'draft_updates':len(drafts),
    'whisper_draft_beam':args.draft_beam,
    'whisper_standard_decode':args.standard_decode,
    'final_updates':sum(r['phase']=='final' for r in rows),
    'first_draft_after_play_call_seconds':drafts[0]['wall_time']-play if drafts else None,
    'rewrite_updates':sum(e['rewritten']>0 for e in events),
    'large_rewrite_updates':sum(e['rewritten']>=5 for e in events),
    'asr_median_seconds':statistics.median(asr) if asr else None,
    'asr_p95_seconds':percentile(asr,.95),'asr_max_seconds':max(asr) if asr else None,
    'maximum_caption_characters':max([len(e['text']) for e in events] or [0]),
    'maximum_visible_rows':max([p.get('visible_rows',0) for p in paints] or [0]),
    'saw_ruby':any(p.get('ruby_count') for p in paints),
    'saw_idle_clear':idle_seen,
    'rows_over_limit':sum(p.get('visible_rows',0)>2 for p in paints),'poll_errors':errors,
    'local_inference_since_backend_start':read_json(ROOT/'logs/status.json').get('local_inference',{}),
    'scope':'Functional and timing trial; no reference transcript/CER, playback-call timing is not speech-aligned latency.'}
write_json(ROOT/f'logs/anime-model-{args.model}{args.tag}.json',report)
write_json(ROOT/'logs/anime-trial-active.json',{'trial_id':trial_id,'model':args.model,'state':'done'})
print(json.dumps(report),flush=True)
print(json.dumps({'transient_samples':samples,'latest':events[-1]['text'][:90] if events else None},ensure_ascii=True),flush=True)
