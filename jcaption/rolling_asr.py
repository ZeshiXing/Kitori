"""Bound repeated offline decoding without pretending to cache model attention.

Method reference: ufal/whisper_streaming (MIT), LocalAgreement and timestamped
audio trimming. This project owns capture identities, duplicate suppression and
the conservative speech-boundary handling for backends without timestamps.
"""
from dataclasses import dataclass
import hashlib
import math
import time


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Recognition:
    text: str
    words: tuple = ()


def join_text(left, right):
    left, right = left.rstrip(), right.lstrip()
    if left and right and left[-1].isascii() and right[0].isascii() and left[-1].isalnum() and right[0].isalnum():
        return left + ' ' + right
    return left + right


class RollingRecognizer:
    """Only re-decode the uncommitted tail of one capture utterance.

    Prefer mature VAD speech-pause boundaries. Timestamp fallback requires
    agreement in two audio revisions and a sentence/pause boundary. Text-only
    backends without reliable boundaries retain their complete audio window.
    With no trustworthy boundary we keep context rather than silently drop it.
    """
    def __init__(self, decode, final_changes_decode=False, timestamps=False,
                 trim_seconds=5.0, hold_seconds=0.8, speech_boundary=None):
        self.decode = decode
        self.final_changes_decode = final_changes_decode
        self.timestamps = timestamps
        self.speech_boundary = speech_boundary
        self.trim_seconds, self.hold_seconds = trim_seconds, hold_seconds
        self.identity = None
        self.totals = dict(calls=0, duplicate_hits=0, input_seconds=0.0,
                           full_window_seconds=0.0, max_window_seconds=0.0,
                           timestamp_trims=0, speech_pause_trims=0,
                           boundary_seconds=0.0, boundary_errors=0)
        self.totals['empty_prefix_cuts_rejected'] = 0
        self.totals.update(empty_drafts=0, empty_finals=0)
        self.reset()

    def reset(self):
        self.offset = 0
        self.committed_end = 0.0
        self.committed = ''
        self.previous_words = ()
        self.last_key = None
        self.last_text = ''
        self.last_final = False
        self.last_length = 0

    def set_utterance(self, identity):
        if identity != self.identity:
            self.reset()
            self.identity = identity

    def infer(self, pcm, rate, final):
        if not pcm:
            return Recognition('')
        result = self.decode(pcm, rate, final)
        seconds = len(pcm) / (rate * 2)
        self.totals['calls'] += 1
        if not result.text.strip():
            self.totals['empty_finals' if final else 'empty_drafts'] += 1
        self.totals['input_seconds'] += seconds
        self.totals['max_window_seconds'] = max(self.totals['max_window_seconds'], seconds)
        return result

    def transcribe(self, pcm, rate, final=True):
        if rate != 16000 or len(pcm) % 2:
            raise ValueError('Rolling recognition requires 16 kHz signed PCM16')
        if len(pcm) < self.last_length:
            # Hosts/callers without identities can still start a fresh buffer.
            self.reset()
        key = (rate, len(pcm), hashlib.blake2b(pcm, digest_size=16).digest())
        if key == self.last_key and (not final or self.last_final or not self.final_changes_decode):
            self.totals['duplicate_hits'] += 1
            self.last_final = self.last_final or final
            return self.last_text
        self.totals['full_window_seconds'] += len(pcm) / (rate * 2)
        tail = pcm[self.offset:]
        # Decode the prefix once at an already observed speech pause, leaving
        # >=500 ms live tail. No samples are deleted and no future gap is awaited.
        # Finalization already decodes the complete remaining tail. Splitting
        # it first adds a boundary scan and a second decode without helping
        # any future update in this utterance.
        if (not final and not self.timestamps and self.speech_boundary and
                len(tail) / (rate * 2) >= self.trim_seconds):
            started = time.perf_counter()
            try:
                cut = self.speech_boundary(tail, rate)
            except Exception:
                # Optional VAD failure must not stop captions or guess a cut.
                self.totals['boundary_errors'] += 1
                cut = None
            self.totals['boundary_seconds'] += time.perf_counter()-started
            if cut is not None and (type(cut) is not int or cut % 2 or not rate*2 <= cut <= len(tail)-rate):
                self.totals['boundary_errors'] += 1
                cut = None
            if cut:
                prefix = self.infer(tail[:cut], rate, True)
                if prefix.text.strip():
                    self.committed = join_text(self.committed, prefix.text)
                    self.offset += cut
                    tail = pcm[self.offset:]
                    self.totals['speech_pause_trims'] += 1
                else:
                    # A temporary empty ASR result is not proof of silence.
                    # Keep the onset available for the next/full-tail decode.
                    self.totals['empty_prefix_cuts_rejected'] += 1
        result = self.infer(tail, rate, final)
        words = self.uncommitted_words(result.words, rate, len(tail))
        text = ''.join(w.text for w in words) if words is not None else result.text
        output = join_text(self.committed, text)
        if self.timestamps and not final and words:
            self.trim_agreed(words, len(pcm) / (rate * 2), rate)
        else:
            self.previous_words = words or ()
        self.last_key, self.last_length = key, len(pcm)
        self.last_text, self.last_final = output, final
        return output.strip()

    def uncommitted_words(self, words, rate, byte_length):
        if not words:
            return None
        origin = self.offset / (rate * 2)
        duration = byte_length / (rate * 2)
        valid, last = [], -1.0
        for word in words:
            if (not math.isfinite(word.start) or not math.isfinite(word.end) or
                    not 0 <= word.start <= word.end <= duration + .1 or word.end < last):
                # Never use bad alignment to decide an irreversible audio cut.
                return None
            last = word.end
            start, end = origin + word.start, origin + word.end
            if end <= self.committed_end + .08 and start < self.committed_end-.08:
                continue
            if (start < self.committed_end-.05 and self.committed and
                    self.committed.endswith(word.text.strip())):
                continue  # Retained left context, not a newly spoken repetition.
            valid.append(Word(start, end, word.text))
        return tuple(valid)

    def trim_agreed(self, words, duration, rate):
        agreed = []
        for old, new in zip(self.previous_words, words):
            if (old.text != new.text or abs(old.start-new.start) > .35 or
                    abs(old.end-new.end) > .35 or new.end > duration-self.hold_seconds):
                break
            agreed.append(new)
        self.previous_words = words
        if duration-self.offset/(rate*2) < self.trim_seconds or not agreed:
            return
        # Seal sentences or clear word-aligned pauses. An agreed subword is not a
        # safe audio cut: alignment jitter can put the following particle into
        # left context. Without a sentence boundary, keep decoding the tail.
        boundaries = [i+1 for i, word in enumerate(agreed)
                      if word.text.rstrip().endswith(('。', '！', '？', '!', '?'))]
        boundaries += [i+1 for i in range(len(agreed)-1)
                       if agreed[i+1].start-agreed[i].end >= .24]
        if not boundaries:
            return
        agreed = agreed[:max(boundaries)]
        if not agreed or agreed[-1].end-self.committed_end < .5:
            return
        self.committed = join_text(self.committed, ''.join(w.text for w in agreed))
        self.committed_end = agreed[-1].end
        # A little acoustic context avoids cutting the next syllable. Timestamp
        # filtering removes this overlap, not textual global deduplication.
        self.offset = max(self.offset, int((self.committed_end-.2)*rate)*2)
        self.previous_words = words[len(agreed):]
        self.totals['timestamp_trims'] += 1

class WindowedEngine:
    """Persistent offline engine plus an utterance-local rolling scheduler."""
    def __init__(self, engine):
        self.engine = engine
        self.rolling = RollingRecognizer(
            self.decode_window,
            final_changes_decode=getattr(engine, 'final_changes_decode', False),
            timestamps=getattr(engine, 'word_timestamps', False),
            speech_boundary=getattr(engine, 'speech_boundary', None))

    def decode_window(self, pcm, rate, final):
        # Keep linguistic context as a short prompt, not repeatedly encoded old
        # audio. Honor the user's option to disable Whisper context transfer.
        self.engine.context_prompt = self.rolling.committed[-160:]
        # Short utterances keep the original fast path. Alignment is needed
        # before the first trim, and thereafter to remove retained left context.
        self.engine.align_current_window = (self.rolling.timestamps and
            (bool(self.rolling.offset) or len(pcm) >= int(3.5*32000)))
        return self.engine.decode_window(pcm, rate, final)

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def set_utterance(self, identity):
        self.rolling.set_utterance(identity)

    def transcribe(self, pcm, rate, final=True):
        return self.rolling.transcribe(pcm, rate, final)

    def close(self):
        self.rolling.reset()
        self.engine.close()

    def inference_stats(self):
        return {**{key: round(value, 4) if isinstance(value, float) else value
                   for key, value in self.rolling.totals.items()},
                'strategy':('speech-pauses' if self.rolling.speech_boundary else
                            'timestamp-agreement' if self.rolling.timestamps else 'full-window')}
