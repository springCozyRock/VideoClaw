"""Evidence-routed, bounded cross-stage repair with durable outcome tracking."""
import copy
from dataclasses import asdict
from memory.harness.checks import ChainAudit
from memory.contracts.errors import QualityBlocked
from memory.contracts.models import Segment, Reference
from memory.assets.files import digest, media
from memory.narrative.planning import validate_plan


def validate_route(value, request):
    if value.get('action') not in ('revise_plan', 'replace_reference', 'regenerate_segment'):
        raise ValueError('Unsupported repair action')
    if value.get('segment_id') not in {s['id'] for s in request['segments']}:
        raise ValueError('Unknown repair segment')
    if not value.get('reason') or not value.get('evidence_ids') or not set(value['evidence_ids']) <= set(request['checks']):
        raise ValueError('Attribution requires existing check IDs and a reason')
    if value['action']=='replace_reference':
        if value.get('reference_id') not in {r['id'] for r in request['references']} or not value.get('prompt'):
            raise ValueError('Reference repair requires an existing reference and prompt')
    return dict(value, attribution_status='hypothesis')


class RepairLoop:
    def __init__(self, store, host, policy):
        self.store, self.host, self.policy = store, host, policy

    def apply(self, segments, references, cancel=None):
        if cancel: cancel()
        pending = self.store.data.get('pending_repair')
        if pending:
            key, request = pending['id'], copy.deepcopy(pending['request'])
            checks = request['checks']
        else:
            checks = {k:v for k,v in self.store.data.get('checks',{}).items()
                      if k in self.store.data.get('active_failure_checks', []) and v['status']=='fail'
                      and self.store.data.get('repairs',{}).get(k,{}).get('status')=='proposed'}
            if not checks:
                raise QualityBlocked('No evidence-backed chain failure available for cross-stage repair')
            request = {'segments':[asdict(s) for s in segments], 'references':[asdict(r) for r in references],
                       'checks':checks, 'plan':self.store.data.get('plan'),
                       'actual_memory':self.store.snapshot(), 'budget':self.policy.chain_repairs,
                       'experiences':self.store.data.get('repair_experiences', [])[-20:]}
            key='repair/'+digest([self.store.data.get('fingerprint'), sorted(checks), len(self.store.data.get('repair_runs', {}))])
            self.store.data['pending_repair'] = {'id':key, 'request':copy.deepcopy(request)}
            self.store.save()
        self.store.data.setdefault('repair_runs', {})
        route=self.store.operation(key+'/route',request,
            lambda:validate_route(self.host.plan_chain_repair(request),request))
        start=next(i for i,s in enumerate(segments) if s.id==route['segment_id'])
        start=min(start,len(self.store.data['committed']))
        new_segments, new_refs=list(segments),list(references)
        plan=None
        if route['action']=='revise_plan':
            oldplan=self.store.data.get('plan')
            if not oldplan:
                raise QualityBlocked('Plan repair requires a registered versioned Plan')
            plan_request=copy.deepcopy(self.store.data.get('planning_request',{}))
            plan_request.update(previous_plan=oldplan, goals=oldplan['goals'],
                completed=[asdict(s) for s in segments[:start]],
                actual_memory=request['actual_memory'], repair=route, defects=checks)
            plan=self.store.operation(key+'/plan',plan_request,
                lambda:validate_plan(self.host.plan_story(plan_request),plan_request))
            report=ChainAudit(self.store,self.host).check('plan',{'plan':{'kind':'text','content':plan}},plan_request)
            if report['status']!='pass':
                raise QualityBlocked('Repaired plan was not verified')
            new_segments=[Segment(**s) for s in plan['segments']]
        elif route['action']=='replace_reference':
            ref=next(r for r in references if r.id==route['reference_id'])
            target=self.store.root/'repairs'/digest(key)/'reference.png'
            target.parent.mkdir(parents=True,exist_ok=True)
            asset=self.store.operation(key+'/reference',{'route':route,'source':media(ref.path)},
                lambda:media(self.host.render_frame(Segment('repair-reference',ref.description,1,ref.entities,ref.locations),
                    route['prompt'],[ref.path],target)))
            report=ChainAudit(self.store,self.host).check('frame',{'candidate':dict(asset,kind='frame',role='candidate'),
                'identity_anchor':dict(media(ref.path),kind='frame',role='identity_anchor')},
                {'reference':asdict(ref),'defects':checks})
            if report['status']!='pass':
                raise QualityBlocked('Repaired reference was not verified')
            new_refs=[Reference(r.id,asset['path'],r.description,r.entities,r.locations) if r.id==ref.id else r for r in references]
            # Reference plans may affect any segment; conservatively invalidate all.
            start=0
        if cancel: cancel()
        run={'id':key,'route':route,'status':'applied','before_checks':list(checks),
             'segments':[asdict(s) for s in new_segments], 'references':[asdict(r) for r in new_refs],
             'invalidated_from':start}
        self.store.data['repair_runs'][key]=run
        for cid in checks:
            self.store.data['repairs'][cid]['status']='executing'
            self.store.data['repairs'][cid]['run_id']=key
        if plan:
            self.store.data['plan']=plan
            self.store.data.setdefault('plan_versions',{})[plan['revision_id']]=plan
        self.store.data.pop('pending_repair', None)
        self.store.revise_execution(new_segments,new_refs,start)
        return new_segments,new_refs

    def finish(self, report):
        for run in self.store.data.get('repair_runs',{}).values():
            if run['status']!='applied': continue
            run.update(status='verified' if report['status']=='pass' else 'unresolved', after_check=report['id'])
            for cid in run['before_checks']:
                self.store.data['repairs'][cid]['status']=run['status']
            # Improvement is an observed evaluation outcome, not proof of causal attribution.
            self.store.data.setdefault('repair_experiences',[]).append({
                'run_id':run['id'],'action':run['route']['action'],
                'before_checks':run['before_checks'],'after_check':report['id'],
                'outcome':run['status'],'attribution_status':'hypothesis'})
        self.store.save()
