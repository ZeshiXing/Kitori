"""Japanese analysis delegates to Sudachi; layout delegates to HTML ruby."""
import re
import threading
from collections import OrderedDict

KANJI = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0003134f々〆]')


def hiragana(reading):
    return ''.join(chr(ord(c) - 0x60) if '\u30a1' <= c <= '\u30f6' else c for c in reading)


class JapaneseAnnotator:
    def __init__(self):
        from sudachipy import dictionary, tokenizer
        self.tokenizer = dictionary.Dictionary(dict='small').create()
        self.mode = tokenizer.Tokenizer.SplitMode.B
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def tokens(self, text):
        # Locate surfaces in the original text so offsets remain code points,
        # including supplementary characters and spaces.
        result, cursor = [], 0
        with self.lock:
            if text in self.cache:
                self.cache.move_to_end(text)
                return [dict(row) for row in self.cache[text]]
            for morpheme in self.tokenizer.tokenize(text, self.mode):
                surface = morpheme.surface()
                begin = text.find(surface, cursor)
                if begin < 0:
                    raise ValueError('Tokenizer surface did not match caption')
                end = begin + len(surface)
                result.append({'start': begin, 'end': end, 'surface': surface,
                               'reading': hiragana(morpheme.reading_form()) if KANJI.search(surface) else ''})
                cursor = end
            # Boundary checks and ruby use the same exact-text analysis. Keep
            # copies: display state adds fields and may freeze a reading.
            self.cache[text] = tuple(dict(row) for row in result)
            if len(self.cache) > 16:
                self.cache.popitem(last=False)
        return result

    def safe_commit_end(self, text, common_end):
        # Hold the last morpheme for additional Japanese context.
        tokens = self.tokens(text)
        return max((t['end'] for t in tokens[:-1] if t['end'] <= common_end), default=0)
