#!/usr/bin/env python3
"""Versioned public DirectorBench preparation, audit, video binding and evaluation."""
from __future__ import annotations
import argparse, ast, copy, hashlib, importlib, importlib.metadata, json, math, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'benchmarks/directorbench_public'
DATA=ROOT/'datasets/directorbench_public'
CONFIG=ROOT/'configs/directorbench_public'
COMMIT='63174ef2a00df2ae839d74a9af7f91883c790f8b'
SPLITS={'original':'dataset_original.jsonl','cross_lingual':'dataset_cross_lingual.jsonl','multilingual':'dataset_multilingual.jsonl'}
TYPE_MAP={'叙事/故事类':'narrative','电影镜头类':'cinematic','科幻类（反规律）':'sci_fi','动作类':'action','日常生活（vlog）':'vlog','商业营销':'commercial','教育新闻':'educational','音乐类':'music'}
WEIGHTS=('text_story_arc','visual_camera','audio_emotion','cross_modal_sync')

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def objhash(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def dump(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_name(p.name+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(p)
def jsonl(path,rows):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
def load(path):return json.loads(Path(path).read_text())
def rel(path):return str(Path(path).resolve().relative_to(ROOT))
def public_imports():
 existing=sys.modules.get('directorbench')
 if existing and SOURCE.resolve() not in Path(existing.__file__).resolve().parents:raise RuntimeError('Legacy DirectorBench already imported; use a clean process')
 sys.path.insert(0,str(SOURCE))
 import directorbench
 if SOURCE.resolve() not in Path(directorbench.__file__).resolve().parents:raise RuntimeError('Wrong DirectorBench import path')
 return directorbench

def parse_objects(text):
 """Accept JSON, JSONL or public pretty-printed comma-separated objects; reject corruption."""
 dec=json.JSONDecoder();pos=0;rows=[]
 while True:
  while pos<len(text) and text[pos].isspace():pos+=1
  if pos==len(text):break
  if rows and text[pos]==',':
   pos+=1
   while pos<len(text) and text[pos].isspace():pos+=1
   if pos==len(text):raise ValueError('Dangling separator after final JSON object')
  obj,pos=dec.raw_decode(text,pos)
  if isinstance(obj,list):
   if rows or text[pos:].strip():raise ValueError('JSON array must be the sole top-level value')
   rows=obj;break
  if not isinstance(obj,dict):raise ValueError('Expected top-level JSON object')
  rows.append(obj)
 if any(not isinstance(x,dict) for x in rows):raise ValueError('All records must be objects')
 return rows

def normalize_profile(raw):
 p=copy.deepcopy(raw);changes=[];taste=p['personalization']['user_taste']
 if 'lip_sync' in taste:
  aliases={'must':True,'required':True,'true':True,'false':False,'optional':None}
  val=aliases.get(str(taste['lip_sync']).lower(),'UNKNOWN')
  if val=='UNKNOWN':raise ValueError('Unsupported lip_sync alias')
  if 'wants_lip_sync' in taste and taste['wants_lip_sync']!=val:raise ValueError('Conflicting lip sync preference')
  taste['wants_lip_sync']=val
  changes.append({'path':'personalization.user_taste.wants_lip_sync','source':'lip_sync','source_value':taste['lip_sync'],'value':val})
 w=p['personalization']['priority_weights']
 if set(w)!=set(WEIGHTS) or any(not isinstance(v,(int,float)) or v<0 for v in w.values()) or not math.isclose(sum(w.values()),1,abs_tol=1e-8):raise ValueError('Invalid priority weights')
 return p,changes

def build_case(split,row,ordinal,source_path):
 for key in ('meta_id','sample_id','variant_id','main_instruction','duration_sec','modality_details'):
  if key not in row:raise ValueError(f'{split} record {ordinal}: missing {key}')
 variant=row['variant_id'];base=row['sample_id']
 for v in (variant,base):
  if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',v) or v in ('.','..'):raise ValueError('Unsafe case identifier')
 duration=float(row['duration_sec']) if row['duration_sec'] is not None else None
 if duration is not None and (not math.isfinite(duration) or duration<=0):raise ValueError('Non-positive target duration')
 details=row['modality_details']
 if not isinstance(details,dict) or any(x not in details for x in ('text','visual','audio')):raise ValueError('Missing modality specifications')
 scripts=details['text'].get('script',[]);visuals=details['visual'].get('shots',[])
 if not isinstance(scripts,list) or not isinstance(visuals,list):raise ValueError('Shot annotations must be arrays')
 for entries in (scripts,visuals):
  ids=[str(x['shot_id']) for x in entries]
  if len(ids)!=len(set(ids)):raise ValueError('Repeated shot_id in one modality')
 known_durations=[float(x['duration_sec']) for x in scripts if x.get('duration_sec') is not None]
 annotated=sum(known_durations) if len(known_durations)==len(scripts) else None
 warnings=[]
 if duration is None:warnings.append('TARGET_DURATION_NOT_PUBLISHED')
 if annotated is None:warnings.append('SCRIPT_SHOT_DURATIONS_INCOMPLETE')
 if not scripts:warnings.append('NO_PUBLISHED_SCRIPT_SNIPPETS')
 if duration is not None and annotated is not None and not math.isclose(annotated,duration,abs_tol=.1):warnings.append('SCRIPT_DURATION_DIFFERS_FROM_TARGET')
 if {str(x['shot_id']) for x in scripts}!={str(x['shot_id']) for x in visuals}:warnings.append('TEXT_VISUAL_SHOT_IDS_DIFFER')
 canonical=TYPE_MAP.get(row.get('video_type'),row.get('video_type'))
 if canonical not in set(TYPE_MAP.values()):raise ValueError('Unknown video_type '+str(row.get('video_type')))
 key=split+'/'+variant;folder=DATA/'cases'/key
 dump(folder/'metadata.json',row)
 prompt=row['main_instruction']+'\n\nObjective task specification (published metadata, including any partial script annotations):\n'+json.dumps({'duration_sec':row['duration_sec'],'video_type':canonical,'modality_details':details},ensure_ascii=False,indent=2)+'\n'
 (folder/'evaluation_prompt.txt').write_text(prompt)
 (folder/'reference_snippets.txt').write_text(json.dumps(details['text'],ensure_ascii=False,indent=2)+'\n')
 # Preserve published per-shot annotations; do not invent missing shots or rebalance durations.
 storyboard=[]
 lookup={str(x['shot_id']):x for x in scripts}
 for shot in visuals:
  combined=copy.deepcopy(lookup.get(str(shot['shot_id']),{}));combined.update(copy.deepcopy(shot));storyboard.append(combined)
 dump(folder/'published_storyboard.json',storyboard)
 entry={'case_key':key,'split':split,'variant_id':variant,'sample_id':base,'base_case_key':'original/'+base,'meta_id':row['meta_id'],'canonical_video_type':canonical,'instruction_language':row.get('instruction_lang',row.get('language')),'content_language':row.get('content_lang_resolved',row.get('content_lang',details['audio'].get('multi_language'))),'target_duration_sec':duration,'published_script_duration_sec':annotated,'published_script_shots':len(scripts),'published_visual_shots':len(visuals),'annotation_warnings':warnings,'metadata_path':rel(folder/'metadata.json'),'prompt_path':rel(folder/'evaluation_prompt.txt'),'reference_snippets_path':rel(folder/'reference_snippets.txt'),'storyboard_path':rel(folder/'published_storyboard.json'),'source':{'path':rel(source_path),'record_ordinal_1based':ordinal,'record_sha256':objhash(row)}}
 entry['input_hashes']={name:digest(ROOT/entry[name]) for name in ('metadata_path','prompt_path','reference_snippets_path','storyboard_path')}
 return entry

def code_identity():
 commit=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
 if commit!=COMMIT:raise RuntimeError('Unexpected official commit '+commit)
 status=subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain','--untracked-files=no'],text=True).strip()
 if status:raise RuntimeError('Official tracked source has local changes: '+status)
 return commit

def prepare():
 code_identity();public_imports()
 from directorbench.schemas import UserProfile,UserTaste
 from directorbench.checkpoints import CHECKPOINTS
 DATA.mkdir(parents=True,exist_ok=True);CONFIG.mkdir(parents=True,exist_ok=True)
 raw_paths={}
 sources=[('profiles.jsonl',SOURCE/'data/profiles.jsonl')]+[(filename,SOURCE/'data/metadata'/filename) for filename in SPLITS.values()]
 for name,src in sources:
  target=DATA/'raw'/name;target.parent.mkdir(parents=True,exist_ok=True)
  if target.exists() and digest(target)!=digest(src):raise RuntimeError('Raw snapshot changed; create a new version instead of overwriting')
  if not target.exists():shutil.copy2(src,target)
  raw_paths[rel(target)]=digest(src)
 raw_profiles=parse_objects((DATA/'raw/profiles.jsonl').read_text());profiles=[];aliases=[]
 for raw in raw_profiles:
  profile,changes=normalize_profile(raw);model=UserProfile.from_profile_dict(profile)
  unknown=set(profile['personalization']['user_taste'])-set(UserTaste.model_fields)-{'lip_sync'}
  if unknown:raise ValueError('Unmapped public preference fields: '+str(unknown))
  profiles.append(profile)
  if changes:aliases.append({'profile_id':profile['profile_id'],'changes':changes})
 if len({p['profile_id'] for p in profiles})!=len(profiles):raise ValueError('Duplicate profile IDs')
 jsonl(DATA/'normalized/profiles.jsonl',profiles)
 all_cases=[];counts={}
 for split,name in SPLITS.items():
  rows=parse_objects((DATA/'raw'/name).read_text());entries=[]
  for i,row in enumerate(rows,1):entries.append(build_case(split,row,i,DATA/'raw'/name))
  if len({x['case_key'] for x in entries})!=len(entries):raise ValueError('Repeated variant ID within '+split)
  jsonl(DATA/'normalized'/(split+'.jsonl'),rows);counts[split]=len(rows);all_cases.extend(entries)
 originals={x['sample_id']:x for x in all_cases if x['split']=='original'}
 for x in all_cases:
  base=originals.get(x['sample_id'])
  if base is None or base['meta_id']!=x['meta_id']:raise ValueError('Variant-to-original identity mismatch: '+x['case_key'])
 jsonl(DATA/'index.jsonl',all_cases)
 registry={k:[x.model_dump(mode='json') for x in v] for k,v in CHECKPOINTS.items()}
 metric_names=set()
 for p in (SOURCE/'directorbench/agents').glob('*.py'):
  for node in ast.walk(ast.parse(p.read_text())):
   if isinstance(node,ast.keyword) and node.arg=='metric_name' and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):metric_names.add(node.value.value)
 dump(CONFIG/'checkpoint_registry.json',{'upstream_commit':COMMIT,'registered_metrics':registry,'registered_metric_count':len(registry),'checkpoint_count':sum(map(len,registry.values())),'additional_code_metrics':sorted(metric_names-set(registry)),'excluded_by_project_policy':['bgm_consistency'],'excluded_checkpoint_ids':[x.id for x in CHECKPOINTS['bgm_consistency']]})
 protocol={'id':'directorbench_public_63174ef_qwen35_no_bgm_v1','upstream_commit':COMMIT,'judge':'qwen3.5-omni-plus','reference_mode_default':'reference-free','BGM':'SKIPPED_BY_USER; original data/weights/registry preserved; native remaining aggregation','personalized_generation_prompts':'Not supplied by this release; no synthetic LLM-generated replacements created','evaluation_prompt':'Published main_instruction plus verbatim modality requirements; generation prompt must be recorded separately when binding a video','profile_transformations':aliases,'paper_vs_release':{'paper_task_count':80,'published_original_count':counts['original'],'registered_checkpoint_metrics':len(registry),'registered_checkpoints':sum(map(len,registry.values())),'README_metric_count':14,'code_additional_metrics':sorted(metric_names-set(registry)),'stability_aggregation':'Native implementation uses visual_camera weight for both video and stability'},'fallback_policy':'Persist native results with explicit degraded/failed validity; no claim of full protocol coverage when tools fail','historical_results':'Separate legacy modified code and experiments; not imported or re-scored'}
 dump(CONFIG/'protocol.json',protocol)
 template=CONFIG/'video_manifest.template.jsonl'
 jsonl(template,[{'method':'default','case_key':x['case_key'],'video_path':None,'video_sha256':None,'generated_with_profile':None,'generation_prompt_file':None} for x in all_cases])
 normalized_files={rel(p):digest(p) for p in (DATA/'normalized').glob('*.jsonl')}
 manifest={'version':1,'prepared_at':datetime.now(timezone.utc).isoformat(),'source':str(SOURCE),'commit':COMMIT,'raw_sha256':raw_paths,'normalized_sha256':normalized_files,'index_sha256':digest(DATA/'index.jsonl'),'protocol_sha256':digest(CONFIG/'protocol.json'),'registry_sha256':digest(CONFIG/'checkpoint_registry.json'),'counts':counts,'total_variants':len(all_cases),'profiles':len(profiles),'evaluation_pairs':len(all_cases)*len(profiles),'warnings':{'target_duration_missing':sum('TARGET_DURATION_NOT_PUBLISHED' in x['annotation_warnings'] for x in all_cases),'script_durations_incomplete':sum('SCRIPT_SHOT_DURATIONS_INCOMPLETE' in x['annotation_warnings'] for x in all_cases),'script_duration_differs':sum('SCRIPT_DURATION_DIFFERS_FROM_TARGET' in x['annotation_warnings'] for x in all_cases),'text_visual_shot_ids_differ':sum('TEXT_VISUAL_SHOT_IDS_DIFFER' in x['annotation_warnings'] for x in all_cases)},'data_status':'ALIGNED_PUBLIC_RELEASE','video_status':'NOT_GENERATED; explicit bindings required'}
 dump(CONFIG/'manifest.json',manifest)
 print(json.dumps({'status':'PREPARED','counts':counts,'profiles':len(profiles),'variants':len(all_cases),'pairs':manifest['evaluation_pairs'],'annotation_warnings':manifest['warnings']},ensure_ascii=False))
 return manifest

def cases():return {x['case_key']:x for x in parse_objects((DATA/'index.jsonl').read_text())}
def profiles():return {x['profile_id']:x for x in parse_objects((DATA/'normalized/profiles.jsonl').read_text())}
def verify_files():
 m=load(CONFIG/'manifest.json');code_identity();public_imports()
 for mapping in ('raw_sha256','normalized_sha256'):
  for name,want in m[mapping].items():
   if digest(ROOT/name)!=want:raise RuntimeError('Data hash changed: '+name)
 for p,key in [(DATA/'index.jsonl','index_sha256'),(CONFIG/'protocol.json','protocol_sha256'),(CONFIG/'checkpoint_registry.json','registry_sha256')]:
  if digest(p)!=m[key]:raise RuntimeError('Manifest hash changed: '+str(p))
 for entry in cases().values():
  for name,want in entry['input_hashes'].items():
   if digest(ROOT/entry[name])!=want:raise RuntimeError('Case artifact changed: '+entry['case_key']+'/'+name)
 return m

def audit():
 m=verify_files();public_imports()
 from directorbench.schemas import UserProfile
 from directorbench.graph import create_initial_state
 # All 2,996 public variant/profile combinations must round-trip into native input state.
 total=0
 for entry in cases().values():
  prompt=(ROOT/entry['prompt_path']).read_text()
  for raw in profiles().values():
   state=create_initial_state(video_path='/NOT_GENERATED/'+entry['case_key']+'.mp4',user_prompt=prompt,user_profile=raw)
   assert state.user_profile.profile_id==raw['profile_id']
   assert state.user_profile.priority_weights.model_dump()==raw['personalization']['priority_weights']
   assert state.script_text=='' and state.storyboard is None
   assert load(ROOT/entry['metadata_path'])['main_instruction'] in state.user_prompt
   total+=1
 report={'status':'PASS','upstream_commit':COMMIT,'native_input_pairs_validated':total,'counts':m['counts'],'profiles':m['profiles'],'registry':{'metrics':9,'checkpoints':40},'no_api_calls':True,'no_video_generation':True,'annotation_warnings':m['warnings'],'source_module':str(SOURCE/'directorbench/__init__.py')}
 dump(CONFIG/'alignment_audit.json',report);print(json.dumps(report,ensure_ascii=False))
 return report

def bindings():
 p=CONFIG/'video_bindings.json'
 return load(p) if p.exists() else {}
def bind(args):
 verify_files();entry=cases()[args.case];video=args.video.resolve();method=getattr(args,'method','default')
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',method) or method in ('.','..'):raise ValueError('Unsafe method identifier')
 binding_key=method+'::'+args.case
 if not video.is_file():raise FileNotFoundError(video)
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(video)],text=True))
 if not any(s.get('codec_type')=='video' for s in probe.get('streams',[])):raise ValueError('No video stream')
 pids=profiles()
 if args.generation_profile is not None and args.generation_profile not in pids:raise ValueError('Unknown generation profile')
 row={'method':method,'case_key':entry['case_key'],'video_path':str(video),'video_sha256':digest(video),'target_duration_sec':entry['target_duration_sec'],'actual_duration_sec':float(probe['format']['duration']),'generated_with_profile':args.generation_profile,'generation_prompt_file':str(args.generation_prompt.resolve()) if args.generation_prompt else None,'generation_prompt_sha256':digest(args.generation_prompt) if args.generation_prompt else None,'bound_at':datetime.now(timezone.utc).isoformat()}
 import fcntl
 with (CONFIG/'bindings.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);rows=bindings()
  if binding_key in rows and {k:v for k,v in rows[binding_key].items() if k!='bound_at'}!={k:v for k,v in row.items() if k!='bound_at'}:raise RuntimeError('Binding exists with different video/provenance; preserve it and use a separate evaluation version')
  rows.setdefault(binding_key,row);dump(CONFIG/'video_bindings.json',rows)
 print(json.dumps(row,ensure_ascii=False))

def plan(args):
 verify_files();entry=cases()[args.case];profile=profiles()[args.profile];method=getattr(args,'method','default')
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',method) or method in ('.','..'):raise ValueError('Unsafe method identifier')
 binding=bindings().get(method+'::'+args.case)
 if binding:
  if digest(binding['video_path'])!=binding['video_sha256']:raise RuntimeError('Bound video changed')
  if binding.get('generation_prompt_file') and digest(binding['generation_prompt_file'])!=binding['generation_prompt_sha256']:raise RuntimeError('Generation prompt changed')
 reference=args.reference_mode
 item={'method':method,'status':'READY_FOR_RUNTIME_PREFLIGHT' if binding else 'WAITING_FOR_VIDEO','case':entry,'profile':profile,'video_binding':binding,'reference_mode':reference,'user_prompt_path':str(ROOT/entry['prompt_path']),'script_text_path':str(ROOT/entry['reference_snippets_path']) if reference=='published-reference' else None,'storyboard_path':str(ROOT/entry['storyboard_path']) if reference=='published-reference' else None,'protocol':load(CONFIG/'protocol.json'),'no_api_calls':True}
 if args.command!='run':print(json.dumps(item,ensure_ascii=False,indent=2))
 return item

def execute(args):
 item=plan(args)
 if not args.execute:print(json.dumps(item,ensure_ascii=False,indent=2));return
 if not item['video_binding']:raise RuntimeError('Bind a generated video first; this command does not generate videos')
 from directorbench_public_provider import install_provider
 public_imports();from directorbench.config import EvalConfig
 from directorbench.graph import build_eval_graph,create_initial_state
 from directorbench.main import _append_tool_trace
 from directorbench.report import ReportWriter
 config=EvalConfig();config.llm.model=config.vlm.model='qwen3.5-omni-plus';config.preprocess.separate_audio_tracks=False
 provenance={k:v for k,v in item.items() if k not in ('status','no_api_calls')}
 runtime=runtime_preflight();provenance['runtime_environment']=runtime
 provenance['eval_config']=config.model_dump(exclude={'llm':{'api_key'},'vlm':{'api_key'}})
 provenance['adapter_sha256']=digest(Path(__file__).with_name('directorbench_public_provider.py'))
 provenance['runner_sha256']=digest(__file__)
 runtime_digest=objhash(provenance);folder=ROOT/'experiments/directorbench_public/evaluation'/item['method']/args.case/f'profile_{args.profile:02d}'/runtime_digest[:16]
 folder.mkdir(parents=True,exist_ok=True)
 import fcntl,logging
 with (folder/'run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if (folder/'result.json').exists():print('Existing result; preserved:',folder);return
  dump(folder/'provenance.json',provenance)
  adapter=install_provider(ROOT,folder,config)
  from directorbench.agents.audio_agent import AudioEvalAgent
  AudioEvalAgent._eval_bgm=lambda self,state:None  # existing user BGM exclusion, source untouched
  logging.basicConfig(filename=str(folder/'eval_debug.log'),level=logging.INFO)
  entry=item['case'];state=create_initial_state(video_path=item['video_binding']['video_path'],user_prompt=(ROOT/entry['prompt_path']).read_text(),script_text=Path(item['script_text_path']).read_text() if item['script_text_path'] else '',storyboard=load(item['storyboard_path']) if item['storyboard_path'] else None,user_profile=item['profile'])
  try:
   final=build_eval_graph(config).invoke(state);report=final.get('diagnosis')
   if report is None:raise RuntimeError('No diagnosis produced')
   tools=[x.model_dump(mode='json') if hasattr(x,'model_dump') else x for x in final.get('tool_context',[])]
   failures=final.get('errors',[])+adapter.errors
   degraded=[x for x in tools if x.get('status') in ('failed','fallback')]
   status='FAILED' if failures else 'COMPLETED_WITH_LIMITATIONS' if degraded or entry['annotation_warnings'] or report.needs_human_review else 'COMPLETED'
   writer=ReportWriter(output_dir=str(folder));writer.append(report,video_path=state.video_path,user_prompt=state.user_prompt,script_text=state.script_text,storyboard=state.storyboard,user_profile=state.user_profile)
   _append_tool_trace(str(folder),report.report_id,state.video_path,final)
   dump(folder/'result.json',{'status':status,'protocol_id':item['protocol']['id'],'runtime_sha256':runtime_digest,'errors':failures,'degraded_tools':degraded,'annotation_warnings':entry['annotation_warnings'],'excluded_metrics':['bgm_consistency'],'report':report.model_dump(mode='json')})
   print(status,folder)
   if failures:raise SystemExit(1)
  except Exception as ex:
   dump(folder/'failure.json',{'status':'FAILED','error':adapter.redact(str(ex))});raise

def runtime_preflight():
 verify_files()
 import importlib.util
 modules=['pydantic','openai','langgraph','langchain_core','requests','cv2','numpy','torch','sentence_transformers','scenedetect']
 distributions={'cv2':'opencv-contrib-python','sentence_transformers':'sentence-transformers','langchain_core':'langchain-core','scenedetect':'scenedetect'}
 dependencies={}
 for name in modules:
  spec=importlib.util.find_spec(name)
  try:version=importlib.metadata.version(distributions.get(name,name))
  except importlib.metadata.PackageNotFoundError:version=None
  dependencies[name]={'available':spec is not None,'version':version,'module_origin':spec.origin if spec else None}
 hub=Path('/mnt/data/bts/models/hf/hub/models--sentence-transformers--all-MiniLM-L6-v2')
 snapshot=hub/'snapshots'/(hub/'refs/main').read_text().strip() if (hub/'refs/main').exists() else None
 assets={'whisper_large_v3':{'path':str(ROOT/'.cache/faster-whisper-large-v3'),'ready':(ROOT/'.cache/faster-whisper-large-v3/model.bin').is_file()},'sentence_bert':{'path':str(snapshot) if snapshot else None,'ready':bool(snapshot and (snapshot/'config.json').is_file())},'mobileviclip_repo':{'path':str(ROOT/'third_party/mobileviclip'),'ready':(ROOT/'third_party/mobileviclip').is_dir()},'mobileviclip_weights':{'path':str(ROOT/'.cache/directorbench_public/models/mobileviclip_small.pt'),'ready':(ROOT/'.cache/directorbench_public/models/mobileviclip_small.pt').is_file()}}
 tools={name:shutil.which(name) for name in ('ffmpeg','ffprobe')}
 report={'status':'CODE_DATA_ALIGNED','python':sys.version,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'source_module':str(SOURCE/'directorbench/__init__.py'),'dependencies':dependencies,'tools':tools,'assets':assets,'all_optional_models_ready':all(x['ready'] for x in assets.values()),'no_api_calls':True,'no_actual_metric_inference':True}
 dump(CONFIG/'runtime_preflight.json',report);dump(CONFIG/'environment.json',{'python':report['python'],'prefix':report['prefix'],'base_prefix':report['base_prefix'],'dependencies':dependencies,'shared_dependency_path':'/mnt/data/bts/envs/directorbench/lib/python3.10/site-packages'})
 print(json.dumps(report,ensure_ascii=False,indent=2));return report

def main():
 p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
 for c in ('prepare','audit','status','list','preflight'):subs.add_parser(c)
 bindp=subs.add_parser('bind');bindp.add_argument('--case',required=True);bindp.add_argument('--method',default='default');bindp.add_argument('--video',type=Path,required=True);bindp.add_argument('--generation-profile',type=int);bindp.add_argument('--generation-prompt',type=Path)
 for c in ('plan','run'):
  sub=subs.add_parser(c);sub.add_argument('--case',required=True);sub.add_argument('--method',default='default');sub.add_argument('--profile',type=int,required=True);sub.add_argument('--reference-mode',choices=['reference-free','published-reference'],default='reference-free')
  if c=='run':sub.add_argument('--execute',action='store_true',help='Actually call paid Qwen evaluation; omitted means dry-run')
 a=p.parse_args()
 if a.command=='prepare':prepare()
 elif a.command=='audit':audit()
 elif a.command=='preflight':runtime_preflight()
 elif a.command=='status':
  m=verify_files();print(json.dumps({'status':'ALIGNED','manifest':m,'bound_videos':len(bindings()),'audit':load(CONFIG/'alignment_audit.json') if (CONFIG/'alignment_audit.json').exists() else None},ensure_ascii=False,indent=2))
 elif a.command=='list':
  for x in cases().values():print(x['case_key'],x['meta_id'],x['canonical_video_type'],x['target_duration_sec'])
 elif a.command=='bind':bind(a)
 elif a.command=='plan':plan(a)
 else:execute(a)
if __name__=='__main__':main()
