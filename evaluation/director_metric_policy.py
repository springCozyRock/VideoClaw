"""User-authorized BGM exclusion with native offline score reaggregation."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parent
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,copy,fcntl,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CONFIG_ROOT, DIRECTOR_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT
sys.path.insert(0,str((DIRECTOR_ROOT)))
from directorbench.agents.diagnosis import DiagnosisSynthesizer
from directorbench.config import EvalConfig
from directorbench.schemas import EvalResult,UserProfile,DiagnosisReport

METRIC='bgm_consistency'
CHECKPOINTS=['bgm_mood_match','bgm_transition_smoothness','bgm_tempo_pacing','bgm_volume_balance']
POLICY={'version':'user_skip_bgm_v1','excluded_metrics':{METRIC:{'status':'SKIPPED_BY_USER','score':None,'checkpoint_ids':CHECKPOINTS,'aggregation':'Excluded; remaining metric and dimension weights normalized by native DirectorBench methods.'}}}

def read(p):return load_json(p)
def write(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.%d.tmp'%os.getpid());tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def apply_policy(result,profile):
 if result.get('metric_policy',{}).get('version')==POLICY['version']:return result
 updated=copy.deepcopy(result);old=result['report'];raw=[EvalResult.model_validate(x) for x in old['all_results']]
 synth=DiagnosisSynthesizer.__new__(DiagnosisSynthesizer);synth.config=EvalConfig()
 native_before=synth._compute_overall_score(synth._compute_dimension_scores(raw,profile),profile)
 if abs(native_before-old['overall_score'])>1e-8:raise RuntimeError('Native aggregation parity failed before exclusion')
 retained=[x for x in raw if x.metric_name!=METRIC]
 dimensions=synth._compute_dimension_scores(retained,profile);overall=synth._compute_overall_score(dimensions,profile)
 report=updated['report'];report['all_results']=[x.model_dump(mode='json') for x in retained]
 report['dimension_scores']=dimensions;report['overall_score']=overall;report['overall_grade']=synth._assign_grade(overall)
 report['bottlenecks']=[x.model_dump(mode='json') for x in synth._identify_bottlenecks(retained)]
 report['needs_human_review']=[x.model_dump(mode='json') for x in retained if x.confidence<synth.config.confidence_threshold]
 report['checkpoint_registry_snapshot']=synth._build_checkpoint_snapshot(retained)
 labels={'script':'Script Quality','video':'Visual Quality','audio':'Audio Quality','crossmodal':'Cross-Modal Alignment','stability':'Generation Stability'}
 report['radar_data']={labels[k]:v for k,v in dimensions.items()}
 report['summary']='Overall score %.4f (Grade %s), excluding bgm_consistency at the user\'s request.'%(overall,report['overall_grade'])
 report['detailed_analysis']='BGM consistency and its four checkpoints are SKIPPED_BY_USER. Remaining individual metric results are unchanged; dimensions, overall score, grade, bottlenecks and review lists are recomputed with native DirectorBench methods. Earlier judge narrative was based on a different metric set and is retained in before_bgm_skip/result.json for audit. Other tool limitations remain visible in tool_traces.jsonl and evaluation/validity.json.'
 updated['metric_policy']=copy.deepcopy(POLICY);updated['protocol_variant']='user_authorized_unified_qwen35_without_bgm_consistency'
 updated.setdefault('config',{})['excluded_metrics']=[METRIC]
 if [x for x in old['all_results'] if x['metric_name']!=METRIC]!=report['all_results']:raise RuntimeError('Retained metric values changed')
 DiagnosisReport.model_validate(report)
 return updated

def sweep():
 profiles={p['profile_id']:UserProfile.from_profile_dict(p) if 'personalization' in p else UserProfile(**p) for p in read((CONFIG_ROOT / 'directorbench_profiles.json'))}
 count=changed=0;cases=[]
 for item in read((CONFIG_ROOT / 'manifest.json'))['cases']:
  cid=item['case_id'];folder=RUN/'evaluation/directorbench'/cid;results=[]
  for path in sorted(folder.glob('profile_*/result.json')):
   result=read(path);count+=1
   if result.get('metric_policy',{}).get('version')!=POLICY['version']:
    revised=apply_policy(result,profiles[result['profile_id']]);archive=path.parent/'before_bgm_skip/result.json'
    if not archive.exists():write(archive,result)
    write(path,revised);changed+=1;result=revised
    # Keep native append-only records untouched; publish the revised record separately.
    source=path.parent/'results.jsonl'
    if source.exists():
     records=[]
     for line in source.read_text().splitlines():
      record=json.loads(line)
      if record.get('report_id')==result['report']['report_id']:
       record['results']=result['report'];record['checkpoint_registry']=result['report']['checkpoint_registry_snapshot'];record['metric_policy']=POLICY;records.append(record)
     target=path.parent/'results_excluding_bgm.jsonl';temp=target.with_name(target.name+'.%d.tmp'%os.getpid());temp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records));temp.replace(target)
   results.append(result)
  if results:write(folder/'summary.json',results)
  cases.append({'case_id':cid,'policy_applied_profiles':len(results),'expected_profiles':7})
 status={'updated_at':datetime.now(timezone.utc).isoformat(),'policy':POLICY,'policy_applied_profiles':count,'expected_profiles':35,'changed_this_sweep':changed,'validation':'Native aggregation parity checked before each update; retained metric results unchanged; revised reports schema-validated; no paid judge or generation calls.','cases':cases}
 write(RUN/'evaluation/bgm_skip_status.json',status)
 print('BGM exclusion: profiles',count,'updated',changed,flush=True)
 return count

def main():
 p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');args=p.parse_args()
 lock=(RUN/'bgm_policy.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 completed_checks=0
 while True:
  count=sweep();completed_checks=completed_checks+1 if count==35 else 0
  if not args.watch or completed_checks>=3:return
  time.sleep(15)
if __name__=='__main__':main()
