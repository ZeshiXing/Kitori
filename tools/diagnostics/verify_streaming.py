"""Actual synthetic playback -> loopback -> GPU ASR -> independent captions.

Stores timing/count metadata only. This is not an animation accuracy benchmark.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import wave
import winsound

import requests

ROOT = Path(__file__).resolve().parents[2]
TEXT = '今日は日本語の字幕を見ながら勉強していますが、長い文章を話している途中にも、文字が少しずつ表示されるかどうかを確認しています。'
config = json.loads((ROOT / 'config/caption.json').read_text(encoding='utf-8'))
url = f"http://127.0.0.1:{config.get('caption_port', 8766)}"
client = requests.Session()
client.trust_env = False
subprocess.run(['powershell.exe', '-NoProfile', '-File', str(ROOT / 'tools/diagnostics/play_demo.ps1'),
                '-GenerateOnly', '-Text', TEXT], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
with wave.open(str(ROOT / 'logs/demo-ja.wav')) as audio:
    duration = audio.getnframes() / audio.getframerate()
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    status = json.loads((ROOT / 'logs/status.json').read_text(encoding='utf-8'))
    log = (ROOT / 'logs/runtime.log').read_text(encoding='utf-8')
    if ('Whispering Tiger is now ready!' in log or 'JP_CAPTION_CAPTURE_READY' in log) and status.get('streaming'):
        break
    time.sleep(0.5)
else:
    raise SystemExit('Streaming backend was not ready')
baseline = client.get(url + '/api/metrics', timeout=2).json()['observations']
if any(row['wall_time'] > time.time() - 3 for row in baseline):
    raise SystemExit('Other desktop audio is being transcribed. Pause other audio before this latency check.')
started = time.time()
winsound.PlaySound(str(ROOT / 'logs/demo-ja.wav'), winsound.SND_FILENAME | winsound.SND_ASYNC)
print(json.dumps({'playback_started': True, 'audio_seconds': duration}), flush=True)
deadline = time.monotonic() + duration + 12
observations = []
paint_observations = []
last_paint = None
while time.monotonic() < deadline:
    metrics = client.get(url + '/api/metrics', timeout=2).json()
    observations = [row for row in metrics['observations'] if row['wall_time'] >= started]
    if config.get('luna_output_enabled'):
        output = client.get(url + '/api/state', timeout=2).json()['luna_output']
        paint = output.get('paint')
        if paint and paint != last_paint:
            paint_observations.append({**paint, 'seconds_after_play_call':time.time()-started})
            last_paint = paint
    if time.time() >= started + duration and any(row['phase'] == 'final' for row in observations):
        break
    time.sleep(0.1)
drafts = [row for row in observations if row['phase'] == 'draft' and row['characters']]
finals = [row for row in observations if row['phase'] == 'final']
state = client.get(url + '/api/state', timeout=2).json()
current = state['current'] or {}
result = {
    'local_model': config['local_model'],
    'configured_language': config.get('language'),
    'detected_language': current.get('language'),
    'source': 'Microsoft Haruka synthetic Japanese, WASAPI speaker loopback',
    'timing_valid': True,
    'audio_seconds_including_2s_silence': duration,
    'speech_seconds_approximate': duration - 2,
    'first_draft_seconds_after_play_call': drafts[0]['wall_time'] - started if drafts else None,
    'first_final_seconds_after_play_call': finals[0]['wall_time'] - started if finals else None,
    'draft_updates': len(drafts), 'final_updates': len(finals),
    'draft_before_speech_end': bool(drafts and drafts[0]['wall_time'] < started + duration - 2),
    'ruby_tokens_in_current_caption': sum(bool(row['reading']) for row in current.get('ruby', [])),
    'asr_seconds': [row['asr_seconds'] for row in observations],
    'luna_paint_observations': paint_observations,
    'luna_mixed_draft_painted': any(p['stable_characters'] and p['draft_characters'] for p in paint_observations),
    'claim_scope': 'single synthetic sample; playback-call latency, not phoneme-aligned latency or anime CER',
}
(ROOT / 'logs/streaming-check.json').write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2))
client.close()
if not result['draft_before_speech_end'] or len(drafts) < 2 or not finals:
    raise SystemExit('Actual streaming playback check failed; inspect logs/streaming-check.json')
