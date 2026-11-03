#!/usr/bin/env python3
"""Dedicated VideoClaw service for this five-story benchmark; native timing retained."""
import os,sys,threading,time
from pathlib import Path
from rate_limit_policy import RATE_LIMIT_RETRY_SECONDS, MAX_RATE_LIMIT_RETRIES, is_rate_limited
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
os.environ['MSVBENCH_AUDIT_DIR']=str(ROOT/'experiments/msvbench_agents_20261018/videoclaw_adapted/judge_calls')
import videoclaw_runtime as runtime
runtime.RUN=ROOT/'experiments/msvbench_agents_20261018/videoclaw/generation_ledger'
runtime.configure();runtime.install_adapters()
from models.llm_client import LLM
from models.image_client import ImageClient
from models.video_client import VideoClient
from msvbench_qwen import QwenAPI
query=LLM.query;image=ImageClient.generate_image;video=VideoClient.generate_video
image_slots=threading.BoundedSemaphore(2);video_slots=threading.BoundedSemaphore(4);rate=threading.Lock();last=[0.0]
def wrapped_query(self,prompt,image_urls=None,model='qwen3.5-plus',safe_content=True,task_id=None,web_search=False):
 if model=='qwen3.5-omni-plus':
  paths=[]
  for value in image_urls or []:
   if str(value).startswith('file://'):value=str(value)[7:]
   if not Path(str(value)).is_file():raise ValueError('Quality judge requires a local image path')
   paths.append(str(value))
  api=QwenAPI();text=api.generate_from_images(paths,prompt) if paths else api.generate_from_text(prompt)
  return self.full_to_half(text) if safe_content else text
 return query(self,prompt,image_urls or [],model,safe_content,task_id,web_search)
def wrapped_image(self,*args,**kwargs):
 with image_slots:
  for attempt in range(5):
   with rate:
    delay=max(0,3-(time.monotonic()-last[0]));time.sleep(delay);last[0]=time.monotonic()
   try:return image(self,*args,**kwargs)
   except Exception as ex:
    if not is_rate_limited(ex) or attempt==4:raise
    time.sleep(RATE_LIMIT_RETRY_SECONDS)
def wrapped_video(self,*args,**kwargs):
 with video_slots:return video(self,*args,**kwargs)
LLM.query=wrapped_query;ImageClient.generate_image=wrapped_image;VideoClient.generate_video=wrapped_video
if __name__=='__main__':
 import uvicorn
 uvicorn.run('api.app:app',host='127.0.0.1',port=8013,access_log=False)
