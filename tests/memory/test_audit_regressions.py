import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from memory import Segment
from memory.harness.checks import validate_report,RUBRICS
from memory.runtime.controller import MemoryController
from memory.contracts.errors import QualityBlocked
from memory.assets.store import MemoryStore
import test_repair_loop as fixtures

class AuditRegressions(unittest.TestCase):
    def test_cancel_after_reference_check_reuses_paid_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=fixtures.RepairTests().memory(tmp);host=fixtures.RepairBackend();host.repair_action='replace_reference'
            def stop():
                if list(Path(m.directory).glob('repairs/*/reference.png')):raise InterruptedError()
            with self.assertRaises(InterruptedError):m.generate(host,check_cancel=stop)
            with MemoryStore(m.directory,'test') as store:
                pending=store.data['pending_repair']['id']
            m.generate(host)
            self.assertEqual(host.routes,1)
            self.assertEqual(len(list(Path(m.directory).glob('repairs/*/reference.png'))),1)
            self.assertEqual(m.snapshot()['repair_runs'][pending]['status'],'verified')
    def test_invalidated_revision_and_candidate_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=fixtures.RepairTests().memory(tmp);m.generate(fixtures.RepairBackend())
            before=m.snapshot()['M']
            with MemoryStore(m.directory,'test') as store:old=store.data['invalidated_revisions'][0]
            with self.assertRaisesRegex(ValueError,'invalidated'):m.reselect('s1',old)
            with self.assertRaisesRegex(ValueError,'invalidated'):m.select_candidate('s1','segment/1/video/0',fixtures.RepairBackend())
            self.assertEqual(m.snapshot()['M'],before)
    def test_sequence_pass_needs_both_sides(self):
        request={'stage':'sequence','rubrics':RUBRICS['sequence'],'sources':{s:{'kind':'video','duration':5} for s in ('a','b')}}
        report={'checks':[dict(criterion=c,status='pass',evidence=[dict(source_id='a',detail='visible',start=0,end=1)]) for c in request['rubrics']]}
        with self.assertRaisesRegex(ValueError,'paired'):validate_report(report,request)
        for c in report['checks']:c['evidence'].append(dict(source_id='b',detail='corresponding state',start=0,end=1))
        self.assertEqual(validate_report(report,request)['status'],'pass')
    def test_identity_requires_actual_anchor(self):
        request={'stage':'frame','rubrics':{'C.identity':'compare'},'sources':{'c':{'kind':'frame','role':'candidate'}}}
        report={'checks':[dict(criterion='C.identity',status='pass',evidence=[dict(source_id='c',detail='looks like character')])]}
        with self.assertRaisesRegex(ValueError,'anchor'):validate_report(report,request)
    def test_event_gate_uses_observation_not_plan(self):
        first=dict(segment_id='s0',purpose='get key',expected_begin='no key',expected_end='has key',depends_on=[])
        second=dict(segment_id='s1',purpose='open door',expected_begin='has key',expected_end='open door',depends_on=['s0'])
        controller=object.__new__(MemoryController)
        controller.store=SimpleNamespace(data={'plan':{'beats':[first,second]}})
        segment=Segment('s1','open door',5)
        records=[{'segment':{'id':'s0'},'completed_goals':[{'status':'completed'}]}]
        with self.assertRaises(QualityBlocked):controller._check_event_dependencies(segment,records)
        records[0]['event_assessment']={'status':'pass','beat':first}
        controller._check_event_dependencies(segment,records)
        records[0]['event_assessment']['beat']=dict(first,expected_end='key on floor')
        with self.assertRaises(QualityBlocked):controller._check_event_dependencies(segment,records)
    def test_reselection_revokes_delivery_certification(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=fixtures.RepairTests().memory(tmp);m.generate(fixtures.RepairBackend())
            self.assertEqual(m.snapshot()['delivery']['status'],'passed')
            chosen=next(v for v in m.snapshot()['M'] if v['segment_id']=='s1')
            m.reselect('s1',chosen['revision_id'])
            self.assertEqual(m.snapshot()['delivery']['status'],'pending')
