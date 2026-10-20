"""Optional literal phrase removal after Whisper decoding; no model retry."""
import re
import unicodedata


# Editable examples, deliberately excluding ordinary thanks and short replies.
DEFAULT_WHISPER_BLOCKLIST = (
    'ご視聴ありがとうございました',
    'ご視聴ありがとうございます',
    'チャンネル登録をお願いします',
    'チャンネル登録をお願いいたします',
    '字幕を頂きましてありがとうございました',
    'Thank you for watching',
    'Thanks for watching',
)


def validate_blocklist(value):
    if (not isinstance(value, list) or len(value) > 200 or
            any(not isinstance(term, str) or not term.strip() or len(term) > 200 or
                any(unicodedata.category(char) == 'Cc' for char in term) for term in value)):
        raise ValueError('屏蔽词表最多 200 条，每条 1–200 字，不能包含换行或控制字符。')
    return list(dict.fromkeys(term.strip() for term in value))


class WhisperPhraseFilter:
    def __init__(self, enabled=False, phrases=DEFAULT_WHISPER_BLOCKLIST):
        self.enabled = enabled is True
        # Longest alternatives first, so overlapping entries cannot leave tails.
        phrases = validate_blocklist(list(phrases))
        patterns = [r'\s*'.join(re.escape(char) for char in term if not char.isspace())
                    for term in sorted(phrases, key=len, reverse=True)]
        self.pattern = re.compile('|'.join(patterns), re.IGNORECASE) if patterns else None

    @classmethod
    def from_config(cls, config):
        return cls(config.get('whisper_blocklist_enabled', False),
                   config.get('whisper_blocklist', DEFAULT_WHISPER_BLOCKLIST))

    def ranges(self, text):
        if not self.enabled or self.pattern is None:
            return []
        return [(match.start(), match.end()) for match in self.pattern.finditer(text)]

    @staticmethod
    def remove_ranges(text, ranges):
        cursor, parts = 0, []
        for start, end in ranges:
            parts.append(text[cursor:start])
            cursor = end
        parts.append(text[cursor:])
        result = ''.join(parts).strip()
        # Don't emit a punctuation-only subtitle after removing a whole phrase.
        return result if any(unicodedata.category(char)[0] in 'LN' for char in result) else ''

    def apply(self, text):
        ranges = self.ranges(text)
        return self.remove_ranges(text, ranges) if ranges else text

    def words(self, words):
        """Remove spans across word boundaries, preserving original media times."""
        text = ''.join(word.word for word in words)
        ranges = self.ranges(text)
        if ranges and not self.remove_ranges(text, ranges):
            return []
        rows, offset = [], 0
        for word in words:
            end = offset + len(word.word)
            local = [(max(start, offset)-offset, min(stop, end)-offset)
                     for start, stop in ranges if start < end and stop > offset]
            value = self.remove_ranges(word.word, local) if local else word.word
            if value.strip():
                rows.append({'word':value, 'start':word.start, 'end':word.end})
            offset = end
        return rows
