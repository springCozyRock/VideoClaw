import unittest
from memory.narrative.planning import validate_plan

class PlanningTests(unittest.TestCase):
    def plan(self):
        return {'goals': ['open door'], 'segments': [{'id': 's1', 'context': 'get key', 'duration': 5}],
                'beats': [{'segment_id': 's1', 'purpose': 'obtain key', 'expected_begin': 'empty hands',
                           'expected_end': 'holding key', 'depends_on': []}]}
    def test_version_and_intentions(self):
        p = validate_plan(self.plan(), {})
        self.assertEqual(p['schema'], 'aard.plan/1')
        self.assertNotIn('M', p)
        self.assertEqual(p, validate_plan(self.plan(), {}))
    def test_future_dependency_rejected(self):
        p = self.plan(); p['beats'][0]['depends_on'] = ['s2']
        with self.assertRaises(ValueError): validate_plan(p, {})
    def test_goal_change_rejected(self):
        with self.assertRaises(ValueError): validate_plan(self.plan(), {'goals': ['keep door shut']})
    def test_completed_rewrite_rejected(self):
        with self.assertRaises(ValueError): validate_plan(self.plan(), {'completed': [{'id': 'old'}]})
