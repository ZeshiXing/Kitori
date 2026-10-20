"""Same loaded model, baseline vs rolling on self-authored synthetic audio.

Not an anime accuracy test. Stores only durations/counts and edit distances.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unicodedata
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from jcaption.local_models import MODELS, backend_for
from jcaption.settings import read_json, write_json

TEXT = ('今日は日本語の字幕を見ながら勉強しています。'
        '長い文章の途中でも文字が少しずつ表示されます。'
        '確認できた音声は繰り返し計算せず、新しい言葉を処理します。'
        '最後の言葉まで表示できるか確認しています。')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c)[0] in 'LN')


def distance(left, right):
    row = list(range(len(right)+1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = new
    return row[-1]


def check(name):
    from jcaption.local_asr import create_local_engine
    config = read_json(ROOT/'config/caption.json')
    config['local_model'] = name
    engine = create_local_engine(ROOT, config)
    raw = getattr(engine, 'engine', engine)
    with wave.open(str(ROOT/'work/rolling-probe.wav'), 'rb') as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        pcm = audio.readframes(audio.getnframes())
    results, synthetic_debug = {}, {}
    try:
        # Both lanes use the very same loaded weights and quality settings.
        for lane in ('baseline', 'rolling'):
            calls, texts = [], []
            if lane == 'rolling':
                engine.set_utterance(('synthetic-rolling-check', 0))
            offsets = list(range(24000, len(pcm), 24000)) + [len(pcm)]
            for index, offset in enumerate(offsets):
                chunk, final = pcm[:offset], index == len(offsets)-1
                started = time.perf_counter()
                if lane == 'baseline' and backend_for(name) == 'whisper':
                    import numpy as np
                    options = {} if config.get('whisper_standard_decode') else {'temperature':0,'condition_on_previous_text':False}
                    segments, _ = raw.model.transcribe(
                        np.frombuffer(chunk,dtype='<i2').astype(np.float32)/32768,
                        language='ja', task='transcribe', vad_filter=False,
                        beam_size=max(3, raw.draft_beam) if final else raw.draft_beam,
                        word_timestamps=False, **options)
                    text = ''.join(s.text for s in segments).strip()
                else:
                    text = (raw.transcribe(chunk,16000,final) if lane == 'baseline' else
                            engine.transcribe(chunk,16000,final))
                calls.append(time.perf_counter()-started)
                texts.append(text)
            if lane == 'rolling':
                before = engine.inference_stats()['calls']
                assert engine.transcribe(pcm,16000,True) == texts[-1]
                assert engine.inference_stats()['calls'] == before
            ordered = sorted(calls)
            results[lane] = {'updates':len(calls), 'decode_wall_seconds':sum(calls),
                             'median_call_seconds':ordered[len(ordered)//2],
                             'p95_call_seconds':ordered[int((len(ordered)-1)*.95)],
                             'final_call_seconds':calls[-1],
                             'nonempty_drafts':sum(bool(t) for t in texts[:-1]),
                             'reference_characters':len(normalized(TEXT)),
                             'final_character_edits':distance(normalized(TEXT),normalized(texts[-1]))}
            if lane == 'rolling':
                results[lane]['scheduler'] = engine.inference_stats()
            # Explicitly synthetic diagnostic, never normal capture logging.
            print(json.dumps({'synthetic_lane':lane,'final':texts[-1]},ensure_ascii=True),flush=True)
            synthetic_debug[lane] = texts
        write_json(ROOT/f'work/rolling-synthetic-texts-{name}.json',
                   {'source':'self-authored synthetic only','reference':TEXT,'lanes':synthetic_debug})
        write_json(ROOT/f'logs/rolling-check-{name}.json',
                   {'model':name,'source':'self-authored Microsoft Haruka synthetic PCM',
                    'audio_seconds':len(pcm)/32000,'results':results,
                    'scope':'unpaced replay, model already loaded; not playback latency or anime CER'})
        print(json.dumps(results),flush=True)
    finally:
        engine.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=MODELS, default='large-v3')
    args = parser.parse_args()
    if backend_for(args.model) == 'whisper' and not os.environ.get('WT_PLUGIN_HOST'):
        backend = ROOT/'apps/TigerBackend/audioWhisper'
        shutil.copy2(ROOT/'plugins/local_model_check.py', backend/'Plugins/local_model_check.py')
        profile = ROOT/'logs/rolling-check-host.json'
        write_json(profile, {'plugins':{'LocalModelCheckPlugin':True},'plugin_settings':{}})
        env = {**os.environ,'JP_CAPTION_ROOT':str(ROOT),'JP_CAPTION_CHECK_MODEL':args.model,
               'JP_CAPTION_CHECK_SCENARIO':'rolling','PYTHONIOENCODING':'utf-8'}
        started = time.time()
        outcome = subprocess.run([str(backend/'audioWhisper.exe'),'--plugin_host','--config',str(profile)],
                                 cwd=backend,env=env,input='{"type":"quit"}\n',text=True,
                                 encoding='utf-8',errors='replace',capture_output=True,timeout=300,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        print(outcome.stdout[-6000:])
        report = ROOT/f'logs/rolling-check-{args.model}.json'
        if outcome.returncode or not report.is_file() or report.stat().st_mtime < started:
            raise SystemExit(outcome.stderr[-2500:])
        print(report.read_text(encoding='utf-8'))
    else:
        check(args.model)
