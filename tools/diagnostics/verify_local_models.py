"""Real model checks on explicitly synthetic Japanese; metadata-only saved reports."""
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
from jcaption.local_models import EXTRA_MODELS, backend_for
from jcaption.settings import write_json

TEXT = '今日は日本語の字幕を見ながら勉強します'


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c)[0] in 'LN')


def check(name, backend='vulkan', native_backend=None):
    from jcaption.local_asr import create_local_engine
    from jcaption.settings import read_json
    config = read_json(ROOT / 'config/caption.json')
    ffmpeg = str(Path(config['ffmpeg_bin']) / 'ffmpeg.exe') if config.get('ffmpeg_bin') else 'ffmpeg'
    output = ROOT / 'logs/local-probe-ja.wav'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(ROOT / 'logs/demo-ja.wav'),
                    '-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)], check=True, capture_output=True)
    started = time.perf_counter()
    engine = create_local_engine(ROOT, {'local_model':name, 'language':'ja', 'device':'cuda',
                                       'compute_type':'float16', 'local_native_backend':backend,
                                       'local_stream_chunk_seconds':.5})
    load_seconds = time.perf_counter() - started
    with wave.open(str(output), 'rb') as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1 and audio.getsampwidth() == 2
        pcm = audio.readframes(audio.getnframes())
    first, updates, text = None, 0, ''
    started = time.perf_counter()
    try:
        for offset in range(16000, len(pcm), 16000):
            wait = offset / 32000 - (time.perf_counter() - started)
            if wait > 0:
                time.sleep(wait)
            result = engine.transcribe(pcm[:offset], 16000, False)
            if result and result != text:
                updates += 1
                first = first if first is not None else time.perf_counter() - started
                text = result
        wait = len(pcm) / 32000 - (time.perf_counter() - started)
        if wait > 0:
            time.sleep(wait)
        result = engine.transcribe(pcm, 16000, True)
        elapsed = time.perf_counter() - started
        report = {'model':name, 'source':'synthetic Japanese PCM paced in growing 0.5s snapshots',
                  'load_seconds':load_seconds, 'first_draft_seconds':first, 'draft_updates':updates,
                  'audio_seconds':len(pcm)/32000, 'final_elapsed_seconds':elapsed,
                  'normalized_exact_match':normalize(result) == normalize(TEXT),
                  'characters':len(result), 'nonempty':bool(result),
                  'runtime_backend':('cuda' if backend_for(name) == 'whisper' else
                                     'cpu' if backend_for(name) == 'reazon' else backend)}
        write_json(ROOT / f'logs/local-check-{name}.json', report)
        print(json.dumps(report), flush=True)
        # This explicitly synthetic test result is printed for manual diagnosis,
        # never copied into the ordinary metadata report.
        print(json.dumps({'synthetic_result':result}, ensure_ascii=True), flush=True)
        if not result:
            raise RuntimeError('Model returned no synthetic transcription')
        return report
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=EXTRA_MODELS, required=True)
    parser.add_argument('--native-backend', choices=['vulkan','cuda','cpu'], default='vulkan')
    args = parser.parse_args()
    if backend_for(args.model) == 'whisper' and not os.environ.get('WT_PLUGIN_HOST'):
        # Reuse Tiger's real faster-whisper/CUDA environment without injecting
        # frozen binary dependencies into the project's different Python ABI.
        host = ROOT / 'apps/TigerBackend/audioWhisper'
        shutil.copy2(ROOT / 'plugins/local_model_check.py', host / 'Plugins/local_model_check.py')
        profile = ROOT / 'logs/local-model-check.yaml'
        write_json(profile, {'plugins':{'LocalModelCheckPlugin':True}, 'plugin_settings':{}})
        environment = os.environ.copy()
        environment.update(JP_CAPTION_ROOT=str(ROOT), JP_CAPTION_CHECK_MODEL=args.model, PYTHONIOENCODING='utf-8')
        started = time.time()
        result = subprocess.run([str(host / 'audioWhisper.exe'), '--plugin_host', '--config', str(profile)],
                                cwd=host, env=environment, input='{"type":"quit"}\n',
                                text=True, encoding='utf-8', errors='replace', capture_output=True,
                                timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        print(result.stdout[-5000:])
        report = ROOT / f'logs/local-check-{args.model}.json'
        if result.returncode or not report.exists() or report.stat().st_mtime < started:
            raise SystemExit('Real upstream model check failed: ' + result.stderr[-2000:])
        return
    check(args.model, args.native_backend)


if __name__ == '__main__':
    main()
