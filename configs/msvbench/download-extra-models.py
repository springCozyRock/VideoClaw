import os,json,time,shutil,concurrent.futures
from pathlib import Path
os.environ.update(HF_ENDPOINT="https://hf-mirror.com",HF_HUB_DISABLE_XET="1",HF_HUB_DOWNLOAD_TIMEOUT="120",HF_HUB_ETAG_TIMEOUT="30")
from huggingface_hub import HfApi,snapshot_download
ROOT=Path("/mnt/data/bts/repos/LongVideoMemory");repo=ROOT/"benchmarks/msvbench";state=ROOT/"configs/msvbench/downloads";state.mkdir(exist_ok=True)
models=[
 ("monst3r","Junyi42/MonST3R_PO-TA-S-W_ViTLarge_BaseDecoder_512_dpt","Metrics/MotionQuality/tools/monst3r/checkpoints/MonST3R",["config.json","model.safetensors"]),
 ("kalm-v2","HIT-TMG/KaLM-embedding-multilingual-mini-instruct-v2","Metrics/StoryVideoAlignment/tools/KaLM-embedding-multilingual-mini-instruct-v2",["*.json","*.py","*.safetensors","vocab.json","merges.txt","1_Pooling/*"]),
 ("step1x","stepfun-ai/Step1X-Edit","Metrics/VideoConsistency/tools/Step1X-Edit/weights/Step1X-Edit",["step1x-edit-i1258.safetensors","vae.safetensors","config.json"]),
 ("sharecaptioner","Lin-Chen/ShareCaptioner-Video","Metrics/StoryVideoAlignment/tools/ShareGPT4Video/captioner/weights",["*.json","*.py","pytorch_model*.bin","*.model","*.txt"])]
def run(item):
 name,model,target,patterns=item;p=state/(name+".json");record={"model":model,"target":str(repo/target),"status":"STARTING"}
 def save():
  tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(record,indent=2));tmp.replace(p)
 for attempt in range(5):
  try:
   if shutil.disk_usage(ROOT).free<20*1024**3:raise RuntimeError("Free disk below20GiB; stop downloads")
   revision=record.get("revision") or HfApi().model_info(model).sha
   record.update(revision=revision,status="DOWNLOADING",attempt=attempt,updated=time.time());save()
   result=snapshot_download(model,revision=revision,local_dir=str(repo/target),allow_patterns=patterns,max_workers=2)
   record.update(status="DOWNLOADED_NOT_INFERENCE_VERIFIED",path=result,updated=time.time());save();return
  except Exception as e:
   record.update(status="RETRYING" if attempt<4 else "FAILED",error=str(e),updated=time.time());save()
   if "below20GiB" in str(e):return
   time.sleep(min(30,5*(attempt+1)))
if shutil.disk_usage(ROOT).free<80*1024**3:raise RuntimeError("Need80GiB free for remaining weights and VQA headroom")
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run,models))
