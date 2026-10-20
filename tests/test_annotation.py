"""Shared real Sudachi analysis must not leak mutable display annotations."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from jcaption.annotation import JapaneseAnnotator
from jcaption.state import CaptionState


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.annotator=JapaneseAnnotator()
        self.tokenize=Mock(wraps=self.annotator.tokenizer.tokenize)
        self.annotator.tokenizer=SimpleNamespace(tokenize=self.tokenize)

    def test_boundary_and_ruby_share_analysis_but_revised_context_is_reanalysed(self):
        self.annotator.safe_commit_end('今日は学校です',5)
        rows=self.annotator.tokens('今日は学校です')
        self.assertTrue(any(row['reading'] for row in rows))
        self.assertEqual(self.tokenize.call_count,1)
        self.annotator.tokens('今日は学校でした')
        self.assertEqual(self.tokenize.call_count,2)

    def test_reading_freeze_and_display_mutation_cannot_poison_shared_analysis(self):
        text='今日は学校です'
        state=CaptionState('annotation')
        state.accept(dict(session_id='annotation',utterance_id=0,revision=1,text=text,final=True))
        rows=self.annotator.tokens(text)
        expected=[dict(row) for row in rows]
        self.assertTrue(state.apply_annotation(0,1,rows))
        rows[0]['reading']='変更'
        rows[0]['stable']=True
        self.assertEqual(self.annotator.tokens(text),expected)

    def test_cache_stays_bounded_and_eviction_preserves_result(self):
        first=self.annotator.tokens('最初の字幕')
        for index in range(20):
            self.annotator.tokens(f'字幕{index}')
        before=self.tokenize.call_count
        self.assertLessEqual(len(self.annotator.cache),16)
        self.assertEqual(self.annotator.tokens('最初の字幕'),first)
        self.assertEqual(self.tokenize.call_count,before+1)


if __name__=='__main__':
    unittest.main()
