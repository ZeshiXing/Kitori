"""Fail before shutdown if a pending local model cannot be started."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jcaption.local_models import model_ready, validate_language
from jcaption.settings import read_json, capture_vad_threshold, local_capture_pipeline

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['local'], required=True)
    args = parser.parse_args()
    config = read_json(ROOT / 'config/caption.json')
    if config.get('recognition_source') == 'windows_livecaptions':
        from jcaption.windows_captions import prepare_reader
        prepare_reader(ROOT)
    else:
        capture_vad_threshold(config)
        local_capture_pipeline(config)
        validate_language(config['local_model'], config.get('language', 'auto'))
        if not model_ready(ROOT, config['local_model'], config.get('local_native_backend', 'vulkan')):
            raise SystemExit('Local model/runtime not ready. Prepare it in recognition settings first.')
