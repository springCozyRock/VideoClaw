#!/usr/bin/env python3
"""Server-side watcher: finalized media -> metrics -> incremental report.

Independent of SSH/Codex lifetime. Only frozen, verified final videos are scored.
"""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import concurrent.futures,fcntl,hashlib,json,os,subprocess,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
from workspace_paths import BASELINE_ROOT, PROJECT_ROOT, RUN_ROOT, CONFIG_ROOT, VISTORY_ENV, load_json

from short_drama_protocol import current_report
ROOT = BASELINE_ROOT;PROJECT = PROJECT_ROOT;RUN = RUN_ROOT
EVAL_SCRIPTS={'vbench':ROOT/'evaluation/vbench_full.py','short_drama':ROOT/'evaluation/eval_short_drama.py','directorbench':ROOT/'evaluation/eval_director.py','vistorybench':ROOT/'evaluation/eval_vistory.py'}
DIRECTOR='/mnt/data/bts/envs/directorbench/bin/python';VBENCH='/mnt/data/bts/envs/vbench/bin/python'
LOCK=threading.Lock();GPUS=set()

def now():return datetime.now(timezone.utc).isoformat()
def dump(path,data):
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
def read(path,default=None):return load_json(path) if path.exists() else default
def fingerprint(script):return hashlib.sha256(script.read_bytes()).hexdigest() if script.exists() else None

def evaluation_families():
 default=['vbench','short_drama','directorbench','vistorybench']
 families=read(CONFIG_ROOT/'evaluation_protocol.json',{}).get('active_evaluation_families',default)
 if not isinstance(families,list) or not families or len(set(families))!=len(families) or any(x not in EVAL_SCRIPTS for x in families):
  raise ValueError('Invalid active evaluation families')
 return families

def gpu():
 while True:
  with LOCK:
   output=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
   candidates=[]
   for row in output.splitlines():
    index,free,util=[int(x.strip()) for x in row.split(',')]
    if index not in GPUS and free>18000 and util<25:candidates.append((free,-util,index))
   if candidates:
    index=max(candidates)[2];GPUS.add(index);return index
  time.sleep(20)

def stage(cid,name,script,python,args,needs_gpu=False):
 path=RUN/'evaluation/stages'/cid/(name+'.json');old=read(path,{})
 if name not in evaluation_families():
  dump(path,{'case_id':cid,'stage':name,'status':'SKIPPED_BY_USER','score':None,'updated_at':now(),'reason':'Excluded by active_evaluation_families in evaluation_protocol.json'})
  return 'SKIPPED_BY_USER'
 sha=fingerprint(script)
 if sha is None:return 'WAITING_FOR_CONFIGURATION'
 if name=='directorbench' and read(RUN/'evaluation/asr_environment.json',{}).get('status')!='READY':return 'WAITING_FOR_CONFIGURATION'
 if name=='vistorybench' and read(RUN/'evaluation/vistory_environment.json',{}).get('status')!='READY':return 'WAITING_FOR_CONFIGURATION'
 if old.get('status')=='COMPLETE':
  if name!='short_drama':return 'COMPLETE'
  subprocess.run([python,str(script),'--case',cid,'--prepare'],cwd=str(PROJECT),check=True)
  if current_report(RUN,cid).get('status')=='COMPLETE_SELECTED_METRICS':return 'COMPLETE'
 if old.get('status')=='WAITING_PROVIDER' and old.get('retry_after',0)>time.time():return 'WAITING_PROVIDER'
 if old.get('status')=='FAILED' and old.get('script_sha256')==sha:return 'FAILED'
 env=os.environ.copy();index=gpu() if needs_gpu else None
 env['CUDA_VISIBLE_DEVICES']=str(index) if index is not None else ''
 env['OMP_NUM_THREADS']='4';env['MKL_NUM_THREADS']='4';env['HF_ENDPOINT']='https://hf-mirror.com';env['HF_HOME']='/mnt/data/bts/models/hf';env['TORCH_HOME']='/mnt/data/bts/models/torch'
 log=RUN/'logs'/('eval_'+cid+'_'+name+'.log')
 status={'case_id':cid,'stage':name,'status':'RUNNING','started_at':now(),'script_sha256':sha,'gpu':index,'log':str(log)};dump(path,status)
 print(now(),cid,name,'started',flush=True)
 try:
  with log.open('a') as handle:
   process=subprocess.Popen([python,'-u',str(script)]+args,cwd=str(PROJECT),env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT)
   status['pid']=process.pid;dump(path,status)
   try:code=process.wait(timeout=4*3600)
   except subprocess.TimeoutExpired:process.kill();process.wait();raise RuntimeError('Evaluation stage exceeded four hours; partial results preserved')
  status.update(status='COMPLETE' if code==0 else 'FAILED',exit_code=code,finished_at=now())
  pause=read(RUN/'evaluation/provider_pause.json',{})
  if code!=0 and pause.get('retry_after',0)>time.time():status.update(status='WAITING_PROVIDER',retry_after=pause['retry_after'],provider_reason=pause.get('reason'))
 except Exception as ex:status.update(status='FAILED',error=str(ex),finished_at=now())
 finally:
  if index is not None:
   with LOCK:GPUS.discard(index)
 dump(path,status);print(now(),cid,name,status['status'],flush=True);return status['status']

def run_case(cid):
 video=RUN/'videos'/(cid+'.mp4');outcomes={}
 for name in evaluation_families():
  python={'vbench':VBENCH,'short_drama':DIRECTOR,'directorbench':DIRECTOR,'vistorybench':str(VISTORY_ENV/'bin/python')}[name]
  args=['--videos',str(video),'--output',str(RUN/'evaluation/vbench'/cid)] if name=='vbench' else ['--case',cid]
  outcomes[name]=stage(cid,name,EVAL_SCRIPTS[name],python,args,name!='short_drama')
 return outcomes

def report(ids):
 rows=[];data=[];families=evaluation_families()
 labels={'vbench':'VBench','short_drama':'Short-Drama','directorbench':'DirectorBench','vistorybench':'ViStoryBench'}
 excluded=[name for name in EVAL_SCRIPTS if name not in families]
 for cid in ids:
  generation=read(RUN/'cases'/cid/'generation.json',{})
  stages={name:read(RUN/'evaluation/stages'/cid/(name+'.json'),{}).get('status','WAITING') for name in families}
  if 'short_drama' in families:stages['short_drama']=current_report(RUN,cid).get('status')
  rows.append('| '+cid+' | '+generation.get('status','GENERATING')+' | '+' | '.join(stages.values())+' |')
  item={'case_id':cid,'generation':generation,'evaluation_stages':stages}
  for name in families:
   filename='full_frame_eval_results.json' if name=='vbench' else 'summary.json'
   item[name]=current_report(RUN,cid) if name=='short_drama' else read(RUN/'evaluation'/name/cid/filename)
  data.append(item)
 dump(RUN/'evaluation/summary.json',{'updated_at':now(),'judge':'qwen3.5-omni-plus','protocol_variant':'user_authorized_unified_qwen35','active_evaluation_families':families,'excluded_evaluation_families':excluded,'cases':data,'human_evaluation':'Prepared separately; requires real annotators, not included as completed metrics'})
 header='| Case | Generation | '+' | '.join(labels[name] for name in families)+' |'
 separator='|'+'---|'*(len(families)+2)
 text='# Five-sample generation and evaluation\n\nUpdated: '+now()+'\n\nModel: wan3.0-video; 720P; 16:9; audio; original total duration 469 seconds. All LLM/VLM judges: qwen3.5-omni-plus.\n\n'+header+'\n'+separator+'\n'+'\n'.join(rows)+'\n\nExcluded by user: '+(', '.join(excluded) or 'none')+'. Prior excluded outputs are retained as historical evidence and are not aggregated.\n\nThis is a five-prompt experiment, not the complete datasets reported in either paper. Judge substitutions and protocol adaptations are disclosed in evaluation_protocol.json. Native automatic encoders are unchanged. No human scores are fabricated.\n\nMachine-readable results: '+str(RUN/'evaluation/summary.json')+'.\n'
 (RUN/'REPORT.md').write_text(text)

def main():
 lock=(RUN/'evaluation_watch.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 ids=[x['case_id'] for x in read((CONFIG_ROOT / 'manifest.json'))['cases']];active={};checked={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  while True:
   for cid,job in list(active.items()):
    if job.done():
     try:checked[cid]=job.result()
     except Exception as ex:checked[cid]={'watcher_error':str(ex)}
     del active[cid]
   for cid in ids:
    if cid in active:continue
    if not (RUN/'cases'/cid/'generation.json').exists():continue
    stages=[read(RUN/'evaluation/stages'/cid/(name+'.json'),{}) for name in evaluation_families()]
    if all(s.get('status')=='COMPLETE' for s in stages):continue
    if cid in checked:
     repaired=any(s.get('status')=='FAILED' and s.get('script_sha256')!=fingerprint(EVAL_SCRIPTS[s['stage']]) for s in stages)
     waiting=checked[cid].get('vistorybench')=='WAITING_FOR_CONFIGURATION'
     vistory_ready=EVAL_SCRIPTS['vistorybench'].exists() and read(RUN/'evaluation/vistory_environment.json',{}).get('status')=='READY'
     waiting_asr=checked[cid].get('directorbench')=='WAITING_FOR_CONFIGURATION' and read(RUN/'evaluation/asr_environment.json',{}).get('status')=='READY'
     provider_ready=any(s.get('status')=='WAITING_PROVIDER' and s.get('retry_after',0)<=time.time() for s in stages)
     if not repaired and not waiting_asr and not provider_ready and not (waiting and vistory_ready):continue
    if len(active)<2:active[cid]=pool.submit(run_case,cid)
   report(ids)
   complete=all(all(read(RUN/'evaluation/stages'/cid/(name+'.json'),{}).get('status')=='COMPLETE' for name in evaluation_families()) for cid in ids)
   if complete:
    dump(RUN/'evaluation/finished.json',{'status':'AUTOMATIC_EVALUATION_COMPLETE','finished_at':now(),'judge':'qwen3.5-omni-plus','human_evaluation':'AWAITING_REAL_ANNOTATORS'});print(now(),'all automatic evaluations complete',flush=True);return
   dump(RUN/'evaluation/watch_status.json',{'status':'RUNNING','updated_at':now(),'active_cases':list(active),'checked_cases':checked})
   time.sleep(30)

if __name__=='__main__':main()
