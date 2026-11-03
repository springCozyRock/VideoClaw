from pathlib import Path
import os,json,hashlib
ROOT=Path("/mnt/data/bts/repos/LongVideoMemory");repo=ROOT/"benchmarks/msvbench"
base=Path("/mnt/data/shy/hzj/AniMaker/Benchmark/EvalCrafter/checkpoints")
items=[]
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def link(src,dst,metric,replace_equal=False):
 src=Path(src);dst=Path(dst);assert src.exists() and os.access(src,os.R_OK),src
 if dst.is_symlink():assert dst.resolve()==src.resolve(),dst
 elif dst.exists():
  if not replace_equal:raise RuntimeError("Existing destination: "+str(dst))
  assert digest(src)==digest(dst),"different checkpoint: "+str(dst)
 if not dst.is_symlink():
  dst.parent.mkdir(parents=True,exist_ok=True);temp=dst.with_name(dst.name+".reuse-link")
  if temp.is_symlink():temp.unlink()
  temp.symlink_to(src);os.replace(temp,dst)
 size=src.stat().st_size if src.is_file() else sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
 entry={"metric":metric,"source":str(src),"reference":str(dst),"bytes":size,"verification":"readable; exact filename/version; inference not claimed"}
 if src.is_file():entry["sha256"]=digest(src)
 items.append(entry)
link(base/"ckpt/sam_vit_b_01ec64.pth",repo/"Tools/Segment-and-Track-Anything/ckpt/sam_vit_b_01ec64.pth","face_consistency,character_consistency")
link(base/"ckpt/R50_DeAOTL_PRE_YTB_DAV.pth",repo/"Tools/Segment-and-Track-Anything/ckpt/R50_DeAOTL_PRE_YTB_DAV.pth","face_consistency,character_consistency")
link(base/"ckpt/groundingdino_swint_ogc.pth",repo/"Tools/Segment-and-Track-Anything/ckpt/groundingdino_swint_ogc.pth","tracking")
link(base/"VideoMAE/vit-base-p16_videomaev2-vit-g-dist-k710-pre_16x4x1_kinetics-400_20230510-3e7f93b2.pth",repo/"Metrics/MotionQuality/checkpoints/VideoMAE/vit-base-p16_videomaev2-vit-g-dist-k710-pre_16x4x1_kinetics-400_20230510-3e7f93b2.pth","action_recognition")
link(base/"clip-vit-base-patch32",repo/"Metrics/MotionQuality/checkpoints/clip-vit-base-patch32","action_recognition")
link(base/"vgg_face_weights.h5",ROOT/".cache/msvbench/deepface/.deepface/weights/vgg_face_weights.h5","face_consistency")
link("/mnt/data/lzy/remote/dense-img/Models/sam2.1_hiera_large.pt",ROOT/".cache/msvbench/sam2/sam2.1_hiera_large.pt","action_recognition; SAM2.1 candidate, match tracker config before use")
link(base/"DOVER/pretrained_weights/DOVER.pth",repo/"Metrics/VisualQuality/checkpoints/DOVER/DOVER.pth","dover",replace_equal=True)
dreambase=Path("/mnt/data/shy/hzj/AniMaker/models");cache=ROOT/".cache/msvbench/dreamsim"
for name in ["clip_vitb16_pretrain.pth.tar","open_clip_vitb16_pretrain.pth.tar","dino_vitb16_pretrain.pth","ensemble_lora/adapter_config.json","ensemble_lora/adapter_model.safetensors"]:link(dreambase/name,cache/name,"background_consistency")
link(dreambase/"facebookresearch_dino_main",cache/"facebookresearch_dino_main","DreamSim DINO backbone source")
report={"status":"LOCAL_REFERENCES_CREATED_NOT_FULL_METRICS_VERIFIED","items":items,"total_referenced_bytes":sum(x["bytes"] for x in items),"not_interchangeable":[{"source":"/mnt/data/shy/hzj/AniMaker/Benchmark/MusIQ/musiq.pth","variant":"SPAQ, sha256 starts358bb6af","current_variant":"KonIQ, sha256 startse95806b9"},{"source":"/mnt/data/share/KaLM-v2d5, KaLM-embedding-multilingual-mini-instruct-v1, v1.5","reason":"Do not substitute for required multilingual-mini-instruct-v2 without verifying provenance"}],"not_found_in_readable_scanned_paths":["CLIP-FlanT5-XXL","Step1X-Edit model weights","MonST3R model weights","SimpleSlidingCaptioner.py","grounded_sam2_tracking.py","camera_analysis.py"],"search_scope":"Readable /mnt/data and /home/xzr, depth up to9; targeted AniMaker checkpoints and caches inspected separately; permission errors skipped"}
(ROOT/"configs/msvbench/reused-models.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
print("REFERENCES",len(items),"BYTES",report["total_referenced_bytes"])
