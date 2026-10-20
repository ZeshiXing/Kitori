"""Install pinned external weights/runtime. No model code or user keys are downloaded."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jcaption.local_models import (EXTRA_MODELS, RUNTIME_PACKAGES, RUNTIME_VERSION,
                                   model_directory, runtime_directory, backend_for, runtime_ready)
from jcaption.settings import write_json
import requests


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url, target, expected, size=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (size is None or target.stat().st_size == size) and checksum(target) == expected:
        return
    partial = target.with_name(target.name + '.part')
    offset = partial.stat().st_size if partial.exists() else 0
    with requests.get(url, headers={'Range': f'bytes={offset}-'} if offset else {},
                      stream=True, timeout=(15, 45)) as response:
        response.raise_for_status()
        if response.status_code == 206:
            if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                raise ValueError('Unexpected download byte range')
        elif response.status_code == 200:
            offset = 0
        else:
            raise ValueError('Unexpected download response')
        with partial.open('ab' if offset else 'wb') as output:
            total = offset
            last = total // (16 * 1024 * 1024)
            for block in response.iter_content(1024 * 1024):
                output.write(block)
                total += len(block)
                if total // (16 * 1024 * 1024) != last:
                    last = total // (16 * 1024 * 1024)
                    print(json.dumps({'resource':target.name, 'downloaded_MB':round(total / 1e6),
                                      'total_MB':round(size / 1e6) if size else None}), flush=True)
    if (size is not None and partial.stat().st_size != size) or checksum(partial) != expected:
        partial.unlink(missing_ok=True)
        raise ValueError('下载校验失败，请重试')
    partial.replace(target)


def install(name, backend='vulkan'):
    entry = EXTRA_MODELS[name]
    directory = model_directory(ROOT, name)
    for filename, item in entry['files'].items():
        download(item['url'], directory / filename, item['sha256'], item['size'])
    write_json(directory / 'installed.json', {key: file['sha256'] for key, file in entry['files'].items()})
    if backend_for(name) in ('qwen3_asr', 'voxtral_realtime') and not runtime_ready(ROOT, name, backend):
        destination = runtime_directory(ROOT, backend)
        for filename, expected in RUNTIME_PACKAGES[backend]:
            archive = ROOT / 'downloads' / filename
            download(f'https://github.com/0xShug0/audio.cpp/releases/download/{RUNTIME_VERSION}/{filename}',
                     archive, expected)
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    if not (destination / member.filename).resolve().is_relative_to(destination.resolve()):
                        raise ValueError('Invalid runtime archive path')
                package.extractall(destination)
        write_json(destination / 'installed.json', dict(RUNTIME_PACKAGES[backend]))
    elif backend_for(name) == 'reazon' and not runtime_ready(ROOT, name):
        python = ROOT / '.venv/Scripts/python.exe'
        if not python.is_file():
            raise ValueError('请先准备本项目的 .venv')
        subprocess.run([str(python), '-m', 'pip', 'install', 'sherpa-onnx==1.13.3', 'numpy>=2,<3'], check=True)
    print(json.dumps({'installed':name, 'verified':True}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=EXTRA_MODELS, required=True)
    parser.add_argument('--native-backend', choices=RUNTIME_PACKAGES, default='vulkan')
    args = parser.parse_args()
    install(args.model, args.native_backend)
