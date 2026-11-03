#!/usr/bin/env python3
"""Read-only deployment and live download/continuation status."""
import json,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return {}
report=read(ROOT/'configs/msvbench/deployment.json')
print('MSVBench',report.get('upstream_commit'))
print('Judge:',report.get('judge'),'(adapted protocol)')
print('Verified named metrics:',report.get('verified_named_metrics'),'/19; formal benchmark has not been run')
for metric,entry in report.get('metrics',{}).items():print(metric,entry['status'],entry.get('reason',''))
for p in sorted((ROOT/'configs/msvbench/downloads').glob('*.json'))+[ROOT/'configs/msvbench/vqa-download.json']:
 r=read(p);print('DOWNLOAD',p.stem,r.get('status','UNKNOWN'),r.get('error',''))
c=read(ROOT/'configs/msvbench/continuation.json')
if c:
 alive=False
 try:os.kill(c.get('pid',0),0);alive=True
 except (OSError,ValueError):pass
 print('CONTINUATION',c.get('status'),'pid',c.get('pid'),'process_exists',alive,'updated_seconds_ago',round(time.time()-c.get('updated',0)))
 for metric,item in c.get('tasks',{}).items():print('  ',metric,item['status'],item.get('reason',''))
