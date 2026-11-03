#!/usr/bin/env python3
"""Conservative shared Qwen queue for resuming the frozen snapshot runners."""
from pathlib import Path
import contextlib
import fcntl
import hashlib
import json
import runpy
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from msvbench_qwen import QwenAPI
from rate_limit_policy import REQUEST_GAP_SECONDS

@contextlib.contextmanager
def paced(self):
    folder=ROOT/'experiments/aard_shared_qwen_queue';folder.mkdir(exist_ok=True)
    key=hashlib.sha256((self.base+'|'+self.model).encode()).hexdigest()
    with (folder/(key+'.lock')).open('a+') as gate:
        fcntl.flock(gate,fcntl.LOCK_EX)
        stamp=folder/(key+'.json')
        last=json.loads(stamp.read_text()).get('ended_at',0) if stamp.exists() else 0
        delay=max(0,last+REQUEST_GAP_SECONDS-time.time())
        if delay:time.sleep(delay)
        try:yield
        finally:
            temporary=stamp.with_suffix('.tmp')
            temporary.write_text(json.dumps({'ended_at':time.time(),'minimum_gap_seconds':REQUEST_GAP_SECONDS}))
            temporary.replace(stamp)
QwenAPI.request_slot=paced
sys.argv[0]=str(ROOT/'scripts/run_memory_aard_snapshot.py')
runpy.run_path(sys.argv[0],run_name='__main__')
