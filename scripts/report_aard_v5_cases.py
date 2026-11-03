#!/usr/bin/env python3
"""Read-only experiment monitor; writes diagnostics, never retries model calls or changes selections."""
import argparse,json,time
from collections import Counter
from pathlib import Path

def read(path,default=None):
    return json.loads(path.read_text()) if path.exists() else default

def summarize(path):
    status=read(path/'status.json',{'status':'NOT_STARTED'})
    m=read(path/'memory/memory.json',{})
    records=m.get('committed',[]);operations=m.get('operations',{})
    candidates=m.get('candidates',{});appearance=m.get('appearance_candidates',{})
    checks=[]
    for key,c in list(appearance.items())+list(candidates.items()):
        result=c.get('inspection',{}).get('checks',c.get('state_checks',{}))
        failed=[{'entity':r['condition']['entity'],'attribute':r['condition']['attribute'],'phase':r['condition']['phase'],
                 'status':r['status'],'expected':r['condition'].get('expected'),'observed':r['observed'].get('value'),
                 'reason':r['observed'].get('reason','')} for r in result.get('conditions',[]) if r['status'] not in ('passed','not_applicable')]
        if failed:checks.append({'candidate':key,'media':c.get('media'),'failures':failed})
    total=len(m.get('inputs',{}).get('segments',[]))
    return {'run':str(path),'status':status,'total_segments':total,'selected_segments':len(records),
        'internal_quality_passed':sum(bool(r['accepted']) for r in records),
        'video_response_receipt_count':len(list((path/'tasks').glob('*.response.json'))),
        'verified_appearances':list(m.get('appearance_references',{})),
        'appearance_registry_ready':m.get('appearance_registry_ready',False),
        'appearance_candidate_count':len(appearance),'boundary_video_candidate_count':len(candidates),
        'judge_response_count':len(list((path/'memory/judge_calls').glob('*/response.json'))),
        'generation_receipt_count':len(list((path/'meter/calls').glob('*.json'))),
        'operation_counts':dict(Counter(v['status'] for v in operations.values())),
        'recent_operations':[{'key':k,'status':v['status']} for k,v in list(operations.items())[-3:]],
        'final_video':status.get('video'),
        'segments':[{'index':r['index'],'id':r['segment']['id'],'accepted':r['accepted'],
            'state_passed':r.get('state_checks',{}).get('critical_passed'),'mode':r['mode'],'video':r['video'],
            'completed_goals':r['completed_goals'],'unresolved_goals':r['unresolved_goals']} for r in records],
        'failed_state_checks':checks,'case_input':read(path/'input_manifest.json'),
        'reused_receipts':read(path/'reused_operation_provenance.json'),
        'code_provenance':str(path.parent/'code_provenance.json')}

def main():
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--watch',action='store_true');a=p.parse_args()
    config=read(a.cases.resolve());out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    last=None
    while True:
        cases={name:summarize(Path(path)) for name,path in config['cases'].items()}
        terminal=all(c['status']['status'] in ('COMPLETED','BLOCKED','STOPPED_BY_USER') for c in cases.values())
        report={'updated_at':time.time(),'terminal':terminal,'cases':cases,'protocol':config.get('protocol',{}),
            'scope':'Exploratory integration validation across documented frozen V5 revisions; no official benchmark score or controlled causal improvement claim.'}
        temporary=out/'report.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2));temporary.replace(out/'report.json')
        lines=['# V5 三案例验证进度','','该报告来自运行回执；内部模型评审不是官方基准分数。不同修订的失败和修复均保留。','',
            '| 案例 | 状态 | 已选片段 | 内部质量通过 | 已验证形态 |','| --- | --- | --- | --- | --- |']
        for name,c in cases.items():lines.append('| '+name+' | '+c['status']['status']+' | '+str(c['selected_segments'])+'/'+str(c['total_segments'])+' | '+str(c['internal_quality_passed'])+' | '+str(len(c['verified_appearances']))+' |')
        for name,c in cases.items():
            lines+=['','## '+name,'','运行目录：`'+c['run']+'`','', '最近阶段：'+', '.join(x['key']+' ('+x['status']+')' for x in c['recent_operations'])]
            if c['status'].get('detail'):lines+=['','阻断原因：'+c['status']['detail']]
            if c['final_video']:lines+=['','视频：`'+c['final_video']+'`']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
        compact={name:{'status':c['status']['status'],'selected':c['selected_segments'],'verified':len(c['verified_appearances']),'last':c['recent_operations'][-1:] } for name,c in cases.items()}
        if compact!=last:print(json.dumps(compact,ensure_ascii=False),flush=True);last=compact
        if not a.watch or terminal:return
        time.sleep(30)
if __name__=='__main__':main()
