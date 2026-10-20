"""Model metadata and verified local assets; inference remains in upstream libraries."""
import json
from pathlib import Path

WHISPER_MODELS = ('tiny', 'base', 'small', 'medium', 'large-v2', 'large-v3', 'large-v3-turbo')
EXTRA_MODELS = json.loads(Path(__file__).with_name('local_model_catalog.json').read_text(encoding='utf-8'))
MODELS = (*WHISPER_MODELS, *EXTRA_MODELS)
NATIVE_BACKENDS = ('vulkan', 'cuda', 'cpu')
RUNTIME_VERSION = 'v0.9.2-drama3-base-small'
RUNTIME_PACKAGES = {
    'vulkan': [('audio-v0.9.2-drama3-base-small-bin-windows-x64-vulkan-portable.zip',
                '9c943d406af3543cc5005d158ed583210cd7a13371bffcd4b7f262f7a6a5ad16')],
    'cuda': [('audio-v0.9.2-drama3-base-small-bin-windows-x64-cuda13.3.zip',
              'b570efa4b17c2aa32c431c653489c009b58f57f60d68782b3b94b6c06304a9e8'),
             ('audio-v0.9.2-drama3-base-small-cudart-windows-x64-cuda13.3.zip',
              'cf58e70c53db680af5e4b8e5ef538ffd1d81bd489ef49843fe486fcd079c9182')],
    # The portable Vulkan package includes the CPU backend too.
    'cpu': [('audio-v0.9.2-drama3-base-small-bin-windows-x64-vulkan-portable.zip',
             '9c943d406af3543cc5005d158ed583210cd7a13371bffcd4b7f262f7a6a5ad16')],
}


def backend_for(name):
    return EXTRA_MODELS[name]['backend'] if name in EXTRA_MODELS else 'whisper'


def is_whisper(name):
    return name in MODELS and backend_for(name) == 'whisper'


def model_label(name):
    return EXTRA_MODELS[name]['label'] if name in EXTRA_MODELS else 'Whisper ' + str(name)


def model_directory(root, name):
    if name not in MODELS:
        raise ValueError('不支持的本地模型')
    return (Path(root) / 'models' / name if name in EXTRA_MODELS else
            Path(root) / 'apps/TigerBackend/audioWhisper/.cache/whisper' / (name + '-ct2-fp16'))


def runtime_directory(root, backend='vulkan'):
    if backend not in NATIVE_BACKENDS:
        raise ValueError('不支持的本地推理设备')
    return Path(root) / 'apps/audio.cpp' / (RUNTIME_VERSION + '-' + ('vulkan' if backend == 'cpu' else backend))


def runtime_executable(root, backend='vulkan'):
    matches = list(runtime_directory(root, backend).rglob('audiocpp_server.exe'))
    if len(matches) != 1:
        raise ValueError('请先准备 audio.cpp 运行环境')
    return matches[0]


def validate_language(name, language):
    if name in ('kotoba-v2', 'reazonspeech-k2') and language not in ('auto', 'ja', None):
        raise ValueError('所选模型只支持日语，请选择日语或 Default')


def assets_installed(root, name):
    if name not in EXTRA_MODELS:
        return False
    entry = EXTRA_MODELS[name]
    directory = model_directory(root, name)
    try:
        receipt = json.loads((directory / 'installed.json').read_text(encoding='utf-8'))
        return (receipt == {key: file['sha256'] for key, file in entry['files'].items()} and
                all((directory / key).stat().st_size == file['size'] for key, file in entry['files'].items()))
    except (OSError, ValueError):
        return False


def runtime_ready(root, name, native_backend='vulkan'):
    kind = backend_for(name)
    if kind in ('qwen3_asr', 'voxtral_realtime'):
        try:
            directory = runtime_directory(root, native_backend)
            receipt = json.loads((directory / 'installed.json').read_text(encoding='utf-8'))
            runtime_executable(root, native_backend)
            return receipt == dict(RUNTIME_PACKAGES[native_backend])
        except (OSError, ValueError):
            return False
    if kind == 'reazon':
        # Worker uses this project's Python, never Tiger's frozen environment.
        site = Path(root) / '.venv/Lib/site-packages'
        return (site / 'sherpa_onnx/__init__.py').is_file() and (site / 'numpy/__init__.py').is_file()
    return True


def model_ready(root, name, native_backend='vulkan'):
    from .settings import model_installed
    return model_installed(root, name) and runtime_ready(root, name, native_backend)
