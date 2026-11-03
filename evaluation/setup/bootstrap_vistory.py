"""Add missing ViStoryBench packages in a private venv, reusing cached Torch."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import json,os,subprocess,shutil
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CACHE_ROOT, VISTORY_ENV, VISTORY_ROOT

ROOT = BASELINE_ROOT
ready_path=(RUN_ROOT / 'evaluation/vistory_environment.json')
ready_path.write_text(json.dumps({'status':'SETTING_UP','note':'Validating all required auxiliary weights before enabling formal evaluation'})+'\n')
SOURCE=Path('/mnt/data/bts/repos/vistorybench')
PRIVATE=(VISTORY_ROOT)
if not PRIVATE.exists():
 shutil.copytree(SOURCE,PRIVATE,ignore=shutil.ignore_patterns('.git','data','.venv','venv','__pycache__','.env','*.log'))
ada=PRIVATE/'vistorybench/bench/content/AdaFace'
if not (ada/'inference.py').exists():
 if ada.exists():shutil.rmtree(ada)
 commit=subprocess.check_output(['git','-C',str(SOURCE),'ls-tree','HEAD','vistorybench/bench/content/AdaFace'],text=True).split()[2]
 subprocess.run(['git','clone','https://github.com/mk-minchul/AdaFace',str(ada)],check=True)
 subprocess.run(['git','-C',str(ada),'checkout',commit],check=True)
VENV=(VISTORY_ENV)
BASE='/mnt/data/bts/envs/vbench/bin/python'
if not (VENV/'bin/python').exists():subprocess.run([BASE,'-m','venv','--system-site-packages',str(VENV)],check=True)
site=VENV/'lib/python3.10/site-packages';site.mkdir(parents=True,exist_ok=True)
(site/'reuse_vbench.pth').write_text('/mnt/data/bts/envs/vbench/lib/python3.10/site-packages\n')
env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';env['MAX_JOBS']='2';env['PIP_CACHE_DIR']=str((CACHE_ROOT / 'pip'))
packages=['natsort==8.4.0','onnx==1.17.0','onnxruntime==1.20.1','albumentations==1.3.1','qudida==0.0.4','prettytable==3.12.0','supervision==0.6.0','open_clip_torch==2.32.0','insightface==0.7.3','groundingdino-py==0.4.0']
subprocess.run([str(VENV/'bin/python'),'-m','pip','install','--no-deps','--no-build-isolation']+packages,env=env,check=True)
gpus=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
free=[(int(row.split(',')[1]),row.split(',')[0].strip()) for row in gpus.splitlines() if int(row.split(',')[1])>5000 and int(row.split(',')[2])<10]
if not free:raise RuntimeError('No idle GPU for native AdaFace import check; retry bootstrap when one is available')
env['CUDA_VISIBLE_DEVICES']=max(free)[1]
result=subprocess.run([str(VENV/'bin/python'),'-c',"import sys; sys.path.insert(0,"+repr(str(PRIVATE))+"); from vistorybench.bench.content.cids_evaluator import CIDSEvaluator; print('CIDS_IMPORT_OK')"],env=env,cwd=str(PRIVATE),check=True)
import urllib.request,hashlib
cache=(CACHE_ROOT / 'facexlib');cache.mkdir(parents=True,exist_ok=True)
weight_records=[]
for name,release in [('detection_Resnet50_Final.pth','v0.1.0'),('parsing_parsenet.pth','v0.2.2')]:
 target=cache/name
 urls=['https://hf-mirror.com/Skywork/SkyReels-A1/resolve/6aa51f8dc0c291ada1ea420cfe729bdba94ae118/eval/face_encoder/'+name,'https://github.com/xinntao/facexlib/releases/download/'+release+'/'+name]
 for url in urls:
  if target.exists():break
  partial=target.with_suffix('.partial')
  try:
   print('Downloading auxiliary weight',name,'from',url,flush=True)
   with urllib.request.urlopen(url,timeout=30) as response,partial.open('wb') as output:shutil.copyfileobj(response,output)
   if partial.stat().st_size<1000000:raise RuntimeError('Weight file too small')
   partial.replace(target)
  except Exception as ex:print('Download failed',str(ex),flush=True)
 if not target.exists():raise RuntimeError('Unable to obtain required native auxiliary weight '+name)
 subprocess.run([str(VENV/'bin/python'),'-c','import torch;torch.load('+repr(str(target))+',map_location="cpu",weights_only=True);print("WEIGHT_VALIDATED")'],env=env,check=True)
 weight_records.append({'name':name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'source_urls':urls})
cache.joinpath('manifest.json').write_text(json.dumps(weight_records,indent=2)+'\n')
path=(RUN_ROOT / 'evaluation/vistory_environment.json')
path.write_text(json.dumps({'status':'READY','python':str(VENV/'bin/python'),'source':str(PRIVATE),'adaface_commit':'c60eaa786a42c03444f3df7096dbaf9d57ae010d','packages':packages,'reused_site_packages':'/mnt/data/bts/envs/vbench/lib/python3.10/site-packages','groundingdino_device':'cpu','note':'CPU GroundingDINO avoids compiling CUDA extensions; native model weights, detection thresholds, matching and feature formulas are preserved.'},indent=2)+'\n')
