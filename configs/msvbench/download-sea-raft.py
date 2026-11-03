import os,json,time,sys
from pathlib import Path
os.environ["HF_ENDPOINT"]="https://hf-mirror.com";os.environ["HF_HUB_DISABLE_XET"]="1"
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
import torch
root=Path("/mnt/data/bts/repos/LongVideoMemory")
state=root/"configs/msvbench/downloads/sea-raft.json"
try:
 state.write_text(json.dumps({"status":"DOWNLOADING","repo":"MemorySlices/Tartan-C-T-TSKH-spring540x960-M","revision":"eb97ef34ba5d856c3fa2cdcd073150c057ac8b69"}))
 src=hf_hub_download("MemorySlices/Tartan-C-T-TSKH-spring540x960-M","model.safetensors",revision="eb97ef34ba5d856c3fa2cdcd073150c057ac8b69",local_dir=str(root/".cache/msvbench/sea-raft"),endpoint="https://hf-mirror.com")
 target=root/"benchmarks/msvbench/Metrics/MotionQuality/tools/monst3r/third_party/RAFT/models/Tartan-C-T-TSKH-spring540x960-M.pth"
 target.parent.mkdir(parents=True,exist_ok=True);weights=load_file(src)
 sys.path.insert(0,str(root/"benchmarks/msvbench/Metrics/MotionQuality/tools/monst3r"))
 from third_party import raft
 args=raft.json_to_args(str(root/"benchmarks/msvbench/Metrics/MotionQuality/tools/monst3r/third_party/RAFT/core/configs/congif_spring_M.json"))
 args.msvbench_full_checkpoint=True;model=raft.RAFT2(args)
 expected=model.state_dict(keep_vars=True);aliases={}
 for key,value in expected.items():
  if key not in weights:
   match=[k for k,v in expected.items() if k in weights and v.shape==value.shape and v.data_ptr()==value.data_ptr()]
   if not match:raise RuntimeError("Missing non-shared checkpoint tensor: "+key)
   aliases[key]=match[0];weights[key]=weights[match[0]]
 model.load_state_dict(weights,strict=True)
 torch.save(weights,target)
 import hashlib
 state.write_text(json.dumps({"status":"DOWNLOADED_NOT_INFERENCE_VERIFIED","repo":"MemorySlices/Tartan-C-T-TSKH-spring540x960-M","revision":"eb97ef34ba5d856c3fa2cdcd073150c057ac8b69","source":src,"target":str(target),"conversion":"safetensors tensor dict to torch.save; no value changes","shared_aliases_restored":aliases,"strict_load_verified":True,"tensor_count":len(weights),"source_sha256":hashlib.sha256(Path(src).read_bytes()).hexdigest(),"target_sha256":hashlib.sha256(target.read_bytes()).hexdigest()},indent=2))
except Exception as ex:state.write_text(json.dumps({"status":"FAILED","error":str(ex)}));raise
