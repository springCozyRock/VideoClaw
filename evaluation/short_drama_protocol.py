"""Deterministic Figure-10 units; all paper-unspecified choices are explicit."""
import hashlib
import json

VERSION = 'figure10_aligned_v2'
METRICS = ('opening_hook','end_hook','escalation_effect','narrative_coherence',
           'character_spatial_continuity','environment_layout_continuity',
           'bgm_emotion_alignment','transition_naturalness')
SCOPES = dict(zip(METRICS, ('drama','scene','scene','drama','clip_pair','clip_pair','scene','scene_pair')))
DEFAULTS = {
    'opening_seconds': 10.0,
    'scene_ending_seconds': 10.0,
    'middle_fraction': [1/3, 2/3],
    'transition_tail_seconds': 5.0,
    'transition_head_seconds': 5.0,
    'video_sampling_fps': 1.0,
    'frame_max_width': 448,
    'continuity_frame_max_width': 768,
    'continuity_frames_per_side': 3,
    'continuity_spacing': 'consecutive_decoded_frames',
    'audio': 'original aligned audio; mono 16 kHz PCM16, no BGM separation',
    'temperature': 0.1,
    'max_tokens': 2048,
}
DISCLOSURES = {
    'source': 'https://arxiv.org/html/2605.22144v1#A13.F10',
    'scope_choice': 'Figure 10 primary; Section 3.2 describes scene-level opening/coherence differently. No claim of author-resolved equivalence.',
    'paper_specified': ['8 metrics and native rubrics','integer 1-5 score plus evidence-based analysis',
                        'Figure 10 drama opening first 10 seconds','adjacent pre-assembly clip tail 3 + head 3 frames'],
    'implementation_choices_not_paper_requirements': ['last 10 seconds of each scene for end_hook',
        'middle third of each scene for escalation_effect','5 seconds either side of scene transitions',
        '1 FPS for audiovisual units','consecutive spacing of the 3+3 continuity frames',
        'frame resize/JPEG and audio encoding','temperature, token cap, retries',
        'unit mean within case, then equal weight across cases'],
    'judge_variant': 'Qwen3.5-Omni-Plus only, user selected; not original three-judge ensemble',
    'dataset_variant': 'Metrics transferred to existing project samples, not paper 50-prompt reproduction',
    'scene_boundary_limit': 'Uses declared input scene boundaries; actual semantic cuts require separately verified annotation',
    'transitions': 'Includes entire explicitly annotated transition if provided. No invented bridge clip.',
}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def settings(overrides=None):
    result = dict(DEFAULTS)
    if overrides:
        unknown=set(overrides)-set(result)
        if unknown:raise ValueError('Unknown short-drama settings: '+str(sorted(unknown)))
        result.update(overrides)
    if result['opening_seconds'] != 10 or result['continuity_frames_per_side'] != 3:
        raise ValueError('Figure 10 opening and paper 3+3 sampling must be retained')
    lo,hi=result['middle_fraction']
    if not 0 <= lo < hi <= 1:raise ValueError('Invalid middle_fraction')
    for key in ['scene_ending_seconds','transition_tail_seconds','transition_head_seconds','video_sampling_fps']:
        if result[key] <= 0:raise ValueError('Non-positive '+key)
    return result


def build_jobs(units, duration, config=None, na_reasons=None):
    cfg=settings(config);duration=float(duration)
    if duration<=0:raise ValueError('Non-positive video duration')
    scenes=units['scenes'];clips=units['clips']
    for label,items,key in [('scene',scenes,'scene_id'),('clip',clips,'clip_id')]:
        if len({x[key] for x in items})!=len(items):raise ValueError('Duplicate '+label+' id')
        previous=0
        for x in items:
            a,b=float(x['start_sec']),float(x['end_sec'])
            if a<previous-1e-6 or a<0 or b<=a or b>duration+0.1:raise ValueError('Invalid '+label+' interval')
            previous=b
        if not items:raise ValueError('No '+label+' annotations')
        if abs(float(items[0]['start_sec']))>0.1 or abs(float(items[-1]['end_sec'])-duration)>0.1:
            raise ValueError(label+' annotations do not cover full planned timeline')
        if any(abs(float(a['end_sec'])-float(b['start_sec']))>0.1 for a,b in zip(items,items[1:])):
            raise ValueError('Non-contiguous '+label+' annotations require an explicit assembled timeline')
    jobs=[]
    def av(metric,unit,a,b,context):
        if b<=a:raise ValueError('Empty evidence window')
        jobs.append(dict(metric=metric,unit=unit,scope=SCOPES[metric],kind='audiovisual',start_sec=a,end_sec=b,reference=context))
    av('opening_hook','drama_opening_10s',0,min(10.,duration),{'evaluation_region':'drama first 10 seconds'})
    av('narrative_coherence','whole_drama',0,duration,{'evaluation_region':'entire drama'})
    for scene in scenes:
        a,b=float(scene['start_sec']),float(scene['end_sec']);unit='scene_%02d'%scene['scene_id']
        av('end_hook',unit,max(a,b-cfg['scene_ending_seconds']),b,scene)
        lo,hi=cfg['middle_fraction']
        av('escalation_effect',unit,a+(b-a)*lo,a+(b-a)*hi,scene)
        av('bgm_emotion_alignment',unit,a,b,scene)
    for before,after in zip(clips,clips[1:]):
        for metric in METRICS[4:6]:
            job=dict(metric=metric,unit='clip_%02d_to_%02d'%(before['clip_id'],after['clip_id']),
                     scope=SCOPES[metric],kind='continuity',previous=before,next=after,
                     reference={'previous':before,'next':after})
            if (na_reasons or {}).get(metric):job.update(status='NOT_APPLICABLE',reason=na_reasons[metric])
            jobs.append(job)
    for before,after in zip(scenes,scenes[1:]):
        transition=next((t for t in units.get('transitions',[]) if t.get('before_scene_id')==before['scene_id'] and t.get('after_scene_id')==after['scene_id']),None)
        left=float(before['end_sec']);right=float(after['start_sec'])
        if transition:
            ta,tb=float(transition['start_sec']),float(transition['end_sec'])
            if not float(before['start_sec']) <= ta <= tb <= float(after['end_sec']):raise ValueError('Invalid annotated transition interval')
            left=min(left,ta);right=max(right,tb)
        av('transition_naturalness','scene_%02d_to_%02d'%(before['scene_id'],after['scene_id']),
           max(float(before['start_sec']),left-cfg['transition_tail_seconds']),
           min(float(after['end_sec']),right+cfg['transition_head_seconds']),
           {'previous':before,'next':after,'annotated_transition':transition,
            'no_separate_transition_annotation':transition is None})
    return jobs


def aggregate(jobs,results):
    report={}
    for metric in METRICS:
        expected=[x for x in jobs if x['metric']==metric and x.get('status')!='NOT_APPLICABLE']
        records=[x for x in results if x['metric']==metric and x.get('status')=='SCORED']
        excluded=[x for x in jobs if x['metric']==metric and x.get('status')=='NOT_APPLICABLE']
        complete=len(records)==len(expected) and bool(expected)
        report[metric]={'score':sum(x['score'] for x in records)/len(records) if complete else None,
            'scored_units':len(records),'expected_units':len(expected),'excluded_units':len(excluded),
            'status':'SCORED' if complete else ('NOT_APPLICABLE' if not expected else 'INCOMPLETE')}
    return report


def current_report(run_root, case_id):
    """Never surface legacy/partial/different-fingerprint output as current scores."""
    from pathlib import Path
    base=Path(run_root)/'evaluation'/('short_drama_'+VERSION)/case_id
    plan_path=base/'current_plan.json';summary_path=base/'latest_summary.json'
    plan=json.loads(plan_path.read_text()) if plan_path.exists() else None
    summary=json.loads(summary_path.read_text()) if summary_path.exists() else None
    if plan and summary and plan['fingerprint']==summary.get('fingerprint') and set(summary.get('metrics_selected',[]))==set(METRICS):
        return summary
    jobs=plan.get('jobs',[]) if plan else []
    return {'case_id':case_id,'status':'PENDING_ALIGNED_REEVALUATION','protocol_version':VERSION,
        'fingerprint':plan.get('fingerprint') if plan else None,'metrics':aggregate(jobs,[]) if jobs else {},
        'units':[],'legacy_results_are_current':False,
        'legacy_summary':str(Path(run_root)/'evaluation/short_drama'/case_id/'summary.json'),
        'plan':str(plan_path) if plan else None,'partial_summary':str(summary_path) if summary else None}


def parse_response(text):
    """Only tolerate one enclosing Markdown fence; never extract a loose score."""
    import re
    raw=text.strip();match=re.fullmatch(r'```(?:json)?[ \t]*\n([\s\S]*?)\n```',raw)
    value=json.loads(match.group(1) if match else raw)
    if not isinstance(value,dict) or type(value.get('score')) is not int or not 1<=value['score']<=5:
        raise ValueError('Expected JSON integer score in 1..5')
    if not isinstance(value.get('analysis'),str) or not value['analysis'].strip():
        raise ValueError('Missing evidence-based analysis')
    return value,bool(match)
