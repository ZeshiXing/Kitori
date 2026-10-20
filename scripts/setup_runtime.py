"""Prepare separately downloaded upstream resources for the desktop installer."""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from install_local_model import download, checksum
from jcaption.settings import write_json, model_installed


def safe_extract(archive, destination):
    """Reject Windows absolute paths, traversal, links and ambiguous ZIP names."""
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            name = item.filename.replace('\\', '/')
            parts = name.split('/')
            if (PureWindowsPath(name).drive or name.startswith('/') or '..' in parts or
                    ':' in name or stat.S_ISLNK(item.external_attr >> 16) or
                    any(p.endswith((' ', '.')) for p in parts if p)):
                raise ValueError('Unsafe runtime archive member')
            target = (destination / name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Runtime archive escapes installation directory')
        package.extractall(destination)


def resource_archive(entry, cache):
    errors = []
    for url in entry['urls']:
        target = cache / entry.get('filename', url.rsplit('/', 1)[-1])
        try:
            download(url, target, entry['sha256'], entry.get('size'))
            return target
        except Exception as error:
            errors.append(str(error))
    raise RuntimeError('Download failed; run setup again to resume: ' + '; '.join(errors))


def install_archive(entry, cache, destination, executable):
    receipt = destination / '.jcaption-resource.json'
    if receipt.is_file() and (destination / executable).is_file():
        installed = json.loads(receipt.read_text(encoding='utf-8'))
        if installed.get('sha256') == entry['sha256']:
            print('Already prepared: ' + destination.name, flush=True)
            return
    if destination.exists():
        raise RuntimeError('Existing unverified runtime was kept: ' + str(destination))
    archive = resource_archive(entry, cache)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / ('.setup-' + uuid.uuid4().hex)
    temporary.mkdir()
    print('Unpacking ' + destination.name + '...', flush=True)
    try:
        safe_extract(archive, temporary)
        if entry.get('source_root'):
            source = (temporary / entry['source_root']).resolve()
            renamed = (temporary / entry['target_root']).resolve()
            if source.parent != temporary.resolve() or renamed.parent != temporary.resolve():
                raise ValueError('Invalid runtime root mapping')
            source.rename(renamed)
            for filename, expected in entry.get('file_checksums', {}).items():
                if checksum(renamed / filename) != expected:
                    raise ValueError('Runtime source/model file checksum mismatch')
        if not (temporary / executable).is_file():
            raise RuntimeError('Upstream archive layout has changed')
        write_json(temporary / '.jcaption-resource.json', {'sha256': entry['sha256'], 'version': entry['version']})
        temporary.rename(destination)
    finally:
        if temporary.exists():
            assert temporary.resolve().parent == destination.parent.resolve() and temporary.name.startswith('.setup-')
            shutil.rmtree(temporary)


def install_whisper(root, name, cache):
    if model_installed(root, name):
        print('Model already prepared: ' + name, flush=True)
        return
    catalog = json.loads((root / 'jcaption/model_catalog.json').read_text(encoding='utf-8'))
    entry = catalog[name]
    archive = resource_archive({'urls': entry['urls'], 'sha256': entry['checksum']}, cache)
    target = root / 'apps/TigerBackend/audioWhisper/.cache/whisper'
    directory = target / (name + '-ct2-fp16')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '.caption-download-incomplete').touch()
    safe_extract(archive, target)
    for filename, expected in entry['file_checksums'].items():
        if checksum(directory / filename) != expected:
            raise ValueError('Whisper model file checksum mismatch: ' + filename)
    write_json(directory / 'hash_checked', entry['file_checksums'])
    (directory / '.caption-download-incomplete').unlink()


def initial_configuration(root, mode, language):
    path = root / 'config/caption.json'
    if not path.exists():
        config = json.loads((root / 'config/caption.example.json').read_text(encoding='utf-8'))
        config.update(local_model='small' if mode == 'cpu' else 'large-v3-turbo',
                      device='cuda' if mode == 'gpu' else 'cpu',
                      compute_type='float16' if mode == 'gpu' else 'int8',
                      recognition_source='windows_livecaptions' if mode == 'windows' else 'models')
        if mode != 'windows':
            config['ffmpeg_bin'] = str(root / 'apps/TigerBackend/toolchain/ffmpeg/bin')
        write_json(path, config)
    if not (root / 'config/ui.json').exists():
        write_json(root / 'config/ui.json', {'language': language})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['gpu', 'cpu', 'windows'], required=True)
    parser.add_argument('--language', choices=['zh', 'en', 'ja'], default='zh')
    parser.add_argument('--with-luna', action='store_true')
    parser.add_argument('--cache-dir', type=Path)
    args = parser.parse_args()
    root = ROOT
    resources = json.loads((root / 'scripts/setup_resources.json').read_text(encoding='utf-8'))
    cache = (args.cache_dir or root / 'downloads').resolve()
    cache.mkdir(parents=True, exist_ok=True)
    (root / 'logs').mkdir(exist_ok=True)
    if args.mode != 'windows':
        print('Preparing Whispering Tiger (5.1 GB download)...', flush=True)
        install_archive(resources['tiger'], cache, root / 'apps/TigerBackend', Path('audioWhisper/audioWhisper.exe'))
        print('Preparing Silero voice activity detection...', flush=True)
        install_archive(resources['silero'], cache, root / 'apps/TigerBackend/audioWhisper/.cache/silero-vad-v5',
                        Path('snakers4_silero-vad_master/src/silero_vad/data/silero_vad.jit'))
        print('Preparing Whisper model...', flush=True)
        install_whisper(root, 'small' if args.mode == 'cpu' else 'large-v3-turbo', cache)
    if args.with_luna:
        print('Preparing optional LunaTranslator...', flush=True)
        install_archive(resources['luna'], cache, root / 'apps/LunaTranslator', Path('LunaTranslator_x64/LunaTranslator.exe'))
    initial_configuration(root, args.mode, args.language)
    env = os.environ.copy()
    env['JP_CAPTION_ROOT'] = str(root)
    env['PYTHONIOENCODING'] = 'utf-8'
    print('Checking the runtime...', flush=True)
    subprocess.run([sys.executable, str(root / 'scripts/check_local_runtime.py'), '--mode', 'local'],
                   cwd=root, env=env, check=True)
    subprocess.run([sys.executable, str(root / 'scripts/prepare_runtime.py'), '--mode', 'local', '--timeout', '180'],
                   cwd=root, env=env, check=True)
    write_json(root / '.jcaption-install.json', {'status': 'complete', 'version': '0.3.0', 'mode': args.mode})
    print('Ready. Open Settings.cmd. Windows Live Captions needs its language pack enabled in Windows first.'
          if args.mode == 'windows' else 'Ready. Open Start-Local.cmd or Settings.cmd.', flush=True)


if __name__ == '__main__':
    main()
