"""Reconstructed video-frame extraction interface for MSVBench."""
from pathlib import Path
import cv2,json
class VideoFrameExtractor:
 def extract_frames_from_video(self,video_path,output_dir,fps=32):
  out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
  cap=cv2.VideoCapture(str(video_path));native=cap.get(cv2.CAP_PROP_FPS)
  if native<=0:return False
  stride=max(1,round(native/fps));i=0;kept=[]
  while True:
   ok,frame=cap.read()
   if not ok:break
   if i%stride==0:
    cv2.imwrite(str(out/('%06d.jpg'%len(kept))),frame,[cv2.IMWRITE_JPEG_QUALITY,95]);kept.append(i/native)
   i+=1
  cap.release()
  (out/'sampling.json').write_text(json.dumps({'source':str(Path(video_path).resolve()),'native_fps':native,'requested_fps':fps,'stride':stride,'frame_timestamps':kept,'adapter':'reconstructed'}))
  return len(kept)>=2
