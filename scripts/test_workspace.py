"""Run offline checks only; never call real generation/judging APIs."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
env={**os.environ,'VIDEOCLAW_BACKEND':str(ROOT/'video-claw/video-claw/backend'),'MEMORY_HOST_ROOT':str(ROOT)}
commands=[[sys.executable,'scripts/test_memory.py'],[sys.executable,'-m','unittest','discover','-s','tests','-p','test_videoclaw_paradigms.py'],[sys.executable,'-m','unittest','discover','-s','tests','-p','test_generation_meter.py'],[sys.executable,'-m','unittest','discover','-s','tests','-p','test_rate_limit_policy.py']]
if (ROOT/'tests/test_prompt_language.py').exists():commands.append([sys.executable,'-m','unittest','discover','-s','tests','-p','test_prompt_language.py'])
for command in commands:subprocess.run(command,cwd=ROOT,env=env,check=True)
print('All offline workspace checks passed.')
