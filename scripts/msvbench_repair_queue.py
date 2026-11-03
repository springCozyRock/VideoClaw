#!/usr/bin/env python3
"""One-shot repair evaluation queue; never generates videos or rewrites old results."""
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'experiments/msvbench_agents_20261018'
REPAIR = ROOT / 'experiments/msvbench_repair_20261019'


def read(p, default=None):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temp.replace(p)


def main():
    with (REPAIR / 'evaluation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        statefile = REPAIR / 'evaluation_state.json'
        state = read(statefile, {'status': 'RUNNING', 'tasks': {}})
        rows = read(ROOT / 'configs/msvbench_agents_20261018/manifest.json')['stories']
        deadline = time.time() + 3 * 86400
        while time.time() < deadline:
            deployment = read(ROOT / 'configs/msvbench/deployment.json')['metrics']
            gate = read(REPAIR / 'full_story_flash_gate.json')
            if gate.get('status') == 'PASSED':
                state['tasks']['videoclaw/01/story_video_consistency'] = {
                    'status': 'SCORED', 'evidence': gate['evidence'],
                    'mode': 'FULL_STORY_FLASH_VALIDATION', 'native_score_recomputed': True}
            generated = {}
            for method in ['videoclaw', 'codex_composition']:
                generated[method] = 0
                for row in rows:
                    sid = row['story']
                    folder = RUN / method / 'stories' / sid
                    if read(folder / 'status.json').get('status') != 'GENERATED':
                        continue
                    generated[method] += 1
                    for metric, ready in deployment.items():
                        key = '/'.join([method, sid, metric])
                        if state['tasks'].get(key, {}).get('status') in ['SCORED', 'PARTIAL', 'FAILED']:
                            continue
                        reviewed = REPAIR / 'reviewed_results' / method / sid / metric / 'status.json'
                        review = read(reviewed)
                        if review.get('status') in ['SCORED', 'PARTIAL']:
                            state['tasks'][key] = {'status': review['status'], 'evidence': str(reviewed),
                                                   'mode': 'REVIEW_OF_EXISTING_NATIVE_OUTPUT', 'native_score_recomputed': False}
                            save(statefile, state)
                            continue
                        if ready['status'] != 'SMOKE_VERIFIED':
                            state['tasks'][key] = {'status': 'WAITING_DEPLOYMENT', 'reason': ready.get('reason')}
                            continue
                        if metric == 'story_video_consistency' and gate.get('status') != 'PASSED':
                            state['tasks'][key] = {'status': 'WAITING_VALIDATION', 'reason': 'Full story FlashAttention validation pending'}
                            continue
                        free = int(subprocess.check_output(['nvidia-smi', '-i', '6', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True).strip())
                        if free < 36000:
                            continue
                        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
                        output = REPAIR / 'evaluation_runs' / stamp
                        target = output / method / sid / metric
                        # Carry only successful cached judge responses, never failure records.
                        original = Path(review.get('original_evidence', ''))
                        if original.is_file():
                            for response in (original.parent / 'judge_calls').glob('*/response.json'):
                                dest = target / 'judge_calls' / response.parent.name / 'response.json'
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(response, dest)
                        cmd = ['bash', str(ROOT / 'scripts/msvbench.sh'), '--method', method, '--story', sid,
                               '--metric', metric, '--videos', str(folder / 'shots'), '--prompt', row['prompt'],
                               '--script', row['script'], '--camera', row['camera'], '--characters', row['evaluation_characters'],
                               '--output-root', str(output)]
                        state['tasks'][key] = {'status': 'RUNNING', 'started': time.time(), 'command': cmd}
                        save(statefile, state)
                        log = REPAIR / 'evaluation_logs' / (key.replace('/', '_') + '.log')
                        log.parent.mkdir(parents=True, exist_ok=True)
                        env = dict(os.environ, CUDA_VISIBLE_DEVICES='6', PYTHONUTF8='1',
                                   MSVBENCH_DNS_FALLBACK=str(REPAIR / 'resolver_fallback.json'))
                        try:
                            with log.open('w') as stream:
                                process = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                                         stderr=subprocess.STDOUT, timeout=86400)
                            evidence = target / 'status.json'
                            result = read(evidence)
                            status = result.get('status', 'FAILED')
                            state['tasks'][key] = {'status': status, 'evidence': str(evidence),
                                                   'log': str(log), 'returncode': process.returncode,
                                                   'finished': time.time(), 'mode': 'NATIVE_RECOMPUTATION'}
                        except Exception as error:
                            state['tasks'][key] = {'status': 'FAILED', 'error': str(error), 'log': str(log)}
                        save(statefile, state)
            state.update(status='RUNNING', generated_stories=generated, updated=time.time(),
                         waiting_metrics=[m for m, v in deployment.items() if v['status'] != 'SMOKE_VERIFIED'])
            save(statefile, state)
            target_count = sum(generated.values()) * len(deployment)
            terminal = sum(v['status'] in ['SCORED', 'PARTIAL', 'FAILED'] for v in state['tasks'].values())
            if terminal == target_count and all(v == len(rows) for v in generated.values()):
                state['status'] = 'FINISHED'
                save(statefile, state)
                return
            time.sleep(30)
        state['status'] = 'TIME_LIMIT_REACHED'
        save(statefile, state)


if __name__ == '__main__':
    main()
