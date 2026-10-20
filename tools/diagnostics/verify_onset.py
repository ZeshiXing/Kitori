"""Real speaker-loopback test: Japanese speech after several silent gaps.

Only self-authored synthetic WAVs are generated. Reports contain timings and
reference edit counts, never capture audio or recognized text.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import wave
import winsound

import requests

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from jcaption.settings import write_json
from tools.diagnostics.verify_rolling_asr import normalized, distance

TEXT='明日の朝、駅の前で待ち合わせましょう。'


def prepare(quiet_onsets=False, text=TEXT):
    script=ROOT/'work/onset-voice.ps1'
    output=ROOT/'work/onset-voice.wav'
    script.write_text("""Add-Type -AssemblyName System.Speech
$taskOnsetVoice=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
 $taskOnsetVoice.SelectVoice('Microsoft Haruka Desktop')
 $taskOnsetVoice.Rate=-1
 $taskOnsetVoice.SetOutputToWaveFile('"""+str(output).replace("'","''")+"""')
 $taskOnsetVoice.Speak('"""+text.replace("'","''")+"""')
 $taskOnsetVoice.SetOutputToNull()
} finally { $taskOnsetVoice.Dispose() }
""",encoding='utf-8-sig')
    subprocess.run(['powershell.exe','-NoProfile','-File',str(script)],check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
    with wave.open(str(output),'rb') as source:
        params=source.getparams()
        pcm=source.readframes(source.getnframes())
    width=params.sampwidth*params.nchannels
    rate=params.framerate
    if quiet_onsets:
        from array import array
        values=array('h');values.frombytes(pcm)
        for i in range(min(len(values),int(.45*rate)*params.nchannels)):
            t=i/(rate*params.nchannels)
            gain=.08 if t<.3 else .08+.92*(t-.3)/.15
            values[i]=int(values[i]*gain)
        pcm=values.tobytes()
    audio=bytearray()
    starts=[]
    for gap in (4,6,10):
        audio.extend(bytes(gap*rate*width))
        starts.append(len(audio)/(rate*width))
        audio.extend(pcm)
    audio.extend(bytes(4*rate*width))
    path=ROOT/'work/onset-playback.wav'
    with wave.open(str(path),'wb') as target:
        target.setparams(params)
        target.writeframes(audio)
    return path,starts,len(audio)/(rate*width)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag',required=True)
    parser.add_argument('--quiet-onsets',action='store_true')
    parser.add_argument('--text',default=TEXT,help='Self-authored synthetic diagnostic phrase')
    args=parser.parse_args()
    path,starts,duration=prepare(args.quiet_onsets,args.text)
    client=requests.Session();client.trust_env=False
    url='http://127.0.0.1:8766'
    state=client.get(url+'/api/state',timeout=2).json()
    if not state.get('backend_ready'):
        raise SystemExit('Backend not ready')
    baseline=client.get(url+'/api/metrics',timeout=2).json()['observations']
    if any(r['wall_time']>time.time()-3 for r in baseline):
        raise SystemExit('Pause other desktop audio before this synthetic test')
    started=time.time()
    events={};samples={}
    winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
    print(json.dumps({'playing_synthetic':True,'seconds':duration,'onsets':starts}),flush=True)
    try:
        while time.time()<started+duration+2:
            for row in client.get(url+'/api/metrics',timeout=1).json()['observations']:
                if row['wall_time']>=started:
                    events[(row['utterance_id'],row['revision'])]=row
            current=client.get(url+'/api/state',timeout=1).json().get('current') or {}
            key=(current.get('utterance_id'),current.get('revision'))
            if key in events and current.get('text') and not current.get('display_expired'):
                samples[key]=current.get('text','')
            time.sleep(.04)
    finally:
        winsound.PlaySound(None,0)
    results=[]
    reference=normalized(args.text)
    for index,onset in enumerate(starts):
        end=starts[index+1] if index+1<len(starts) else duration+2
        rows=[(key,r) for key,r in events.items() if onset<=r['wall_time']-started<end]
        visible=[(k,r) for k,r in rows if r['characters']]
        correct=[r for k,r in visible if normalized(samples.get(k,'')).startswith(reference[:4])]
        finals=[(k,r) for k,r in rows if r['phase']=='final' and r['characters']]
        final_text=samples.get(finals[-1][0],'') if finals else ''
        results.append({'silent_gap_seconds':(4,6,10)[index],
                        'first_visible_after_onset':visible[0][1]['wall_time']-started-onset if visible else None,
                        'first_correct_prefix_after_onset':correct[0]['wall_time']-started-onset if correct else None,
                        'first_visible_asr_seconds':visible[0][1].get('asr_seconds') if visible else None,
                        'first_visible_audio_seconds':visible[0][1].get('audio_seconds') if visible else None,
                        'first_visible_phase':visible[0][1]['phase'] if visible else None,
                        'nonempty_drafts':sum(r['phase']=='draft' for _,r in visible),
                        'final_edits':distance(reference,normalized(final_text)),
                        'final_starts_with_reference':normalized(final_text).startswith(reference[:4]),
                        'nonempty_updates':len(visible)})
    report={'source':'Microsoft Haruka self-authored Japanese, real WASAPI loopback',
            'reference_characters':len(reference),'quiet_onsets':args.quiet_onsets,'trials':results,
            'scope':'three synthetic restarts; playback-clock timings, not anime accuracy'}
    write_json(ROOT/f'logs/onset-{args.tag}.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
