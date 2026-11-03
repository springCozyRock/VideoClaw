#!/usr/bin/env python3
"""Apply a shared Qwen request queue without changing the frozen model payloads."""
from pathlib import Path
import runpy
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from msvbench_qwen import QwenAPI
original=QwenAPI.__init__
def queued_init(self,*args,**kwargs):
    original(self,*args,**kwargs)
    self.rate_dir=ROOT/'experiments/aard_shared_qwen_queue'
QwenAPI.__init__=queued_init
sys.argv[0]=str(ROOT/'scripts/run_memory_aard_snapshot.py')
runpy.run_path(sys.argv[0],run_name='__main__')
