"""Local MobileViCLIP weight configuration and integrity provenance."""
import hashlib,os,json
from pathlib import Path

def configure_mobileviclip(root):
 root=Path(root);models=root/'.cache/directorbench_public/models'
 os.environ.update(MOBILEVICLIP_REPO=str(root/'third_party/mobileviclip'),MOBILEVICLIP_SMALL_CKPT=str(models/'mobileviclip_small.pt'),MOBILEVICLIP_VISION_CKPT=str(models/'mobileclip_s2.pt'),MOBILEVICLIP_TEXT_CKPT=str(models/'mobileclip_s2.pt'),MOBILEVICLIP_EXTRA_CKPT=str(models/'mobileviclip_small.pt'),MOBILEVICLIP_NUM_FRAMES='8',MOBILEVICLIP_PRECISION='fp32')

def model_provenance(root):
 root=Path(root)
 def digest(p):
  h=hashlib.sha256()
  with p.open('rb') as f:
   for c in iter(lambda:f.read(4*1024*1024),b''):h.update(c)
  return h.hexdigest()
 paths=['.cache/directorbench_public/models/mobileviclip_small.pt','.cache/directorbench_public/models/mobileclip_s2.pt','configs/mobileviclip/runtime-imports.patch','scripts/mobileviclip_runtime.py','third_party/mobileviclip/models/backbones/internvideo2/__init__.py','third_party/mobileviclip/models/mobileviclip_small.py','third_party/mobileviclip/models/mobileviclip_tiny.py']
 hashes={name:digest(root/name) if (root/name).is_file() else None for name in paths}
 smoke=root/'experiments/mobileviclip/smoke/result.json';result=json.loads(smoke.read_text()) if smoke.is_file() else {}
 weights=result.get('weights',{});verified=result.get('status')=='PASS' and all(weights.get(Path(name).name,{}).get('sha256')==hashes[name] for name in paths[:2]) and all(hashes.values()) and all(result.get('runtime_sha256',{}).get(name)==hashes[name] for name in paths[2:])
 return {'ready':verified,'sha256':hashes,'smoke_report':str(smoke),'smoke_report_sha256':digest(smoke) if smoke.is_file() else None,'num_frames':8,'precision':'fp32','device':'cpu (native DirectorBench scoring)','checkpoint_composition':'MobileCLIP-S2 base vision/text plus MobileViCLIP-Small trained parameters'}
