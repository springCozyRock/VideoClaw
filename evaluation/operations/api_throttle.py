"""Shared process-safe transport pacing and provider cooldown."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import fcntl,json,time
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, load_json
ROOT = BASELINE_ROOT
STATE=(RUN_ROOT / 'evaluation/provider_pause.json')

class ProviderUnavailable(BaseException):pass

def cooldown(reason,seconds=600):
 state={'status':'WAITING_PROVIDER','reason':reason,'retry_after':time.time()+seconds,'created_at':time.time()}
 temp=STATE.with_suffix('.%d.tmp'%__import__('os').getpid());temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(STATE)

class RequestSlot:
 def __enter__(self):
  self.handle=((RUN_ROOT / 'evaluation/provider.lock')).open('a+')
  fcntl.flock(self.handle,fcntl.LOCK_EX)
  if STATE.exists():
   state=load_json(STATE)
   if state.get('retry_after',0)>time.time():
    self.handle.close();raise ProviderUnavailable('Provider cooldown: '+state.get('reason',''))
  pace=(RUN_ROOT / 'evaluation/provider_next.txt')
  try:delay=float(pace.read_text())-time.time()
  except (FileNotFoundError,ValueError):delay=0
  if delay>0:time.sleep(min(delay,10))
  pace.write_text(str(time.time()+6))
  return self
 def __exit__(self,*args):self.handle.close()
