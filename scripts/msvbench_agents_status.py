#!/usr/bin/env python3
"""Read-only status of the two authorized five-story MSVBench experiments."""
import json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'experiments/msvbench_agents_20261018'
def read(p):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}
manifest=read(RUN/'manifest.json');processes=read(RUN/'processes.json')
print('RUN',RUN)
print('Models:',manifest.get('generation'))
for name,row in processes.items():
 if isinstance(row,dict) and row.get('pid'):
  p=Path(f"/proc/{row['pid']}/cmdline")
  print('PROCESS',name,row['pid'],'ALIVE' if p.exists() else 'EXITED')
for method in ('videoclaw','codex_composition'):
 done=0
 for row in manifest.get('stories',[]):
  p=RUN/method/'stories'/row['story'];s=read(p/'status.json')
  done+=s.get('status')=='GENERATED'
  print(method,row['story'],s.get('status', 'COLLECTION_FAILED' if (p/'collection_error.json').exists() else 'PIPELINE_EXITED_UNCOLLECTED' if method=='codex_composition' and read(RUN/'codex_composition/process.json').get('status')=='PIPELINE_EXITED' else 'QUEUED_OR_AGENT_PLANNING'),s.get('stage',''),s.get('error',''),s.get('duration_sec',''))
 print('FINISHED',method,done,'/5')
e=read(RUN/'evaluation/state.json')
print('EVALUATION',e.get('status','NOT_STARTED'),'scored',sum(t.get('status')=='SCORED' for t in e.get('tasks',{}).values()),'failed',sum(t.get('status')=='FAILED' for t in e.get('tasks',{}).values()),'waiting metrics',e.get('waiting_metrics',[]))
