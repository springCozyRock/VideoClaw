#!/usr/bin/env python3
"""One-shot continuation: verify remaining metrics on public fixtures as weights arrive."""
import fcntl,json,os,subprocess,sys,time,datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'configs/msvbench/continuation.json'
TASKS={
 'camera_control':['monst3r','sea-raft'],
 'story_video_consistency':['kalm-v2','sharecaptioner'],
 'background_consistency':['step1x'],
 'vqa':['vqa'],
}

def read(path):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return {}

def save(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False));tmp.replace(path)

def download(name):
 return read(ROOT/'configs/msvbench/vqa-download.json' if name=='vqa' else ROOT/f'configs/msvbench/downloads/{name}.json')

def update_deployment(metric,evidence):
 path=ROOT/'configs/msvbench/deployment.json'
 with (ROOT/'.cache/msvbench/deployment.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  obj=read(path)
  obj['metrics'][metric]={'status':'SMOKE_VERIFIED','evidence':[evidence],'scope':'Public reference fixtures; adapted protocol, not formal benchmark scores'}
  obj['verified_named_metrics']=sum(x['status']=='SMOKE_VERIFIED' for x in obj['metrics'].values())
  obj['full_benchmark_ready']=False
  obj['all_metric_smoke_tests_passed']=obj['verified_named_metrics']==len(obj['metrics'])
  obj['updated']=datetime.datetime.now().isoformat()
  save(path,obj)

def main():
 os.chdir(ROOT)
 with (ROOT/'.cache/msvbench/autoverify.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  obj=read(STATE)
  if not obj:obj={'scope':'Only synthetic/public MSVBench fixtures; one-shot deployment continuation','tasks':{m:{'status':'WAITING_WEIGHTS','dependencies':d} for m,d in TASKS.items()}}
  obj.update(pid=os.getpid(),status='ACTIVE',started=obj.get('started',time.time()))
  deadline=time.time()+24*3600
  while time.time()<deadline:
   obj['updated']=time.time();save(STATE,obj)
   for metric,deps in TASKS.items():
    item=obj['tasks'][metric]
    if item['status'] in ('SMOKE_VERIFIED','FAILED','BLOCKED_DOWNLOAD'):continue
    states={name:download(name).get('status','UNKNOWN') for name in deps}
    item['download_states']=states
    if any(s=='FAILED' for s in states.values()):
     item.update(status='BLOCKED_DOWNLOAD',reason='A required download failed; inspect its JSON/log');continue
    if not all(s.startswith('DOWNLOADED') for s in states.values()):
     item['status']='WAITING_WEIGHTS';continue
    try:
     free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits','-i','4'],text=True).strip())
    except Exception as ex:item.update(status='WAITING_GPU',reason=str(ex));continue
    if free<30000:item.update(status='WAITING_GPU',free_mib=free);continue
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out=Path('experiments/msvbench_smoke')/f'auto-{stamp}-{metric}'
    fixture=Path('experiments/msvbench_smoke/public_pair')
    cmd=['bash','scripts/msvbench.sh','--method','public_reference_smoke','--story','01','--metric',metric,'--videos',str(fixture/'videos'),'--prompt',str(fixture/'prompt.txt'),'--script',str(fixture/'character_fixture.json'),'--camera',str(fixture/'camera.txt'),'--output-root',str(out)]
    item.update(status='RUNNING',command=cmd,started=time.time());save(STATE,obj)
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='4',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',MSVBENCH_KALM_ATTN='sdpa')
    log=ROOT/f'.cache/msvbench/autoverify-{metric}.log'
    try:
     with log.open('w') as stream:
      result=subprocess.run(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=4*3600)
     evidence=out/'public_reference_smoke/01'/metric/'status.json'
     native=read(ROOT/evidence)
     item.update(returncode=result.returncode,evidence=str(evidence),log=str(log.relative_to(ROOT)),finished=time.time())
     if result.returncode==0 and native.get('status')=='SCORED' and not native.get('issues'):
      item['status']='SMOKE_VERIFIED';update_deployment(metric,str(evidence))
     else:item.update(status='FAILED',reason='Actual inference failed; score invalid. Inspect evidence/log.')
    except Exception as ex:item.update(status='FAILED',error=str(ex),log=str(log.relative_to(ROOT)))
    save(STATE,obj)
   if all(i['status'] in ('SMOKE_VERIFIED','FAILED','BLOCKED_DOWNLOAD') for i in obj['tasks'].values()):
    obj['status']='FINISHED' if all(i['status']=='SMOKE_VERIFIED' for i in obj['tasks'].values()) else 'NEEDS_ATTENTION'
    save(STATE,obj);return
   time.sleep(30)
  obj['status']='TIME_LIMIT_REACHED';save(STATE,obj)

if __name__=='__main__':main()
