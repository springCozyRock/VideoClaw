import sys,time,json
from pathlib import Path
root=Path("/mnt/data/bts/repos/LongVideoMemory");sys.path.insert(0,str(root/"scripts"))
from msvbench_autoverify import update_deployment
evidence=Path("experiments/msvbench_smoke/vqa_cache_v2/public_reference_smoke/01/vqa/status.json")
until=time.time()+7200
while time.time()<until:
 p=root/evidence
 if p.exists():
  obj=json.loads(p.read_text())
  if obj.get("status")=="SCORED" and not obj.get("issues"):
   update_deployment("vqa",str(evidence));print("VQA_SMOKE_REGISTERED",flush=True)
  else:print("VQA_STILL_FAILED",obj.get("issues"),flush=True)
  break
 time.sleep(5)
