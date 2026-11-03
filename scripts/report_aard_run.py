#!/usr/bin/env python3
"""Summarize recorded AARD integration evidence without calling any model."""
import argparse
import json
from pathlib import Path
import time


def summarize(run):
    state = json.loads((run / 'memory/memory.json').read_text())
    status = json.loads((run / 'status.json').read_text())
    records = state['committed']
    judges, usage, truncated = [], [], 0
    for path in (run / 'memory/judge_calls').glob('*/response.json'):
        response = json.loads(path.read_text())
        chunks = response.get('chunks', [])
        values = [c['usage'] for c in chunks if c.get('usage')]
        if values:
            usage.append(values[-1])
        if any(choice.get('finish_reason') == 'length' for c in chunks for choice in c.get('choices', [])):
            truncated += 1
        judges.append(str(path))
    task_receipts = [json.loads(p.read_text()) for p in (run / 'tasks').glob('*.json')
                     if not p.name.endswith('.response.json')]
    result = {'case': run.name, 'status': status['status'], 'updated_at': time.time(),
              'scope': 'Integration case study; no matched-budget baseline or official benchmark result',
              'planned_segments': len(state['inputs']['segments']), 'selected_segments': len(records),
              'quality_passed_segments': sum(r['accepted'] for r in records),
              'selected_seconds': sum(r['segment']['duration'] for r in records),
              'generated_video_candidates': len(list((run / 'memory/media').glob('*.mp4'))),
              'video_task_receipts': len(task_receipts),
              'judge_completed_responses': len(judges), 'judge_output_limit_truncations': truncated,
              'judge_usage_raw': usage,
              'prompt_experiences': {label: sum(x['label'] == label for x in state.get('prompt_experiences', []))
                                     for label in ('pos', 'neg')},
              'supplemental_reviews': len(list((run / 'review_repairs').glob('*.json'))),
              'reconciliations': state.get('reconciliations', []),
              'models': {k: v for k, v in state['inputs']['backend'].items() if k != 'sources'},
              'segments': []}
    for record in records:
        result['segments'].append({
            'index': record['index'], 'id': record['segment']['id'], 'mode': record['mode'],
            'video': record['video'], 'quality_passed': record['accepted'],
            'review': record['review'], 'boundary_quality': record['boundary_quality'],
            'completed_goals': record['completed_goals'], 'unresolved_goals': record['unresolved_goals'],
            'dependencies': record['dependencies']})
    if status['status'] == 'COMPLETED':
        final = json.loads((run / 'result.json').read_text())
        result['final_video'] = final['video']
        result['final_probe'] = json.loads((run / 'final_probe.json').read_text())
    output = run / 'evidence_summary.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return {k: result[k] for k in ('case', 'status', 'selected_segments', 'quality_passed_segments',
                                 'selected_seconds', 'generated_video_candidates', 'prompt_experiences')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    for run in sorted(p for p in args.root.iterdir() if (p / 'config.json').exists()):
        print(json.dumps(summarize(run.resolve()), ensure_ascii=False))
