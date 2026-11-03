#!/usr/bin/env python3
"""ViStoryBench video adapter: 1 FPS, native rubrics/CIDS, unified Qwen judge.

Adaptations are recorded, rather than represented as an exact paper reproduction.
No missing model, transport error or absent character is converted to a score.
"""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parent
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import argparse,concurrent.futures,hashlib,json,os,re,sys,threading,time
from pathlib import Path
from PIL import Image
from eval_media import ROOT,RUN,credentials,dump,frame
from api_throttle import RequestSlot,ProviderUnavailable,cooldown
from workspace_paths import INPUT_ROOT, CACHE_ROOT, VISTORY_ROOT, CONFIG_ROOT, load_json

SOURCE=(VISTORY_ROOT);STAMP='20261015_210000'
IDS=['action_006','cinematic_008','educational_008','music_004','narrative_074']
CAST={
 'action_006': [('hero','蓝夹克英雄','person wearing a blue jacket','realistic_human',0),('fugitive','红夹克逃跑者','person wearing a red hoodie','realistic_human',0)],
 'cinematic_008':[('woman','米色风衣女性','woman wearing a beige coat','realistic_human',0)],
 'educational_008':[],
 'music_004':[('singer','银发女歌手','female singer with silver hair','realistic_human',0)],
 'narrative_074':[('girl','企鹅女孩','penguin girl','unrealistic_human',0),('cat','黑白奶牛猫','black and white cat','non_human',1)]}
APPEAR={'narrative_074':[['girl'],['girl','cat'],['girl'],['girl','cat'],['girl','cat']]}
ERRORS=[];ERROR_LOCK=threading.Lock();CALL_LOCKS={};CALL_GUARD=threading.Lock();OUT=None

def normalize_score_text(text):
 # Keep the native parser and rubric. Only normalize a bracketed score line
 # explicitly permitted by the upstream prompt's 'Score: [Your Score]' format.
 scores=re.findall(r'(?:score|Score):\s*[a-zA-Z]*\s*(\d+)',text)
 if scores:
  value=int(scores[0])
  if not 0<=value<=4:raise ValueError('Score outside native 0-4 range')
  return text,value,False
 pattern=r'(?m)^([ \t]*(?:score|Score):[ \t]*)\[[ \t]*([0-4])[ \t]*\]([ \t]*)$'
 matches=list(re.finditer(pattern,text))
 if len(matches)!=1:raise ValueError('No unambiguous native 0-4 score')
 match=matches[0];normalized=text[:match.start()]+match.group(1)+match.group(2)+match.group(3)+text[match.end():]
 return normalized,int(match.group(2)),True

def native_judge(transcript=None,top_p=0.2,temp=0.,model_type='',api_key='',base_url='',seed=123,max_tokens=512,**kwargs):
 """Only change transport/model; retain native prompts, temperature and parser."""
 import requests
 payload={'model':'qwen3.5-omni-plus','messages':transcript or [],'temperature':temp,'max_tokens':max_tokens,'seed':seed,'stream':True,'modalities':['text'],'stream_options':{'include_usage':True}}
 sha=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 folder=OUT/'judge_calls'/sha
 with CALL_GUARD:lock=CALL_LOCKS.setdefault(sha,threading.Lock())
 with lock:
  cached=folder/'response.json'
  if cached.exists():
   previous=load_json(cached)
   return previous.get('normalized_text',previous['text'])
  # Recover the first usable recorded response; never select the highest score.
  for prior in sorted(folder.glob('attempt_*.json'),key=lambda p:int(p.stem.rsplit('_',1)[1])):
   previous=load_json(prior)
   try:normalized,score,changed=normalize_score_text(previous.get('text',''))
   except ValueError:continue
   dump(cached,dict(previous,normalized_text=normalized,score=score,attempt=int(prior.stem.rsplit('_',1)[1]),recovered_from=str(prior),score_format_normalized=changed))
   return normalized
  from eval_director import redact_media
  dump(folder/'request.json',dict(redact_media(payload),endpoint=base_url,payload_sha256=sha,native_top_p_argument_unused_by_original_transport=top_p))
  last=''
  for attempt in range(3):
   try:
    with RequestSlot(), requests.post(base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+api_key},json=payload,stream=True,timeout=(30,240)) as response:
     if response.status_code==429:
      message=response.text[:1500].replace(api_key,'[REDACTED]');cooldown(message,600 if 'insufficient_quota' in message else 90);raise ProviderUnavailable('HTTP 429: '+message)
     if response.status_code!=200:raise RuntimeError('HTTP %s: '%response.status_code+response.text[:1500].replace(api_key,'[REDACTED]'))
     chunks=[];text=''
     for line in response.iter_lines():
      if not line.startswith(b'data: ') or line==b'data: [DONE]':continue
      item=json.loads(line[6:]);chunks.append(item)
      for choice in item.get('choices',[]):text+=choice.get('delta',{}).get('content') or ''
    dump(folder/('attempt_%d.json'%attempt),{'text':text,'chunks':chunks})
    normalized,score,changed=normalize_score_text(text)
    dump(cached,{'text':text,'normalized_text':normalized,'chunks':chunks,'score':score,'attempt':attempt,'score_format_normalized':changed});return normalized
   except Exception as ex:
    last=str(ex).replace(api_key,'[REDACTED]');dump(folder/('error_%d.json'%attempt),{'error':last});time.sleep(attempt+1)
  with ERROR_LOCK:ERRORS.append({'request':sha,'error':last})
  raise ProviderUnavailable(last)

def prepare(cid,plan,out,smoke=False):
 storyid=str(IDS.index(cid)+1).zfill(2);dataset=out/'dataset';outputs=out/'outputs'
 story=dataset/'ViStory'/storyid;shotsdir=outputs/'codex/base/en'/STAMP/storyid/'shots'
 shotsdir.mkdir(parents=True,exist_ok=True);cast=CAST[cid];allkeys=[c[0] for c in cast]
 characters={c[0]:{'name_en':c[1],'name_ch':c[1],'prompt_en':c[2],'prompt_ch':c[2],'tag':c[3],'num_of_appearances':-1} for c in cast}
 shots=[];evidence=[];cursor=0
 for clipidx,clip in enumerate(plan['shots']):
  keys=APPEAR.get(cid,[allkeys]*len(plan['shots']))[clipidx]
  for offset in range(clip['duration_sec']):
   if smoke and shots:break
   index=len(shots)+1;path=shotsdir/('frame_%04d.jpg'%index)
   rec=frame(RUN/'videos'/(cid+'.mp4'),cursor+offset,path,100000)
   rec.update(clip_id=clip['shot_id'],caption=clip['description'],declared_character_keys=keys);evidence.append(rec)
   # Both languages carry the original Chinese script; no machine translation.
   bilingual=lambda value:{'en':value,'ch':value}
   shots.append({'index':index,'Setting Description':bilingual(plan['bible']+'\n'+clip['description']),'Plot Correspondence':bilingual(clip['description']),'Characters Appearing':bilingual(keys),'Static Shot Description':bilingual(clip['description']),'Shot Perspective Design':bilingual(clip['description'])})
  cursor+=clip['duration_sec']
 dump(story/'story.json',{'Story_type':{'en':'DirectorBench video adaptation','ch':'DirectorBench 视频适配'},'Characters':characters,'Shots':shots})
 dump(out/'evidence.json',{'sampling_fps':1,'timestamps':'t=0,1,...,duration-1; nearest original frame','caption_scope':'Original generated-clip interval caption; no published finer timestamp labels available','frames':evidence})
 return storyid,dataset,outputs,story,shots

def reference_portraits(evaluator,cid,plan,story,out):
 import torch
 refs=[]
 for key,name,prompt,tag,clipindex in CAST[cid]:
  target=story/'image'/key/'reference.jpg'
  if target.exists():continue
  clip=plan['shots'][clipindex];start=sum(x['duration_sec'] for x in plan['shots'][:clipindex])
  # Fixed order: actual midpoint memory anchor, then evenly spaced fallbacks.
  candidates=[clip['duration_sec']/2]+[clip['duration_sec']*x for x in [.1,.3,.7,.9]]
  selected=None
  for n,offset in enumerate(candidates):
   path=out/'reference_candidates'/key/('%02d.jpg'%n)
   rec=frame(RUN/'videos'/(cid+'.mp4'),start+offset,path,100000)
   boxes,logits,_,_=evaluator.dino_detect(str(path),prompt)
   if len(logits)==0:continue
   for index in torch.argsort(logits,descending=True):
    crop=evaluator.crop_img(str(path),boxes[index:index+1])
    if not crop:continue
    feats=evaluator.get_char_feat(crop,encoder_name=evaluator._get_encoder_name(tag))
    if feats is None:continue
    target.parent.mkdir(parents=True,exist_ok=True);crop[0].save(target,quality=95)
    selected={'key':key,'name':name,'source':rec,'detection_prompt':prompt,'box_cxcywh':boxes[index].tolist(),'detector_confidence':float(logits[index]),'reference':str(target),'selection':'First valid detected portrait in fixed midpoint,10%,30%,70%,90% order; no score optimization'};break
   if selected:break
  if not selected:raise RuntimeError('No valid native reference embedding for '+key+'; metric cannot be scored')
  refs.append(selected)
 if refs:dump(out/'reference_provenance.json',{'reference_source':'Generated first appearance clip; original dataset provides no external identity images for these prompts','references':refs,'comparison_limit':'Measures stability relative to generated anchors, not identity fidelity to externally supplied ground truth'})

def main():
 global OUT,CAST,APPEAR
 parser=argparse.ArgumentParser();parser.add_argument('--case',required=True);parser.add_argument('--smoke',action='store_true');args=parser.parse_args();cid=args.case
 custom=CONFIG_ROOT/'vistory_cast.json'
 if custom.exists():
  entry=load_json(custom)[cid]
  CAST=dict(CAST,**{cid:[tuple(x) for x in entry['cast']]})
  APPEAR=dict(APPEAR,**{cid:entry['appearances']})
 OUT=RUN/'evaluation'/('vistory_smoke' if args.smoke else 'vistorybench')/cid;OUT.mkdir(parents=True,exist_ok=True)
 import fcntl
 lock=(OUT/'run.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX)
 sys.path.insert(0,str(SOURCE));os.chdir(SOURCE)
 import yaml
 import vistorybench.bench.prompt_align.gptv_utils as utils
 utils.gptv_query=native_judge
 from vistorybench.bench.prompt_align.prompt_align_evaluator import PromptAlignEvaluator
 plan=load_json((INPUT_ROOT) / cid / 'plan.json');sid,dataset,outputs,story,shots=prepare(cid,plan,OUT,args.smoke)
 config=yaml.safe_load((SOURCE/'config.yaml').read_text());env=credentials()
 config['cli_args']={'dataset_path':str(dataset),'outputs_path':str(outputs),'pretrain_path':'/mnt/data/bts/repos/vistorybench/data/pretrain','result_path':str(OUT/'native_results'),'api_key':env['DASHSCOPE_API_KEY'],'base_url':env.get('JUDGE_BASE_URL','https://dashscope.aliyuncs.com/compatible-mode/v1'),'model_id':'qwen3.5-omni-plus'}
 config['evaluators']['prompt_align']['gpt']['model']='qwen3.5-omni-plus'
 dump(OUT/'protocol.json',{'judge':'qwen3.5-omni-plus','original_paper_judge':'ChatGPT 5.0','sampling_fps':1,'image_preprocess':'native load_img_content: 512x512 PIL resize, JPEG','native_source':str(SOURCE),'native_rubrics':['scene','character_action','single_character_action'],'CIDS':'native CIDSEvaluator; face ensemble for realistic humans, CLIP for others; Hungarian matching; original weights/thresholds','reference_adaptation':'Generated first appearance anchor portraits; fixed fallback order if no face embedding at midpoint','caption_adaptation':'Each 1FPS frame uses the containing planned clip caption, because no fine per-frame labels are published','character_free_case':'Character-specific metrics NA; not zero','native_single_aggregation':'Preserves native integer rounding per frame then story; unrounded per-character values also retained','groundingdino_device':'cpu; feature models cuda; no CUDA extension required'})
 align=PromptAlignEvaluator(config,STAMP,'base','en',STAMP)
 def one(index,dim):
  path=OUT/'alignment'/dim/('%04d.json'%(index+1))
  if path.exists():return load_json(path)
  shot=shots[index];prompt=shot['Setting Description' if dim=='scene' else 'Static Shot Description']['en']
  image=outputs/'codex/base/en'/STAMP/sid/'shots'/('frame_%04d.jpg'%(index+1))
  score=align._eval_single_dimension(dim,prompt,str(image));result={'frame_index_1fps':index,'score':score,'metric':dim};dump(path,result);return result
 alignresults=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  futures=[pool.submit(one,i,dim) for i in range(len(shots)) for dim in (['scene','character_action'] if CAST[cid] else ['scene'])]
  for f in concurrent.futures.as_completed(futures):alignresults.append(f.result())
 if ERRORS:dump(OUT/'errors.json',ERRORS);raise RuntimeError('Judge errors prevent a valid metric summary')
 metrics={}
 for dim,label in [('scene','scene_alignment'),('character_action','global_character_action')]:
  values=[x['score'] for x in alignresults if x['metric']==dim]
  metrics[label]={'status':'SCORED','score':sum(values)/len(values),'n':len(values),'range':[0,4]} if values else {'status':'NA_NO_CHARACTERS'}
 if CAST[cid]:
  done=OUT/'cids_native.json'
  if done.exists():cids=load_json(done)
  else:
   import vistorybench.bench.content.cids_evaluator as module
   nativepredict=module.predict
   def cpu_predict(*a,**kw):
    try:return nativepredict(*a,**dict(kw,device='cpu'))
    except Exception as ex:
     with ERROR_LOCK:ERRORS.append({'detector_error':str(ex)})
     raise
   module.predict=cpu_predict
   original_helper=module.FaceRestoreHelper
   def cached_helper(*a,**kw):
    kw['model_rootpath']=str((CACHE_ROOT / 'facexlib'))
    return original_helper(*a,**kw)
   module.FaceRestoreHelper=cached_helper
   evaluator=module.CIDSEvaluator(config,STAMP,'base','en',STAMP)
   required=['dino','clip']+(['arcface','adaface','facenet'] if any(c[3]=='realistic_human' for c in CAST[cid]) else [])
   missing=[name for name in required if getattr(evaluator,name,None) is None]
   if any(c[3]=='realistic_human' for c in CAST[cid]) and evaluator.face_helper is None:missing.append('face_helper')
   if missing:raise RuntimeError('Required native encoders missing: '+','.join(missing))
   reference_portraits(evaluator,cid,plan,story,OUT)
   common='person' if cid!='narrative_074' else 'penguin character. cat.'
   evaluator.PRE_TEXT_PROMPT={c[0]:common for c in CAST[cid]}
   cids=evaluator.evaluate('codex',sid)
   if ERRORS:dump(OUT/'errors.json',ERRORS);raise RuntimeError('Native detector/judge errors prevent a valid CIDS summary')
   if not cids or 'metrics' not in cids:raise RuntimeError('Missing native CIDS results')
   dump(done,cids)
  metrics['cross_character_consistency']={'status':'SCORED','score':cids['metrics']['cids_cross_mean'],'native_metric':'cids_cross_mean','per_character':cids['cids'],'reference_adaptation':True}
  value=cids['metrics'].get('single_character_action')
  if value is None:raise RuntimeError('Native single-character action returned no score')
  metrics['single_character_action']={'status':'SCORED','score':value,'range':[0,4],'native_aggregation':True,'detailed_scores':cids.get('detailed_scores',{})}
 else:
  metrics['cross_character_consistency']={'status':'NA_NO_CHARACTERS'};metrics['single_character_action']={'status':'NA_NO_CHARACTERS'}
 dump(OUT/'summary.json',{'case_id':cid,'judge':'qwen3.5-omni-plus','status':'COMPLETE','protocol_variant':'User-authorized unified Qwen35 plus disclosed video/reference adaptation','metrics':metrics,'n_sampled_frames':len(shots),'protocol':str(OUT/'protocol.json')})
 print(cid,'ViStoryBench complete',flush=True)

if __name__=='__main__':main()
