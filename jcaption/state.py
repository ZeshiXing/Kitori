"""Versioned caption state using LocalAgreement-2's common-prefix idea.

Method reference: ufal/whisper_streaming (MIT). This implementation handles
display state only; audio windowing and model inference are external adapters.
"""
from collections import deque
from copy import deepcopy
import threading
import time


def common_prefix_length(left, right):
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right))


def previous_reading_line(snapshot, seconds=4, now=None):
    """Retain one completed live caption without delaying the new caption."""
    current = snapshot.get('current') or {}
    history = snapshot.get('history') or []
    if (seconds <= 0 or not history or snapshot.get('input_mode') == 'lookahead' or
            'started_monotonic' not in current):
        return None
    now = time.monotonic() if now is None else now
    previous = history[-1]
    if (now - current['started_monotonic'] < seconds and previous.get('phase') == 'final'
            and previous.get('text')):
        return previous
    return None


def display_window(snapshot, idle_seconds=4, now=None):
    """Expire only the display copy, preserving ASR revisions/history for recovery."""
    result = deepcopy(snapshot)
    current = result.get('current')
    retained = result.pop('last_nonempty', None)
    if result.get('input_mode') != 'lookahead' and current and not current.get('text'):
        # Empty drafts/finals are recognition state, not a request to erase
        # already visible words. Keep their original phase and idle deadline.
        candidates = ([retained] if retained else []) + list(reversed(result.get('history', [])))
        previous = next((line for line in candidates if line.get('text')), None)
        if previous:
            current = result['current'] = deepcopy(previous)
            current['display_retained'] = True
            result['history'] = [line for line in result['history']
                                 if line['utterance_id'] != previous['utterance_id']]
    if idle_seconds <= 0 or result.get('input_mode') == 'lookahead':
        return result
    now = time.monotonic() if now is None else now
    def expired(line):
        stamp = line.get('content_updated_monotonic', line.get('updated_monotonic'))
        return stamp is not None and now - stamp >= idle_seconds
    result['history'] = [line for line in result.get('history', []) if not expired(line)]
    if current and expired(current):
        current.update(text='', stable_text='', draft_text='', ruby=[], display_expired=True)
    return result


class CaptionState:
    def __init__(self, session_id, boundary=None, clock=time.monotonic):
        self.session_id, self.boundary, self.clock = session_id, boundary, clock
        self.condition = threading.Condition(threading.RLock())
        self.sequence = 0
        self.current = None
        self.last_nonempty = None
        self.previous_hypothesis = ''
        self.history = deque(maxlen=5)
        self.observations = deque(maxlen=256)
        self.frozen_readings = {}
        self.counts = {'draft_updates': 0, 'final_updates': 0, 'rejected_updates': 0,
                       'annotation_updates': 0, 'final_corrections': 0}

    def accept(self, event):
        if (event.get('session_id') != self.session_id or
                type(event.get('utterance_id')) is not int or event['utterance_id'] < 0 or
                type(event.get('revision')) is not int or event['revision'] < 1 or
                type(event.get('final')) is not bool or
                not isinstance(event.get('text'), str) or len(event['text']) > 8000 or
                not isinstance(event.get('language', 'ja'), str) or len(event.get('language', 'ja')) > 20):
            raise ValueError('Invalid caption update')
        with self.condition:
            old = self.current
            identity = event['utterance_id']
            if old and (identity < old['utterance_id'] or
                        (identity == old['utterance_id'] and
                         (event['revision'] <= old['revision'] or old['phase'] in ('final', 'cancelled')))):
                self.counts['rejected_updates'] += 1
                return False
            new_utterance = old is None or identity != old['utterance_id']
            if event['text'].strip():
                self.last_nonempty = None
            elif old and old['text']:
                self.last_nonempty = deepcopy(old)
            if new_utterance:
                if old and old['text']:
                    self.history.append(deepcopy(old))
                self.previous_hypothesis = ''
                self.frozen_readings.clear()
            text = event['text'].strip()
            stable = '' if new_utterance else old['stable_text']
            correction = False
            pending_correction = False
            if event['final']:
                correction = bool(stable and not text.startswith(stable))
                if correction:
                    self.frozen_readings.clear()
                    self.counts['final_corrections'] += 1
                stable = text
                phase = 'final' if text else 'cancelled'
                self.counts['final_updates'] += 1
            else:
                if stable and not text.startswith(stable):
                    # A revised hypothesis must stay visible. Roll back only
                    # the changed commitment rather than freeze all new text
                    # until a final arrives, potentially many seconds later.
                    pending_correction = True
                    agreed = common_prefix_length(stable, text)
                    end = self.boundary(text, agreed) if self.boundary and agreed else agreed
                    stable = text[:min(end, agreed)]
                    self.frozen_readings = {key: value for key, value in self.frozen_readings.items()
                                            if key[1] <= len(stable)}
                else:
                    agreed = common_prefix_length(self.previous_hypothesis, text)
                    end = self.boundary(text, agreed) if self.boundary and agreed else agreed
                    stable = text[:max(len(stable), min(end, agreed))]
                phase = 'draft'
                self.counts['draft_updates'] += 1
            self.previous_hypothesis = event['text'].strip()
            self.current = {
                'session_id': self.session_id, 'utterance_id': identity,
                'revision': event['revision'], 'phase': phase, 'text': text,
                'stable_text': stable, 'draft_text': text[len(stable):],
                'ruby': [], 'annotation_revision': None,
                'correction': correction, 'pending_correction': pending_correction,
                'backend': event.get('backend', 'local'), 'input_mode': 'live',
                'language': event.get('language', 'ja'),
                'lookahead': 'unavailable', 'timing_quality': 'none',
                'media_start_ms': None, 'media_end_ms': None,
                'updated_monotonic': self.clock(),
                'content_updated_monotonic': (self.clock() if new_utterance or text != old['text'] else
                    old.get('content_updated_monotonic', old['updated_monotonic'])),
                'started_monotonic': self.clock() if new_utterance else old['started_monotonic'],
            }
            self.observations.append({
                'wall_time': time.time(), 'monotonic': self.clock(),
                'utterance_id': identity, 'revision': event['revision'], 'phase': phase,
                'characters': len(text), 'stable_characters': len(stable),
                'asr_seconds': event.get('asr_seconds'), 'audio_seconds': event.get('audio_seconds'),
            })
            self.sequence += 1
            self.condition.notify_all()
            return True

    def apply_annotation(self, identity, revision, spans):
        with self.condition:
            current = self.current
            if not current or identity != current['utterance_id'] or revision != current['revision']:
                return False
            stable_end = len(current['stable_text'])
            rows = []
            for span in spans:
                row = dict(span)
                if current['text'][row['start']:row['end']] != row['surface']:
                    raise ValueError('Annotation does not match caption')
                key = (row['start'], row['end'], row['surface'])
                stable = row['end'] <= stable_end
                if key in self.frozen_readings:
                    row['reading'] = self.frozen_readings[key]
                elif stable:
                    self.frozen_readings[key] = row['reading']
                row['stable'] = stable
                rows.append(row)
            current['ruby'] = rows
            current['annotation_revision'] = revision
            self.counts['annotation_updates'] += 1
            self.sequence += 1
            self.condition.notify_all()
            return True

    def snapshot(self):
        with self.condition:
            return {'session_id': self.session_id, 'sequence': self.sequence, 'streaming': True,
                    'current': deepcopy(self.current), 'history': deepcopy(list(self.history)),
                    'last_nonempty': deepcopy(self.last_nonempty),
                    'input_mode': 'live', 'lookahead': 'unavailable'}

    def metrics(self):
        with self.condition:
            return {**self.counts, 'streaming': True, 'input_mode': 'live',
                    'observations': list(self.observations)}

    def wait(self, after_sequence, timeout=1):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence != after_sequence, timeout)
            return self.snapshot()
