#!/usr/bin/env python3
"""Native VideoClaw narrative_074 baseline, without Memory; metered provider calls."""
import argparse
import asyncio
import copy
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from generation_meter import Meter, save


def prepare(run):
    if (run/'config.json').exists():return json.loads((run/'config.json').read_text())
    source=ROOT/'benchmarks/directorbench/data/metadata/dataset_original.jsonl'
    record=next(json.loads(line) for line in source.read_text().splitlines() if json.loads(line).get('meta_id')=='narrative_074')
    previous=json.loads((ROOT/'experiments/videoclaw_memory_narrative_074_20261024/config.json').read_text())
    request=dict(previous['request'],enable_concurrency=True)
    config=dict(session_id='vc074pure_'+str(int(time.time()*1000)),request=request,memory_enabled=False,
                host='native VideoClaw six agents, benchmark script/storyboard input locks, provider compatibility adapters only',
                concurrency='native parallel execution enabled; prior Memory run was serial, so wall times are not a controlled speedup comparison',
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                code_commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
                upstream_commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip())
    save(run/'config.json',config);save(run/'inputs/original.json',record)
    files={}
    for name in ('run_videoclaw_baseline.py','generation_meter.py','videoclaw_runtime.py','videoclaw_smoke.py'):
        src=ROOT/'scripts'/name;dst=run/'code'/name;dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(src,dst);files[name]=hashlib.sha256(src.read_bytes()).hexdigest()
    save(run/'code/source_hashes.json',files)
    save(run/'pricing.json',dict(checked_date='2026-10-25',region='China Beijing',currency='CNY',
        video_per_second_720p=.6,image_per_output=.2,qwen37_input_per_million=2,qwen37_output_per_million=8,
        qwen35omni_input_per_million=7,qwen35omni_output_per_million=40,
        sources=['https://help.aliyun.com/zh/model-studio/wan3-0-video','https://help.aliyun.com/zh/model-studio/wan2-7-image',
                 'https://help.aliyun.com/zh/model-studio/qwen3-7-plus','https://help.aliyun.com/zh/model-studio/qwen3-5-omni-plus'],
        basis='official list prices, token cache discounts when usage reports cache hits; account bill and free quotas unavailable'))
    return config


async def execute(run,config,meter):
    import videoclaw_runtime as runtime
    runtime.RUN=run;runtime.configure()
    import videoclaw_fast
    fast=videoclaw_fast.install;videoclaw_fast.install=lambda:None
    try:runtime.install_adapters()
    finally:videoclaw_fast.install=fast
    meter.install()
    from core.orchestrator import WorkflowEngine,WorkflowStage
    from videoclaw_smoke import lock_script,lock_storyboard,validate,verify_selected
    class IsolatedEngine(WorkflowEngine):
        def _load_sessions_from_disk(self):pass
    engine=IsolatedEngine();engine._session_dir=str(run/'sessions');Path(engine._session_dir).mkdir(exist_ok=True)
    sid=config['session_id'];engine.create_session(sid,config['request']);state=engine.get_state(sid)
    record=json.loads((run/'inputs/original.json').read_text())
    stages=[]
    async def stage(name,modifications=None):
        tag=name+('_locked' if modifications else '_native');meter.stage=tag
        start=time.time();logging.info('BEGIN %s',tag)
        save(run/'status.json',dict(status='RUNNING',stage=tag,session_id=sid,started_at=STARTED,updated_at=start,memory_enabled=False))
        current,data=(engine.prepare_intervention_execution(sid,name,modifications) if modifications else engine.prepare_stage_execution(sid,name,{}))
        current.error=None
        def progress(phase,step,percent,data=None):
            with (run/'agent_events.jsonl').open('a') as out:
                out.write(json.dumps(dict(time=time.time(),stage=tag,phase=phase,step=step,percent=percent,data=data),ensure_ascii=False,default=str)+'\n')
        try:
            result=await engine.execute_stage(current,WorkflowStage(name),data,intervention=modifications,progress_callback=progress)
            if current.error or current.status.get(name) in ('error','stopped'):raise RuntimeError(current.error or current.status[name])
            artifact=copy.deepcopy(current.artifacts[name])
            save(run/'stages'/(tag+'.json'),dict(artifact=artifact,result=result,state=current.to_dict()))
            return artifact
        finally:
            stages.append(dict(name=tag,started_at=start,ended_at=time.time(),wall_sec=time.time()-start))
            save(run/'stage_timings.json',stages);meter.summarize(time.time()-STARTED)
            logging.info('END %s',tag)
    native=await stage('script_generation')
    script=await stage('script_generation',{'modified_script':lock_script(record,copy.deepcopy(native))})
    chars=await stage('character_design');verify_selected(chars,['characters','settings'],4)
    native=await stage('storyboard')
    await stage('storyboard',{'modified_storyboard':lock_storyboard(record,copy.deepcopy(native),script)})
    refs=await stage('reference_generation');verify_selected(refs,['scenes'],5)
    videos=await stage('video_generation');clips=verify_selected(videos,['clips'],5)
    expected={'seg_1_'+str(i+1):seconds for i,seconds in enumerate((10,12,12,14,12))}
    if {c['id'] for c in clips}!=set(expected):raise RuntimeError('Incorrect shot coverage')
    for clip in clips:validate(Path(clip['selected']).resolve(),expected[clip['id']])
    final=await stage('post_production');finals=final.get('final_videos',[])
    if len(finals)!=1:raise RuntimeError('Expected one final drama')
    path=Path(finals[0]['path']).resolve();probe=validate(path,60)
    duration=float(probe['format']['duration']);save(run/'probe.json',probe)
    deliverable=run/'videos/narrative_074.mp4';deliverable.parent.mkdir(exist_ok=True);shutil.copyfile(path,deliverable)
    loaded=[m for m in sys.modules if m=='memory' or m.startswith('memory.')]
    if loaded:raise RuntimeError('Baseline unexpectedly loaded Memory: '+str(loaded))
    cost=meter.summarize(time.time()-STARTED,duration)
    save(run/'status.json',dict(status='COMPLETED',session_id=sid,memory_enabled=False,memory_modules_loaded=loaded,
         video=str(deliverable),duration_sec=duration,sha256=hashlib.sha256(deliverable.read_bytes()).hexdigest(),
         started_at=STARTED,ended_at=time.time(),updated_at=time.time(),cost=cost,
         scope='native VideoClaw technical completion; benchmark input locks; no quality score implied'))
    report='# Pure VideoClaw narrative_074\n\n'
    report+='Final duration: %.3f sec. End-to-end wall time: %.2f min.\n\n'%(duration,cost['wall_clock_sec']/60)
    report+='Estimated total: CNY %.4f. Per finished minute: CNY %.4f; %.2f wall minutes.\n\n'%(cost['estimated_total_cny'],cost['cny_per_finished_minute'],cost['wall_minutes_per_finished_minute'])
    report+='Sample count: 1. Official Beijing list-price estimate, not an account bill; includes all recorded candidates/retries and native planning/judging. No Memory. Parallel execution enabled; do not compare wall time directly to the prior serial Memory run.\n\n'
    report+='```json\n'+json.dumps(cost,ensure_ascii=False,indent=2)+'\n```\n'
    (run/'REPORT.md').write_text(report)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();run=args.run.resolve();run.mkdir(parents=True,exist_ok=True)
    global STARTED
    STARTED=time.time()
    with (run/'runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);config=prepare(run)
        if not args.execute:print(json.dumps(dict(prepared=str(run),session_id=config['session_id'])));return
        if (run/'process.json').exists():raise SystemExit('Existing attempt: inspect receipts before any restart; do not duplicate paid calls')
        save(run/'process.json',dict(pid=os.getpid(),started_at=STARTED))
        meter=Meter(run);logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
        try:asyncio.run(execute(run,config,meter))
        except BaseException as exc:
            status=json.loads((run/'status.json').read_text()) if (run/'status.json').exists() else {}
            status.update(status='FAILED',error=str(exc),updated_at=time.time());save(run/'status.json',status)
            meter.summarize(time.time()-STARTED);raise

if __name__=='__main__':main()
