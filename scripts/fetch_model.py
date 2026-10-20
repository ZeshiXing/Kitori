"""Install Tiger's existing model archive and verify its upstream SHA-256."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--model', choices=['tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3', 'large-v3-turbo'], default='large-v3-turbo')
args = parser.parse_args()
entries = json.loads((ROOT / 'jcaption/model_catalog.json').read_text(encoding='utf-8'))
entry = entries[args.model]
url = next(url for url in entry['urls'] if 'eu2.' in url)
response = requests.head(url, timeout=20)
response.raise_for_status()
total = int(response.headers['content-length'])
archive = ROOT / 'downloads' / url.rsplit('/', 1)[-1]
size = 8 * 1024 * 1024
chunks = (total + size - 1) // size
parts_directory = ROOT / 'downloads' / (args.model + '-parts')
parts_directory.mkdir(parents=True, exist_ok=True)
print(json.dumps({'resource': 'asr', 'download_MB': round(total / 1e6)}), flush=True)

def fetch(index):
    start, end = index * size, min((index + 1) * size, total) - 1
    part = parts_directory / f'{index:04d}.part'
    for attempt in range(5):
        existing = part.stat().st_size if part.exists() else 0
        if existing == end - start + 1:
            return part
        try:
            with requests.get(url, headers={'Range': f'bytes={start + existing}-{end}'},
                              stream=True, timeout=(15, 40)) as response:
                if response.status_code != 206:
                    raise RuntimeError('Model server does not support range downloads')
                if response.headers.get('Content-Range') != f'bytes {start + existing}-{end}/{total}':
                    raise RuntimeError('Unexpected model byte range')
                with part.open('ab') as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk: output.write(chunk)
            if part.stat().st_size == end - start + 1:
                return part
        except (requests.RequestException, OSError):
            if attempt == 4: raise
        time.sleep(2 ** attempt)
    if part.stat().st_size != end - start + 1:
        raise RuntimeError('Incomplete model download')
    return part

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    jobs = [pool.submit(fetch, i) for i in range(chunks)]
    completed = 0
    for job in concurrent.futures.as_completed(jobs):
        job.result()
        completed += 1
        print(json.dumps({'completed_chunks': completed, 'total_chunks': chunks}), flush=True)
    parts = [parts_directory / f'{i:04d}.part' for i in range(chunks)]
digest = hashlib.sha256()
with archive.open('wb') as output:
    for part in parts:
        with part.open('rb') as source:
            while chunk := source.read(4 * 1024 * 1024):
                output.write(chunk); digest.update(chunk)
if digest.hexdigest() != entry['checksum']:
    raise RuntimeError('Upstream model archive checksum mismatch')
target = ROOT / 'apps/TigerBackend/audioWhisper/.cache/whisper'
target.mkdir(parents=True, exist_ok=True)
model_directory = target / (args.model + '-ct2-fp16')
model_directory.mkdir(exist_ok=True)
(model_directory / '.caption-download-incomplete').touch()
with zipfile.ZipFile(archive) as package:
    for info in package.infolist():
        if not (target / info.filename).resolve().is_relative_to(target.resolve()):
            raise RuntimeError('Model archive path escapes target directory')
    package.extractall(target)
for filename, expected in entry.get('file_checksums', {}).items():
    checksum = hashlib.sha256()
    with (model_directory / filename).open('rb') as source:
        while chunk := source.read(4 * 1024 * 1024):
            checksum.update(chunk)
    if checksum.hexdigest() != expected:
        raise RuntimeError('Upstream model file checksum mismatch: ' + filename)
# Tiger's own cache manifest, written only after verifying every upstream hash.
(model_directory / 'hash_checked').write_text(
    json.dumps(entry['file_checksums'], sort_keys=True), encoding='utf-8')
(model_directory / '.caption-download-incomplete').unlink(missing_ok=True)
manifest = {'resource': 'asr', 'model': args.model, 'sha256': digest.hexdigest(),
            'matches_upstream_checksum': True, 'download_bytes': total}
(ROOT / 'downloads/model-installed.json').write_text(
    json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps(manifest), flush=True)
