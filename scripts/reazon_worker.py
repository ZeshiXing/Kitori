"""Persistent sherpa-onnx inference worker. Stdout is an in-memory IPC protocol."""
import argparse
import base64
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-dir', type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    import sherpa_onnx
    directory = args.model_dir
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(directory / 'encoder-epoch-99-avg-1.int8.onnx'),
        decoder=str(directory / 'decoder-epoch-99-avg-1.int8.onnx'),
        joiner=str(directory / 'joiner-epoch-99-avg-1.int8.onnx'),
        tokens=str(directory / 'tokens.txt'), num_threads=4, sample_rate=16000,
        feature_dim=80, decoding_method='greedy_search', provider='cpu')
    print(json.dumps({'ready':True}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        pcm = base64.b64decode(request['pcm'], validate=True)
        if len(pcm) > 16000 * 2 * 30 or len(pcm) % 2:
            raise ValueError('Invalid audio length')
        if len(pcm) < 3840:
            print(json.dumps({'text':''}), flush=True)
            continue
        stream = recognizer.create_stream()
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        # Zipformer's convolution needs enough feature frames even for a short
        # interjection. Zero padding adds no capture-time waiting.
        if len(samples) < 4000:
            samples = np.pad(samples, (0, 4000-len(samples)))
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        print(json.dumps({'text':stream.result.text}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'error':'local_inference_failed'}), flush=True)
        raise SystemExit(1)
