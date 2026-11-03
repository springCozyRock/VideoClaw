"""Qwen transport for MSVBench's unchanged GeminiAPI-facing metric code."""
import base64, copy, fcntl, hashlib, io, json, os, time, contextlib
from pathlib import Path
from types import SimpleNamespace
import requests
from PIL import Image
from rate_limit_policy import RATE_LIMIT_RETRY_SECONDS, REQUEST_GAP_SECONDS, MAX_RATE_LIMIT_RETRIES, is_rate_limited

ROOT = Path(__file__).resolve().parents[1]
ERRORS = []

def dump(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str),encoding='utf-8');tmp.replace(path)

def credentials():
    env=dict(os.environ)
    for line in (ROOT/'.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);env[k.strip()]=v.strip().strip('\"\'')
    return env

class QwenAPI:
    def __init__(self, api_keys=None, proxy=None):
        self.env=credentials();self.key=self.env.get('DASHSCOPE_API_KEY','')
        if not self.key: raise RuntimeError('DASHSCOPE_API_KEY missing from project .env')
        self.base=self.env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
        self.model='qwen3.5-omni-plus';self.current_key_index=0;self.api_keys=['project-env']
        self.uploaded_videos={0:{}};self.file_owner_by_name={}
        self.out=Path(os.environ.get('MSVBENCH_AUDIT_DIR',str(ROOT/'experiments/msvbench_smoke/judge_calls')))
    def upload_video(self, video_path):
        path=str(Path(video_path).resolve())
        if not Path(path).is_file():raise FileNotFoundError(path)
        item=SimpleNamespace(name=path,uri=path,state=SimpleNamespace(name='ACTIVE'))
        self.uploaded_videos[0][video_path]=item;self.file_owner_by_name[path]=0
        return item
    def _image(self,path):
        with Image.open(path) as img:
            img=img.convert('RGB');img.thumbnail((768,768));buf=io.BytesIO();img.save(buf,format='JPEG',quality=90)
        return 'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()
    def _video(self,path):
        import cv2
        cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS);n=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps<=0 or n<=0:cap.release();raise ValueError('Cannot decode video '+str(path))
        duration=n/fps;frames=[];times=[]
        if duration>240:cap.release();raise ValueError('Video exceeds declared 240-frame/1-fps limit; split shots explicitly')
        for t in range(max(1,int(__import__('math').ceil(duration)))):
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,bgr=cap.read()
            if not ok:cap.release();raise ValueError('Failed to decode timestamp '+str(t))
            img=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB));img.thumbnail((768,768))
            buf=io.BytesIO();img.save(buf,format='JPEG',quality=90)
            frames.append('data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode());times.append(t)
        cap.release()
        return {'type':'video','video':frames,'fps':1},dict(path=str(Path(path).resolve()),duration=duration,frame_timestamps_seconds=times)
    @contextlib.contextmanager
    def request_slot(self):
        directory=getattr(self,'rate_dir',None)
        if directory is None:
            yield;return
        folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256((self.base+'|'+self.model).encode()).hexdigest()
        with (folder/(key+'.lock')).open('a+') as gate:
            fcntl.flock(gate,fcntl.LOCK_EX)
            stamp=folder/(key+'.json')
            last=json.loads(stamp.read_text()).get('ended_at',0) if stamp.exists() else 0
            delay=max(0,last+REQUEST_GAP_SECONDS-time.time())
            if delay:time.sleep(delay)
            try:yield
            finally:dump(stamp,dict(ended_at=time.time()))

    def _call(self,prompt,image_paths=None,video_paths=None):
        content=[{'type':'text','text':prompt}];media=[]
        for p in image_paths or []:
            url=self._image(p);content.append({'type':'image_url','image_url':{'url':url}});media.append({'path':str(p),'kind':'image'})
        for p in video_paths or []:
            item,info=self._video(p);content.append(item);media.append(info)
        payload={'model':self.model,'messages':[{'role':'user','content':content}],'stream':True,'stream_options':{'include_usage':True},'modalities':['text'],'max_tokens':8192}
        if getattr(self,'thinking_budget',None) is not None:
            payload.update(enable_thinking=True,thinking_budget=self.thinking_budget)
        sha=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest();folder=self.out/sha;folder.mkdir(parents=True,exist_ok=True)
        with (folder/'call.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if (folder/'response.json').exists(): return json.loads((folder/'response.json').read_text())['text']
            dump(folder/'request.json',{'model':self.model,'prompt':prompt,'media':media,'payload_sha256':sha,'endpoint':self.base,'stream':True,'max_tokens':8192,'temperature':'provider default, as in upstream Gemini request','thinking_budget':payload.get('thinking_budget')})
            delays=getattr(self,'retry_delays',(1,2))
            with self.request_slot():
                for attempt in range(max(len(delays), MAX_RATE_LIMIT_RETRIES)+1):
                    try:
                        with requests.post(self.base+'/chat/completions',headers={'Authorization':'Bearer '+self.key},json=payload,stream=True,timeout=(30,240)) as res:
                            if res.status_code!=200:raise RuntimeError('HTTP '+str(res.status_code)+': '+res.text[:1200].replace(self.key,'[REDACTED]'))
                            text='';chunks=[]
                            for line in res.iter_lines():
                                if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
                                item=json.loads(line[6:]);chunks.append(item)
                                if item.get('error'):raise RuntimeError(str(item['error']))
                                for choice in item.get('choices',[]):text+=choice.get('delta',{}).get('content') or ''
                        if not text.strip():raise ValueError('Empty model response')
                        dump(folder/'response.json',{'text':text,'chunks':chunks,'attempt':attempt,'model':self.model});return text
                    except Exception as ex:
                        msg=str(ex).replace(self.key,'[REDACTED]');dump(folder/('error_%d.json'%attempt),{'error':msg})
                        dump(folder/('failure_'+str(time.time_ns())+'.json'),dict(error=msg,attempt=attempt,created_at=time.time()))
                        limited = is_rate_limited(msg)
                        retry_wait = (RATE_LIMIT_RETRY_SECONDS if attempt < MAX_RATE_LIMIT_RETRIES else None) if limited else (delays[attempt] if attempt < len(delays) else None)
                        if retry_wait is None:
                            ERRORS.append({'request':sha,'error':msg});raise RuntimeError(msg) from None
                        time.sleep(retry_wait)
    def generate_from_text(self,prompt,model=None):return self._call(prompt)
    def generate_from_images(self,image_paths,prompt,model=None):return self._call(prompt,image_paths=image_paths)
    def generate_from_videos(self,video_paths,prompt,model=None):return self._call(prompt,video_paths=video_paths)
    def generate_from_video_file(self,video_file,prompt,model=None):return self._call(prompt,video_paths=[video_file.name])
    def generate_multimodal(self,prompt,image_paths=None,video_paths=None,video_files=None,model=None):
        return self._call(prompt,image_paths, list(video_paths or [])+[v.name for v in video_files or []])
    def is_current_key_usable(self,test_video_path=None,prompt='Summarize the video.',model=None):
        return bool(self.generate_from_videos([test_video_path],prompt))
