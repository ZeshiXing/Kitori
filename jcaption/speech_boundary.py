"""Pause detection using existing Silero runtimes; never removes audio samples."""
from pathlib import Path


def gap_cut(segments, samples, rate):
    candidates = []
    for left, right in zip(segments, segments[1:]):
        end, start = int(left['end']), int(right['start'])
        middle = (end+start)//2
        if start-end >= int(.16*rate) and rate <= middle <= samples-int(.5*rate):
            candidates.append(middle*2)
    return candidates[-1] if candidates else None


class TorchSpeechBoundary:
    """Use Tiger's already installed official Silero JIT and utility module."""
    def __init__(self, root):
        import importlib.util
        import sys
        folder = (Path(root)/'apps/TigerBackend/audioWhisper/.cache/silero-vad-v5/'
                  'snakers4_silero-vad_master/src/silero_vad')
        spec = importlib.util.spec_from_file_location('jcaption_silero_utils', folder/'utils_vad.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.model = module.init_jit_model(str(folder/'data/silero_vad.jit'))
        self.get_segments = module.get_speech_timestamps
        self.iterator_class = module.VADIterator

    def __call__(self, pcm, rate):
        import numpy as np
        import torch
        samples = np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        segments = self.get_segments(torch.from_numpy(samples), self.model,
                                     sampling_rate=rate, threshold=.4,
                                     min_speech_duration_ms=0, min_silence_duration_ms=160,
                                     speech_pad_ms=0)
        return gap_cut(segments, len(samples), rate)


class SherpaSpeechBoundary:
    """Use the optional project-owned sherpa runtime, no Torch dependency."""
    def __init__(self, root):
        import sherpa_onnx
        model = (Path(root)/'apps/TigerBackend/audioWhisper/.cache/silero-vad-v5/'
                 'snakers4_silero-vad_master/src/silero_vad/data/silero_vad.onnx')
        if not model.is_file():
            raise FileNotFoundError(model)
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(model)
        config.silero_vad.threshold = .4
        config.silero_vad.min_silence_duration = .16
        config.silero_vad.min_speech_duration = 0
        config.sample_rate = 16000
        config.num_threads = 1
        self.vad = sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=60)

    def __call__(self, pcm, rate):
        import numpy as np
        samples = np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        self.vad.reset()
        # sherpa's streaming VAD must be fed at its model frame size; passing
        # the whole tail at once does not produce the intermediate boundaries.
        window = self.vad.config.silero_vad.window_size
        for offset in range(0,len(samples),window):
            self.vad.accept_waveform(samples[offset:offset+window])
        self.vad.flush()
        segments = []
        while not self.vad.empty():
            row = self.vad.front
            segments.append({'start':row.start,'end':row.start+len(row.samples)})
            self.vad.pop()
        return gap_cut(segments,len(samples),rate)
