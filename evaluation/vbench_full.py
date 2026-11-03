#!/usr/bin/env python3
"""Native VBench metrics over every frame, with bounded memory.

Only execution is streamed: native decoders, transforms, weights, pair scores,
and frame/clip aggregation are preserved. --parity checks against native code.
"""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parent
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse, importlib, json, os, sys
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, VBENCH_ROOT, load_json

ROOT = BASELINE_ROOT
SOURCE=(VBENCH_ROOT)
sys.path.insert(0,str(SOURCE))
os.environ['VBENCH_CACHE_DIR']='/mnt/data/bts/models/vbench'
os.environ['TORCH_HOME']='/mnt/data/bts/models/torch'

import cv2, numpy as np, torch
import torch.nn.functional as F
from decord import VideoReader
from vbench.utils import clip_transform, dino_transform
from vbench import VBench

SUBJECT=importlib.import_module('vbench.subject_consistency')
BACKGROUND=importlib.import_module('vbench.background_consistency')
MOTION=importlib.import_module('vbench.motion_smoothness')
ORIGINAL=(SUBJECT.subject_consistency,BACKGROUND.background_consistency,MOTION.MotionSmoothness.motion_score)

def feature_consistency(model,paths,device,kind,batch_size=1):
 transform=dino_transform(224) if kind=='subject' else clip_transform(224)
 total=0.; count=0; results=[]
 for path in paths:
  reader=VideoReader(path,num_threads=1); n=len(reader)
  if n<2: raise ValueError('VBench requires at least two frames')
  first=None; previous=None; score=0.; seen=0
  for start in range(0,n,batch_size):
   pixels=reader.get_batch(range(start,min(n,start+batch_size))).asnumpy()
   frames=torch.tensor(pixels,dtype=torch.float32).permute(0,3,1,2)
   images=transform(frames).to(device)
   with torch.no_grad():
    features=model(images) if kind=='subject' else model.encode_image(images)
    features=F.normalize(features,dim=-1,p=2)
   for feature in features:
    feature=feature.unsqueeze(0)
    if first is None: first=feature
    else:
     score+=(max(0.,F.cosine_similarity(previous,feature).item())+max(0.,F.cosine_similarity(first,feature).item()))/2
    previous=feature; seen+=1
   del images,features,frames
  entry={'video_path':path,'video_results':score/(seen-1),'frame_count':seen}
  if kind=='background':entry.update(video_sim=score,cnt_per_video=seen-1)
  results.append(entry); total+=score; count+=seen-1
 return total/count,results

def subject(model,paths,device,read_frame):
 if read_frame:raise ValueError('Only MP4 full-frame protocol supported')
 return feature_consistency(model,paths,device,'subject',1)

def background(model,preprocess,paths,device,read_frame):
 if read_frame:raise ValueError('Only MP4 full-frame protocol supported')
 return feature_consistency(model,paths,device,'background',8)

def motion_score(self,path):
 from vbench.third_party.amt.utils.utils import img2tensor,tensor2img,InputPadder
 cap=cv2.VideoCapture(path)
 def next_frame():
  good,bgr=cap.read()
  return cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB) if good else None
 left=next_frame(); values=[]
 if left is None:raise ValueError('Empty video')
 try:
  while True:
   middle=next_frame(); right=next_frame()
   if middle is None or right is None:break
   a=img2tensor(left).to(self.device); b=img2tensor(right).to(self.device)
   h,w=a.shape[-2:]
   scale=self.anchor_resolution/(h*w)*np.sqrt((self.vram_avail-self.anchor_memory_bias)/self.anchor_memory)
   scale=1 if scale>1 else scale
   scale=1/np.floor(1/np.sqrt(scale)*16)*16
   padder=InputPadder(a.shape,int(16/scale)); a,b=padder.pad(a,b)
   with torch.no_grad():pred=self.model(a,b,self.embt,scale_factor=scale,eval=True)['imgt_pred']
   pred=tensor2img(padder.unpad(pred))
   values.append(self.get_diff(middle,pred))
   left=right
   del a,b,pred
 finally:cap.release()
 if not values:raise ValueError('Motion metric requires at least three frames')
 return float((255.-np.mean(np.array(values)))/255.)

def patch():
 SUBJECT.subject_consistency=subject
 BACKGROUND.background_consistency=background
 MOTION.MotionSmoothness.motion_score=motion_score

def run(videos,out,name):
 bench=VBench(torch.device('cuda'),str(SOURCE/'vbench/VBench_full_info.json'),str(out))
 bench.evaluate(videos_path=str(videos),name=name,dimension_list=['subject_consistency','background_consistency','motion_smoothness'],local=True,read_frame=False,mode='custom_input')
 return load_json(out / (name + '_eval_results.json'))

def main():
 p=argparse.ArgumentParser();p.add_argument('--videos',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--parity',action='store_true');a=p.parse_args()
 torch.set_num_threads(4); a.output.mkdir(parents=True,exist_ok=True)
 if a.parity:
  native=run(a.videos,a.output,'native')
  torch.cuda.empty_cache();patch();streamed=run(a.videos,a.output,'streamed')
  comparisons={k:{'native':native[k][0],'streamed':streamed[k][0],'absolute_error':abs(native[k][0]-streamed[k][0])} for k in native}
  # CLIP runs in native FP16 on CUDA. Changing only batch size can change GEMM
  # rounding; use two FP16 ulps for that metric, FP32 tolerance for the others.
  tolerances={'subject_consistency':1e-5,'background_consistency':2*float(np.finfo(np.float16).eps),'motion_smoothness':1e-7}
  passed=all(x['absolute_error']<tolerances[k] for k,x in comparisons.items())
  report={'passed':passed,'tolerances':tolerances,'fp16_batch_rounding_note':'Background CLIP uses native FP16; all frames and pair-score formula are unchanged.','comparisons':comparisons}
  (a.output/'parity.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
  if not passed:raise RuntimeError('Streaming parity check failed')
 else:
  parity=(RUN_ROOT / 'evaluation/vbench_parity/parity.json')
  if not parity.exists() or not load_json(parity).get('passed'):raise RuntimeError('Run native parity validation before long-video scoring')
  patch();result=run(a.videos,a.output,'full_frame')
  (a.output/'protocol.json').write_text(json.dumps({'sampling':'every decoded frame; no cap or temporal downsampling','execution':'bounded-memory equivalent of native metric functions','parity_validation':str(parity),'source':str(SOURCE),'metrics':list(result)},indent=2))

if __name__=='__main__':main()
