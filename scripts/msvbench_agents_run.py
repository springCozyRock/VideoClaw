#!/usr/bin/env python3
"""Run the authorized five-story VideoClaw and Codex+Composition experiments."""
import argparse,concurrent.futures,datetime,fcntl,hashlib,json,os,shutil,subprocess,sys,threading,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'experiments/msvbench_agents_20261018';CFG=ROOT/'configs/msvbench_agents_20261018'
BACKEND=ROOT/'video-claw/video-claw/backend';API='http://127.0.0.1:8012';LOCK=threading.RLock()
def read(p,default=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8'))
 except (OSError,ValueError):return {} if default is None else default
def dump(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with LOCK:
  tmp=p.with_name(p.name+f'.{os.getpid()}.{threading.get_ident()}.tmp');tmp.write_text(json.dumps(x,indent=2,ensure_ascii=False,default=str),encoding='utf-8');tmp.replace(p)
def request(method,path,body=None):
 r=requests.request(method,API+path,json=body,timeout=60);r.raise_for_status();return r.json()
def stage(folder,sid,name,intervention=None):
 snapshot=request('GET',f'/api/project/{sid}/status')
 if intervention is None and snapshot.get('status',{}).get(name)=='completed' and name in snapshot.get('artifacts',{}):return snapshot['artifacts'][name]
 dump(folder/'status.json',{'status':'RUNNING','stage':name,'session_id':sid,'updated':time.time()})
 url=f'/api/project/{sid}/execute/{name}';body={'resolution':'720P'}
 if intervention is not None:url=f'/api/project/{sid}/intervene';body={'stage':name,'modifications':intervention}
 with requests.post(API+url,json=body,stream=True,timeout=(30,24*3600)) as response:
  response.raise_for_status()
  with (folder/f'{name}.sse').open('a',encoding='utf-8') as stream:
   for line in response.iter_lines():
    if line:stream.write(line.decode('utf-8',errors='replace')+'\n');stream.flush()
 snapshot=request('GET',f'/api/project/{sid}/status');dump(folder/f'{name}.json',snapshot.get('artifacts',{}).get(name,{}))
 if snapshot.get('error') or snapshot.get('status',{}).get(name) in ('error','stopped'):raise RuntimeError(snapshot.get('error') or snapshot['status'][name])
 return snapshot.get('artifacts',{}).get(name,{})
def segments(value):
 if isinstance(value,list):return [s for item in value for s in segments(item)]
 if isinstance(value,dict):
  if isinstance(value.get('segments'),list):return value['segments']
  return [s for item in value.values() if isinstance(item,(list,dict)) for s in segments(item)]
 return []
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)],text=True))
def validate(p,duration=None):
 j=probe(p);v=next((x for x in j['streams'] if x['codec_type']=='video'),None)
 if not v or v['height']<720 or abs(v['width']/v['height']-16/9)>.03:raise RuntimeError('Invalid video format: '+str(p))
 if duration is not None and abs(float(j['format']['duration'])-duration)>.5:raise RuntimeError('Video duration differs from plan: '+str(p))
 return j
def extract(source,start,end,target):
 if end<=start:raise ValueError('Nonpositive shot interval')
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():validate(target,end-start);return
 temp=target.with_name(target.stem+'.tmp.mp4')
 subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(end-start),'-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','fast','-crf','18','-c:a','aac',str(temp)],check=True,timeout=900)
 validate(temp,end-start);temp.replace(target)
def videoclaw_case(row):
 sid=row['story'];folder=RUN/'videoclaw/stories'/sid;folder.mkdir(parents=True,exist_ok=True)
 if read(folder/'status.json').get('status')=='GENERATED':return
 try:
  script=read(row['script']);prompts=Path(row['prompt']).read_text().splitlines();camera=Path(row['camera']).read_text().splitlines()
  payload={'idea':f'MSVBench official complete story {sid}; preserve all provided story content. Let native VideoClaw plan durations.',
   'style':'Match the supplied official character reference images and the original scene descriptions; preserve identities throughout.',
   'video_ratio':'16:9','video_resolution':'720P','episodes':1,'expand_idea':False,'llm_model':'qwen3.7-plus','vlm_model':'qwen3.5-omni-plus',
   'image_t2i_model':'wan2.7-image','image_it2i_model':'wan2.7-image','video_model':'wan3.0-video','video_first_frame_model':'wan3.0-video',
   'video_generation_mode':'first_frame','enable_concurrency':True,'web_search':False}
  dump(folder/'request.json',payload)
  session=read(folder/'session.json')
  if not session:
   if (folder/'session_submission.json').exists():raise RuntimeError('Uncertain session creation; reconcile before resubmitting')
   dump(folder/'session_submission.json',{'status':'SUBMITTING','time':time.time()})
   session=request('POST','/api/project/start',payload);dump(folder/'session.json',session)
  session_id=session['session_id']
  chars=[{'character_id':'char_'+str(c['id']),'name':c['name'],'description':c['description'],'species':''} for c in script['characters']]
  settings=[{'setting_id':'set_'+str(s['id']),'name':s['name'],'description':s['description']} for s in script['environments']]
  # One input line per canonical shot; native annotation and segment planner choose timing.
  lines=[];index=0;bychar={str(c['id']):c['name'] for c in script['characters']};byenv={str(e['id']):e for e in script['environments']}
  for scene_index,scene in enumerate(script['script'],1):
   env=byenv[str(scene['environment'])];desc=env['description'].lower()
   tod='夜' if any(w in desc for w in ('night','moon','stars')) else ('傍晚' if any(w in desc for w in ('dusk','sunset','twilight')) else ('晨' if 'morning' in desc else '日'))
   space='外' if any(w in desc for w in ('outdoor','courtyard','garden','street','forest','meadow','river','woods','lawn')) else '内'
   lines.append(f"第1集-第{scene_index}场 {tod} {space} {env['name']}")
   for clip in scene['clips']:
    names=', '.join(bychar[str(cid)] for cid in clip['characters'])
    lines.append(f"<action>[MSVBench canonical shot {index+1:03d}] {names}. {prompts[index]} Camera motion instruction: {camera[index]}</action>")
    index+=1
  content='\n'.join(lines)
  imported={'project_id':'proj_'+session_id,'session_id':session_id,'title':'MSVBench '+sid,'meta':{'official_story':sid,'official_shot_order_locked':True,'duration_policy':'native independent planning'},'characters':chars,'settings':settings,'episodes':[{'episode_number':1,'act_title':'MSVBench '+sid,'content':content}]}
  if not (folder/'formatted_script_input.json').exists():
   history=folder/'input_format_history';history.mkdir(exist_ok=True)
   for prior in ('script_generation.json','storyboard.json'):
    if (folder/prior).exists():shutil.copy2(folder/prior,history/prior)
   stage(folder,session_id,'script_generation',{'modified_script':imported})
   dump(folder/'formatted_script_input.json',{'script':imported,'adapter':'Original per-shot text/roles preserved; native <action> and scene headers; native timing unchanged'})
   (folder/'character_design.done').unlink(missing_ok=True);(folder/'storyboard.json').unlink(missing_ok=True)
  assetbase=BACKEND/'code/result/image'/session_id/'Assets/characters';assetbase.mkdir(parents=True,exist_ok=True)
  for ref in row['character_inputs']:
   target=assetbase/('char_'+ref['id']+Path(ref['path']).suffix)
   if not target.exists():shutil.copy2(ref['path'],target)
  if not (folder/'character_design.done').exists():
   art=stage(folder,session_id,'character_design')
   for key in ('characters','settings'):
    for item in art.get(key,[]):
     if not item.get('selected') or not (BACKEND/item['selected']).is_file():raise RuntimeError('Incomplete character/environment asset: '+str(item.get('id')))
   (folder/'character_design.done').touch()
  if not (folder/'storyboard.json').exists():art=stage(folder,session_id,'storyboard')
  else:art=read(folder/'storyboard.json')
  segs=segments(art);shots=[s for seg in segs for s in seg.get('shots',[])]
  if len(shots)!=row['shots']:raise RuntimeError(f'Native storyboard has {len(shots)} shots; expected {row["shots"]}. Reconcile official mapping before video generation.')
  dump(folder/'timing_plan.json',{'source':'native VideoClaw StoryboardAgent, unmodified duration heuristics and segment planning','segments':segs,'canonical_shots':len(shots),'total_duration_sec':sum(float(s['total_duration']) for s in segs)})
  if not (folder/'reference_generation.done').exists():
   art=stage(folder,session_id,'reference_generation')
   scenes=art.get('scenes',[])
   if len(scenes)!=len(segs) or any(not x.get('selected') for x in scenes):raise RuntimeError('Incomplete storyboard reference images')
   (folder/'reference_generation.done').touch()
  art=stage(folder,session_id,'video_generation')
  clips={x['id']:x for x in art.get('clips',[]) if x.get('selected')}
  if len(clips)!=len(segs):raise RuntimeError('Incomplete generated segments')
  entries=[];index=0
  for seg in segs:
   clip=BACKEND/clips[seg['segment_id']]['selected'];validate(clip,float(seg['total_duration']));offset=0.0
   for shot in seg['shots']:
    index+=1;end=offset+float(shot['duration']);target=folder/'shots'/f'{index:02d}.mp4';extract(clip,offset,end,target)
    entries.append({'official_shot_index':index,'path':str(target),'source_segment':str(clip),'start_sec':offset,'end_sec':end,'boundary_source':'native storyboard planned boundaries','duration_sec':end-offset});offset=end
  stage(folder,session_id,'post_production')
  source=BACKEND/'code/result/video'/session_id/'output'/f'{session_id}_ep1.mp4'
  p=validate(source,sum(float(s['total_duration']) for s in segs));final=folder/'final.mp4';shutil.copy2(source,final)
  dump(folder/'evaluation_manifest.json',{'story':sid,'final_video':str(final),'shots':entries,'protocol':'Official shot correspondence by native plan order; compound segments split at planned boundaries, not detected cuts'})
  dump(folder/'status.json',{'status':'GENERATED','session_id':session_id,'final_video':str(final),'shots':len(entries),'duration_sec':float(p['format']['duration']),'updated':time.time()})
 except Exception as ex:dump(folder/'status.json',{'status':'FAILED','error':str(ex),'updated':time.time()});print('VIDEOCLAW',sid,'FAILED',str(ex),flush=True)
def run_videoclaw():
 with (RUN/'videoclaw/run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  for _ in range(60):
   try:request('GET','/api/config');break
   except requests.RequestException:time.sleep(2)
  else:raise RuntimeError('Dedicated VideoClaw API not available')
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(videoclaw_case,read(CFG/'manifest.json')['stories']))
def run_codex():
  command=[str(ROOT/'.venvs/codex_composition/bin/python'), str(ROOT/'baselines/codex/run.py'),
           '--profile','msvbench','run']
  result=subprocess.run(command,cwd=ROOT)
  if result.returncode:raise RuntimeError('Codex pipeline exited '+str(result.returncode))

def collect_codex(row):
 sid=row['story'];folder=RUN/'codex_composition/stories'/sid
 if read(folder/'status.json').get('status')=='GENERATED':return
 candidates=[]
 for p in (RUN/'codex_composition/runtime/generation').rglob('evaluation_manifest.json'):
  try:
   j=read(p)
   if str(j.get('story','')).zfill(2)==sid:candidates.append((p,j))
  except Exception:pass
 if not candidates:return
 if len(candidates)>1:raise RuntimeError('Multiple Codex manifests for story '+sid)
 p,j=candidates[0];entries=j.get('shots',[])
 if len(entries)!=row['shots']:return
 final=Path(j.get('final_video',str(p.parent/'final.mp4')))
 if not final.is_absolute():final=p.parent/final
 if not final.exists():return
 folder.mkdir(parents=True,exist_ok=True);export=[]
 for i,item in enumerate(entries,1):
  if int(item['official_shot_index'])!=i:raise RuntimeError('Codex canonical order mismatch')
  source=Path(item['path']);source=source if source.is_absolute() else p.parent/source
  start=float(item.get('start_sec',0));end=float(item.get('end_sec',float(probe(source)['format']['duration'])))
  target=folder/'shots'/f'{i:02d}.mp4';extract(source,start,end,target);export.append(dict(item,evaluation_path=str(target)))
 media=validate(final);shutil.copy2(final,folder/'final.mp4')
 dump(folder/'evaluation_manifest.json',{'original_manifest':str(p),'story':sid,'final_video':str(folder/'final.mp4'),'shots':export})
 dump(folder/'status.json',{'status':'GENERATED','final_video':str(folder/'final.mp4'),'agent_output':str(p.parent),'shots':len(export),'duration_sec':float(media['format']['duration']),'updated':time.time()})
def evaluate():
 rows=read(CFG/'manifest.json')['stories'];statepath=RUN/'evaluation/state.json';state=read(statepath,{'status':'RUNNING','tasks':{}});deadline=time.time()+7*86400
 with (RUN/'evaluation/run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  while time.time()<deadline:
   for row in rows:
    try:collect_codex(row)
    except Exception as ex:dump(RUN/'codex_composition/stories'/row['story']/'collection_error.json',{'error':str(ex),'time':time.time()})
   deployment=read(ROOT/'configs/msvbench/deployment.json');ready=[m for m,e in deployment.get('metrics',{}).items() if e['status']=='SMOKE_VERIFIED']
   for method in ('videoclaw','codex_composition'):
    for row in rows:
     sid=row['story'];folder=RUN/method/'stories'/sid
     if read(folder/'status.json').get('status')!='GENERATED':continue
     for metric in ready:
      key=f'{method}/{sid}/{metric}'
      if state['tasks'].get(key,{}).get('status') in ('SCORED','FAILED'):continue
      free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits','-i','6'],text=True).strip())
      if free<36000:continue
      stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');out=RUN/'evaluation/runs'/stamp
      command=['bash',str(ROOT/'scripts/msvbench.sh'),'--method',method,'--story',sid,'--metric',metric,'--videos',str(folder/'shots'),'--prompt',row['prompt'],'--script',row['script'],'--camera',row['camera'],'--characters',row['evaluation_characters'],'--output-root',str(out)]
      state['tasks'][key]={'status':'RUNNING','started':time.time(),'command':command};state['updated']=time.time();dump(statepath,state)
      log=RUN/'evaluation/logs'/f'{method}_{sid}_{metric}.log';log.parent.mkdir(exist_ok=True,parents=True)
      try:
       with log.open('w') as stream:r=subprocess.run(command,cwd=ROOT,env=dict(os.environ,CUDA_VISIBLE_DEVICES='6',PYTHONUTF8='1'),stdout=stream,stderr=subprocess.STDOUT,timeout=24*3600)
       evidence=out/method/sid/metric/'status.json';score=read(evidence)
       state['tasks'][key]={'status':'SCORED' if r.returncode==0 and score.get('status')=='SCORED' else 'FAILED','evidence':str(evidence),'log':str(log),'finished':time.time()}
      except Exception as ex:state['tasks'][key]={'status':'FAILED','error':str(ex),'log':str(log),'finished':time.time()}
      state['updated']=time.time();dump(statepath,state)
   generated={m:sum(read(RUN/m/'stories'/r['story']/'status.json').get('status')=='GENERATED' for r in rows) for m in ('videoclaw','codex_composition')}
   state['generated_stories']=generated;state['updated']=time.time();state['waiting_metrics']=[m for m,e in deployment.get('metrics',{}).items() if e['status']!='SMOKE_VERIFIED'];dump(statepath,state)
   target=len(rows)*2*len(deployment.get('metrics',{}))
   if sum(x.get('status') in ('SCORED','FAILED') for x in state['tasks'].values())==target and all(v==5 for v in generated.values()):state['status']='FINISHED';dump(statepath,state);return
   time.sleep(30)
 state['status']='TIME_LIMIT_REACHED';dump(statepath,state)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['videoclaw','codex','evaluate']);mode=parser.parse_args().mode
 RUN.mkdir(exist_ok=True);(RUN/'evaluation').mkdir(exist_ok=True)
 for name in ('videoclaw','codex_composition'):(RUN/name).mkdir(exist_ok=True)
 {'videoclaw':run_videoclaw,'codex':run_codex,'evaluate':evaluate}[mode]()
if __name__=='__main__':main()
