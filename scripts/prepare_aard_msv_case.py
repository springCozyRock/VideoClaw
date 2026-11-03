#!/usr/bin/env python3
"""Freeze one existing native MSVBench plan for unchanged AARD V3 testing."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
HOST_FILES = ['run_memory_aard.py', 'run_memory_aard_snapshot.py', 'run_aard_queued_slow.py',
              'videoclaw_runtime.py', 'msvbench_qwen.py', 'generation_meter.py']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--story', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if len(a.story) != 2 or not a.story.isdigit():
        raise ValueError('Use the two-digit official story id')
    old = ROOT / 'experiments/msvbench_agents_20261018/videoclaw/stories' / a.story
    original = ROOT / 'experiments/msvbench_agents_20261018/inputs' / a.story
    backend = ROOT / 'video-claw/video-claw/backend'
    source_paths = [old / n for n in ['request.json', 'script_generation.json', 'character_design.json', 'storyboard.json']]
    source = {p.stem: json.loads(p.read_text()) for p in source_paths}
    canonical = json.loads((original / 'script.json').read_text())
    segments = [s for e in source['storyboard']['episodes'] for s in e['segments']]
    official_shots = [c for scene in canonical['script'] for c in scene['clips']]
    assert sum(len(s['shots']) for s in segments) == len(official_shots)
    assert all(2 <= s['total_duration'] <= 15 and sum(x['duration'] for x in s['shots']) == s['total_duration'] for s in segments)
    out = a.out.resolve()
    if out.exists():
        raise ValueError('Choose a new experiment directory; never overwrite a frozen run')
    run = out / ('story' + a.story)
    assets = run / 'inputs/assets'
    assets.mkdir(parents=True)
    frozen = {'meta': copy.deepcopy(source['request']), 'artifacts': {
        k: copy.deepcopy(source[k]) for k in ['script_generation', 'character_design', 'storyboard']}}
    frozen['artifacts']['reference_generation'] = {'scenes': []}
    manifest = []
    for group in ['characters', 'settings']:
        for item in frozen['artifacts']['character_design'][group]:
            path = Path(item['selected'])
            path = (path if path.is_absolute() else backend / path).resolve(strict=True)
            target = assets / (group + '-' + item['id'] + path.suffix)
            if group == 'characters':
                official = original / 'character_inputs' / (item['id'] + path.suffix)
                assert sha(official) == sha(path), 'Native character anchor differs from official input'
            shutil.copyfile(path, target)
            assert sha(path) == sha(target)
            item['selected'] = str(target)
            item['versions'] = [str(target)]
            manifest.append({'id': item['id'], 'group': group, 'source': str(path), 'path': str(target), 'sha256': sha(target)})
    save(run / 'inputs/session.json', frozen)
    for name in ['script.json', 'prompt.txt', 'camera.txt']:
        shutil.copy2(original / name, run / 'inputs' / ('benchmark_original.json' if name == 'script.json' else name))
    info = {'case': 'story' + a.story, 'segments': len(segments), 'shots': len(official_shots),
            'duration_seconds': sum(s['total_duration'] for s in segments), 'reference_assets': manifest,
            'source_files': {str(p): sha(p) for p in source_paths + [original / 'script.json', original / 'prompt.txt', original / 'camera.txt']},
            'frozen_session_sha256': sha(run / 'inputs/session.json'),
            'scope': 'Existing native VideoClaw storyboard and source anchors; fresh V3 references/boundaries/videos. No old generated clips or learned prompt experience.',
            'limitations': 'Native shot grouping/timing and any source translation differences are retained. Planned shot boundaries are not detected cuts. Not official benchmark evaluation.',
            'manual_plan_edits': False, 'max_video_candidates': 2 * len(segments)}
    save(run / 'input_manifest.json', info)
    save(out / 'manifest.json', {run.name: info})
    archive = out / 'code_snapshot'
    shutil.copytree(ROOT / 'memory', archive / 'memory', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    host_hashes = {}
    for name in HOST_FILES + ['prepare_aard_msv_case.py']:
        rel = 'scripts/' + name
        target = archive / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
        host_hashes[rel] = sha(ROOT / rel)
    save(out / 'code_provenance.json', {'created_at': time.time(),
        'git_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'dirty': subprocess.check_output(['git', '-C', str(ROOT), 'status', '--short'], text=True),
        'snapshot_sha256': {str(p.relative_to(archive)): sha(p) for p in archive.rglob('*.py')},
        'host_sha256': host_hashes, 'execution': 'Unchanged current V3 frozen package with existing paced launcher'})
    save(out / 'external_service_authorization.json', {'recorded_at': time.time(),
        'source': 'User in this chat: 用现在的版本再给我测试一下 msv story01; prior authorization: 付费生成直接做无需审批',
        'services': 'Project-configured DashScope/Qwen image/video generation and multimodal review'})
    print(json.dumps({'run': str(run), 'segments': len(segments), 'seconds': info['duration_seconds'], 'api_calls': 0}))

if __name__ == '__main__':
    main()
