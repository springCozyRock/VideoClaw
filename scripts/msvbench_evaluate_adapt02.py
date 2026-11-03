#!/usr/bin/env python3
"""Evaluate only the separately-labelled user-authorized story-02 adaptation."""
from pathlib import Path
import os,json,time,subprocess,fcntl
ROOT=Path(__file__).resolve().parents[1];FOLDER=ROOT/'experiments/msvbench_agents_20261018/videoclaw_adapted/stories/02';REPAIR=ROOT/'experiments/msvbench_repair_20261019'
def read(p):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return {}
def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2));t.replace(p)
def main():
 with (FOLDER/'evaluation.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if read(FOLDER/'status.json').get('status')!='GENERATED':raise RuntimeError('Adaptation is not complete')
  row=read(FOLDER/'evaluation_inputs.json');state=read(FOLDER/'evaluation_state.json') or {'status':'RUNNING','variant':'CONTENT_ADAPTED','tasks':{}}
  metrics=read(ROOT/'configs/msvbench/deployment.json')['metrics']
  ordered=[m for m in metrics if m!='story_video_consistency']+['story_video_consistency']
  for metric in ordered:
   if state['tasks'].get(metric,{}).get('status') in ['SCORED','PARTIAL','FAILED']:continue
   if metrics[metric]['status']!='SMOKE_VERIFIED':continue
   deadline=time.time()+86400
   while int(subprocess.check_output(['nvidia-smi','-i','5','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())<35000:
    if time.time()>deadline:raise RuntimeError('GPU wait limit')
    time.sleep(30)
   out=REPAIR/'adapted_evaluation_runs'/time.strftime('%Y%m%d-%H%M%S')
   cmd=['bash',str(ROOT/'scripts/msvbench.sh'),'--method','videoclaw_adapted','--story','02','--metric',metric,'--videos',str(FOLDER/'shots'),'--prompt',row['prompt'],'--script',row['script'],'--camera',row['camera'],'--characters',row['evaluation_characters'],'--output-root',str(out)]
   state['tasks'][metric]={'status':'RUNNING','started':time.time()};save(FOLDER/'evaluation_state.json',state)
   log=REPAIR/'adapted_evaluation_logs'/(metric+'.log');log.parent.mkdir(parents=True,exist_ok=True)
   try:
    with log.open('w') as stream:r=subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,CUDA_VISIBLE_DEVICES='5',PYTHONUTF8='1',MSVBENCH_DNS_FALLBACK=str(REPAIR/'resolver_fallback.json')),stdout=stream,stderr=subprocess.STDOUT,timeout=86400)
    evidence=out/'videoclaw_adapted/02'/metric/'status.json';data=read(evidence);state['tasks'][metric]={'status':data.get('status','FAILED'),'evidence':str(evidence),'returncode':r.returncode,'finished':time.time()}
   except Exception as ex:state['tasks'][metric]={'status':'FAILED','error':str(ex),'log':str(log)}
   save(FOLDER/'evaluation_state.json',state)
  state['status']='FINISHED';save(FOLDER/'evaluation_state.json',state)
if __name__=='__main__':main()
