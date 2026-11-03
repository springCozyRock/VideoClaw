"""External Qwen SSE transport; no edits to DirectorBench's published metric code."""
from __future__ import annotations
import fcntl,hashlib,json,os,threading
from pathlib import Path
from types import SimpleNamespace
import requests

class QwenProvider:
 def __init__(self,root,output,config):
  self.root=Path(root);self.output=Path(output);self.errors=[];self.errors_lock=threading.Lock();self.slots=threading.BoundedSemaphore(2)
  env={}
  for raw in (self.root/'.env').read_text().splitlines():
   line=raw.strip()
   if line and not line.startswith('#') and '=' in line:
    k,v=line.split('=',1);env[k.strip()]=v.strip().strip('\"\'')
  self.key=env.get('DASHSCOPE_API_KEY','')
  if not self.key:raise RuntimeError('Project .env lacks DASHSCOPE_API_KEY')
  self.endpoint=env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
  self.model='qwen3.5-omni-plus'
  config.llm.api_key=config.vlm.api_key=self.key;config.llm.base_url=self.endpoint
 def redact(self,value):return str(value).replace(self.key,'[REDACTED]')
 def media_redacted(self,value):
  if isinstance(value,dict):return {k:self.media_redacted(v) for k,v in value.items()}
  if isinstance(value,list):return [self.media_redacted(v) for v in value]
  if isinstance(value,str) and value.startswith('data:'):return '[inline media sha256='+hashlib.sha256(value.encode()).hexdigest()+']'
  return value
 def write(self,path,value):
  path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(path)
 def create(self,**kwargs):
  requested_json=kwargs.pop('response_format',None)
  payload=dict(kwargs,model=self.model,stream=True,stream_options={'include_usage':True},modalities=['text'])
  sha=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest();folder=self.output/'judge_calls'/sha;folder.mkdir(parents=True,exist_ok=True)
  with (folder/'call.lock').open('w') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   if (folder/'response.json').exists():
    text=json.loads((folder/'response.json').read_text())['text']
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
   self.write(folder/'request.json',{'payload':self.media_redacted(payload),'payload_sha256':sha,'requested_response_format':requested_json,'note':'Native prompts/parser retained; JSON SDK flag removed for Qwen Omni streaming compatibility','endpoint':self.endpoint})
   try:
    with self.slots,requests.post(self.endpoint+'/chat/completions',headers={'Authorization':'Bearer '+self.key},json=payload,stream=True,timeout=(30,300)) as response:
     if response.status_code!=200:raise RuntimeError('HTTP '+str(response.status_code)+': '+self.redact(response.text[:1500]))
     text='';chunks=[];finish=[]
     for line in response.iter_lines():
      if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
      item=json.loads(line[6:]);chunks.append(item)
      if item.get('error'):raise RuntimeError(str(item['error']))
      for choice in item.get('choices',[]):
       text+=choice.get('delta',{}).get('content') or ''
       if choice.get('finish_reason'):finish.append(choice['finish_reason'])
    if not text.strip() or 'length' in finish:raise RuntimeError('Empty or truncated Qwen response')
    with self.errors_lock:self.errors[:]=[x for x in self.errors if x['request_sha256']!=sha]
    self.write(folder/'response.json',{'text':text,'chunks':chunks,'model':self.model,'finish_reasons':finish})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
   except Exception as ex:
    error={'request_sha256':sha,'error':self.redact(ex)}
    with self.errors_lock:self.errors.append(error)
    self.write(folder/'error.json',error);raise RuntimeError(error['error']) from None
 def build_client(self,config,proxy=None):
  return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))),self.model,False

def install_provider(root,output,config):
 import directorbench.llm_utils as llm
 adapter=QwenProvider(root,output,config);llm._build_client=adapter.build_client
 for k in list(os.environ):
  if k.startswith('AZURE_OPENAI_'):os.environ.pop(k)
 os.environ['LLM_MAX_ATTEMPTS']='3'
 os.environ['HF_ENDPOINT']='https://hf-mirror.com'
 os.environ['HF_HOME']=str(Path(root)/'.cache/directorbench_public/huggingface')
 os.environ['TORCH_HOME']=str(Path(root)/'.cache/directorbench_public/torch')
 from mobileviclip_runtime import configure_mobileviclip
 configure_mobileviclip(root)
 hub=Path('/mnt/data/bts/models/hf/hub/models--sentence-transformers--all-MiniLM-L6-v2')
 if (hub/'refs/main').exists():
  snapshot=hub/'snapshots'/(hub/'refs/main').read_text().strip()
  if snapshot.is_dir():os.environ['SENTENCE_BERT_MODEL_PATH']=str(snapshot)
 model=Path(root)/'.cache/faster-whisper-large-v3'
 if (model/'model.bin').exists():
  os.environ.update(ASR_BACKEND='faster_whisper',FASTER_WHISPER_MODEL=str(model),FASTER_WHISPER_DEVICE='cuda',FASTER_WHISPER_COMPUTE_TYPE='float16',FASTER_WHISPER_BEAM_SIZE='5')
 return adapter
