import tempfile
import unittest
from memory.harness.checks import ChainAudit, validate_report, RUBRICS
from memory.assets.store import MemoryStore

class ChainTests(unittest.TestCase):
    def request(self):
        return {'rubrics': RUBRICS['video'], 'sources': {'v': {'kind': 'video', 'duration': 5}}}
    def result(self):
        return {'checks': [dict(criterion=k, status='pass', evidence=[dict(source_id='v',detail='visible action',start=1,end=2)]) for k in RUBRICS['video']]}
    def test_temporal_evidence_must_be_valid(self):
        result=self.result(); result['checks'][0]['evidence'][0]['end']=8
        with self.assertRaises(ValueError): validate_report(result,self.request())
    def test_missing_source_rejected(self):
        result=self.result(); result['checks'][0]['evidence'][0]['source_id']='imagined'
        with self.assertRaises(ValueError): validate_report(result,self.request())
    def test_missing_criterion_rejected(self):
        result=self.result(); result['checks'].pop()
        with self.assertRaises(ValueError): validate_report(result,self.request())
    def test_failure_proposes_repair_and_replays_without_call(self):
        parent=self
        class Host:
            calls=0
            def check_chain(self, request):
                self.calls+=1
                result=parent.result(); result['checks'][0].update(status='fail',defect='event incomplete')
                return result
        with tempfile.TemporaryDirectory() as tmp, MemoryStore(tmp,'test') as store:
            host=Host(); audit=ChainAudit(store,host)
            first=audit.check('video', self.request()['sources'])
            audit.check('video', self.request()['sources'])
            self.assertEqual(host.calls,1)
            repair=store.data['repairs'][first['id']]
            self.assertEqual(repair['attribution_status'],'hypothesis')
            self.assertTrue(repair['requires_recheck'])
    def test_unsupported_judge_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, MemoryStore(tmp,'test') as store:
            result=ChainAudit(store,object()).check('video',self.request()['sources'])
            self.assertEqual(result['status'],'unknown')
