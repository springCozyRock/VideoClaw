"""Reconstructed MSVBench adapter: GroundingDINO + official SAM2 propagation.

Not the authors' unpublished wrapper. Defaults and crop policy are recorded.
"""
from pathlib import Path
import sys,json,cv2,numpy as np,torch
from PIL import Image
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'configs/msvbench').is_dir())
REPO=ROOT/'benchmarks/msvbench'
TRACKER=REPO/'Tools/Segment-and-Track-Anything'
sys.path[:0]=[str(TRACKER),str(TRACKER/'src/groundingdino')]
class GroundedSAM2Tracker:
 def __init__(self,model_id='IDEA-Research/grounding-dino-tiny',prompt_type='box',device=None,box_threshold=0.25,text_threshold=0.30):
  if model_id!='IDEA-Research/grounding-dino-tiny' or prompt_type!='box':raise ValueError('Only the deployed Swin-T box tracker is supported')
  from tool.detector import Detector
  from sam2.build_sam import build_sam2_video_predictor
  self.device=device or ('cuda' if torch.cuda.is_available() else 'cpu')
  self.box_threshold=box_threshold;self.text_threshold=text_threshold
  self.detector=Detector(self.device)
  self.predictor=build_sam2_video_predictor('configs/sam2.1/sam2.1_hiera_l.yaml',str(ROOT/'.cache/msvbench/sam2/sam2.1_hiera_large.pt'),device=self.device)
 @torch.inference_mode()
 def process_video(self,video_path,text_prompt,source_frames_dir,tracking_results_dir,cropped_frames_dir,output_video_path,cropped_video_path):
  from groundingdino.util.inference import predict
  from torchvision.ops import box_convert
  frames=Path(source_frames_dir);tracks=Path(tracking_results_dir);crops=Path(cropped_frames_dir)
  for p in (frames,tracks,crops):p.mkdir(parents=True,exist_ok=True)
  cap=cv2.VideoCapture(str(video_path));fps=cap.get(cv2.CAP_PROP_FPS);count=0
  if fps<=0:raise ValueError('Cannot determine input FPS')
  while True:
   ok,bgr=cap.read()
   if not ok:break
   cv2.imwrite(str(frames/('%05d.jpg'%count)),bgr,[cv2.IMWRITE_JPEG_QUALITY,95]);count+=1
  cap.release()
  if count<2:raise ValueError('SAM2 tracking needs at least two frames')
  image=Image.open(frames/'00000.jpg').convert('RGB');w,h=image.size
  _,tensor=self.detector.image_transform_grounding(image)
  boxes,logits,phrases=predict(self.detector.gd,tensor,text_prompt.lower(),self.box_threshold,self.text_threshold,device=self.device)
  if len(boxes)==0:raise ValueError('NO_TARGET_DETECTION: '+text_prompt)
  selected=int(logits.argmax());box=box_convert(boxes[selected:selected+1]*torch.tensor([w,h,w,h]),'cxcywh','xyxy')[0].cpu().numpy()
  with torch.autocast('cuda',dtype=torch.bfloat16,enabled=self.device.startswith('cuda')):
   state=self.predictor.init_state(video_path=str(frames),offload_video_to_cpu=True)
   self.predictor.add_new_points_or_box(inference_state=state,frame_idx=0,obj_id=1,box=box)
   trajectory=[]
   for idx,ids,masks in self.predictor.propagate_in_video(state):
    mask=(masks[0,0]>0).cpu().numpy();ys,xs=np.where(mask)
    if len(xs):trajectory.append({'frame':int(idx),'xyxy':[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]})
   self.predictor.reset_state(state)
  if not trajectory:raise ValueError('NO_TRACKED_TARGET')
  rect=np.asarray([x['xyxy'] for x in trajectory]);x0,y0=rect[:,:2].min(0);x1,y1=rect[:,2:].max(0)
  pad=int(min(x1-x0,y1-y0)*0.1);x0=max(0,int(x0-pad));y0=max(0,int(y0-pad));x1=min(w,int(x1+pad));y1=min(h,int(y1+pad))
  x1=x0+((x1-x0)//2)*2;y1=y0+((y1-y0)//2)*2
  if min(x1-x0,y1-y0)<2:raise ValueError('Invalid tracked crop')
  writer=cv2.VideoWriter(str(cropped_video_path),cv2.VideoWriter_fourcc(*'mp4v'),fps,(x1-x0,y1-y0))
  if not writer.isOpened():raise RuntimeError('Cannot create cropped video')
  for idx in range(count):
   bgr=cv2.imread(str(frames/('%05d.jpg'%idx)));crop=bgr[y0:y1,x0:x1];writer.write(crop)
   cv2.imwrite(str(crops/('%05d.jpg'%idx)),crop)
  writer.release()
  (tracks/'tracking.json').write_text(json.dumps({'adapter':'reconstructed; not author original','detector':'GroundingDINO Swin-T OGC','tracker':'SAM2.1 Hiera Large','selection':'highest confidence first-frame box','thresholds':[self.box_threshold,self.text_threshold],'crop':'temporal union of mask bounding boxes plus 10% margin; original FPS','crop_xyxy':[x0,y0,x1,y1],'frames':count,'tracked_frames':len(trajectory),'trajectory':trajectory},indent=2))
  return str(cropped_video_path)
