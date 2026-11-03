"""Anonymous randomized empty forms; never create simulated human ratings."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import csv,hashlib,html,json,os,random,shutil
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CONFIG_ROOT, INPUT_ROOT, load_json
ROOT = BASELINE_ROOT;RUN = RUN_ROOT;OUT=RUN/'human_annotation'
DIRECTOR=['character_consistency','scene_consistency','object_consistency','voice_consistency','style_consistency','character_setting_plausibility','scene_plausibility','voice_plausibility','instruction_following','plot_logic','element_continuity','segment_continuity','camera_plausibility','action_quality','duration_allocation','structural_stability']

def savejson(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def table(path,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def copyfile(source,target):
 target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():
  try:os.link(source,target)
  except OSError:shutil.copy2(source,target)
def main():
 OUT.mkdir(parents=True,exist_ok=True);protocol=load_json((CONFIG_ROOT / 'evaluation_protocol.json'));ids=[x['case_id'] for x in load_json((CONFIG_ROOT / 'manifest.json'))['cases']]
 rng=random.Random(20261016);shuffled=ids[:];rng.shuffle(shuffled);blind={cid:'V%03d'%(i+1) for i,cid in enumerate(shuffled)};mapping=[];sdb=[];director=[]
 for cid in ids:
  bid=blind[cid];dest=OUT/'participant_assets'/bid
  copyfile(RUN/'videos'/(cid+'.mp4'),dest/'video.mp4')
  copyfile((INPUT_ROOT)/cid/'benchmark_prompt.txt',dest/'requirements.txt')
  mapping.append({'blind_id':bid,'case_id':cid,'sha256':load_json(RUN / 'cases' / cid / 'generation.json')['sha256']})
  report=load_json(RUN / 'evaluation/short_drama' / cid / 'summary.json')
  for i,unit in enumerate(report['units']):
   uid=bid+'-U%03d'%(i+1);asset=OUT/'participant_assets'/bid/uid
   # Identical extracted audiovisual evidence or 3+3 frame evidence used by the automatic judge.
   source=RUN/'evaluation/short_drama'/cid/'evidence'
   candidate=source/unit['unit']
   if not candidate.exists():
    units=load_json((CONFIG_ROOT / 'evaluation_units.json'))[cid];name=unit['unit']
    if name=='drama_opening_10s':start,end=0,10
    elif name=='whole_drama':start,end=0,load_json((INPUT_ROOT) / cid / 'plan.json')['duration_sec']
    elif '_to_' in name:
     a,b=[int(v) for v in __import__('re').findall(r'\d+',name)];start=units['scenes'][a-1]['start_sec'];end=units['scenes'][b-1]['end_sec']
    else:
     number=int(name.split('_')[-1]);scene=units['scenes'][number-1];start,end=scene['start_sec'],scene['end_sec']
    candidate=source/('%03d_%03d'%(start,end))
   evidence=load_json(candidate / 'evidence.json');frames=[]
   for j,entry in enumerate(evidence['frames']):
    target=asset/('frame_%04d.jpg'%j);copyfile(Path(entry['path']),target);frames.append({'file':target.name,'timestamp_sec':entry['timestamp_sec'],'side':entry.get('side')})
   if evidence.get('audio'):copyfile(Path(evidence['audio']),asset/'audio.wav')
   savejson(asset/'evidence.json',{'frames':frames,'start_sec':evidence.get('start_sec'),'end_sec':evidence.get('end_sec'),'audio':'audio.wav' if evidence.get('audio') else None,'sampling_fps':evidence.get('sampling_fps'),'note':'Same automatic-evaluation evidence; timestamps within source video or source clip for 3+3 pairs'})
   rubric=protocol['short_drama']['rubrics'][unit['metric']]['rubric']
   page='<html><meta charset="utf-8"><title>'+uid+'</title><h1>'+uid+'</h1><p>'+html.escape(rubric)+'</p>'
   if evidence.get('audio'):page+='<audio controls src="audio.wav"></audio>'
   page+=''.join('<figure><img width="480" src="'+f['file']+'"><figcaption>t='+str(f['timestamp_sec'])+'</figcaption></figure>' for f in frames)
   (asset/'view.html').write_text(page+'</html>')
   sdb.append({'unit_id':uid,'blind_video_id':bid,'metric':unit['metric'],'evidence':str(asset.relative_to(OUT))+'/view.html','rubric':rubric,'score_1_to_5':'','not_applicable_reason':'','comment':''})
  director.append({'blind_video_id':bid,'video':'participant_assets/'+bid+'/video.mp4','requirements':'participant_assets/'+bid+'/requirements.txt',**{name:'' for name in DIRECTOR},'not_applicable_reasons':'','comment':''})
 savejson(OUT/'coordinator_only/blind_mapping.json',mapping)
 for study,count,rows in [('short_drama',20,sdb),('directorbench',14,director)]:
  for annotator in range(1,count+1):
   target=OUT/'forms'/study/('rater_%02d.csv'%annotator)
   if target.exists():continue
   order=rows[:];random.Random(20261016+annotator+(100 if study=='directorbench' else 0)).shuffle(order);table(target,order)
 (OUT/'README.md').write_text('''# Human annotation package — awaiting real annotators

The forms contain no scores. Keep coordinator_only/ private; distribute the appropriate forms and participant_assets/ to raters. Method names and automatic scores are withheld; order is randomized independently for each rater with a recorded seed. This is a five-video, one-method pilot, not the papers’ complete multi-method human study.

Short-Drama-Bench: 20 real raters, 1–5 Likert, eight short-drama criteria using exactly the same units/evidence as the current automatic protocol variant. Each row links a page with the original sampled frames and original unit audio, or the 3+3 consecutive boundary frames. Full videos are also available for context. Sampling and scope adaptations are documented in evaluation_protocol.json; the exact original survey UI is not published.

DirectorBench: 14 real raters; 1–5 Likert across the 16 published criteria. Watch the full video with audio and the requirements. Column names follow the paper. The paper does not publish per-score verbal anchors or a complete criterion-to-dimension weight table; these are not invented here. Preserve raw criterion scores for audit. Generation was not independently repeated for seven profiles, so this pilot does not test seven personalized generation conditions.

Do not fill scores for absent modalities just to complete a row; document NA and the reason. Only aggregate completed valid human ratings, and report actual rater count and missingness. No human score can be inferred from model scores.

Sources: https://arxiv.org/html/2605.22144v1 (Section 3.2 / Appendix F); https://arxiv.org/html/2605.30090v1 (Section 4).
''')
 savejson(OUT/'status.json',{'status':'PREPARED_AWAITING_REAL_ANNOTATORS','short_drama_raters_required':20,'directorbench_raters_required':14,'completed_human_ratings':0,'short_drama_units':len(sdb),'directorbench_videos':len(director),'seed':20261016})
 print('Human package prepared; real ratings remain pending')
if __name__=='__main__':main()
