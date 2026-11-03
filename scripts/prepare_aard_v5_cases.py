#!/usr/bin/env python3
"""Freeze native inputs and the tested V5 source for three fresh case runs; no API calls."""
import argparse,copy,hashlib,json,shutil,subprocess,time
from pathlib import Path
from rate_limit_policy import REQUEST_GAP_SECONDS, RATE_LIMIT_RETRY_SECONDS
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2))
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args()
    source=a.source.resolve();out=a.out.resolve()
    if out.exists():raise ValueError('Choose a new experiment directory; never overwrite a frozen run')
    validation=json.loads((source.parent/'offline_validation.json').read_text())
    if not validation['successful'] or validation['skipped']:raise ValueError('Native offline verification must pass first')
    cases={'narrative_074':'experiments/memory_aard_20261031_v3/narrative_074',
        'story08':'experiments/memory_aard_20261031_v3/story08',
        'story01':'experiments/memory_aard_v3_story01_20261031/story01'}
    out.mkdir(parents=True);manifest={}
    for name,relative in cases.items():
        original=ROOT/relative;session_path=original/'inputs/session.json';session=json.loads(session_path.read_text())
        frozen=copy.deepcopy(session);run=out/name;assets=run/'inputs/assets';assets.mkdir(parents=True)
        asset_records=[]
        for group in ('characters','settings'):
            for item in frozen['artifacts']['character_design'].get(group,[]):
                src=Path(item['selected'])
                if not src.is_absolute():src=ROOT/'video-claw/video-claw/backend'/src
                src=src.resolve(strict=True);dst=assets/(group+'-'+item['id']+src.suffix);shutil.copy2(src,dst)
                if sha(src)!=sha(dst):raise ValueError('Copied input changed')
                item['selected']=str(dst);item['versions']=[str(dst)]
                asset_records.append({'id':item['id'],'source':str(src),'path':str(dst),'sha256':sha(dst)})
        frozen['artifacts']['reference_generation']={'scenes':[]}
        save(run/'inputs/session.json',frozen)
        for filename in ('benchmark_original.json','prompt.txt','camera.txt','input_manifest.json'):
            src=original/'inputs'/filename
            if src.exists():shutil.copy2(src,run/'inputs'/filename)
        segments=[s for e in frozen['artifacts']['storyboard']['episodes'] for s in e['segments']]
        item={'case':name,'source_session':str(session_path),'source_sha256':sha(session_path),
            'frozen_session_sha256':sha(run/'inputs/session.json'),'segments':len(segments),
            'seconds':sum(s['total_duration'] for s in segments),'shots':sum(len(s['shots']) for s in segments),
            'assets':asset_records,'manual_plan_edits':False,
            'scope':'Same native input plan and initial anchors; fresh V5 global references, appearance states and generated clips. Prior operator-assisted runtime plans and generated videos are not reused.'}
        save(run/'input_manifest.json',item);manifest[name]=item
    snapshot=out/'code_snapshot';shutil.copytree(source,snapshot,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    host=['run_memory_aard_v5.py','run_memory_aard_v5_snapshot.py','run_aard_v5_queued.py',
        'rate_limit_policy.py','videoclaw_runtime.py','msvbench_qwen.py','generation_meter.py','videoclaw_fast.py','aard_qwen_pacing.py','prepare_aard_v5_cases.py']
    for name in host:
        dst=snapshot/'scripts'/name;dst.parent.mkdir(exist_ok=True);shutil.copy2(ROOT/'scripts'/name,dst)
    save(out/'manifest.json',manifest);save(out/'offline_validation.json',validation)
    save(out/'code_provenance.json',{'created_at':time.time(),'git_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
        'snapshot_sha256':{str(p.relative_to(snapshot)):sha(p) for p in snapshot.rglob('*.py')},
        'host_sha256':{'scripts/'+n:sha(ROOT/'scripts'/n) for n in host}})
    save(out/'launch_protocol.json',{'version':'V5','frame_candidates':3,'video_candidates':3,'reference_candidates':3,
        'critical_state_gate':True,'qwen_minimum_gap_seconds':REQUEST_GAP_SECONDS,'rate_limit_retry_seconds':RATE_LIMIT_RETRY_SECONDS,'operator_plan_rewrites':False,
        'evaluation':'Source fidelity, identity/style, mutable states and event progression; internal gates are not official benchmark scores',
        'story01_baseline':'Previous V3 run was stopped after 4/8 selected segments; its provider output was recovered without re-generation.'})
    save(out/'external_service_authorization.json',{'recorded_at':time.time(),'source':'User: 继续向AARD靠拢迭代，并用这3个案例来测试验证，付费模型无需审批',
        'services':'Configured DashScope/Qwen image/video generation, multimodal assessment and semantic embeddings'})
    print(json.dumps({'experiment':str(out),'cases':{k:{x:v[x] for x in ('segments','seconds','shots')} for k,v in manifest.items()},'api_calls':0}))
if __name__=='__main__':main()
