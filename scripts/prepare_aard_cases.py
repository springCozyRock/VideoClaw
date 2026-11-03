#!/usr/bin/env python3
"""Freeze the requested benchmark plans and reusable global references; no old clips/seed frames."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'video-claw/video-claw/backend'
SOURCES = {
    'narrative_074': 'experiments/videoclaw_pure_narrative_074_20261025/sessions/vc074pure_1792933141821.json',
    'story08': 'experiments/videoclaw_auto_msvbench08_20261026/sessions/lvma_1793016695946.json',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise SystemExit('Choose a new experiment directory; frozen inputs are not overwritten')
    out.mkdir(parents=True)
    summary = {}
    for case, relative in SOURCES.items():
        source = ROOT / relative
        snapshot = json.loads(source.read_text())
        run = out / case
        inputs = run / 'inputs'
        assets = inputs / 'assets'
        assets.mkdir(parents=True)
        frozen = {'meta': copy.deepcopy(snapshot['meta']), 'artifacts': {
            k: copy.deepcopy(snapshot['artifacts'][k]) for k in ('script_generation', 'character_design', 'storyboard')
            if k in snapshot['artifacts']}}
        frozen['artifacts']['reference_generation'] = {'scenes': []}
        asset_manifest = []
        for group in ('characters', 'settings'):
            for item in frozen['artifacts']['character_design'].get(group, []):
                original = Path(item['selected'])
                original = original if original.is_absolute() else BACKEND / original
                original = original.resolve(strict=True)
                target = assets / (group + '-' + str(item['id']) + original.suffix)
                shutil.copyfile(original, target)
                item['selected'] = str(target)
                item['versions'] = [str(target)]
                asset_manifest.append({'id': item['id'], 'group': group, 'source': str(original),
                                       'path': str(target), 'sha256': sha(target)})
        segments = [s for e in frozen['artifacts']['storyboard']['episodes'] for s in e['segments']]
        assert sum(s['total_duration'] for s in segments) == 60
        assert len(segments) == (5 if case == 'narrative_074' else 9)
        assert sum(len(s['shots']) for s in segments) == (5 if case == 'narrative_074' else 21)
        if case == 'narrative_074':
            dataset = ROOT / 'benchmarks/directorbench/data/metadata/dataset_original.jsonl'
            original = next(json.loads(l) for l in dataset.read_text().splitlines() if json.loads(l).get('meta_id') == case)
        else:
            dataset = ROOT / 'experiments/msvbench_agents_20261018/inputs/08/script.json'
            original = json.loads(dataset.read_text())
        (inputs / 'benchmark_original.json').write_text(json.dumps(original, ensure_ascii=False, indent=2))
        (inputs / 'session.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2))
        manifest = {'case': case, 'source_session': str(source), 'source_session_sha256': sha(source),
            'benchmark_source': str(dataset), 'benchmark_source_sha256': sha(dataset),
            'segments': len(segments), 'shots': sum(len(s['shots']) for s in segments), 'duration_seconds': 60,
            'reference_assets': asset_manifest,
            'reuse': 'Prepared global characters/environments and native locked storyboard; fresh boundary frames and videos',
            'boundary_mapping': 'Native planned shot durations; not measured cuts in generated videos',
            'max_video_candidates': 2 * len(segments), 'max_generated_video_seconds': 120}
        (run / 'input_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        summary[case] = manifest
    sources = list((ROOT / 'memory').rglob('*.py')) + [ROOT / 'scripts' / n for n in
        ('run_memory_aard.py', 'prepare_aard_cases.py', 'videoclaw_runtime.py', 'msvbench_qwen.py', 'generation_meter.py')]
    archive = out / 'code_snapshot'
    for source in sources:
        target = archive / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    provenance = {'git_commit': subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
                  'dirty': subprocess.check_output(['git','-C',str(ROOT),'status','--short'],text=True),
                  'source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sources}}
    (out / 'code_provenance.json').write_text(json.dumps(provenance, indent=2))
    (out / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: {'segments':v['segments'], 'seconds':v['duration_seconds']} for k,v in summary.items()}))


if __name__ == '__main__':
    main()
