import unittest
from types import SimpleNamespace
from memory.contracts.models import FRAME_METRICS, validate_observation

class ReviewConsistencyTests(unittest.TestCase):
    def test_unregistered_relation_reports_exact_ids_without_inventing_entity(self):
        value={'camera':'static','events':[],'entities':[{'id':'Rabbit','kind':'character','identity':'rabbit','state':'awake','motion':'still','evidence':[{'start':0,'end':0,'detail':'visible'}]}], 'spatial_relations':[{'subject':'rabbit','relation':'on','object':'Bed'}]}
        with self.assertRaises(ValueError) as caught:
            validate_observation(value,1)
        self.assertIn('Rabbit',str(caught.exception))
        self.assertIn('Bed',str(caught.exception))
        self.assertEqual(len(value['entities']),1)
