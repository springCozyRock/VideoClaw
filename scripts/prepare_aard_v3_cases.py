#!/usr/bin/env python3
"""Freeze V3 separately, preserving the V2 case plans and source reference bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
HOST_FILES=['scripts/run_memory_aard.py','scripts/run_memory_aard_snapshot.py',
            'scripts/videoclaw_runtime.py','scripts/msvbench_qwen.py','scripts/generation_meter.py']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-runs',type=Path,required=True)
    p.add_argument('--code-source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();source=a.source_runs.resolve();code=a.code_source.resolve()
    if out.exists():raise ValueError('Choose a new experiment directory')
    out.mkdir(parents=True)
    archive=out/'code_snapshot'
    shutil.copytree(code/'memory',archive/'memory',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(code/'tests',archive/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    host_hashes={}
    for name in HOST_FILES+['scripts/prepare_aard_v3_cases.py']:
        target=archive/name;target.parent.mkdir(exist_ok=True,parents=True)
        shutil.copyfile(ROOT/name,target);host_hashes[name]=sha(ROOT/name)
    summary={}
    for case in ['narrative_074','story08']:
        old=source/case;run=out/case;inputs=run/'inputs';assets=inputs/'assets'
        assets.mkdir(parents=True)
        frozen=json.loads((old/'inputs/session.json').read_text())
        manifest=[]
        for group in ['characters','settings']:
            for item in frozen['artifacts']['character_design'][group]:
                original=Path(item['selected']).resolve(strict=True)
                target=assets/(group+'-'+str(item['id'])+original.suffix)
                shutil.copyfile(original,target)
                if sha(original)!=sha(target):raise ValueError('Reference copy mismatch')
                item['selected']=str(target);item['versions']=[str(target)]
                manifest.append({'id':item['id'],'source':str(original),'path':str(target),'sha256':sha(target)})
        save(inputs/'session.json',frozen)
        shutil.copyfile(old/'inputs/benchmark_original.json',inputs/'benchmark_original.json')
        segments=[s for e in frozen['artifacts']['storyboard']['episodes'] for s in e['segments']]
        summary[case]={'source_run':str(old),'source_session_sha256':sha(old/'inputs/session.json'),
            'frozen_session_sha256':sha(inputs/'session.json'),'segments':len(segments),
            'duration_seconds':sum(s['total_duration'] for s in segments),'reference_assets':manifest,
            'scope':'Same canonical plans and input anchors; fresh V3 global reference DAG, frames and videos',
            'comparison_limit':'V2 includes logged assisted recovery. This is a paired case study, not a controlled benchmark score.'}
        save(run/'input_manifest.json',summary[case])
    save(out/'manifest.json',summary)
    save(out/'code_provenance.json',{'created_at':time.time(),
        'git_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
        'dirty':subprocess.check_output(['git','-C',str(ROOT),'status','--short'],text=True),
        'snapshot_sha256':{str(p.relative_to(archive)):sha(p) for p in archive.rglob('*.py')},
        'host_sha256':host_hashes,'execution':'Snapshot memory package; verified native host runner and transports'})
    save(out/'external_service_authorization.json',{'source':'user instruction in this chat',
        'instruction':'上一版本接续产出视频 迭代新的一版后继续用这两个案例验证，付费生成直接做无需审批',
        'services':'Project-configured DashScope/Qwen image/video generation and multimodal review',
        'recorded_at':time.time()})
    print(json.dumps({k:{'segments':v['segments'],'seconds':v['duration_seconds']} for k,v in summary.items()}))

if __name__=='__main__':main()
