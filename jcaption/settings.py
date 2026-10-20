"""Small, atomic settings files, separate from model/runtime implementation."""
import json
from pathlib import Path
import os
import tempfile
import re
import math


from .local_models import MODELS, EXTRA_MODELS, assets_installed, model_ready, validate_language
LANGUAGES = {'auto': 'Default / 自动检测', 'ja': '日语', 'en': '英语', 'zh': '中文',
             'ko': '韩语', 'fr': '法语', 'de': '德语', 'es': '西班牙语', 'ru': '俄语',
             'it': '意大利语', 'pt': '葡萄牙语', 'ar': '阿拉伯语'}
def local_config(config):
    """Migrate retired cloud preferences without reading credentials or key files."""
    return {**{key: value for key, value in config.items()
               if not key.startswith('api_') and key != 'minimax_stream_response'}, 'mode': 'local'}


def recognition_language(config):
    language = config.get('language', 'auto')
    return None if language in ('auto', '', None, 'default') else language


def capture_vad_threshold(config):
    """Capture sensitivity; separate from offline pause-boundary detection."""
    value = config.get('capture_vad_threshold', .4)
    if type(value) not in (int, float) or not math.isfinite(value) or not .05 <= value <= .9:
        raise ValueError('Capture VAD threshold must be between 0.05 and 0.9')
    return float(value)


def local_capture_pipeline(config):
    value=config.get('capture_pipeline','continuous')
    if value not in ('continuous','tiger'):
        raise ValueError('Unsupported local capture pipeline')
    return value


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.stem, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def model_installed(root, name):
    if name not in MODELS:
        return False
    if name in EXTRA_MODELS:
        return assets_installed(root, name)
    directory = Path(root) / 'apps/TigerBackend/audioWhisper/.cache/whisper' / (name + '-ct2-fp16')
    if (directory / '.caption-download-incomplete').exists():
        return False
    # Downloads/extraction interrupted before validation are not ready to load.
    catalog = read_json(Path(__file__).with_name('model_catalog.json'))
    required = catalog[name]['file_checksums']
    return all((directory / file).is_file() and (directory / file).stat().st_size > 0 for file in required)


def save_recognition(root, values):
    """Validate the complete pending form before replacing any working setting."""
    allowed = {'recognition_source', 'local_model', 'language', 'mode', 'display_mode',
               'whisper_blocklist_enabled', 'whisper_blocklist', 'local_native_backend',
               'local_native_device', 'local_stream_chunk_seconds', 'whisper_draft_beam',
               'whisper_standard_decode'}
    if set(values) - allowed:
        raise ValueError('不支持的设置字段')
    path = Path(root) / 'config/caption.json'
    config = read_json(path)
    if not config:
        raise ValueError('无法读取字幕配置')
    if values.get('mode', 'local') != 'local':
        raise ValueError('仅支持本地识别')
    config = local_config(config)
    config.update(values)
    if type(config.get('whisper_draft_beam', 1)) is not int or config.get('whisper_draft_beam', 1) not in (1,3,5):
        raise ValueError('请选择 Whisper 草稿识别精度')
    if type(config.get('whisper_standard_decode', False)) is not bool:
        raise ValueError('Whisper 标准解码选项无效')
    windows_source = config.get('recognition_source', 'models') == 'windows_livecaptions'
    if config.get('recognition_source', 'models') not in ('models', 'windows_livecaptions'):
        raise ValueError('请选择支持的识别来源')
    from .whisper_filter import validate_blocklist
    if type(config.get('whisper_blocklist_enabled', False)) is not bool:
        raise ValueError('屏蔽幻觉词汇开关无效')
    if 'whisper_blocklist' in config:
        config['whisper_blocklist'] = validate_blocklist(config['whisper_blocklist'])
    if config.get('display_mode', 'overlay') not in ('overlay', 'luna', 'both'):
        raise ValueError('请选择支持的字幕显示端')
    config['luna_output_enabled'] = config.get('display_mode', 'overlay') in ('luna', 'both')
    if config.get('language') not in LANGUAGES:
        raise ValueError('请选择支持的识别语言')
    if config.get('local_model') not in MODELS:
        raise ValueError('请选择支持的本地模型')
    if config.get('local_native_backend', 'vulkan') not in ('vulkan', 'cuda', 'cpu'):
        raise ValueError('请选择支持的本地推理设备')
    device = config.get('local_native_device', -1)
    if type(device) is not int or not -1 <= device <= 15:
        raise ValueError('本地设备编号必须为自动或 0–15')
    chunk = config.get('local_stream_chunk_seconds', 0.5)
    if type(chunk) not in (int, float) or not math.isfinite(chunk) or not 0.25 <= chunk <= 2:
        raise ValueError('流式更新间隔必须在 0.25–2 秒之间')
    if not windows_source:
        validate_language(config['local_model'], config['language'])
    if not windows_source and not model_ready(root, config['local_model'], config.get('local_native_backend', 'vulkan')):
        raise ValueError('请先下载本地模型并准备运行环境')
    write_json(path, config)
    return config


def load_appearance(root):
    values = read_json(Path(root) / 'config/overlay.json')
    def bounded(name, default, minimum, maximum):
        value = values.get(name, default)
        return max(minimum, min(maximum, value)) if type(value) is int else default
    result = {'background_opacity': bounded('background_opacity', 85, 0, 100),
              'font_size': bounded('font_size', 30, 18, 64),
              'max_caption_lines': bounded('max_caption_lines', 2, 1, 4)}
    for key, default in {'background_color': '#ffaaff', 'stable_color': '#ffffff',
                         'draft_color': '#adbcd0', 'shadow_color': '#000000',
                         'outline_color': '#000000'}.items():
        value = values.get(key, default)
        result[key] = value if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) else default
    for key, default in {'toolbar_locked': False, 'auto_height': True, 'centered': True,
                         'italic': False, 'shadow_enabled': True}.items():
        result[key] = values.get(key, default) if type(values.get(key, default)) is bool else default
    family = values.get('font_family', 'Yu Gothic UI')
    result['font_family'] = (family.strip() if isinstance(family, str) and family.strip()
                             and len(family) <= 160 and not re.search(r'[\x00-\x1f]', family) else 'Yu Gothic UI')
    result['font_weight'] = values.get('font_weight', 400) if values.get('font_weight', 400) in (400, 500, 600, 700) else 400
    result['shadow_opacity'] = bounded('shadow_opacity', 100, 0, 100)
    result['shadow_offset_x'] = bounded('shadow_offset_x', 1, -20, 20)
    result['shadow_offset_y'] = bounded('shadow_offset_y', 1, -20, 20)
    result['ruby_scale'] = bounded('ruby_scale', 45, 25, 80)
    for key, default, minimum, maximum in [('shadow_blur', 2, 0, 30),
                                          ('outline_width', 0.5, 0, 4), ('line_height', 1.8, 1.3, 3),
                                          ('previous_caption_seconds', 4, 0, 10),
                                          ('caption_idle_seconds', 4, 0, 30)]:
        value = values.get(key, default)
        result[key] = (max(minimum, min(maximum, value))
                       if type(value) in (int, float) and math.isfinite(value) else default)
    return result
