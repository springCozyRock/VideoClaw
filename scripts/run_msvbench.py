#!/usr/bin/env python3
"""Run one explicitly selected native MSVBench metric with Qwen transport."""
import argparse, contextlib, hashlib, importlib, io, json, os, re, subprocess, sys, math
from pathlib import Path
from msvbench_qwen import QwenAPI, ERRORS, dump
from msvbench_result_audit import audit_result
from msvbench_dns import install as install_dns_fallback
install_dns_fallback()
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT/'benchmarks/msvbench'
REGISTRY={
 'dover':('visual_quality','dover_scores'), 'musiq':('visual_quality','musiq_scores'),
 'visual_attribute_consistency':('visual_quality','brightness_contrast_variance'), 'style_consistency':('visual_quality','style_consistency'),
 'vqa':('story_alignment','vqa_scores'),'detection_count':('story_alignment','detection_scores'),
 'shot_perspective_alignment':('story_alignment','shot_perspective_alignment'),'state_shift_persistence':('story_alignment','state_shift_persistence'),
 'story_video_consistency':('story_alignment','story_video_consistency'),
 'face_consistency':('video_consistency','face_consistency'),'character_consistency':('video_consistency','character_consistency'),
 'background_consistency':('video_consistency','background_consistency'),'clothes_color_consistency':('video_consistency','clothes_color_consistency'),
 'relative_size_consistency':('video_consistency','relative_size_consistency'),
 'action_recognition':('motion_quality','action_recognition'),'action_strength':('motion_quality','action_strength'),
 'camera_control':('motion_quality','camera_control'),'physical_plausibility':('motion_quality','physical_plausibility'),
 'physical_interaction_accuracy':('motion_quality','physical_interaction_accuracy')}

def configure():
 sys.path[:0]=[str(REPO),str(REPO/'Tools')]+[str(REPO/'Metrics'/x) for x in ['VisualQuality','StoryVideoAlignment','VideoConsistency','MotionQuality']]
 original=importlib.import_module('Tools.gemini_api');original.GeminiAPI=QwenAPI;sys.modules['gemini_api']=original
 Base=importlib.import_module('MSVBench').MSVBenchEvaluator
 class QwenEvaluator(Base):
  def _load_gemini_keys_from_env(self):return ['qwen-transport-enabled']
 return QwenEvaluator

def source_hashes():
 files=list(REPO.rglob('*.py'))+list((ROOT/'scripts').glob('*msvbench*.py'))
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files)) if '__pycache__' not in p.parts}

def errors_in(obj):
 if isinstance(obj,float) and not math.isfinite(obj):return [('non_finite_score',str(obj))]
 if isinstance(obj,dict):
  return [(k,str(v)) for k,v in obj.items() if k in ('error','traceback') and v]+[x for v in obj.values() for x in errors_in(v)]
 if isinstance(obj,list):return [x for v in obj for x in errors_in(v)]
 return []

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--method',required=True);parser.add_argument('--story',required=True)
 parser.add_argument('--metric',required=True,choices=REGISTRY)
 parser.add_argument('--videos',type=Path);parser.add_argument('--prompt',type=Path);parser.add_argument('--script',type=Path)
 parser.add_argument('--camera',type=Path);parser.add_argument('--characters',type=Path)
 parser.add_argument('--output-root',type=Path,default=ROOT/'experiments/msvbench/evaluation')
 args=parser.parse_args()
 for value in (args.method,args.story):
  if not re.fullmatch(r'[A-Za-z0-9_.-]+',value) or value in ('.','..'):parser.error('Unsafe method/story identifier')
 cls=configure();evaluator=cls();paths=evaluator.get_input_paths(args.story,args.method)
 for k,v in [('prompt_path',args.prompt),('script_path',args.script),('camera_path',args.camera),('characters_dir',args.characters)]:
  if v is not None:
   if not v.exists():parser.error('Input not found: '+str(v))
   paths[k]=str(v.resolve())
 videos=args.videos.resolve() if args.videos else Path(evaluator.get_video_directory(args.method,args.story))
 files=sorted(p for p in videos.iterdir() if p.suffix.lower() in ('.mp4','.avi','.mov','.mkv','.m4v') and 'complete' not in p.name.lower())
 if not files:parser.error('No shot videos in '+str(videos))
 module,sub=REGISTRY[args.metric]
 if module in ('story_alignment','motion_quality') and args.metric!='action_strength' and not paths.get('prompt_path'):parser.error('This metric requires prompt text')
 if args.metric in ('shot_perspective_alignment','clothes_color_consistency','relative_size_consistency') and not paths.get('script_path'):parser.error('This metric requires a hierarchical script')
 if module in ('story_alignment','motion_quality') and args.metric!='action_strength':
  lines=[x for x in Path(paths['prompt_path']).read_text().splitlines() if x.strip()]
  if len(lines)!=len(files):parser.error('Prompt count must equal shot-video count; provide an explicit subset prompt for smoke tests')
 if args.metric=='camera_control' and len([x for x in Path(paths['camera_path']).read_text().splitlines() if x.strip()])!=len(files):parser.error('Camera instruction count must equal shot-video count')
 if any(not re.fullmatch(r'\d+', p.stem) for p in files):parser.error('Input videos must use numeric canonical shot names; temporary clips are not evaluation inputs')
 if args.metric in ('clothes_color_consistency','relative_size_consistency','shot_perspective_alignment','face_consistency','character_consistency'):
  script=json.loads(Path(paths['script_path']).read_text());count=sum(len(x.get('clips',[])) for x in script.get('script',[]))
  if count!=len(files):parser.error('Script clip count must equal shot-video count')
 if args.metric in ('clothes_color_consistency','relative_size_consistency','face_consistency','character_consistency'):
  if [p.stem for p in files]!=[str(i+1).zfill(2) for i in range(len(files))]:parser.error('Native consistency mapping requires sequential 01.mp4, 02.mp4, ... filenames')
 if args.metric in ('clothes_color_consistency','face_consistency','character_consistency','background_consistency') and len(files)<2:parser.error('Cross-shot clothing consistency requires at least two shot videos')
 out=args.output_root.resolve()/args.method/args.story/args.metric;out.mkdir(parents=True,exist_ok=True)
 import fcntl
 with (out/'run.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  provenance={'metric':args.metric,'module':module,'submetric':sub,'judge':'qwen3.5-omni-plus','official_judge':'gemini-2.5-flash','input_paths':paths,'videos':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files], 'input_file_hashes':{k:hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in paths.items() if Path(v).is_file()},'protocol':'Qwen transport; native rubrics/formulas; videos 1 fps JPEG max side 768; not an exact paper reproduction','upstream_commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),'adapter_sha256':hashlib.sha256((ROOT/'scripts/msvbench_qwen.py').read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'patch_sha256':hashlib.sha256(subprocess.check_output(['git','-C',str(REPO),'diff'])).hexdigest(),'source_file_hashes':source_hashes(),'kalm_attention':os.environ.get('MSVBENCH_KALM_ATTN','sdpa'),'reconstructed_interfaces':['GroundedSAM2Tracker','SimpleSlidingCaptioner','MonST3RProcessor'],'background_offload':True,'sharecaptioner_attention':os.environ.get('MSVBENCH_CAPTION_ATTN','flash_attention_2'),'model_sources':{str(p.relative_to(ROOT)):json.loads(p.read_text()) for p in sorted((ROOT/'configs/msvbench/downloads').glob('*.json'))},'reference_image_hashes':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for v in paths.values() if Path(v).is_dir() for f in sorted(Path(v).rglob('*')) if f.is_file() and f.suffix.lower() in ('.png','.jpg','.jpeg')}}
  provenance['result_audit']='Separate native scores, execution errors and comparison diagnostics; native aggregation unchanged'
  provenance['input_isolation']='Per-metric shot symlinks; native concatenations never enter source shot directory'
  current_hash=hashlib.sha256(json.dumps(provenance,sort_keys=True).encode()).hexdigest()
  statusfile=out/'status.json'
  if statusfile.exists():
   prior=json.loads(statusfile.read_text())
   if prior.get('input_protocol_sha256')==current_hash and prior.get('status')=='SCORED':print('Already scored:',out);return
   if prior.get('input_protocol_sha256')!=current_hash:raise RuntimeError('Inputs/protocol changed: choose a new --output-root to preserve prior evidence')
  dump(out/'protocol.json',provenance);os.environ['MSVBENCH_AUDIT_DIR']=str(out/'judge_calls')
  staged=out/'shot_inputs';staged.mkdir(exist_ok=True)
  for source in files:
   link=staged/source.name
   if not link.exists():link.symlink_to(source)
   elif not link.is_symlink() or link.resolve()!=source:raise RuntimeError('Unexpected staged input: '+str(link))
  evaluator.results_dir=str(out/'native');evaluator.get_video_directory=lambda *a:str(staged);evaluator.get_input_paths=lambda *a:paths
  capture=io.StringIO();result={};exception=None
  with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
   try:result=evaluator.evaluate_single_case(args.method,args.story,modules=[module],submetrics={module:[sub]})
   except Exception as ex:exception=str(ex)
  log=capture.getvalue();(out/'run.log').write_text(log,encoding='utf-8')
  script_data=json.loads(Path(paths['script_path']).read_text()) if paths.get('script_path') else None
  audit=audit_result(result,log,script_data,ERRORS,exception)
  status=audit['status'];issues=audit['issues']
  dump(statusfile,dict(audit,input_protocol_sha256=current_hash,metric=args.metric,native_result=result))
  print(status, args.metric, out)
  if issues:print(json.dumps(issues,ensure_ascii=False)[:2000])
  if status=='FAILED':raise SystemExit(1)

if __name__=='__main__':main()
