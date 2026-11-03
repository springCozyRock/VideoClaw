"""Server-side bounded recovery of interrupted dependency downloads."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import json,os,subprocess,time
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT
def load(p):
 try:return load_json(p)
 except (FileNotFoundError,ValueError):return {}
def main():
 import fcntl
 lock=(RUN/'dependency_watch.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 started=time.time();attempts={};next_try={}
 while time.time()-started<8*3600:
  pending=[]
  for name,script,pidfile in [('asr','setup/prepare_asr.py','prepare_asr.pid'),('vistory','setup/bootstrap_vistory.py','bootstrap_vistory.pid')]:
   state=load(RUN/'evaluation'/(name+'_environment.json'))
   if state.get('status')=='READY':continue
   pending.append(name);alive=False
   try:
    pid=int((RUN/pidfile).read_text());cmd=Path('/proc/%d/cmdline'%pid).read_bytes().decode();alive=script in cmd
   except (FileNotFoundError,ValueError):pass
   if alive or time.time()<next_try.get(name,0):continue
   attempts[name]=attempts.get(name,0)+1
   if attempts[name]>6:continue
   log=(RUN/'logs'/('dependency_'+name+'.log')).open('a')
   process=subprocess.Popen(['python3','-u',str(ROOT/script)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   (RUN/pidfile).write_text(str(process.pid)+'\n');next_try[name]=time.time()+min(1800,300*attempts[name])
   print('Dependency retry',name,attempts[name],process.pid,flush=True)
  (RUN/'evaluation/dependency_watch.json').write_text(json.dumps({'status':'READY' if not pending else 'RECOVERING_DEPENDENCIES','pending':pending,'attempts':attempts,'updated_at_epoch':time.time()},indent=2)+'\n')
  if not pending:return
  time.sleep(120)
 raise RuntimeError('Dependency setup exceeded eight-hour recovery window; inspect dependency logs')
if __name__=='__main__':main()
