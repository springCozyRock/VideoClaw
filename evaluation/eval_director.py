#!/usr/bin/env python3
"""Native DirectorBench rubric and graph, user-selected Qwen3.5 Omni judge."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parent
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,hashlib,itertools,json,logging,os,sys,threading
from pathlib import Path
from types import SimpleNamespace
import requests
from eval_media import ROOT,RUN,credentials,dump
from api_throttle import RequestSlot,ProviderUnavailable,cooldown
from workspace_paths import CONFIG_ROOT, INPUT_ROOT, DIRECTOR_ROOT, load_json

sys.path.insert(0,str((DIRECTOR_ROOT)))
KEY='';BASE='';OUT=None;COUNTER=itertools.count();LOCK=threading.Lock()

def redact_media(value):
 if isinstance(value,dict):return {k:redact_media(v) for k,v in value.items()}
 if isinstance(value,list):return [redact_media(v) for v in value]
 if isinstance(value,str) and value.startswith('data:'):return '[inline media sha256='+hashlib.sha256(value.encode()).hexdigest()+']'
 return value

class StreamCompletions:
 def create(self,**kwargs):
  with LOCK:index=next(COUNTER)
  folder=OUT/'judge_calls'/('%05d'%index)
  requested_json=kwargs.pop('response_format',None)
  payload=dict(kwargs,model='qwen3.5-omni-plus',stream=True,modalities=['text'],stream_options={'include_usage':True})
  dump(folder/'request.json',dict(redact_media(payload),requested_response_format=requested_json,transport_note='Native prompts require JSON; SSE text is aggregated to the native client response interface.'))
  slot=RequestSlot();slot.__enter__()
  try:response=requests.post(BASE+'/chat/completions',headers={'Authorization':'Bearer '+KEY},json=payload,timeout=(30,300),stream=False)
  finally:slot.__exit__()
  if response.status_code==429:
   message=response.text[:1500].replace(KEY,'[REDACTED]');cooldown(message,600 if 'insufficient_quota' in message else 90);raise ProviderUnavailable('HTTP 429: '+message)
  if response.status_code!=200:raise RuntimeError('HTTP %d: '%response.status_code+response.text[:1500].replace(KEY,'[REDACTED]'))
  chunks=[];text=''
  for line in response.iter_lines():
   if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
   obj=json.loads(line[6:]);chunks.append(obj)
   for c in obj.get('choices',[]):text+=c.get('delta',{}).get('content') or ''
  dump(folder/'response.json',{'chunks':chunks,'text':text})
  return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

def build_client(config,proxy=None):
 client=SimpleNamespace(chat=SimpleNamespace(completions=StreamCompletions()))
 return client,'qwen3.5-omni-plus',False

def main():
 global KEY,BASE,OUT
 parser=argparse.ArgumentParser();parser.add_argument('--case',required=True);parser.add_argument('--profile',type=int);args=parser.parse_args()
 env=credentials();KEY=env['DASHSCOPE_API_KEY'];BASE=env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
 os.environ['DASHSCOPE_API_KEY']=KEY;os.environ['OPENAI_API_KEY']=KEY;os.environ['OPENAI_BASE_URL']=BASE;os.environ['DASHSCOPE_BASE_URL']=BASE
 asr=load_json(RUN / 'evaluation/asr_environment.json')
 if asr.get('status')!='READY':raise RuntimeError('Whisper weights not validated; refusing fallback-scored evaluation')
 os.environ['HF_HUB_DISABLE_XET']='1'
 os.environ['ASR_BACKEND']='faster_whisper';os.environ['FASTER_WHISPER_MODEL']=asr['local_model_path'];os.environ['FASTER_WHISPER_DEVICE']='cuda';os.environ['FASTER_WHISPER_COMPUTE_TYPE']='float16';os.environ['FASTER_WHISPER_BEAM_SIZE']='5';os.environ['FASTER_WHISPER_DOWNLOAD_ROOT']='/mnt/data/bts/models/faster-whisper'
 os.environ['HF_HOME']='/mnt/data/bts/models/hf';os.environ['HF_ENDPOINT']='https://hf-mirror.com';os.environ['TORCH_HOME']='/mnt/data/bts/models/torch'
 for k in list(os.environ):
  if k.startswith('AZURE_OPENAI_'):os.environ.pop(k)
 import directorbench.llm_utils as llm
 llm._build_client=build_client
 from directorbench.config import EvalConfig
 from directorbench.preprocessing import Preprocessor
 from directorbench.agents.audio_agent import AudioEvalAgent
 from director_metric_policy import apply_policy
 from directorbench.schemas import UserProfile
 AudioEvalAgent._eval_bgm=lambda self,state:None
 original_record=Preprocessor._record_tool
 def strict_record(self,tool_name,status,*a,**kw):
  original_record(self,tool_name,status,*a,**kw)
  if tool_name=='ASR/FasterWhisper' and str(getattr(status,'value',status)).lower()=='failed':
   raise ProviderUnavailable('Required ASR failed; refusing native fallback scores')
 Preprocessor._record_tool=strict_record
 from directorbench.main import evaluate_video
 profiles=load_json((CONFIG_ROOT / 'directorbench_profiles.json'))
 logging.basicConfig(level=logging.INFO)
 cid=args.case;folder=(INPUT_ROOT)/cid;results=[]
 for profile in profiles:
  pid=profile['profile_id']
  if args.profile is not None and pid!=args.profile:continue
  OUT=RUN/'evaluation/directorbench'/cid/('profile_%02d'%pid)
  done=OUT/'result.json'
  if done.exists():results.append(load_json(done));continue
  config=EvalConfig();config.preprocess.separate_audio_tracks=False;config.llm.model='qwen3.5-omni-plus';config.vlm.model='qwen3.5-omni-plus';config.llm.api_key=KEY;config.vlm.api_key=KEY;config.llm.base_url=BASE;config.output_dir=str(OUT)
  report=evaluate_video(video_path=str(RUN/'videos'/(cid+'.mp4')),user_prompt=(folder/'benchmark_prompt.txt').read_text(),script_text=(folder/'script.txt').read_text(),storyboard=load_json(folder / 'storyboard.json'),user_profile=profile,config=config,output_dir=str(OUT),verbose=True)
  result={'case_id':cid,'profile_id':pid,'judge':'qwen3.5-omni-plus','protocol_variant':'user_authorized_unified_qwen35','original_paper_judge':'GPT-5.4','config':{'temperature':config.llm.temperature,'max_tokens':config.llm.max_tokens,'frames_per_shot':config.preprocess.frames_per_shot,'asr_backend':'faster-whisper','asr_model':'large-v3','asr_compute_type':'float16','asr_beam_size':5},'report':report.model_dump(mode='json')}
  result=apply_policy(result,UserProfile.from_profile_dict(profile) if 'personalization' in profile else UserProfile(**profile))
  dump(done,result);results.append(result)
 dump(RUN/'evaluation/directorbench'/cid/'summary.json',results)

if __name__=='__main__':main()
