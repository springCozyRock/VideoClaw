#!/usr/bin/env python3
"""Prepare two isolated, auditable five-story MSVBench runs. No paid calls."""
import json,hashlib,shutil,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'experiments/msvbench_agents_20261018'
CFG=ROOT/'configs/msvbench_agents_20261018'
BASE=ROOT/'baselines/codex/msvbench_composition'
IDS=['01','02','08','09','14']
DATA=ROOT/'benchmarks/msvbench/Dataset'
def dump(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if (CFG/'manifest.json').exists():print('Already prepared:',RUN);return
 RUN.mkdir(parents=True,exist_ok=True);CFG.mkdir(parents=True,exist_ok=True);BASE.mkdir(parents=True,exist_ok=True)
 original=ROOT/'baselines/codex/composition';oldcfg=ROOT/'configs/codex_composition_wan3'
 for name in ['common.py','tools.py','codex_provider.py']:
  text=(original/name).read_text(encoding='utf-8')
  if name=='common.py':
   text=text.replace("PROJECT / 'baselines/codex/composition'", "PROJECT / 'baselines/codex/msvbench_composition'")
   text=text.replace("PROJECT / 'configs/codex_composition_wan3'", "PROJECT / 'configs/msvbench_agents_20261018/codex'")
   text=text.replace("PROJECT / 'experiments/codex_composition_wan3_720p'", "PROJECT / 'experiments/msvbench_agents_20261018/codex_composition'")
  (BASE/name).write_text(text,encoding='utf-8')
  (BASE/name).chmod(0o755)
 codexcfg=CFG/'codex';codexcfg.mkdir(exist_ok=True)
 config=json.loads((oldcfg/'experiment.json').read_text())
 config.update(codex_bin=str(BASE/'codex_provider.py'),cases=IDS,image_model='wan2.7-image',max_concurrency=2,timeout_seconds=86400,
               protocol_variant='MSVBench five-story input; agent chooses durations; frozen narrative Composition Skill; no memory/evolution')
 dump(codexcfg/'experiment.json',config)
 provider=json.loads((oldcfg/'agent_provider.json').read_text());provider['catalog']=str(codexcfg/'qwen_model_catalog.json')
 dump(codexcfg/'agent_provider.json',provider);shutil.copy2(oldcfg/'qwen_model_catalog.json',codexcfg/'qwen_model_catalog.json')
 shutil.copytree(oldcfg/'foundation_skills',codexcfg/'foundation_skills',dirs_exist_ok=True)
 for p in (codexcfg/'foundation_skills').rglob('*'):
  if p.is_file() and p.suffix in ('.md','.py','.sh'):
   text=p.read_text(encoding='utf-8');p.write_text(text.replace(str(original),str(BASE)),encoding='utf-8')
 src=oldcfg/'frozen_composition/skills/lvm-narrative-wan3';dest=codexcfg/'frozen_composition/skills/lvm-narrative-wan3'
 shutil.copytree(src,dest,dirs_exist_ok=True)
 rows=[]
 for sid in IDS:
  folder=RUN/'inputs'/sid;folder.mkdir(parents=True,exist_ok=True)
  for kind,suffix in [('script','.json'),('prompt','.txt'),('camera','.txt')]:shutil.copy2(DATA/kind/(sid+suffix),folder/(kind+suffix))
  script=json.loads((folder/'script.json').read_text());clips=[c for scene in script['script'] for c in scene['clips']]
  refs=[]
  for char in script['characters']:
   sources=sorted(p for p in (DATA/'characters'/sid/char['name'].replace(' ','_')).glob('*') if p.suffix.lower() in ('.jpg','.png','.jpeg'))
   if not sources:raise RuntimeError('Missing character reference: '+char['name'])
   target=folder/'character_inputs'/('char_'+str(char['id'])+sources[0].suffix)
   target.parent.mkdir(exist_ok=True);shutil.copy2(sources[0],target)
   refs.append({'id':str(char['id']),'name':char['name'],'path':str(target),'sha256':sha(target),'source':str(sources[0])})
  row={'story':sid,'shots':len(clips),'script':str(folder/'script.json'),'prompt':str(folder/'prompt.txt'),'camera':str(folder/'camera.txt'),
       'evaluation_characters':str(DATA/'characters'/sid),'character_inputs':refs,'source_hashes':{p.name:sha(p) for p in folder.iterdir() if p.is_file()}}
  rows.append(row)
  task=RUN/'codex_composition/dataset/narrative'/sid;task.mkdir(parents=True,exist_ok=True)
  dump(task/'source.json',{'benchmark':'MSVBench','story':sid,'original_script':script,'camera_instructions':(folder/'camera.txt').read_text(),'references':refs})
  requirement=f'''Generate one complete multi-shot story for MSVBench story {sid} using the frozen lvm-narrative-wan3 skill and actual foundation tools.
User explicitly chose that each system independently plans its own durations. NO fixed five-second shot requirement. Choose sensible integer durations from story actions/dialogue within actual tool limits. Set your own target total duration from that plan and verify the result. Preserve the given story and the order and coverage of its {len(clips)} canonical shots. Do not invent a replacement story.
Original full hierarchical script: {folder/'script.json'}
Original shot prompts (one line per canonical shot): {folder/'prompt.txt'}
Original camera instructions (one line per shot): {folder/'camera.txt'}
Official character conditioning images: {json.dumps(refs,ensure_ascii=False)}
These are public benchmark inputs. Inspect all supplied character references and preserve the corresponding identities. Use the relevant character references when those characters appear; you are not required to include every character reference in every shot. Shot reference images are NOT supplied for conditioning. Decide whether additional environment references are needed according to the composition skill and the current task; if needed, use the configured image tool. Keep original dialogue meaning/language. Make 720P 16:9 video with audio, using wan2.7-image and wan3.0-video. Follow the selected composition skill. If a paid submission has an unknown outcome, stop and reconcile that task; never duplicate-submit.
Use the original canonical shot IDs to record precise evaluation boundaries. Choose how to group canonical shots into generated segments according to the composition skill and the current task. Export the actual segment offsets for every canonical shot, including when multiple canonical shots share a generated segment. Segmentation for evaluation must derive from your actual plan, not invented labels.
Deliver final.mp4, plan.json, observations.md and evaluation_manifest.json in the task output directory. evaluation_manifest.json must have schema {{"story":"{sid}","final_video":"absolute path", "shots":[{{"official_shot_index":1,"path":"absolute generated clip path","start_sec":0.0,"end_sec":YOUR_ACTUAL_SHOT_END,"description":"original required shot content"}}]}} with exactly {len(clips)} entries in canonical order. Entries may point at the same generated segment only when their non-overlapping offsets identify different shots. Record ALL actual media paths and measurements, never placeholder scores. Do not read old pilot outputs/other cases, do not evolve skills or use memory, do not install packages or delegate. Current inputs are already a complete story, so do not rewrite the plot.
'''
  (task/'requirements.txt').write_text(requirement,encoding='utf-8')
 dump(RUN/'codex_composition/dataset/narrative/skill_query.json',{'skill_name':'lvm-narrative-wan3','skill_query':'Reuse the frozen narrative skill for the supplied MSVBench stories; no skill creation/evolution.'})
 manifest={'created':'2026-10-18','stories':rows,'total_canonical_shots':sum(r['shots'] for r in rows),'methods':['videoclaw','codex_composition'],
 'generation':{'image':'wan2.7-image','video':'wan3.0-video','resolution':'720P','ratio':'16:9','duration':'Each system plans independently; no fixed5s rule','judge':'qwen3.5-omni-plus','codex_agent':'qwen3.8-max-0902'},
 'protocol':'Same five public official stories and character reference inputs. Reference-conditioned adaptation; Qwen judge and reconstructed evaluation interfaces recorded. Not original Gemini leaderboard protocol.',
 'original_frozen_skill_hashes':{str(p.relative_to(src)):sha(p) for p in src.rglob('*') if p.is_file()},
 'skill_source':str(src),'new_adapter':str(BASE),'run':str(RUN)}
 dump(CFG/'manifest.json',manifest);dump(RUN/'manifest.json',manifest)
 dump(codexcfg/'frozen_composition/reuse_lock.json',{'source':str(src),'composition_hashes':manifest['original_frozen_skill_hashes'],'input_manifest_sha256':sha(CFG/'manifest.json'),'skill_changed':False,'foundation_changes':'Only tool command paths changed to isolated adapter','model_settings':manifest['generation']})
 print(json.dumps({'prepared':str(RUN),'stories':IDS,'shots':manifest['total_canonical_shots'],'paid_calls':0},ensure_ascii=False))
if __name__=='__main__':main()
