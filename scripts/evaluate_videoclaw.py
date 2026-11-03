"""Frozen VideoClaw batch -> DirectorBench, native VBench-3, ViStoryBench-4."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 'videoclaw_wan27_preview_eval'
RUN = ROOT / 'experiments' / RUN_ID
CONFIG = ROOT / 'configs' / RUN_ID
SCRIPTS = ROOT / 'baselines/codex/evaluation'
BATCH = ROOT / 'experiments/videoclaw_batch_fast/20261016_wan27_preview'
PUBLISH = ROOT / 'video-claw/video-claw/backend/code/result/batches/20261016_wan27_preview/evaluation'
IDS = ['action_006', 'cinematic_008', 'educational_008', 'music_004', 'narrative_074']
FAMILIES = ['directorbench', 'vbench', 'vistorybench']
RUNTIMES = {'directorbench': '/mnt/data/bts/envs/directorbench/bin/python',
            'vbench': '/mnt/data/bts/envs/vbench/bin/python',
            'vistorybench': str(ROOT / '.venvs/vistorybench/bin/python')}
WRITE_LOCK = threading.RLock()
GPU_CONDITION = threading.Condition()
GPU_CLAIMS = {}
SHUTDOWN = threading.Event()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with WRITE_LOCK:
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temp.replace(path)


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare():
    summary = read(BATCH / 'summary.json')
    if summary.get('status') != 'PASSED' or summary.get('completed') != 5:
        raise RuntimeError('The five source videos are not finalized')
    for path in (RUN / 'videos', RUN / 'inputs', RUN / 'cases', RUN / 'evaluation', RUN / 'logs', CONFIG):
        path.mkdir(parents=True, exist_ok=True)
    records = []
    for cid in IDS:
        item = summary['cases'][cid]
        video = Path(item['video'])
        if sha(video) != item['sha256']:
            raise RuntimeError('Source video changed: ' + cid)
        frozen = RUN / 'videos' / (cid + '.mp4')
        if frozen.exists():
            if sha(frozen) != item['sha256']:
                raise RuntimeError('Frozen video changed: ' + cid)
        else:
            shutil.copy2(video, frozen)
        folder = RUN / 'inputs' / cid
        folder.mkdir(exist_ok=True)
        original = read(BATCH / cid / 'original.json')
        plan = read(BATCH / cid / 'plan.json')
        dump(folder / 'source.json', original)
        dump(folder / 'plan.json', plan)
        dump(folder / 'storyboard.json', [{'shot_id': s['shot_id'], 'duration_sec': s['duration_sec'], 'description': s['description']} for s in plan['shots']])
        (folder / 'benchmark_prompt.txt').write_text(original['main_instruction'] + '\n目标总时长：' + str(original['duration_sec']) + '秒。\n原始多模态要求：\n' + json.dumps(original['modality_details'], ensure_ascii=False, indent=2) + '\n')
        (folder / 'script.txt').write_text('\n\n'.join(f"片段{s['shot_id']}（{s['duration_sec']}秒）\n{s['description']}" for s in plan['shots']) + '\n')
        sid = read(BATCH / cid / 'session.json')['session_id']
        source_clips = ROOT / 'video-claw/video-claw/backend/code/result/video' / sid
        clips = []
        for shot in plan['shots']:
            source = source_clips / f'seg_1_{shot["shot_id"]}.mp4'
            target = RUN / 'cases' / cid / f'shot_{shot["shot_id"]:02d}.mp4'
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            if sha(source) != sha(target):
                raise RuntimeError('Clip changed: ' + str(source))
            clips.append({'shot_id': shot['shot_id'], 'path': str(target), 'sha256': sha(target)})
        dump(RUN / 'cases' / cid / 'generation.json', {'status': 'GENERATED', 'baseline': 'VideoClaw fast preview', 'video': str(frozen), 'sha256': item['sha256'], 'source_session': sid, 'clips': clips})
        records.append({'case_id': cid, 'duration_sec': original['duration_sec'], 'shots': len(plan['shots']), 'sample_path': str(folder), 'video_sha256': item['sha256']})
    source_config = ROOT / 'configs/codex_original_720p'
    for name in ('directorbench_profiles.json', 'directorbench_registry.json', 'evaluation_units.json', 'vbench_prompts.json'):
        shutil.copy2(source_config / name, CONFIG / name)
    protocol = read(source_config / 'evaluation_protocol.json')
    protocol['selected_families'] = FAMILIES
    protocol['short_drama'] = {'status': 'SKIPPED_BY_USER'}
    protocol['generation'].update(baseline='VideoClaw fast preview', image_model='wan2.7-image', source_batch=str(BATCH))
    protocol['reproducibility']['validity_audit'] = str(RUN / 'evaluation/summary.json')
    protocol['vbench']['parity_validation'] = 'New native-versus-streaming parity check on a two-second excerpt from this frozen batch'
    dump(CONFIG / 'evaluation_protocol.json', protocol)
    dump(CONFIG / 'manifest.json', {'cases': records, 'total_duration_sec': 469, 'total_shots': 22, 'selected_families': FAMILIES, 'judge': 'qwen3.5-omni-plus', 'short_drama': 'SKIPPED_BY_USER'})
    previous = ROOT / 'experiments/codex_original_720p/evaluation'
    asr = read(previous / 'asr_environment.json')
    asr['local_model_path'] = str(ROOT / '.cache/faster-whisper-large-v3')
    if not (Path(asr['local_model_path']) / 'model.bin').is_file():
        raise RuntimeError('Validated Whisper checkpoint missing')
    dump(RUN / 'evaluation/asr_environment.json', asr)
    environment = read(previous / 'vistory_environment.json')
    environment.update(python=RUNTIMES['vistorybench'], source=str(ROOT / 'benchmarks/vistorybench'))
    dump(RUN / 'evaluation/vistory_environment.json', environment)
    dump(RUN / 'evaluation/mobileviclip_environment.json', read(previous / 'mobileviclip_environment.json'))
    files = [SCRIPTS / name for name in ('eval_director.py', 'vbench_full.py', 'eval_vistory.py', 'eval_media.py', 'director_metric_policy.py')]
    dump(RUN / 'evaluation/provenance.json', {'baseline': 'VideoClaw', 'source_batch': str(BATCH), 'frozen_at': time.time(), 'files': {str(p): sha(p) for p in files}, 'source_videos': records, 'no_previous_scores_reused': True, 'short_drama': 'SKIPPED_BY_USER'})
    excerpt = RUN / 'evaluation/vbench_parity/input.mp4'
    if not excerpt.exists():
        excerpt.parent.mkdir(exist_ok=True)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(RUN / 'videos/action_006.mp4'), '-t', '2', '-an', '-c:v', 'libx264', '-preset', 'fast', '-threads', '2', '-y', str(excerpt)], check=True)
    print('PREPARED', RUN, '5 videos / 22 frozen source clips', flush=True)


def gpu_acquire(label):
    required = 12000 if label.startswith('vbench') else 10000
    while True:
        with GPU_CONDITION:
            rows = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.free,utilization.gpu', '--format=csv,noheader,nounits'], text=True)
            choices = []
            for line in rows.splitlines():
                index, free, util = [int(x.strip()) for x in line.split(',')]
                claims = GPU_CLAIMS.get(index, [])
                reserved = sum(x[1] for x in claims)
                if len(claims) >= 2:
                    continue
                if free - reserved >= required + 7000 and (util < 25 or claims):
                    choices.append((free - reserved, index))
            if choices:
                index = max(choices)[1]
                GPU_CLAIMS.setdefault(index, []).append((label, required))
                return index
            GPU_CONDITION.wait(15)


def gpu_release(label, index):
    with GPU_CONDITION:
        GPU_CLAIMS[index] = [x for x in GPU_CLAIMS[index] if x[0] != label]
        GPU_CONDITION.notify_all()


def stage_output_valid(label, family, cid):
    if label == 'vbench_parity':
        return bool(read(RUN / 'evaluation/vbench_parity/parity.json', {}).get('passed'))
    if family == 'vbench':
        value = read(RUN / 'evaluation/vbench/all/full_frame_eval_results.json', {})
        return set(value) == {'subject_consistency', 'background_consistency', 'motion_smoothness'}
    if family == 'directorbench':
        return len(list((RUN / 'evaluation/directorbench' / cid).glob('profile_*/result.json'))) == 7
    return read(RUN / 'evaluation/vistorybench' / cid / 'summary.json', {}).get('status') == 'COMPLETE'


def stage(label, family, cid, script, arguments):
    status_path = RUN / 'evaluation/stages' / (label + '.json')
    previous = read(status_path, {})
    if previous.get('status') == 'COMPLETE':
        return True
    previous_pid = previous.get('pid')
    process_environment = Path(f'/proc/{previous_pid}/environ')
    if previous.get('status') == 'RUNNING' and process_environment.exists():
        try:
            owned = ('LVM_EVALUATION_RUN_ID=' + RUN_ID).encode() in process_environment.read_bytes().split(b'\0')
        except (PermissionError, FileNotFoundError):
            owned = False
        if owned:
            print('ADOPTING_EXISTING_STAGE', label, previous_pid, flush=True)
            while process_environment.exists():
                time.sleep(15)
            previous.update(status='COMPLETE' if stage_output_valid(label, family, cid) else 'FAILED', adopted=True, finished_at=time.time())
            dump(status_path, previous)
            return previous['status'] == 'COMPLETE'
    for attempt in range(3):
        status = {'stage': label, 'family': family, 'case_id': cid, 'status': 'WAITING_GPU', 'updated_at': time.time(), 'attempt': attempt + 1}
        dump(status_path, status)
        index = gpu_acquire(label)
        environment = os.environ.copy()
        environment.update(LVM_EVALUATION_RUN_ID=RUN_ID, LVM_EVALUATION_CONFIG_ID=RUN_ID,
                           CUDA_VISIBLE_DEVICES=str(index), OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
                           HF_ENDPOINT='https://hf-mirror.com', HF_HOME='/mnt/data/bts/models/hf', TORCH_HOME='/mnt/data/bts/models/torch')
        log_path = RUN / 'logs' / (label + '.log')
        try:
            with log_path.open('a') as log:
                process = subprocess.Popen([RUNTIMES[family], '-u', str(script)] + arguments,
                                           cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT)
                status.update(status='RUNNING', gpu=index, pid=process.pid, started_at=time.time(), script_sha256=sha(script), log=str(log_path))
                dump(status_path, status)
                print('STARTED', label, 'GPU', index, 'PID', process.pid, flush=True)
                try:
                    code = process.wait(timeout=8 * 3600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError('Eight-hour stage limit reached; partial evidence retained')
            valid = code == 0 and stage_output_valid(label, family, cid)
            status.update(status='COMPLETE' if valid else 'FAILED', exit_code=code, finished_at=time.time())
        except Exception as exc:
            status.update(status='FAILED', error=str(exc), finished_at=time.time())
        finally:
            gpu_release(label, index)
        pause = read(RUN / 'evaluation/provider_pause.json', {})
        if status['status'] != 'COMPLETE' and pause.get('retry_after', 0) > time.time() and attempt < 2:
            status.update(status='WAITING_PROVIDER', retry_after=pause['retry_after'], provider_reason=pause.get('reason'))
            dump(status_path, status)
            while time.time() < pause['retry_after']:
                time.sleep(min(15, max(.1, pause['retry_after'] - time.time())))
            continue
        dump(status_path, status)
        print('FINISHED', label, status['status'], flush=True)
        return status['status'] == 'COMPLETE'
    return False


def run_family(family):
    if family == 'vbench':
        script = SCRIPTS / 'vbench_full.py'
        if not stage('vbench_parity', family, None, script, ['--videos', str(RUN / 'evaluation/vbench_parity/input.mp4'), '--output', str(RUN / 'evaluation/vbench_parity'), '--parity']):
            return
        stage('vbench_all', family, None, script, ['--videos', str(RUN / 'videos'), '--output', str(RUN / 'evaluation/vbench/all')])
    else:
        script = SCRIPTS / ('eval_director.py' if family == 'directorbench' else 'eval_vistory.py')
        for cid in IDS:
            stage(family + '_' + cid, family, cid, script, ['--case', cid])


def publish():
    states = {p.stem: read(p) for p in (RUN / 'evaluation/stages').glob('*.json')}
    vbench = read(RUN / 'evaluation/vbench/all/full_frame_eval_results.json')
    cases = {}
    for cid in IDS:
        db_results = sorted((RUN / 'evaluation/directorbench' / cid).glob('profile_*/result.json'))
        case = {'directorbench': {'completed_profiles': len(db_results), 'expected_profiles': 7, 'stage': states.get('directorbench_' + cid, {}).get('status', 'QUEUED')},
                'vbench': {'stage': states.get('vbench_all', states.get('vbench_parity', {})).get('status', 'QUEUED')},
                'vistorybench': {'stage': states.get('vistorybench_' + cid, {}).get('status', 'QUEUED')}}
        if vbench:
            case['vbench']['metrics'] = {metric: next((entry.get('video_results') for entry in values[1] if Path(entry.get('video_path', '')).stem == cid), None) for metric, values in vbench.items()}
        vs = read(RUN / 'evaluation/vistorybench' / cid / 'summary.json')
        if vs:
            case['vistorybench']['metrics'] = vs.get('metrics')
        if db_results:
            profiles = []
            for path in db_results:
                value = read(path)
                profiles.append({'profile_id': value['profile_id'], 'overall_score': value['report'].get('overall_score')})
            case['directorbench']['profiles'] = profiles
        cases[cid] = case
    finished = len([s for s in states.values() if s.get('status') == 'COMPLETE'])
    failed = [name for name, state in states.items() if state.get('status') == 'FAILED']
    data = {'run_id': RUN_ID, 'updated_at': time.time(), 'selected_families': FAMILIES, 'short_drama': 'SKIPPED_BY_USER',
            'judge': 'qwen3.5-omni-plus', 'completed_stages': finished, 'expected_stages': 12,
            'failed_stages': failed, 'stages': states, 'cases': cases,
            'validity_notes': ['Five-prompt protocol variant, not full benchmark datasets.',
                               'DirectorBench BGM is SKIPPED_BY_USER.',
                               'MobileViCLIP official checkpoint is unavailable; inspect DirectorBench tool traces for provisional fallback evidence.',
                               'ViStoryBench character metrics are NA on character-free educational content; generated anchors assess identity stability, not external identity fidelity.']}
    dump(RUN / 'evaluation/summary.json', data)
    dump(PUBLISH / 'summary.json', data)
    rows = []
    for cid, values in cases.items():
        rows.append('<tr><td>' + cid + '</td><td>' + str(values['directorbench']['completed_profiles']) + '/7 · ' + values['directorbench']['stage'] + '</td><td>' + values['vbench']['stage'] + '</td><td>' + values['vistorybench']['stage'] + '</td></tr>')
    PUBLISH.mkdir(parents=True, exist_ok=True)
    (PUBLISH / 'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta http-equiv="refresh" content="30"><title>VideoClaw 评测</title><style>body{font:16px system-ui;margin:32px;background:#10141c;color:#eee}td,th{padding:12px;border-bottom:1px solid #555}a{color:#86c8ff}</style><h1>VideoClaw 五样例评测</h1><p>DirectorBench · VBench 3 项 · ViStoryBench 4 项；Short-Drama 已跳过。</p><p>裁判 qwen3.5-omni-plus；BGM 跳过；工具缺口及 NA 单独记录。</p><table><tr><th>案例</th><th>DirectorBench</th><th>VBench</th><th>ViStoryBench</th></tr>' + ''.join(rows) + '</table><p><a href="summary.json">完整状态与当前评分 JSON</a></p><p>页面每30秒刷新。执行完成不等于完整论文复现或所有工具证据完备。</p></html>')
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run', 'status'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
        publish()
        return
    if args.command == 'status':
        print(json.dumps(read(RUN / 'evaluation/summary.json'), ensure_ascii=False, indent=2))
        return
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN / 'evaluation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not (RUN / 'evaluation/provenance.json').exists():
            prepare()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(run_family, name) for name in ('vbench', 'directorbench', 'vistorybench')]
            while not all(job.done() for job in jobs):
                publish()
                time.sleep(15)
            for job in jobs:
                job.result()
        status = publish()
        dump(RUN / 'evaluation/finished.json', {'status': 'COMPLETE_WITH_VALIDITY_NOTES' if not status['failed_stages'] else 'PARTIAL_FAILURE', 'failed_stages': status['failed_stages'], 'finished_at': time.time()})


if __name__ == '__main__':
    main()
