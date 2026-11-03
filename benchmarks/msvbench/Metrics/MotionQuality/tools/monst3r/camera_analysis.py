"""Reconstructed MSVBench interface over official MonST3R inference/alignment.

Native scoring remains in CameraControl.py. This adapter exports c2w wxyz poses.
"""
from pathlib import Path
import os,contextlib,json,numpy as np,torch
from scipy.spatial.transform import Rotation
from msvbench_sam2_tensor import tensor_video_loader
from msvbench_flow_numerics import finite_flow_guard
ROOT=Path(__file__).resolve().parent
@contextlib.contextmanager
def working_directory(path):
 old=os.getcwd();os.chdir(path)
 try:yield
 finally:os.chdir(old)
class MonST3RProcessor:
 def __init__(self,weights_path=None,device='cuda',image_size=512,batch_size=16,output_dir=None,silent=False):
  self.weights_path=str(weights_path or ROOT/'checkpoints/MonST3R');self.device=device;self.image_size=image_size;self.batch_size=batch_size;self.silent=silent;self.model=None
  run=os.environ.get('MSVBENCH_AUDIT_DIR')
  self.output_dir=str((Path(run).parent/'camera_geometry' if run else Path(output_dir or ROOT/'demo_tmp')).resolve())
 def process_images(self,image_dir,seq_name=None,**p):
  from dust3r.model import AsymmetricCroCo3DStereo
  from dust3r.utils.image import load_images
  from dust3r.image_pairs import make_pairs
  from dust3r.inference import inference
  from dust3r.cloud_opt import global_aligner,GlobalAlignerMode
  paths=sorted(str(x) for x in Path(image_dir).resolve().glob('*.jpg'));cap=int(p.get('num_frames',200))
  if len(paths)>cap:paths=[paths[i] for i in np.linspace(0,len(paths)-1,cap).astype(int)]
  if len(paths)<2:raise ValueError('MonST3R needs at least two frames')
  if self.model is None:self.model=AsymmetricCroCo3DStereo.from_pretrained(self.weights_path).to(self.device).eval()
  with working_directory(ROOT),tensor_video_loader(),finite_flow_guard(Path(self.output_dir)/(seq_name or Path(image_dir).name)/'flow_numerics.json'):
   images=load_images(paths,size=self.image_size,verbose=not self.silent)
   graph=p.get('scenegraph_type','swinstride')
   if graph in ('swin','swinstride','swin2stride'):graph+='-%d-noncyclic'%int(p.get('winsize',5))
   elif graph=='oneref':graph+='-%d'%int(p.get('refid',0))
   pairs=make_pairs(images,scene_graph=graph,prefilter=None,symmetrize=True)
   with torch.no_grad():output=inference(pairs,self.model,self.device,batch_size=self.batch_size,verbose=not self.silent)
   mode=GlobalAlignerMode.PointCloudOptimizer if len(images)>2 else GlobalAlignerMode.PairViewer
   kwargs={}
   if len(images)>2:
    kwargs=dict(shared_focal=p.get('shared_focal',True),temporal_smoothing_weight=float(p.get('temporal_smoothing_weight',.01)),translation_weight=float(p.get('translation_weight',1.0)),flow_loss_weight=float(p.get('flow_loss_weight',.01)),flow_loss_start_epoch=float(p.get('flow_loss_start_iter',.1)),flow_loss_thre=float(p.get('flow_loss_threshold',25)),use_self_mask=not p.get('use_gt_mask',False),num_total_iter=int(p.get('niter',300)),batchify=True)
   scene=global_aligner(output,device=self.device,mode=mode,verbose=not self.silent,**kwargs)
   if len(images)>2:scene.compute_global_alignment(init='mst',niter=int(p.get('niter',300)),schedule=p.get('schedule','linear'),lr=.01)
   poses=scene.get_im_poses().detach().cpu().numpy()
   if not np.isfinite(poses).all():raise RuntimeError('Nonfinite optimized camera poses; no replacement trajectory')
   rot=Rotation.from_matrix(poses[:,:3,:3]).as_quat()
   table=np.column_stack([np.arange(len(poses)),poses[:,:3,3],rot[:,3],rot[:,:3]])
   out=Path(self.output_dir)/(seq_name or Path(image_dir).name);out.mkdir(parents=True,exist_ok=True)
   trajectory=out/'pred_traj.txt';np.savetxt(trajectory,table)
   (out/'adapter_protocol.json').write_text(json.dumps({'adapter':'reconstructed; not author original','model_path':self.weights_path,'source_frames':paths,'pose_convention':'camera-to-world, frame tx ty tz qw qx qy qz; matches native parser','optimization':kwargs,'schedule':p.get('schedule','linear'),'niter':p.get('niter',300),'geometry_source':'official MonST3R; plots omitted; official default batchified alignment'},indent=2))
  return scene,str(trajectory),None
