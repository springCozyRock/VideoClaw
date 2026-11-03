import concurrent.futures,time,fcntl
from pathlib import Path
from msvbench_agents_run import RUN,CFG,read,videoclaw_case
with (RUN/'videoclaw/input-repair.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 rows=read(CFG/'manifest.json')['stories']
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  futures=[]
  first=next(x for x in rows if x['story']=='01')
  if read(RUN/'videoclaw/stories/01/status.json').get('status')=='FAILED':futures.append(pool.submit(videoclaw_case,first))
  while Path('/proc/4107504/cmdline').exists():time.sleep(5)
  for row in rows:
   if row['story']!='01':futures.append(pool.submit(videoclaw_case,row))
  for f in futures:f.result()
