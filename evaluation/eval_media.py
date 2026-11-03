"""Evidence extraction and auditable Qwen judging; project credentials win."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parent
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import base64,hashlib,json,os,re,subprocess,time
from pathlib import Path
import cv2,requests
from workspace_paths import BASELINE_ROOT, RUN_ROOT, ENV_FILE, load_json

ROOT = BASELINE_ROOT
RUN = RUN_ROOT

def dump(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def credentials():
 env={}
 for line in ((ENV_FILE)).read_text().splitlines():
  if line and not line.startswith('#') and '=' in line:
   k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
 return env

def data_url(p,mime):return 'data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()

def frame(video,seconds,out,max_width=768):
 out.parent.mkdir(parents=True,exist_ok=True)
 cap=cv2.VideoCapture(str(video))
 try:
  fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));index=min(count-1,max(0,round(seconds*fps)))
  if not out.exists():
   cap.set(cv2.CAP_PROP_POS_FRAMES,index);good,image=cap.read()
   if not good:raise RuntimeError('Cannot decode frame '+str(video)+' at '+str(index))
   if image.shape[1]>max_width:image=cv2.resize(image,(max_width,round(image.shape[0]*max_width/image.shape[1])),interpolation=cv2.INTER_AREA)
   if not cv2.imwrite(str(out),image,[cv2.IMWRITE_JPEG_QUALITY,92]):raise RuntimeError('Cannot save evidence frame')
 finally:cap.release()
 return {'video':str(video),'frame_index':index,'timestamp_sec':index/fps,'fps':fps,'frame_count':count,'path':str(out),'image_max_width':max_width}

def audiovisual(video,start,end,folder):
 folder.mkdir(parents=True,exist_ok=True);frames=[]
 for i in range(int(end-start)):
  frames.append(frame(video,start+i,folder/('frame_%04d.jpg'%i),448))
 if not frames:frames.append(frame(video,start,folder/'frame_0000.jpg',448))
 audio=folder/'audio.wav'
 if not audio.exists():
  subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(video),'-t',str(end-start),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(audio)],check=True,stdin=subprocess.DEVNULL)
 timeline={'start_sec':start,'end_sec':end,'sampling_fps':1,'frames':frames,'audio':str(audio),'audio_encoding':'WAV mono 16kHz PCM16'}
 dump(folder/'evidence.json',timeline)
 # Qwen's list-of-video-frames input plus an aligned original audio track.
 content=[{'type':'video','video':[data_url(Path(f['path']),'image/jpeg') for f in frames]}]
 content.append({'type':'input_audio','input_audio':{'data':data_url(audio,'audio/wav'),'format':'wav'}})
 return content,timeline

def continuity(before,after,folder):
 folder.mkdir(parents=True,exist_ok=True);evidence=[]
 for label,video,is_tail in [('previous_tail',before,True),('next_head',after,False)]:
  cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS);n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));cap.release()
  indices=range(max(0,n-3),n) if is_tail else range(min(3,n))
  for i,index in enumerate(indices):evidence.append(dict(frame(video,index/fps,folder/('%s_%d.jpg'%(label,i)),768),side=label))
 if len(evidence)!=6:raise RuntimeError('Continuity needs exactly 3+3 frames')
 dump(folder/'evidence.json',{'protocol':'3 previous tail frames + 3 next head frames, before assembly','frames':evidence})
 content=[]
 for f in evidence:
  content.extend([{'type':'text','text':f['side']+' t=%.6f'%f['timestamp_sec']},{'type':'image_url','image_url':{'url':data_url(Path(f['path']),'image/jpeg')}}])
 return content,{'frames':evidence}

def judge(prompt,content,out,model='qwen3.5-omni-plus',score_range=(1,5)):
 if (out/'result.json').exists():return load_json(out / 'result.json')
 out.mkdir(parents=True,exist_ok=True);env=credentials();key=env['DASHSCOPE_API_KEY']
 base=env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
 payload={'model':model,'messages':[{'role':'user','content':[{'type':'text','text':prompt}]+content}],'modalities':['text'],'stream':True,'stream_options':{'include_usage':True},'max_tokens':2048,'temperature':0.1}
 dump(out/'request.json',{'model':model,'endpoint':base,'prompt':prompt,'payload_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest(),'media_count':len(content),'temperature':0.1,'max_tokens':2048})
 last=None
 for attempt in range(3):
  try:
   response=requests.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload,stream=True,timeout=(30,240))
   if response.status_code!=200:raise RuntimeError('HTTP %d: '%response.status_code+response.text[:1500].replace(key,'[REDACTED]'))
   chunks=[];text=''
   for line in response.iter_lines():
    if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
    item=json.loads(line[6:]);chunks.append(item)
    for c in item.get('choices',[]):text+=c.get('delta',{}).get('content') or ''
   dump(out/('response_attempt_%d.json'%attempt),{'chunks':chunks,'text':text})
   try:parsed=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip()))
   except ValueError:
    match=re.search(r'(?:Score|score)\s*[:：]\s*([0-9]+)',text)
    if not match:raise RuntimeError('Judge returned no parseable score')
    parsed={'score':int(match.group(1)),'analysis':text}
   score=parsed.get('score')
   if not isinstance(score,int) or not score_range[0]<=score<=score_range[1]:raise RuntimeError('Judge score outside rubric range')
   result={'status':'SCORED','model':model,'model_response_id':next((x.get('id') for x in chunks if x.get('id')),None),'score':score,'analysis':parsed.get('analysis',text),'score_range':score_range,'attempt':attempt}
   dump(out/'result.json',result);return result
  except Exception as ex:
   last=str(ex).replace(key,'[REDACTED]');dump(out/('error_attempt_%d.json'%attempt),{'error':last})
   if 'HTTP 401' in last or 'HTTP 403' in last:break
   time.sleep(3*(attempt+1))
 raise RuntimeError(last)
