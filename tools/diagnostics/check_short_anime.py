"""Explicit four-minute anime diagnostic, no audio/transcript files.

Capture raw WASAPI independently of VAD, compare with live output in memory,
then run overlapping continuous-audio Whisper reference windows after playback.
Only timing, counts and disagreements are saved. Reference ASR is not truth.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from jcaption.settings import read_json, write_json


def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text)
                   if unicodedata.category(c)[0] in 'LN').lower()


def capture_check(root, trial):
    try:
        _capture_check(root,trial)
    except Exception as error:
        write_json(root/'logs/short-trial-active.json',{'trial_id':trial,'state':'error','error_type':type(error).__name__})
        print(json.dumps({'short_trial_error':type(error).__name__}),flush=True)


def _capture_check(root,trial):
    import numpy as np
    import pyaudiowpatch as pyaudio
    import requests
    client=requests.Session();client.trust_env=False
    rows=[];seen=set();metrics={};raw=[];first_buffer=None
    maximum_rows=0;saw_ruby=False;saw_idle_clear=False
    config=read_json(root/'config/caption.json')
    with pyaudio.PyAudio() as audio:
        device=audio.get_default_wasapi_loopback()
        rate=int(device['defaultSampleRate']);channels=int(device['maxInputChannels'])
        with audio.open(format=pyaudio.paInt16,channels=channels,rate=rate,input=True,
                        input_device_index=device['index'],frames_per_buffer=1024) as stream:
            ready=time.time()
            write_json(root/'logs/short-trial-active.json',{'trial_id':trial,'state':'ready'})
            marker={};next_poll=0;last_progress=0;errors=0
            deadline=time.time()+180
            while time.time()<deadline:
                available=stream.get_read_available()
                if available:
                    data=stream.read(min(4096,available),exception_on_overflow=False)
                    if first_buffer is None:first_buffer=time.time()-len(data)/(rate*channels*2)
                    raw.append(data)
                if not marker:
                    candidate=read_json(root/'work/short-trial-play.json')
                    if candidate.get('trial_id')==trial:
                        marker=candidate
                        deadline=marker['play_wall_time']+marker.get('seconds',240)
                elif time.time()>=next_poll:
                    next_poll=time.time()+.06
                    try:
                        state=client.get('http://127.0.0.1:8766/api/state',timeout=.5).json()
                        current=state.get('current') or {}
                        paint=state.get('luna_output',{}).get('paint') or {}
                        maximum_rows=max(maximum_rows,paint.get('visible_rows',0))
                        saw_ruby=saw_ruby or bool(paint.get('ruby_count'))
                        saw_idle_clear=saw_idle_clear or current.get('display_expired',False)
                        key=(current.get('utterance_id'),current.get('revision'))
                        if current.get('text') and key not in seen and not current.get('display_expired'):
                            seen.add(key);rows.append({'t':time.time()-marker['play_wall_time'],
                                'id':key[0],'phase':current.get('phase'),'text':current['text']})
                        for row in client.get('http://127.0.0.1:8766/api/metrics',timeout=.5).json()['observations']:
                            if row['wall_time']>=marker['play_wall_time']:
                                metrics[(row['utterance_id'],row['revision'])]=row
                    except requests.RequestException:errors+=1
                    elapsed=time.time()-marker['play_wall_time']
                    if elapsed-last_progress>=30:
                        last_progress=elapsed
                        print(json.dumps({'elapsed':round(elapsed),'updates':len(rows),
                            'finals':sum(r['phase']=='final' for r in rows)}),flush=True)
                time.sleep(.003)
    if not marker:raise RuntimeError('No playback marker')
    seconds=marker.get('seconds',240);play=marker['play_wall_time']
    # WASAPI can omit initial idle callbacks. Preserve their timeline as silence.
    offset=int((play-first_buffer)*rate) if first_buffer is not None else 0
    pcm=b''.join(raw);raw.clear()
    if offset>=0:pcm=pcm[offset*channels*2:]
    else:pcm=bytes(-offset*channels*2)+pcm
    pcm=pcm[:int(seconds*rate)*channels*2]
    ffmpeg=Path(config.get('ffmpeg_bin',''))/'ffmpeg.exe'
    command=[str(ffmpeg) if ffmpeg.is_file() else 'ffmpeg','-v','error','-f','s16le','-ar',str(rate),
             '-ac',str(channels),'-i','pipe:0','-f','s16le','-ar','16000','-ac','1','pipe:1']
    mono=subprocess.run(command,input=pcm,capture_output=True,check=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    del pcm
    values=list(metrics.values());asr=sorted(r['asr_seconds'] for r in values if r.get('asr_seconds') is not None)
    report={'source':'actual anime, independent raw WASAPI in RAM','trial_id':trial,
        'seconds':seconds,'media_start':marker['media_start'],'model':config['local_model'],
        'capture_vad_threshold':config.get('capture_vad_threshold',.4),
        'capture_pipeline':config.get('capture_pipeline','tiger'),
        'maximum_visible_rows':maximum_rows,'saw_ruby':saw_ruby,'saw_idle_clear':saw_idle_clear,
        'captured_seconds':len(mono)/32000,'stream_ready_before_play':ready<=play,
        'drafts':sum(r['phase']=='draft' and r['characters']>0 for r in values),
        'finals':sum(r['phase']=='final' for r in values),
        'empty_finals':sum(r['phase']=='cancelled' for r in values),
        'asr_median':asr[len(asr)//2] if asr else None,
        'asr_p95':asr[int((len(asr)-1)*.95)] if asr else None,
        'asr_max':max(asr) if asr else None,'poll_errors':errors,
        'segments':[{'id':uid,'max_audio_seconds':max(r.get('audio_seconds') or 0 for r in values if r['utterance_id']==uid),
            'nonempty_updates':sum(r['characters']>0 for r in values if r['utterance_id']==uid),
            'final_characters':next((r['characters'] for r in reversed(values) if r['utterance_id']==uid and r['phase'] in ('final','cancelled')),None)}
            for uid in sorted(set(r['utterance_id'] for r in values))]}
    path=root/f"logs/short-anime-{marker.get('tag','trial')}.json"
    write_json(path,report)
    write_json(root/'logs/short-trial-active.json',{'trial_id':trial,'state':'captured'})
    print(json.dumps({'captured':seconds,'segments':len(report['segments'])}),flush=True)
    # Parent pauses anime and unloads the live model before permitting reference.
    deadline=time.time()+300
    while time.time()<deadline:
        request=read_json(root/'work/short-trial-reference.json')
        if request.get('trial_id')==trial:break
        time.sleep(.1)
    else:raise RuntimeError('Reference not requested')
    from faster_whisper import WhisperModel
    from jcaption.local_models import model_directory
    from jcaption.whisper_filter import WhisperPhraseFilter
    model=WhisperModel(str(model_directory(root,config['local_model'])),device='cuda',compute_type='float16',local_files_only=True)
    filt=WhisperPhraseFilter.from_config(config)
    samples=np.frombuffer(mono,dtype='<i2').astype(np.float32)/32768
    references=[];disagreements=[]
    # A 16-second window, with 2 seconds of left/right context around 12 seconds.
    for center in range(0,int(seconds),12):
        begin=max(0,center-2);end=min(seconds,center+14)
        segs,_=model.transcribe(samples[int(begin*16000):int(end*16000)],language=config.get('language','ja'),
            beam_size=3,vad_filter=False,word_timestamps=True,condition_on_previous_text=False,temperature=0)
        for seg in segs:
            start,stop=begin+seg.start,begin+seg.end
            if not center<= (start+stop)/2 < center+12:continue
            text=filt.apply(seg.text).strip()
            if not norm(text):continue
            nearby=[r['text'] for r in rows if start-1<=r['t']<=stop+5]
            target=norm(text)
            similarity=max([1.0 if target in norm(t) else difflib.SequenceMatcher(None,target,norm(t),autojunk=False).ratio() for t in nearby] or [0])
            row={'start':round(start,2),'end':round(stop,2),'characters':len(target),'live_similarity':round(similarity,3)}
            references.append(row)
            if (stop-start<=2.5 and len(target)<=20 and similarity<.6):
                disagreements.append(row)
                if len(disagreements)<=12:
                    print(json.dumps({'transient_short_disagreement':{**row,'reference':text,
                        'nearby_live':[line[-90:] for line in nearby[-2:]]}},ensure_ascii=True),flush=True)
        print(json.dumps({'reference_seconds':min(center+12,seconds)}),flush=True)
    report.update(reference_segments=references,short_disagreements=disagreements,
        scope='Offline reference is ASR, not human truth; disagreements are candidates, not measured omissions/CER.')
    write_json(path,report)
    write_json(root/'logs/short-trial-active.json',{'trial_id':trial,'state':'done'})
    print(json.dumps({'reference_done':True,'short_disagreements':len(disagreements),'report':str(path)}),flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    trial=uuid.uuid4().hex
    backend=ROOT/'apps/TigerBackend/audioWhisper'
    shutil.copy2(ROOT/'plugins/short_caption_check.py',backend/'Plugins/short_caption_check.py')
    profile=ROOT/'work/short-caption-host.json'
    write_json(profile,{'plugins':{'ShortCaptionCheckPlugin':True},'plugin_settings':{}})
    environment={**os.environ,'JP_CAPTION_ROOT':str(ROOT),'JP_CAPTION_SHORT_TRIAL':trial,'PYTHONIOENCODING':'utf-8'}
    process=subprocess.Popen([str(backend/'audioWhisper.exe'),'--plugin_host','--config',str(profile)],
        cwd=backend,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for line in process.stdout:
            try:value=json.loads(line)
            except ValueError:continue
            if any(k in value for k in ('elapsed','captured','reference_seconds','reference_done','transient_short_disagreement','short_trial_error')):
                print(json.dumps(value,ensure_ascii=True),flush=True)
            if value.get('reference_done') or value.get('short_trial_error'):
                process.stdin.write('{"type":"quit"}\n');process.stdin.flush();break
        process.wait(timeout=15)
    finally:
        if process.poll() is None:process.terminate()


if __name__=='__main__':main()
