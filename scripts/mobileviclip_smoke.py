#!/usr/bin/env python3
"""Offline real-weight test of DirectorBench's native MobileViCLIP tool."""
import os,sys,json,time,hashlib,math,logging
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'.cache/directorbench_public/models'
OUT=ROOT/'experiments/mobileviclip/smoke';OUT.mkdir(parents=True,exist_ok=True)
from mobileviclip_runtime import configure_mobileviclip
configure_mobileviclip(ROOT)
os.environ['MOBILEVICLIP_BATCH_SIZE']='2'
sys.path.insert(0,str(ROOT/'benchmarks/directorbench_public'))
import torch,numpy as np,cv2
from PIL import Image
from directorbench.agents.crossmodal_agent import CrossModalEvalAgent
from directorbench.schemas import ToolStatus
torch.set_num_threads(4);torch.manual_seed(0)
torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
logging.basicConfig(level=logging.INFO)
# Generate a local test video; no private project media or remote judge is used.
video=OUT/'moving_red_square.mp4'
writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),8,(256,256))
assert writer.isOpened()
for i in range(16):
 frame=np.zeros((256,256,3),dtype=np.uint8);frame[:]=(210,80,20);cv2.rectangle(frame,(10+i*8,90),(60+i*8,140),(0,0,255),-1);writer.write(frame)
writer.release()
cap=cv2.VideoCapture(str(video));frames=[];paths=[]
for i in range(16):
 ok,frame=cap.read();assert ok
 if i%2==0:
  rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB);frames.append(rgb);p=OUT/f'frame_{i:02d}.png';Image.fromarray(rgb).save(p);paths.append(str(p))
cap.release()
agent=CrossModalEvalAgent.__new__(CrossModalEvalAgent);agent._local_tool_records=[]
load_checks=[];original_load=torch.nn.Module.load_state_dict

def checked_load(self,state_dict,*args,**kwargs):
 result=original_load(self,state_dict,*args,**kwargs)
 if self.__class__.__name__=='MobileViCLIP_Small':
  record={'missing_keys':result.missing_keys,'unexpected_keys':result.unexpected_keys,'model_tensor_count':len(self.state_dict()),'supplied_tensor_count':len(state_dict)};load_checks.append(record)
  if result.missing_keys or result.unexpected_keys:raise RuntimeError('Incomplete MobileViCLIP weights: '+str(record))
 return result
# Block accidental network/API use during inference.
import socket
original_connect=socket.socket.connect
socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Network prohibited in offline smoke test'))
torch.nn.Module.load_state_dict=checked_load
started=time.time()
try:
 score=agent._compute_viclip_similarity('A red square moves across a blue background.',paths[:2])
 assert score is not None and math.isfinite(score) and 0<=score<=1,agent._local_tool_records
 assert load_checks and not any(x['missing_keys'] or x['unexpected_keys'] for x in load_checks)
 repeat=agent._compute_viclip_similarity('A red square moves across a blue background.',paths[:2]);assert abs(score-repeat)<1e-6
 model=CrossModalEvalAgent._mobileviclip_model
 with torch.inference_mode():
  tokens=model.tokenizer(['A red square moves across a blue background.'])
  text=model.encode_text(tokens)
  clip=torch.stack([model.transform(torch.from_numpy(f.copy()).permute(2,0,1).float()) for f in frames]).unsqueeze(0)
  vision=model.encode_vision(clip,test=True)
  assert tuple(text.shape)==tuple(vision.shape)==(1,512)
  assert torch.isfinite(text).all() and torch.isfinite(vision).all()
  assert text.norm()>0 and vision.norm()>0
  cpu_cos=torch.nn.functional.cosine_similarity(text,vision).item()
  gpu=None
  if torch.cuda.is_available():
   # Separate native CPU scoring protocol from an additional genuine temporal GPU forward.
   device='cuda:'+str(os.environ.get('MOBILEVICLIP_SMOKE_GPU','5'));model=model.to(device)
   gt=model.encode_text(tokens.to(device));gv=model.encode_vision(clip.to(device),test=True)
   gpu_cos=torch.nn.functional.cosine_similarity(gt,gv).item()
   assert abs(cpu_cos-gpu_cos)<1e-3,(cpu_cos,gpu_cos)
   gpu={'device':device,'text_shape':list(gt.shape),'vision_shape':list(gv.shape),'cosine':gpu_cos,'cpu_difference':abs(cpu_cos-gpu_cos)}
   model.cpu()
 assert all(r.status==ToolStatus.SUCCESS for r in agent._local_tool_records)
 def digest(p):
  h=hashlib.sha256()
  with p.open('rb') as f:
   for c in iter(lambda:f.read(4*1024*1024),b''):h.update(c)
  return h.hexdigest()
 runtime_files=['configs/mobileviclip/runtime-imports.patch','scripts/mobileviclip_runtime.py','third_party/mobileviclip/models/backbones/internvideo2/__init__.py','third_party/mobileviclip/models/mobileviclip_small.py','third_party/mobileviclip/models/mobileviclip_tiny.py']
 report={'runtime_sha256':{name:digest(ROOT/name) for name in runtime_files},'gpu_tf32_enabled':False,'status':'PASS','no_api_calls':True,'network_prohibited':True,'elapsed_seconds':time.time()-started,'native_directorbench_score':score,'repeat_score':repeat,'weight_load_checks':load_checks,'cpu_temporal_clip':{'shape':list(clip.shape),'text_shape':list(text.shape),'vision_shape':list(vision.shape),'cosine':cpu_cos},'gpu_temporal_clip':gpu,'tool_records':[r.model_dump(mode='json') for r in agent._local_tool_records],'weights':{p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in [MODEL/'mobileviclip_small.pt',MODEL/'mobileclip_s2.pt']},'protocol_note':'Native DirectorBench CPU fp32 text-frame scoring, each image repeated T=8; separate temporal CPU/GPU test is validation only.'}
 (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
finally:
 torch.nn.Module.load_state_dict=original_load;socket.socket.connect=original_connect;os.chdir(ROOT)
