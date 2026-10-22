"""Test acceptance planning, without model/network calls or user data."""
import unittest
from scripts.academy_graph_acceptance import plan_batches


class AcceptancePlanningTests(unittest.TestCase):
    def chapter(self,i,size,review=False):
        return dict(id=f'ch{i:04}',sources=[dict(start=0,end=size)],review_required=review)

    def test_every_chapter_exactly_once_in_book_order_and_within_limits(self):
        index=dict(chapters=[self.chapter(i,4000) for i in range(1,15)])
        batches=plan_batches(index)
        self.assertEqual([c for batch in batches for c in batch],[c['id'] for c in index['chapters']])
        self.assertTrue(all(len(b)<=6 and len(b)*4000<=18000 for b in batches))

    def test_large_valid_chapter_is_standalone(self):
        self.assertEqual(plan_batches(dict(chapters=[self.chapter(1,1000),self.chapter(2,22000),self.chapter(3,1000)])),[['ch0001'],['ch0002'],['ch0003']])

    def test_unsafe_or_unprovided_chapters_rejected_before_calls(self):
        for chapter in (self.chapter(1,24001),self.chapter(1,100,True)):
            with self.assertRaises(ValueError):plan_batches(dict(chapters=[chapter]))
        index=dict(chapters=[self.chapter(1,100)])
        for selected in (['unknown'],['ch0001','ch0001']):
            with self.assertRaises(ValueError):plan_batches(index,selected)

    def test_selected_ids_do_not_reorder_book(self):
        index=dict(chapters=[self.chapter(i,100) for i in range(1,4)])
        self.assertEqual(plan_batches(index,['ch0003','ch0001']),[['ch0001','ch0003']])
