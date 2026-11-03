#!/usr/bin/env python3
"""Summarize current per-video results without rerunning any evaluation."""
from pathlib import Path
from collections import defaultdict,Counter
from statistics import mean,stdev
from datetime import datetime,timezone
import json,hashlib,math,argparse
RUNS={'Codex Agent/Skill':'codex_composition_wan3_720p','VideoClaw':'videoclaw_wan27_preview_eval'}
CASES=['action_006','cinematic_008','educational_008','music_004','narrative_074']

def aggregate(root):
 sources={};systems={}
 def read(p,jsonlines=False):
  raw=p.read_bytes();sources[str(p.relative_to(root))]=hashlib.sha256(raw).hexdigest()
  return [json.loads(s) for s in raw.decode().splitlines() if s.strip()] if jsonlines else json.loads(raw)
 def number(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
 for label,run in RUNS.items():
  base=root/'experiments'/run/'evaluation';metrics={f:defaultdict(dict) for f in ['DirectorBench','DirectorBench dimensions','VBench','ViStoryBench']};detail={};tools=Counter();mobile=Counter();judges=Counter()
  for case in CASES:
   ddir=base/'directorbench'/case;profiles=[];per_metric=defaultdict(list);per_dim=defaultdict(list);profile_metric_counts=Counter();review_count=0
   for pid in range(1,8):
    p=ddir/f'profile_{pid:02d}'/'result.json';data=read(p);assert data['profile_id']==pid and data['case_id']==case
    judges[data.get('judge','unknown')]+=1;r=data['report'];assert number(r['overall_score']);profiles.append(r['overall_score']);seen=set()
    for item in r['all_results']:
     key=item['metric_name'];assert key not in seen,(p,key);seen.add(key)
     assert key!='bgm_consistency','BGM exclusion not applied'
     if number(item.get('score')):per_metric[key].append(item['score']);profile_metric_counts[key]+=1
    for key,value in r['dimension_scores'].items():
     if number(value):per_dim[key].append(value)
    review_count+=int(bool(r.get('needs_human_review')))
    tracep=p.with_name('tool_traces.jsonl')
    if tracep.exists():
     traces=read(tracep,True);matching=[t for t in traces if t.get('report_id')==r['report_id']];assert matching,(p,'No matching tool trace')
     for t in matching[-1].get('tool_calls',[]):
      status=t.get('status','unknown');tools[(t.get('tool_name','unknown'),status)]+=1
      if 'mobileviclip' in t.get('tool_name','').lower():mobile[status]+=1
   metrics['DirectorBench']['overall_score'][case]=mean(profiles)
   for key,values in per_metric.items():metrics['DirectorBench'][key][case]=mean(values)
   for key,values in per_dim.items():metrics['DirectorBench dimensions'][key][case]=mean(values)
   detail[case]={'directorbench_profiles':7,'profile_overall_scores':profiles,'metric_profile_counts':dict(profile_metric_counts),'needs_human_review_profiles':review_count,'vistorybench_status':{}}
   vs=read(base/'vistorybench'/case/'summary.json');assert vs['case_id']==case
   for key,item in vs['metrics'].items():
    detail[case]['vistorybench_status'][key]=item.get('status')
    if item.get('status')=='SCORED':
     assert number(item.get('score')),(case,key,item)
     metrics['ViStoryBench'][key][case]=item['score']
   cs=read(ddir/'summary.json')
   # Keep summaries as sources but aggregate only authoritative result.json above.
  vfiles=sorted((base/'vbench').glob('*/full_frame_eval_results.json'));assert vfiles
  for p in vfiles:
   for key,value in read(p).items():
    assert isinstance(value,list) and len(value)==2
    for row in value[1]:
     case=Path(row['video_path']).stem;assert case in CASES,(p,case)
     assert case not in metrics['VBench'][key],(p,case,'duplicate video')
     assert number(row['video_results']);metrics['VBench'][key][case]=row['video_results']
  for key,values in metrics['VBench'].items():assert set(values)==set(CASES),(label,key)
  systems[label]={'run_id':run,'metrics':{family:{key:{'mean':mean(values.values()),'sample_std':stdev(values.values()) if len(values)>1 else None,'n_videos':len(values),'per_video':values,'excluded_cases':[case for case in CASES if case not in values]} for key,values in rows.items()} for family,rows in metrics.items()},'per_case_audit':detail,'judge_counts':dict(judges),'tool_status_counts':[{'tool':t,'status':s,'n':n} for (t,s),n in sorted(tools.items())],'mobileviclip_historical_status':dict(mobile)}
 comparison={}
 for family in ['DirectorBench','DirectorBench dimensions','VBench','ViStoryBench']:
  comparison[family]={}
  keys=sorted(set().union(*(s['metrics'][family] for s in systems.values())))
  for key in keys:
   values={label:s['metrics'][family].get(key,{}).get('per_video',{}) for label,s in systems.items()};common=sorted(set.intersection(*(set(v) for v in values.values())))
   comparison[family][key]={'means_all_available':{label:mean(v.values()) if v else None for label,v in values.items()},'n_videos':{label:len(v) for label,v in values.items()},'common_cases':common,'means_common_cases':{label:mean(v[c] for c in common) if common else None for label,v in values.items()}}
 for name,sha in sources.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,'Source changed during snapshot: '+name
 return {'created_at':datetime.now(timezone.utc).isoformat(),'scope':'Existing evaluated outputs only; no new evaluation or paid API calls','case_ids':CASES,'aggregation':{'videos':'Arithmetic mean, equal weight per video; no duration/frame-count weighting','directorbench':'Within each video, arithmetic mean over available profile-specific metric scores (7 profiles evaluated), then equal-weight mean over videos','vbench':'Use per-video video_results, not frame-weighted multi-video aggregates','vistorybench':'Use native per-video summary score, then equal-weight mean; exclude NA without zero fill','comparison':'Main means use all available videos per system; matched-case means also provided for unequal coverage'},'limitations':['Five selected DirectorBench prompts, not full official benchmark datasets','DirectorBench and ViStoryBench judge: qwen3.5-omni-plus, adapted protocol','BGM consistency excluded by user','Historical scores predate MobileViCLIP deployment; installing weights did not rerun these evaluations','Public script annotation completeness and input alignment can affect historical DirectorBench results','ViStoryBench character reference images come from generated first appearances, measuring generated-anchor stability','Dynamic applicability may differ across profiles and videos; coverage is retained','These are existing system outputs, not a controlled memory ablation'],'systems':systems,'comparison':comparison,'sources_sha256':sources}

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();report=aggregate(args.root.resolve());args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 for family,rows in report['comparison'].items():
  print(family)
  for key,row in rows.items():print(key,' | '.join(f'{label}: {value:.6f} (n={row["n_videos"][label]})' for label,value in row['means_all_available'].items() if value is not None))
 print('MOBILEVICLIP',{label:s['mobileviclip_historical_status'] for label,s in report['systems'].items()});print('SOURCES',len(report['sources_sha256']))
if __name__=='__main__':main()
