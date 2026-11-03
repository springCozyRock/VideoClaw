import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generation_meter import Meter,save,token_cost,image_count

class MeterTests(unittest.TestCase):
    def test_cache_and_token_aliases(self):
        self.assertAlmostEqual(token_cost('qwen3.7-plus',{'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':500}}),.002)
        self.assertAlmostEqual(token_cost('qwen3.5-omni-plus',{'prompt_tokens':1000,'completion_tokens':100}),.011)
        self.assertIsNone(token_cost('qwen3.7-plus',{}))
    def test_all_candidate_images_count_and_parallel_time_is_wall_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Meter(tmp)
            for _ in range(3):m.end(m.begin('image','wan2.7-image'),'SUCCEEDED',output_images=1)
            save(Path(tmp)/'tasks/a.json',{'status':'SUCCEEDED','duration_sec':60})
            summary=m.summarize(120,60)
            self.assertAlmostEqual(summary['estimated_total_cny'],36.6)
            self.assertEqual(summary['wall_minutes_per_finished_minute'],2)
            self.assertEqual(summary['generated_images'],3)
    def test_unknown_call_prevents_claiming_complete_cost_or_finished_minute(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Meter(tmp);m.end(m.begin('image','wan2.7-image'),'UNKNOWN')
            s=m.summarize(10)
            self.assertFalse(s['usage_complete']);self.assertIsNone(s['cny_per_finished_minute'])
            with self.assertRaises(RuntimeError):m.begin('image','wan2.7-image')
    def test_sdk_image_nested_outputs(self):
        self.assertEqual(image_count({'choices':[{'message':{'content':[{'image':'url'}]}}]}),1)

if __name__=='__main__':unittest.main()
