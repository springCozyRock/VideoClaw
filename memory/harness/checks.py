"""DramaChain-inspired evidence checks. This is not the official 63-leaf benchmark."""
import copy
import math
from memory.assets.files import digest

RUBRICS = {
    'event': {'F.event_state': 'Actual video establishes the planned event outcome and expected end state'},
    'plan': {'F.event_coverage': 'User events and constraints are preserved',
             'P.executability': 'Actions fit the shot duration and are causally executable',
             'E.progression': 'Each beat advances the story without unintended repetition'},
    'frame': {'F.state': 'Boundary matches its intended temporal role',
              'C.identity': 'Identity, scene and props agree with relevant references',
              'P.layout': 'Visible anatomy and spatial layout are plausible'},
    'video': {'F.event_completion': 'Required events actually occur',
              'C.temporal': 'Identity, scene, props and motion remain consistent',
              'P.causal': 'Actions obey temporal and causal preconditions'},
    'sequence': {'C.cross_shot': 'State, props and actions connect across shots',
                 'P.causal': 'Completed events establish later event preconditions',
                 'E.progression': 'The sequence advances goals without unintended repetition or stalling'},
}
ACTIONS = {'event': 'regenerate_video', 'plan': 'revise_plan', 'reference': 'replace_reference',
           'frame': 'repair_frame', 'video': 'regenerate_video', 'sequence': 'review_dependencies'}


def validate_report(value, request):
    checks = value.get('checks')
    if not isinstance(checks, list) or {c.get('criterion') for c in checks} != set(request['rubrics']) or len(checks) != len(request['rubrics']):
        raise ValueError('Cover every requested criterion exactly once')
    for c in checks:
        if c.get('status') not in ('pass', 'fail', 'unknown'):
            raise ValueError('Use pass/fail/unknown')
        evidence = c.get('evidence')
        if not isinstance(evidence, list) or (c['status'] != 'unknown' and not evidence):
            raise ValueError('Definite judgments require evidence')
        for e in evidence:
            source = request['sources'].get(e.get('source_id'))
            if source is None or not isinstance(e.get('detail'), str) or not e['detail'].strip():
                raise ValueError('Evidence must cite an available source and describe it')
            if 'start' in e or 'end' in e:
                a, b = e.get('start'), e.get('end')
                if any(type(x) not in (float, int) or not math.isfinite(x) for x in (a,b)) or not 0 <= a <= b <= source.get('duration', -1):
                    raise ValueError('Invalid evidence timestamps')
            if source['kind'] == 'video' and c['status'] != 'unknown' and 'start' not in e:
                raise ValueError('Video evidence requires timestamps')
            if 'bbox' in e:
                box=e['bbox']
                if not isinstance(box,list) or len(box)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) for x in box) or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:
                    raise ValueError('Bounding box must use normalized xyxy')
        cited = {e['source_id'] for e in evidence}
        videos = {k for k,v in request['sources'].items() if v['kind']=='video'}
        if request.get('stage') == 'sequence' and len(videos) > 1 and c['status'] != 'unknown':
            required = len(videos) if c['status']=='pass' else 2
            if len(cited & videos) < required:
                raise ValueError('Sequence judgments require paired evidence; passing covers all videos')
        if c['criterion']=='C.identity' and c['status'] != 'unknown':
            anchors = {k for k,v in request['sources'].items() if v.get('role')=='identity_anchor'}
            candidates = {k for k,v in request['sources'].items() if v.get('role')=='candidate'}
            if not anchors or not cited & anchors or not cited & candidates:
                raise ValueError('Identity comparison requires candidate and anchor evidence; otherwise unknown')
        if c['status'] == 'fail' and not c.get('defect'):
            raise ValueError('Failures require a defect description')
    # Attribution is only a hypothesis, even when a judge sounds certain.
    return {'checks': copy.deepcopy(checks), 'status': 'fail' if any(c['status']=='fail' for c in checks)
            else 'unknown' if any(c['status']=='unknown' for c in checks) else 'pass'}


class ChainAudit:
    def __init__(self, store, host):
        self.store, self.host = store, host

    def check(self, stage, sources, intent=None):
        request = {'stage': stage, 'rubrics': RUBRICS[stage], 'sources': sources, 'intent': intent}
        key = 'chain/' + digest(request)
        if not hasattr(self.host, 'check_chain'):
            report = {'status': 'unknown', 'checks': [dict(criterion=k,status='unknown',evidence=[]) for k in RUBRICS[stage]]}
        else:
            report = self.store.operation(key, request,
                lambda: validate_report(self.host.check_chain(request), request))
        report = dict(report, id=key, stage=stage, sources=copy.deepcopy(sources))
        self.store.data.setdefault('checks', {})[key] = report
        if report['status'] == 'fail':
            self.store.data.setdefault('active_failure_checks', []).append(key)
            self.store.data.setdefault('repairs', {}).setdefault(key, {
                'check_id': key, 'status': 'proposed',
                'action': ACTIONS[stage], 'attribution_status': 'hypothesis',
                'source_ids': list(sources), 'requires_recheck': True,
                'reason': 'Inspect upstream dependencies before executing; detected defects do not prove root cause'})
        self.store.save()
        return report
