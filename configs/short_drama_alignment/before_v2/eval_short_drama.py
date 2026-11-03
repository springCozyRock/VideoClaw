#!/usr/bin/env python3
"""Paper Short-Drama-Bench metrics with its available Qwen original judge.

Single-judge results are explicitly partial; absent ensemble members stay NA.
"""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,json,re,statistics
from pathlib import Path
from eval_media import ROOT,RUN,audiovisual,continuity,dump,judge
from workspace_paths import CONFIG_ROOT, INPUT_ROOT, REFERENCES_ROOT, load_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--case',required=True);a=p.parse_args();cid=a.case
 protocol=load_json((CONFIG_ROOT / 'evaluation_protocol.json'))['short_drama']
 units=load_json((CONFIG_ROOT / 'evaluation_units.json'))[cid]
 plan=load_json((INPUT_ROOT) / cid / 'plan.json')
 context=((INPUT_ROOT)/cid/'benchmark_prompt.txt').read_text()
 template=((REFERENCES_ROOT / 'short_drama_evaluation_template.txt')).read_text().split('Metric-specific fields:')[0]
 video=RUN/'videos'/(cid+'.mp4');out=RUN/'evaluation/short_drama'/cid
 if not video.exists():raise FileNotFoundError(video)
 jobs=[]
 jobs.append(('opening_hook','drama_opening_10s',0,min(10,plan['duration_sec']),None))
 jobs.append(('narrative_coherence','whole_drama',0,plan['duration_sec'],None))
 for scene in units['scenes']:
  for metric in ['end_hook','escalation_effect','bgm_emotion_alignment']:
   jobs.append((metric,'scene_%02d'%scene['scene_id'],scene['start_sec'],scene['end_sec'],None))
 for previous,next_clip in zip(units['clips'],units['clips'][1:]):
  for metric in ['character_spatial_continuity','environment_layout_continuity']:
   jobs.append((metric,'clip_%02d_to_%02d'%(previous['clip_id'],next_clip['clip_id']),None,None,(previous,next_clip)))
 for before,after in zip(units['scenes'],units['scenes'][1:]):
  jobs.append(('transition_naturalness','scene_%02d_to_%02d'%(before['scene_id'],after['scene_id']),before['start_sec'],after['end_sec'],None))
 results=[];cache={}
 for metric,unit,start,end,pair in jobs:
  jobout=out/metric/unit
  if (jobout/'result.json').exists():result=load_json(jobout / 'result.json')
  else:
   try:
    if pair:
     before,after=pair
     paths=[RUN/'cases'/cid/('shot_%02d.mp4'%x['clip_id']) for x in pair]
     key=('pair',before['clip_id'],after['clip_id'])
     if key not in cache:cache[key]=continuity(*paths,out/'evidence'/unit)
    else:
     key=(start,end)
     if key not in cache:cache[key]=audiovisual(video,start,end,out/'evidence'/('%03d_%03d'%(start,end)))
    content,evidence=cache[key]
    info=protocol['rubrics'][metric]
    prompt=template.replace('{metric}',metric).replace('{scope}',info['scope']+'; evaluation unit '+unit).replace('{rubric}',info['rubric']).replace('{context}',context+'\nCurrent planned screenplay unit: '+unit+'\n'+json.dumps(evidence,ensure_ascii=False))
    result=judge(prompt,content,jobout)
   except Exception as ex:
    result={'status':'FAILED','error':str(ex)};dump(jobout/'failure.json',result)
  results.append(dict(result,metric=metric,unit=unit,case_id=cid))
  print(cid,metric,unit,result.get('score',result.get('error')),flush=True)
 summary={}
 for metric in protocol['metrics']:
  items=[x for x in results if x['metric']==metric]
  scored=[x['score'] for x in items if x['status']=='SCORED']
  summary[metric]={'score':statistics.mean(scored) if scored else None,'scored_units':len(scored),'expected_units':len(items),'failed_units':len(items)-len(scored),'status':'SCORED' if scored and len(scored)==len(items) else ('NOT_APPLICABLE_NO_SCENE_PAIR' if not items else 'INCOMPLETE')}
  reason=protocol.get('not_applicable_by_case',{}).get(cid,{}).get(metric)
  if reason:
   raw=summary[metric].copy()
   summary[metric]={'score':None,'scored_units':0,'expected_units':0,'failed_units':0,'status':'NOT_APPLICABLE_'+reason,'raw_model_summary':raw,'adaptation_note':'Cross-dataset applicability decision; raw judge units are preserved for audit, excluded from primary aggregation.'}
 report={'case_id':cid,'status':'UNIFIED_QWEN35_SCORED','judge':'qwen3.5-omni-plus','judge_count':1,'protocol_variant':'user_authorized_unified_qwen35','original_paper_judge_ensemble':protocol['paper_judges'],'sampling_disclosures':{k:protocol[k] for k in ['sampling_status','continuity_spacing_status','scope_conflict']},'metrics':summary,'units':results}
 dump(out/'summary.json',report)
 if any(x['status']=='FAILED' for x in results):raise RuntimeError('Some judge units failed; see saved evidence and errors')

if __name__=='__main__':main()
