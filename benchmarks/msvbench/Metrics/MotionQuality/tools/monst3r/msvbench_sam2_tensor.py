"""Bridge MonST3R's original tensor-input preprocessing into installed SAM2."""
import contextlib,torch
from unittest.mock import patch
@contextlib.contextmanager
def tensor_video_loader():
 import sam2.sam2_video_predictor as module
 original=module.load_video_frames
 def load(video_path,image_size,offload_video_to_cpu,img_mean=(0.485,0.456,0.406),img_std=(0.229,0.224,0.225),async_loading_frames=False,compute_device=torch.device("cuda")):
  if not isinstance(video_path,torch.Tensor):
   return original(video_path=video_path,image_size=image_size,offload_video_to_cpu=offload_video_to_cpu,img_mean=img_mean,img_std=img_std,async_loading_frames=async_loading_frames,compute_device=compute_device)
  n,c,h,w=video_path.shape
  if n<1 or c!=3:raise ValueError("Expected NCHW RGB frames")
  frames=torch.nn.functional.interpolate(video_path,size=(image_size,image_size),mode="bicubic",align_corners=False)
  destination=torch.device("cpu") if offload_video_to_cpu else compute_device
  frames=frames.to(destination)
  mean=torch.tensor(img_mean,dtype=torch.float32,device=destination)[:,None,None]
  std=torch.tensor(img_std,dtype=torch.float32,device=destination)[:,None,None]
  frames-=mean;frames/=std
  return frames,h,w
 with patch.object(module,"load_video_frames",load):yield
