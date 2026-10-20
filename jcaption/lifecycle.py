"""Request application-wide shutdown through the project-owned stop helper."""
from pathlib import Path
import os
import subprocess


def request_restart(root, config):
    root = Path(root).resolve()
    launch = root / 'scripts/launch.ps1'
    if not launch.is_file():
        raise OSError('Caption launch helper is missing')
    logs = root / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['JP_CAPTION_NO_AUTOPLAY'] = '1'
    with (logs / 'launcher.stdout.log').open('wb') as output, (logs / 'launcher.stderr.log').open('wb') as error:
        return subprocess.Popen(['powershell.exe', '-NoProfile', '-File', str(launch),
                                 '-Mode', 'local', '-Display', config.get('display_mode', 'overlay')],
                                cwd=root, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                                stdout=output, stderr=error)


def request_exit(root):
    root = Path(root).resolve()
    stop = root / 'scripts/stop.ps1'
    if not stop.is_file():
        raise OSError('Caption stop helper is missing')
    return subprocess.Popen(['powershell.exe','-NoProfile','-File',str(stop)],
                            cwd=root, creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
