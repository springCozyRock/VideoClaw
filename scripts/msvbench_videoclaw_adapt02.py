#!/usr/bin/env python3
"""User-authorized clothed story-02 variant; keep the original failed run untouched."""
from pathlib import Path
import os,json,time,copy,fcntl,subprocess,sys,requests
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'experiments/msvbench_agents_20261018'
OUT=RUN/'videoclaw_adapted/stories/02';REPAIR=ROOT/'experiments/msvbench_repair_20261019'
sys.path.insert(0,str(ROOT/'scripts'))
import msvbench_agents_run as m
m.API='http://127.0.0.1:8013'
BODY="中景，平视机位，固定镜头。午后的家庭走廊里，David穿着不透明的蓝色长袖睡衣和长裤，衣物完整覆盖躯干和双腿，背对镜头向走廊深处跑去。妈妈穿着日常家居服，拿着一条毛巾在后方跟着，神情关切。墙上挂着画作，地板有柔和反光。旁白及台词：David runs down the hallway in his blue pajamas. His mom calls, 'David, please slow down and come back!'"
DESCRIPTION="Afternoon, hallway at home, framed pictures on the walls and soft reflections on the floor. David wears opaque blue long-sleeved pajamas and long trousers covering his torso and legs, and runs down the hallway away from the camera. His mom, fully dressed, follows carrying a towel with a concerned expression. David runs down the hallway in his blue pajamas. His mom calls, 'David, please slow down and come back!' Medium shot, eye level shot."
def save(p,d):m.dump(p,d)
def replace_sid(x,sid):
 if isinstance(x,dict):return {k:(sid if k=='session_id' else replace_sid(v,sid)) for k,v in x.items()}
 if isinstance(x,list):return [replace_sid(v,sid) for v in x]
 return x
def patch(sid,stage,data):
 r=requests.patch(m.API+f'/api/project/{sid}/artifact/{stage}',json=data,timeout=60);r.raise_for_status()
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 with (OUT/'run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if m.read(OUT/'status.json').get('status')=='GENERATED':return
  original=RUN/'videoclaw/stories/02'
  saved=m.read(OUT/'session_receipt.json')
  if saved:
   raise RuntimeError('An adapted session already exists; inspect receipts before any paid retry')
  request=m.read(original/'request.json')
  request['idea']='CONTENT-ADAPTED MSVBench story 02. User authorized David to wear opaque pajamas in the hallway segment; preserve all other original content and native timing.'
  r=requests.post(m.API+'/api/project/start',json=request,timeout=60);r.raise_for_status();created=r.json();sid=created['session_id'];save(OUT/'session_receipt.json',created)
  arts={stage:m.read(original/(stage+'.json')) for stage in ['script_generation','character_design','storyboard','reference_generation','video_generation']}
  arts=replace_sid(arts,sid)
  segments=m.segments(arts['storyboard']);target=next(s for s in segments if s['segment_id']=='seg_01_05')
  if len(target['shots'])!=1:raise RuntimeError('Unexpected original segment structure')
  target['shots'][0]['content']=BODY
  for scene in arts['reference_generation']['scenes']:
   if scene['id']=='seg_01_05':
    scene.update(description=BODY,visual_prompt=DESCRIPTION,selected='',versions=[],status='pending')
  for clip in arts['video_generation']['clips']:
   if clip['id']=='seg_01_05':
    clip.update(description=BODY,selected='',versions=[],status='pending')
  import re
  for episode in arts['script_generation'].get('episodes',[]):
   if 'content' in episode:episode['content']=re.sub(r'<action>\[MSVBench canonical shot 005\].*?</action>','<action>[MSVBench canonical shot 005] '+DESCRIPTION+'</action>',episode['content'],flags=re.S)
  for stage,data in arts.items():patch(sid,stage,data);save(OUT/(stage+'.before.json'),data)
  row=copy.deepcopy(next(x for x in m.read(ROOT/'configs/msvbench_agents_20261018/manifest.json')['stories'] if x['story']=='02'))
  official=m.read(row['script']);canonical=[c for s in official['script'] for c in s['clips']];canonical[4]['description']=DESCRIPTION
  prompt=Path(row['prompt']).read_text().splitlines();prompt[4]=DESCRIPTION
  inp=OUT/'adapted_inputs';inp.mkdir(exist_ok=True);save(inp/'script.json',official);(inp/'prompt.txt').write_text('\n'.join(prompt)+'\n')
  row.update(script=str(inp/'script.json'),prompt=str(inp/'prompt.txt'))
  save(OUT/'evaluation_inputs.json',row)
  save(OUT/'protocol_deviation.json',{'variant':'CONTENT_ADAPTED','user_authorized':True,'source_story':'02','source_session':'1792287512932','adapted_session':sid,'changed_official_shot':5,'changed_native_segment':'seg_01_05','change':'David wears opaque blue pajamas; narration/dialogue revised accordingly; scene/camera/native timing retained','reuse':'Eight successful native video segments and all unaffected assets retained','strict_original_result':False})
  refs=m.stage(OUT,sid,'reference_generation',{'regenerate_scenes':['seg_01_05']})
  if not next(s for s in refs['scenes'] if s['id']=='seg_01_05').get('selected'):raise RuntimeError('Adapted reference generation failed')
  video=m.stage(OUT,sid,'video_generation',{'regenerate_clips':['seg_01_05']})
  clips={c['id']:c for c in video.get('clips',[]) if c.get('selected')}
  if len(clips)!=len(segments):raise RuntimeError('Adapted video remains incomplete')
  entries=[];index=0
  for seg in segments:
   path=m.BACKEND/clips[seg['segment_id']]['selected'];m.validate(path,float(seg['total_duration']));offset=0.
   for shot in seg['shots']:
    index+=1;end=offset+float(shot['duration']);dest=OUT/'shots'/f'{index:02d}.mp4';m.extract(path,offset,end,dest)
    entries.append({'official_shot_index':index,'path':str(dest),'source_segment':str(path),'start_sec':offset,'end_sec':end,'content_adapted':index==5});offset=end
  m.stage(OUT,sid,'post_production')
  source=m.BACKEND/'code/result/video'/sid/'output'/f'{sid}_ep1.mp4';info=m.validate(source,sum(float(s['total_duration']) for s in segments))
  import shutil
  shutil.copy2(source,OUT/'final.mp4')
  save(OUT/'evaluation_manifest.json',{'story':'02','variant':'CONTENT_ADAPTED','final_video':str(OUT/'final.mp4'),'shots':entries})
  save(OUT/'status.json',{'status':'GENERATED','variant':'CONTENT_ADAPTED','session_id':sid,'shots':len(entries),'duration_sec':float(info['format']['duration']),'final_video':str(OUT/'final.mp4'),'updated':time.time()})
if __name__=='__main__':
 try:main()
 except Exception as ex:
  OUT.mkdir(parents=True,exist_ok=True);save(OUT/'status.json',{'status':'FAILED','error':str(ex),'updated':time.time(),'variant':'CONTENT_ADAPTED'});raise
