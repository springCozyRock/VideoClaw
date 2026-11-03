import tempfile
import unittest
from pathlib import Path
from memory import Memory, Segment, Reference, Policy
from memory.assets.store import MemoryStore
from memory.contracts.errors import QualityBlocked
from memory.harness.repair import validate_route
from fakes import FakeBackend

class RepairBackend(FakeBackend):
    repair_action='regenerate_segment'
    def __init__(self, always_fail=False):
        super().__init__()
        self.always_fail=always_fail
        self.routes=0
    def check_chain(self, request):
        # Fail only assembled sequence: all isolated candidates appear valid.
        fail=request['stage']=='sequence' and 'candidate' not in request['sources'] and (self.always_fail or self.routes==0)
        evidence=[]
        for key,source in request['sources'].items():
            item={'source_id':key,'detail':'Observed sequence continuity'}
            if source['kind']=='video': item.update(start=0,end=1)
            evidence.append(item)
        return {'checks':[dict(criterion=c,status='fail' if fail else 'pass',defect='cross-shot discontinuity' if fail else '',evidence=evidence) for c in request['rubrics']]}
    def plan_chain_repair(self, request):
        self.routes+=1
        return dict(action=self.repair_action,segment_id='s1',reason='repair suffix',evidence_ids=list(request['checks']), reference_id='anchor',prompt='repair reference')

class RepairTests(unittest.TestCase):
    def memory(self,tmp,budget=2):
        anchor=Path(tmp)/'anchor.png';anchor.write_text('anchor')
        m=Memory(Path(tmp)/'run','test',Policy(global_references=False,frame_candidates=1,video_candidates=1,chain_repairs=budget,selection='strict'))
        m.register_story([Segment('s0','remove apron',5,('Penguin',)),Segment('s1','advance',5,('Penguin',))],
            [Reference('anchor',str(anchor),'Penguin',('Penguin',))])
        return m
    def test_sequence_failure_repairs_suffix_and_rechecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=RepairBackend();m.generate(host)
            self.assertEqual(host.video_count,3)
            snap=m.snapshot()
            self.assertEqual(len(snap['M']),2)
            self.assertFalse(any(v['stale'] for v in snap['M']))
            run=next(iter(snap['repair_runs'].values()))
            self.assertEqual(run['status'],'verified')
            self.assertEqual(run['invalidated_from'],1)
            self.assertEqual(snap['repair_experiences'][0]['attribution_status'],'hypothesis')
            before=host.video_count;m.generate(host);self.assertEqual(host.video_count,before)
    def test_failed_rechecks_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp,1);host=RepairBackend(True)
            with self.assertRaises(QualityBlocked):m.generate(host)
            self.assertEqual(host.routes,1)
            self.assertEqual(next(iter(m.snapshot()['repair_runs'].values()))['status'],'unresolved')
    def test_reference_repair_preserves_original_and_invalidates_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=RepairBackend();host.repair_action='replace_reference'
            m.generate(host)
            self.assertEqual((Path(tmp)/'anchor.png').read_text(),'anchor')
            self.assertEqual(host.video_count,4)
            self.assertEqual(next(iter(m.snapshot()['repair_runs'].values()))['invalidated_from'],0)
    def test_plan_repair_keeps_prefix_and_goal(self):
        from dataclasses import asdict
        from memory.narrative.planning import validate_plan
        class Planner(RepairBackend):
            repair_action='revise_plan'
            def plan_story(self, request):
                import copy
                result=copy.deepcopy(request['previous_plan'])
                result['segments'][1]['context']='advance after removing apron'
                return result
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=Planner()
            plan=validate_plan({'goals':['remove apron then advance'],
                'segments':[asdict(s) for s in m.segments],
                'beats':[dict(segment_id=s.id,purpose='advance',expected_begin='before',expected_end='after',depends_on=[]) for s in m.segments]}, {})
            with MemoryStore(m.directory,'test') as store:
                store.data.update(plan=plan,planning_request={'story':'remove apron then advance','constraints':{}})
                store.save()
            m.generate(host)
            self.assertEqual(host.video_count,3)
            self.assertEqual(m.snapshot()['Plan']['goals'],plan['goals'])
            self.assertEqual(m.snapshot()['storyline'][0]['context'],'remove apron')
            self.assertEqual(m.snapshot()['storyline'][1]['context'],'advance after removing apron')
    def test_cancel_does_not_generate(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=RepairBackend()
            def stop(): raise InterruptedError('cancelled')
            with self.assertRaises(InterruptedError):m.generate(host,check_cancel=stop)
            self.assertEqual(host.video_count,0)

    def test_resume_after_invalidation_does_not_repeat_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=RepairBackend()
            def stop_after_apply():
                if any(r['status']=='applied' for r in m.snapshot()['repair_runs'].values()):
                    raise InterruptedError('stop after durable invalidation')
            with self.assertRaises(InterruptedError):m.generate(host,check_cancel=stop_after_apply)
            self.assertEqual(host.routes,1)
            self.assertEqual(host.video_count,2)
            self.assertTrue(any(v['stale'] for v in m.snapshot()['M']))
            m.generate(host)
            self.assertEqual(host.routes,1)
            self.assertEqual(host.video_count,3)
            self.assertFalse(any(v['stale'] for v in m.snapshot()['M']))
    def test_initial_plan_is_repaired_before_adoption(self):
        from dataclasses import asdict
        class Planner(RepairBackend):
            plans=0
            def plan_story(self,request):
                self.plans+=1
                return {'goals':['remove apron'], 'segments':[asdict(Segment('s0','remove apron',5))],
                    'beats':[dict(segment_id='s0',purpose='advance',expected_begin='before',expected_end='after',depends_on=[])]}
            def check_chain(self,request):
                return {'checks':[dict(criterion=c,status='fail' if self.plans==1 else 'pass',defect='overloaded shot',
                    evidence=[dict(source_id='plan',detail='shot contains too many actions')]) for c in request['rubrics']]}
        with tempfile.TemporaryDirectory() as tmp:
            m=self.memory(tmp);host=Planner()
            m.plan('remove apron',host)
            self.assertEqual(host.plans,2)
            self.assertEqual(host.video_count,0)
            self.assertEqual(m.snapshot()['Plan']['goals'],['remove apron'])

    def test_unknown_evidence_cannot_route(self):
        with self.assertRaises(ValueError):validate_route(dict(repair_action='regenerate_segment',segment_id='s',reason='guess',evidence_ids=['fake']),dict(segments=[{'id':'s'}],checks={},references=[]))
