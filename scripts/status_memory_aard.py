#!/usr/bin/env python3
"""Compact read-only AARD experiment status; no API calls or credentials in output."""
import argparse
import json
from pathlib import Path
import time


def read(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    for run in sorted(p for p in args.root.iterdir() if (p/'config.json').exists()):
        state = read(run/'status.json', {})
        memory = read(run/'memory/memory.json', {})
        process = read(run/'process.json', {})
        now = state.get('updated_at', time.time()) if state.get('status') == 'COMPLETED' else time.time()
        process_stat = Path('/proc/'+str(process.get('pid'))+'/stat')
        try:
            running = process_stat.read_text().split(') ',1)[1][0] != 'Z'
        except FileNotFoundError:
            running = False
        operations = list(memory.get('operations', {}).items())
        tasks = [read(p,{}) for p in (run/'tasks').glob('*.json') if not p.name.endswith('.response.json')]
        candidates = memory.get('candidates', {})
        value = {'case':run.name, 'status':state.get('status'),
            'alive': running,
            'elapsed_minutes': round((now-process.get('started_at',now))/60,1),
            'selected_segments':len(memory.get('committed',[])),
            'passed_segments':sum(r['accepted'] for r in memory.get('committed',[])),
            'last_operations':[(k,v['status']) for k,v in operations[-2:]],
            'video_tasks':{status:sum(t.get('status')==status for t in tasks)
                           for status in sorted(set(str(t.get('status')) for t in tasks))},
            'judged_candidates':len(candidates),
            'judge_responses':len(list((run/'memory/judge_calls').glob('*/response.json')))}
        if state.get('status')=='BLOCKED':
            value['error_type']=state.get('error_type')
        wait = read(args.root/'approval_wait.json', {})
        authorization = read(args.root/'external_service_authorization.json', {})
        if wait.get('time') and authorization.get('recorded_at'):
            value['elapsed_excluding_authorization_wait_minutes'] = round(
                (now-process.get('started_at',now)-
                 max(0,authorization['recorded_at']-wait['time']))/60,1)
        print(json.dumps(value,ensure_ascii=False))


if __name__ == '__main__':
    main()
