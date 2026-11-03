#!/usr/bin/env python3
"""Read-only status of the original batch, content-adapted case and repair workers."""
import json,time
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'experiments/msvbench_agents_20261018';R=ROOT/'experiments/msvbench_repair_20261019'
def read(p):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return {}
def process(name):
 d=read(R/name);pid=d.get('pid');p=Path('/proc')/str(pid)/'cmdline';alive=p.exists()
 return {'pid':pid,'alive':alive,'recorded_status':d.get('status'),'returncode':d.get('returncode')}
out={'updated':time.strftime('%Y-%m-%d %H:%M:%S %z'),'scope':'Adapted MSVBench protocol; not exact original reproduction','deployment':{},'stories':{},'workers':{},'evaluation':{}}
dep=read(ROOT/'configs/msvbench/deployment.json');out['deployment']={'smoke_verified':sum(x.get('status')=='SMOKE_VERIFIED' for x in dep.get('metrics',{}).values()),'total':len(dep.get('metrics',{})),'strict_original_reproduction':False,'full_story_flash_gate':read(R/'full_story_flash_gate.json')}
for method in ['videoclaw','codex_composition','videoclaw_adapted']:
 rows={}
 for sid in (['02'] if method=='videoclaw_adapted' else ['01','02','08','09','14']):
  d=read(RUN/method/'stories'/sid/'status.json')
  if not d:
   if method=='codex_composition' and sid=='02':d={'status':'UNRESOLVED_SUBMISSION'}
   elif method=='codex_composition' and sid=='09':d={'status':'RECOVERING' if read(R/'codex09_resume_process.json').get('status')=='RUNNING' else 'NO_COMPLETE_FINAL'}
   else:d={'status':'NO_COMPLETE_FINAL'}
  rows[sid]={k:v for k,v in d.items() if k in ['status','stage','duration_sec','shots','error','variant','final_video']}
 out['stories'][method]=rows
for name in ['evaluation_process.json','adapted_evaluation_process.json','codex09_resume_process.json','formal_flash_v3_process.json','flash_gate_process.json']:
 out['workers'][name]=process(name)
for name,path in [('original_cases',R/'evaluation_state.json'),('clothed_adaptation',RUN/'videoclaw_adapted/stories/02/evaluation_state.json')]:
 d=read(path);out['evaluation'][name]={'status':d.get('status'),'counts':dict(Counter(v.get('status') for v in d.get('tasks',{}).values())),'running':[k for k,v in d.get('tasks',{}).items() if v.get('status')=='RUNNING']}
print(json.dumps(out,indent=2,ensure_ascii=False))
