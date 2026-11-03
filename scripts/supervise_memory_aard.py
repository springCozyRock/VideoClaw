#!/usr/bin/env python3
"""Supervise existing bounded runs; recover only lossless completed review receipts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from reconcile_aard_review import recover


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def alive(pid):
    path = Path('/proc') / str(pid) / 'stat'
    return path.exists() and path.read_text().split(') ', 1)[1][0] != 'Z'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runs', nargs='+', type=Path)
    p.add_argument('--supplemental-reviews', action='store_true',
                   help='Allow one audited same-media supplemental judge call after invalid completed review responses')
    args = p.parse_args()
    runs = [r.resolve() for r in args.runs]
    halted = {}
    children = {}
    recoveries = 0
    while True:
        for run in runs:
            if str(run) in halted:
                continue
            if run in children:
                children[run].poll()  # Reap exited children before checking /proc.
            status = json.loads((run / 'status.json').read_text())
            if status['status'] == 'COMPLETED':
                halted[str(run)] = 'COMPLETED'
                continue
            process = json.loads((run / 'process.json').read_text())
            if alive(process['pid']):
                continue
            try:
                data = json.loads((run / 'memory/memory.json').read_text())
                pending = [(k, v) for k, v in data['operations'].items() if v['status'] != 'done']
                if pending:
                    if recoveries >= 100:
                        raise RuntimeError('Recovery count limit reached')
                    if 'Uploading file:' in status.get('detail','') and '<Code>FileAlreadyExists</Code>' in status['detail']:
                        # Provider wrappers and native runtime cwd changes remain isolated.
                        with (run/'upload_recovery_supervisor.log').open('ab') as log:
                            subprocess.run([sys.executable, str(Path(__file__).resolve().with_name('recover_aard_upload.py')), str(run)],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True)
                        audit = {'operation': pending[0][0], 'action': 'recovered proven pre-generation upload failure'}
                    else:
                        try:
                            audit = recover(run)
                        except ValueError as exc:
                            if not args.supplemental_reviews or str(exc) != 'No completed response exactly matches the required review schema and request':
                                raise
                            from repair_aard_review import repair
                            audit = repair(run)
                    recoveries += 1
                    print(json.dumps({'case': run.name, 'recovery': audit}), flush=True)
                elif status['status'] != 'BLOCKED' or not (any(
                    v.get('ended_at', 0) > status.get('updated_at', 0)
                    and (v.get('recovered_response') or v.get('supplementary_review'))
                    for v in data['operations'].values()) or
                    (data['inputs']['implementation']=='aard-adaptation-v2' and any(
                        c['id'].startswith('segment/%d/'%len(data['committed']))
                        for c in data.get('prompt_experiences',[])))):
                    raise RuntimeError('No new reconciled review justifies resuming this stopped run')
                from rewind_aard_v2_experiences import rewind
                replay=rewind(run)
                if replay:print(json.dumps({'case':run.name,'experience_replay':replay}),flush=True)
                with (run / 'runner.log').open('ab') as log:
                    child = subprocess.Popen(process['command'], cwd=Path(__file__).resolve().parents[1],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True)
                children[run] = child
                process.setdefault('previous_pids', []).append(process['pid'])
                process.update(pid=child.pid, resumed_at=time.time())
                save(run / 'process.json', process)
            except Exception as exc:
                halted[str(run)] = 'NEEDS_ATTENTION:' + type(exc).__name__
                print(json.dumps({'case': run.name, 'status': halted[str(run)]}), flush=True)
        save(runs[0].parent / 'supervisor_status.json', {
            'updated_at': time.time(), 'recoveries': recoveries, 'halted': halted,
            'active': [str(r) for r in runs if str(r) not in halted]})
        if len(halted) == len(runs):
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
