"""Separate execution status, metric evidence coverage and protocol validity."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,json,time
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CONFIG_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT
def load(path,default=None):return load_json(path) if path.exists() else default
def save(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
def audit():
 cases=[]
 for item in load((CONFIG_ROOT / 'manifest.json'))['cases']:
  cid=item['case_id'];entry={'case_id':cid};sd=load(RUN/'evaluation/short_drama'/cid/'summary.json')
  entry['short_drama']={'failed_units':sum(x.get('failed_units',0) for x in sd['metrics'].values()),'applicable_scored_units':sum(x.get('scored_units',0) for x in sd['metrics'].values()),'raw_judge_units':len(sd['units']),'not_applicable':{k:v['status'] for k,v in sd['metrics'].items() if v['score'] is None}}
  vs=load(RUN/'evaluation/vistorybench'/cid/'summary.json');native=load(RUN/'evaluation/vistorybench'/cid/'cids_native.json',{})
  entry['vistorybench']={'sampled_frames':vs['n_sampled_frames'],'single_action_detection_matched_frames':len(native.get('detailed_scores',{})) if native else None,'single_action_coverage_note':'Native score is conditional on successful detection/matching, not a full-frame denominator. Missing detections are not judge failures.','not_applicable':{k:v['status'] for k,v in vs['metrics'].items() if v.get('status')!='SCORED'}}
  profiles=[]
  for path in sorted((RUN/'evaluation/directorbench'/cid).glob('profile_*/result.json')):
   d=load(path);calls=[]
   trace=path.parent/'tool_traces.jsonl'
   if trace.exists():
    for line in trace.read_text().splitlines():calls.extend(json.loads(line).get('tool_calls',[]))
   skip_bgm='bgm_consistency' in d.get('metric_policy',{}).get('excluded_metrics',{})
   required=['MobileViCLIP-Small','ASR/FasterWhisper']+([] if skip_bgm else ['AudioShake'])
   gaps=[{k:v for k,v in x.items() if k in ['tool_name','status','detail','affects']} for x in calls if x.get('tool_name') in required and str(x.get('status')).lower() not in ['success']]
   report=d['report'];missing_bgm=[{'metric_name':x.get('metric_name'),'native_fallback_score':x.get('score'),'confidence':x.get('confidence'),'primary_measured_score':None} for x in report.get('all_results',[]) if x.get('metric_name')=='bgm_consistency' and x.get('intermediate_repr',{}).get('bgm_features',{}).get('status')=='no_bgm_track']
   profiles.append({'profile_id':d['profile_id'],'execution_status':'COMPLETE','validity':'PROVISIONAL_TOOL_FALLBACKS' if gaps or missing_bgm else 'EVIDENCE_CHECK_PASSED','native_overall_score':report['overall_score'],'tool_gaps':gaps,'unmeasured_metrics':missing_bgm,'excluded_metrics':d.get('metric_policy',{}).get('excluded_metrics',{}),'note':'ASR transcript gaps cannot establish actual audio silence; low-confidence music/voice transcription may hallucinate.'})
  entry['directorbench']={'completed_profiles':len(profiles),'expected_profiles':7,'profiles':profiles};cases.append(entry)
 complete=sum(x['directorbench']['completed_profiles'] for x in cases)
 output={'updated_at_epoch':time.time(),'status':'AUTOMATIC_EXECUTION_FINISHED_WITH_REVIEW_GAPS' if complete==35 else 'PARTIAL_EVALUATION_UNDER_REVIEW','directorbench_completed_profiles':complete,'directorbench_expected_profiles':35,'judge':'qwen3.5-omni-plus','protocol_variant':True,'cases':cases,'human_ratings_collected':0,'primary_warning':'Execution COMPLETE does not imply exact original protocol or complete evidence. Keep native fallback values auditable; do not describe them as measured BGM quality.'}
 save(RUN/'evaluation/validity.json',output);return complete
def main():
 p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');args=p.parse_args()
 while True:
  complete=audit()
  if not args.watch or complete==35:return
  time.sleep(60)
if __name__=='__main__':main()
