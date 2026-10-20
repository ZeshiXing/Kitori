"""Use Tiger's official plugin host to check the bridge and detect speaker loopback."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['local'], default='local')
parser.add_argument('--timeout', type=float, default=60,
                    help='Host check deadline; installers allow more time for first-run initialization')
args = parser.parse_args()
if not 1 <= args.timeout <= 300:
    parser.error('--timeout must be between 1 and 300 seconds')
backend = ROOT / 'apps/TigerBackend/audioWhisper'
config_file = ROOT / 'config/caption.json'
config = json.loads(config_file.read_text(encoding='utf-8-sig'))
from jcaption.settings import local_config, capture_vad_threshold
config = local_config(config)
config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
if config.get('recognition_source') == 'windows_livecaptions':
    from jcaption.windows_captions import prepare_reader
    prepare_reader(ROOT)
    print(json.dumps({'source': 'windows_livecaptions', 'prepared': True}))
    raise SystemExit(0)
(backend / 'Plugins').mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT / 'plugins/japanese_caption.py', backend / 'Plugins/japanese_caption.py')
host_profile = ROOT / 'config/tiger-plugin-host.yaml'
host_profile.write_text(json.dumps({'plugins': {'JapaneseCaptionPlugin': True},
                                    'plugin_settings': {}, 'plugin_timer': 2}, indent=2), encoding='utf-8')
environment = os.environ.copy()
environment['JP_CAPTION_ROOT'] = str(ROOT)
environment['PYTHONIOENCODING'] = 'utf-8'
if config.get('ffmpeg_bin'):
    environment['PATH'] = config['ffmpeg_bin'] + os.pathsep + environment.get('PATH', '')
try:
    result = subprocess.run([str(backend / 'audioWhisper.exe'), '--plugin_host', '--config', str(host_profile)],
                            input='{"type":"quit"}\n',
                            text=True, encoding='utf-8', errors='replace', capture_output=True,
                            cwd=backend, env=environment, timeout=args.timeout)
except subprocess.TimeoutExpired as error:
    def decoded(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
    (ROOT / 'logs/plugin-host-check.log').write_text(
        decoded(error.stdout) + '\n' + decoded(error.stderr), encoding='utf-8')
    raise SystemExit('Tiger host check timed out; see logs/plugin-host-check.log and retry.')
(ROOT / 'logs/plugin-host-check.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
replies = []
for line in result.stdout.splitlines():
    try:
        value = json.loads(line)
        if isinstance(value, dict): replies.append(value)
    except ValueError:
        pass
if result.returncode or any(r.get('type') == 'error' for r in replies):
    print(result.stdout[-3000:] + result.stderr[-3000:])
    raise SystemExit('Tiger plugin-host verification failed; see logs/plugin-host-check.log')
if not any('JapaneseCaptionPlugin' in r.get('enabled', []) for r in replies):
    raise SystemExit('Caption plugin was not enabled by the upstream host')
device = json.loads((ROOT / 'logs/audio-device.json').read_text(encoding='utf-8'))
if not device.get('isLoopbackDevice') or device.get('maxInputChannels', 0) < 1:
    raise SystemExit('No valid speaker loopback device found; microphone capture is not used')
profile = {
    'audio_api': 'WASAPI', 'audio_input_device': device['name'], 'device_index': device['index'],
    'audio_output_device': 'Default', 'stt_enabled': True,
    'stt_type': '',
    'model': config['local_model'], 'current_language': config['language'],
    'whisper_task': 'transcribe', 'ai_device': config['device'], 'ai_device_index': 0,
    'whisper_precision': config['compute_type'], 'whisper_cpu_threads': 4,
    'condition_on_previous_text': False, 'beam_size': 3,
    'energy': 80, 'pause': 0.6, 'phrase_time_limit': config.get('stream_window_seconds', 15),
    'vad_enabled': True, 'vad_confidence_threshold': capture_vad_threshold(config),
    'realtime': True, 'realtime_frequency_time': config.get('local_stream_chunk_seconds', 0.5),
    'realtime_frame_multiply': 1, 'realtime_whisper_model': '',
    'txt_translate': False, 'txt_translator': '',
    'tts_answer': False, 'tts_type': '',
    'osc_ip': '0', 'osc_server_ip': '0', 'websocket_ip': '0', 'verbose': False,
    'plugins': {'JapaneseCaptionPlugin': True}, 'plugin_settings': {},
    'ui_download': False, 'additional_audio_routes': [],
}
# Preserve timestamps and upstream normalization for quiet anime speech.
profile['silence_cutting_enabled'] = False
(ROOT / 'config/tiger.yaml').write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
from jcaption.local_models import backend_for
if backend_for(config['local_model']) == 'voxtral_realtime':
    # Stateful models need consistent growing PCM. Re-normalizing/cutting each
    # whole prefix changes already submitted samples and forces stream resets.
    profile.update(normalize_enabled=False, silence_cutting_enabled=False, denoise_audio='')
    (ROOT / 'config/tiger.yaml').write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'plugin_verified': True, 'mode': args.mode,
                  'loopback_index': device['index'], 'loopback_name': device['name'],
                  'model': config['local_model']}, ensure_ascii=True))
