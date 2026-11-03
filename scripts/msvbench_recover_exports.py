#!/usr/bin/env python3
"""Recover existing outputs only; no generation/API calls."""
import sys,json,time,shutil,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import msvbench_agents_run as m
records=[]
for sid,n in [('01',23),('08',21)]:
 folder=m.RUN/'codex_composition/stories'/sid
 if m.read(folder/'status.json').get('status')=='GENERATED':
  print(sid,'already collected',flush=True);continue
 candidates=[p for p in (m.RUN/'codex_composition/runtime/generation').rglob('evaluation_manifest.json') if m.read(p).get('story')==sid]
 if len(candidates)!=1:raise RuntimeError('Ambiguous manifest '+sid)
 p=candidates[0];original=m.read(p);entries=original['shots']
 if len(entries)!=n or len({s['path'] for s in entries})!=n:raise RuntimeError('Missing/ambiguous canonical shots')
 final=p.parent/'final.mp4';media=m.validate(final);cumulative=0;prepared=[]
 for i,s in enumerate(entries,1):
  if s['official_shot_index']!=i:raise RuntimeError('Shot order')
  clip=p.parent/'clips'/Path(s['path']).name
  start=float(s['start_sec']);end=float(s['end_sec']);length=end-start
  if abs(start-cumulative)>.05 or length<=0:raise RuntimeError('Not a continuous final-video timeline')
  actual=float(m.validate(clip)['format']['duration'])
  if actual+.05<length:raise RuntimeError('Insufficient source duration')
  if i<n and abs(actual-length)>.05:raise RuntimeError('Unexpected non-final trim')
  cumulative=end;prepared.append((s,clip,length,actual))
 if abs(float(media['format']['duration'])-cumulative)>.05:raise RuntimeError('Final timeline mismatch')
 audit={'original_manifest':str(p.resolve()),'original_manifest_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'repair':'Resolve moved output paths; convert final-timeline intervals to clip-local 0..(end-start). Preserve last-shot trim and original timings. No generation calls.','shots':[]}
 for i,(s,clip,length,actual) in enumerate(prepared,1):
  target=folder/'shots'/f'{i:02d}.mp4';target.parent.mkdir(parents=True,exist_ok=True)
  if abs(actual-length)<=.05:
   tmp=target.with_suffix('.recovered.mp4');shutil.copy2(clip,tmp);m.validate(tmp,length);tmp.replace(target)
  else:
   if target.exists():
    old=folder/'recovery_previous'/target.name;old.parent.mkdir(parents=True,exist_ok=True);target.replace(old)
   m.extract(clip,0,length,target)
  audit['shots'].append(dict(s,original_start_sec=s['start_sec'],original_end_sec=s['end_sec'],path=str(clip.resolve()),start_sec=0,end_sec=length,evaluation_path=str(target),source_duration_sec=actual))
 tmp=folder/'final.recovered.mp4';shutil.copy2(final,tmp);tmp.replace(folder/'final.mp4')
 audit.update(story=sid,final_video=str(folder/'final.mp4'))
 m.dump(folder/'evaluation_manifest.json',audit)
 err=folder/'collection_error.json'
 if err.exists():err.replace(folder/'collection_error.before_recovery.json')
 for tmp in (folder/'shots').glob('*.tmp.mp4'):
  dest=folder/'recovery_previous'/tmp.name;dest.parent.mkdir(parents=True,exist_ok=True);tmp.replace(dest)
 m.dump(folder/'status.json',{'status':'GENERATED','final_video':str(folder/'final.mp4'),'agent_output':str(p.parent.resolve()),'shots':n,'duration_sec':float(media['format']['duration']),'updated':time.time(),'recovery_evidence':str(folder/'evaluation_manifest.json')})
 print(sid,'RECOVERED',n,float(media['format']['duration']),flush=True)
 records.append({'story':sid,'shots':n,'duration_sec':float(media['format']['duration'])})
m.dump(m.RUN/'export_recovery_20261019.json',{'recovered':records,'time':time.time(),'generation_calls':0})
