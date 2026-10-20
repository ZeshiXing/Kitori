"""Launch the upstream runtime, keeping recognized speech out of routine logs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import secrets
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
backend = ROOT / 'apps/TigerBackend/audioWhisper'
config = json.loads((ROOT / 'config/caption.json').read_text(encoding='utf-8'))
environment = os.environ.copy()
environment['JP_CAPTION_ROOT'] = str(ROOT)
environment['PYTHONIOENCODING'] = 'utf-8'
environment['PYTHONUNBUFFERED'] = '1'
from jcaption.server import CaptionService
from jcaption.luna import LunaView
from jcaption.settings import read_json, load_appearance, local_capture_pipeline
caption_session = uuid.uuid4().hex
caption_token = secrets.token_urlsafe(32)
view_config = read_json(ROOT / 'config/luna-view.json')
luna_view = (LunaView(ROOT, view_config['view_token'])
             if config.get('luna_output_enabled') and view_config.get('view_token') else None)
service = CaptionService(caption_session, caption_token, port=config.get('caption_port', 8766),
                         luna_url=config['luna_url'] if config.get('luna_output_enabled', True) else None,
                         ffmpeg_bin=config.get('ffmpeg_bin', ''), language=config.get('language', 'auto'),
                         luna_view=luna_view,
                         lookahead_enabled=config.get('recognition_source') != 'windows_livecaptions',
                         appearance_provider=lambda: load_appearance(ROOT))
service.start()
environment['JP_CAPTION_URL'] = f'http://127.0.0.1:{service.port}'
environment['JP_CAPTION_TOKEN'] = caption_token
environment['JP_CAPTION_SESSION'] = caption_session
if config.get('ffmpeg_bin'):
    environment['PATH'] = config['ffmpeg_bin'] + os.pathsep + environment.get('PATH', '')
windows_source = config.get('recognition_source') == 'windows_livecaptions'
continuous_source = not windows_source and local_capture_pipeline(config) == 'continuous'
if windows_source:
    from jcaption.windows_captions import prepare_reader
    command = [str(prepare_reader(ROOT))]
else:
    command = [str(backend / 'audioWhisper.exe'), '--config', str(ROOT / 'config/tiger.yaml')]
    if continuous_source:
        command=[str(backend/'audioWhisper.exe'),'--plugin_host','--config',str(ROOT/'config/tiger-plugin-host.yaml')]
        environment['JP_CAPTION_CONTINUOUS']='1'
process = subprocess.Popen(
    command, cwd=ROOT if windows_source else backend, env=environment,
    stdin=subprocess.PIPE if windows_source or continuous_source else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
service.on_shutdown = process.stdin.close if windows_source or continuous_source else process.terminate
overlay_process = None
tray_process = None
if config.get('display_mode') == 'luna':
    tray_process = subprocess.Popen(
        [sys.executable,str(ROOT / 'scripts/session_tray.py')], cwd=ROOT, env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=(ROOT / 'logs/tray.stdout.log').open('w',encoding='utf-8'),
        stderr=(ROOT / 'logs/tray.stderr.log').open('w',encoding='utf-8'))
if config.get('display_mode', 'overlay') in ('overlay', 'both'):
    overlay_command = [sys.executable, str(ROOT / 'scripts/native_overlay.py')]
    if config.get('startup_media'):
        overlay_command += ['--media', config['startup_media']]
    overlay_process = subprocess.Popen(
        overlay_command, cwd=ROOT, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=(ROOT / 'logs/overlay.stdout.log').open('w', encoding='utf-8'),
        stderr=(ROOT / 'logs/overlay.stderr.log').open('w', encoding='utf-8'))
(ROOT / 'logs/processes.json').write_text(json.dumps({
    'backend_pid': process.pid, 'controller_pid': os.getpid(),
    'overlay_pid': overlay_process.pid if overlay_process else None,
    'tray_pid': tray_process.pid if tray_process else None, 'started_at': time.time()
}, indent=2), encoding='utf-8')
save_transcripts = bool(config.get('save_transcripts', False))
try:
    if windows_source:
        from jcaption.windows_captions import run_reader
        run_reader(process, service, ROOT, config, caption_session)
    else:
        with (ROOT / 'logs/runtime.log').open('w', encoding='utf-8', buffering=1) as log:
            for line in process.stdout:
                if 'Whispering Tiger is now ready!' in line or line.strip()=='JP_CAPTION_CAPTURE_READY':
                    service.backend_ready = True
                    from caption_bridge import StatusFile
                    state = StatusFile(ROOT / 'logs/status.json')
                    state.state = json.loads((ROOT / 'logs/status.json').read_text(encoding='utf-8'))
                    state(stage='listening', backend='local')
                if not save_transcripts and (line.startswith('Transcribe') or 'skipping... result:' in line):
                    continue
                log.write(line)
finally:
    if process.poll() is None:
        if windows_source or continuous_source:
            process.stdin.close()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.terminate()
        else:
            process.terminate()
    service.close()
    if overlay_process and overlay_process.poll() is None:
        overlay_process.terminate()
    if tray_process and tray_process.poll() is None:
        # Include the Windows venv redirector's Qt child in cleanup.
        subprocess.run(['taskkill','/PID',str(tray_process.pid),'/T','/F'],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
exit_code = process.wait()
with (ROOT / 'logs/runtime.log').open('a', encoding='utf-8') as log:
    log.write(f'\nBackend exited with code {exit_code}\n')

