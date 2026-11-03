"""Run the current memory pipeline on a VideoClaw session; freeze source before execution."""
import argparse
import asyncio
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import importlib
import fcntl
import sys
import time
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)

def assemble(run, records):
    output = run / 'videos'
    output.mkdir(exist_ok=True)
    parts = []
    for record in records:
        source = record['video']['path']
        part = output / ('part-%03d.mp4' % record['index'])
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', source], text=True))
        audio = any((s['codec_type'] == 'audio' for s in probe['streams']))
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', source]
        if not audio:
            command += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
        command += ['-map', '0:v:0', '-map', '0:a:0' if audio else '1:a:0', '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1', '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-t', str(record['segment']['duration']), '-movflags', '+faststart', str(part)]
        subprocess.run(command, check=True)
        parts.append(part)
    concat = output / 'concat.txt'
    concat.write_text(''.join(("file '%s'\n" % p.name for p in parts)))
    final = output / 'final.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(final)], check=True)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(final)], text=True))
    expected = sum((r['segment']['duration'] for r in records))
    if abs(float(probe['format']['duration']) - expected) > 1:
        raise ValueError('Final duration mismatch')
    save(run / 'final_probe.json', probe)
    return str(final)

def usage(run):
    judges = []
    for path in (run / 'memory').glob('**/judge_calls/*/response.json'):
        d = json.loads(path.read_text())
        values = [c['usage'] for c in d.get('chunks', []) if c.get('usage')]
        judges.append({'path': str(path), 'model': d.get('model'), 'usage': values[-1] if values else None})
    tasks = [json.loads(p.read_text()) for p in (run / 'tasks').glob('*.json') if not p.name.endswith('.response.json')]
    images = [json.loads(p.read_text()) for p in (run / 'meter/calls').glob('*.json')]
    save(run / 'usage.json', {'judge_calls': judges, 'video_tasks': tasks, 'image_calls': images, 'pricing': 'Raw usage; no complete account-bill estimate claimed'})

def timing_report(run):
    import sqlite3
    database = run / 'memory/artifacts.sqlite3'
    totals, counts = ({}, {})
    if database.exists():
        with sqlite3.connect(str(database)) as db:
            for raw, in db.execute("SELECT data FROM events WHERE kind='phase'"):
                record = json.loads(raw)
                name = record['name']
                if name == 'operation':
                    name += ':' + record['metadata']['key'].split('/', 1)[0]
                totals[name] = totals.get(name, 0) + record['elapsed_seconds']
                counts[name] = counts.get(name, 0) + 1
    transport = [json.loads(p.read_text()) for p in (run / 'timing/transport').glob('*.json')]
    save(run / 'timing.json', {'phase_seconds': totals, 'phase_counts': counts, 'judge_queue_wait_seconds': sum((r['queue_wait_seconds'] for r in transport)), 'judge_request_seconds': sum((r['request_seconds'] for r in transport)), 'notes': 'Aggregated durations overlap across threads and nested phases; do not sum as wall time.'})

async def execute(run, snapshot, policy, integration='unified', stages=None, judge_concurrency=1, pacing_directory=None):
    import videoclaw_runtime as runtime
    runtime.RUN = run
    runtime.configure()
    from aard_qwen_pacing import install as install_pacing
    install_pacing(pacing_directory or ROOT / 'experiments/aard_shared_qwen_queue', max_concurrent=judge_concurrency, metrics_directory=run / 'timing/transport')
    import videoclaw_fast
    old = videoclaw_fast.install
    videoclaw_fast.install = lambda: None
    try:
        runtime.install_adapters(enable_last_frame=True)
    finally:
        videoclaw_fast.install = old
    from config import Config
    Config.PRINT_MODEL_INPUT = False
    from generation_meter import Meter
    meter = Meter(run)
    meter.stage = 'aard_video_generation'
    meter.install()
    from core.orchestrator import WorkflowEngine, WorkflowStage
    from memory import MemoryController
    from memory.adapters.videoclaw import install
    from memory.adapters.videoclaw import VideoClawBackend

    class Engine(WorkflowEngine):

        def _load_sessions_from_disk(self):
            pass
    engine = Engine()
    engine._session_dir = str(run / 'sessions')
    Path(engine._session_dir).mkdir(exist_ok=True)
    sid = 'aard_' + hashlib.sha256(str(run).encode()).hexdigest()[:16]
    engine.create_session(sid, snapshot['meta'])
    state = engine.get_state(sid)
    state.artifacts = copy.deepcopy(snapshot['artifacts'])
    handle = install(engine, sid, run / 'memory', policy)

    def progress(*args, **kwargs):
        handle.sync(state)
        snapshot = handle.memory.snapshot()
        save(run / 'status.json', {'status': 'RUNNING', 'integration': integration, 'committed': len([v for v in snapshot['M'] if not v['stale']]), 'updated_at': time.time()})
        return
    for stage_name in stages or ['video_generation']:
        await engine.execute_stage(state, WorkflowStage(stage_name), {'session_id': sid}, progress_callback=progress)
        save(run / 'session_progress.json', {'meta': state.meta, 'artifacts': state.artifacts})
        if stage_name == 'reference_generation':
            scenes = state.artifacts.get('reference_generation', {}).get('scenes', [])
            missing = [item.get('id', 'unknown') for item in scenes if not item.get('selected') or not Path(item['selected']).is_file()]
            if not scenes or missing:
                save(run / 'stage_failure.json', {'stage': stage_name, 'missing_selected_scenes': missing, 'reason': 'Reference stage incomplete; video stage was not dispatched'})
                raise RuntimeError('Reference stage incomplete; no video dispatch. Missing selected scenes: ' + repr(missing))
    from memory.assets.store import MemoryStore as UnifiedStore
    handle.sync(state)
    with UnifiedStore(run / 'memory', sid) as store:
        records = copy.deepcopy(store.data['committed'])
        expected = len(store.data['inputs']['segments'])
        from memory.assets.files import digest
        delivery = store.data.get('delivery', {})
        if delivery.get('status') not in ('passed', 'local_only') or delivery.get('selection') != digest([r['video'] for r in records]):
            raise RuntimeError('Current sequence has no valid delivery receipt; export blocked')
        if len(records) != expected or any((v['stale'] for v in store.selected(True))):
            raise RuntimeError('Incomplete or stale Memory selections; export blocked')
        if any((not r['accepted'] for r in records)):
            raise RuntimeError('Unverified selection; export blocked')
    handle()
    final = assemble(run, records)
    save(run / 'result.json', {'video': final, 'segments': records, 'quality_passed_segments': sum((r['accepted'] for r in records)), 'scope': integration + ': A2RD-inspired memory; not an official benchmark score'})
    save(run / 'status.json', {'status': 'COMPLETED', 'video': final, 'committed': len(records), 'quality_passed': sum((r['accepted'] for r in records)), 'updated_at': time.time()})

def activate_snapshot(run):
    """Freeze once, then require matching source/host hashes on every resume."""
    directory = run / 'source'
    manifest = directory / 'provenance.json'
    host_names = ('run_memory.py', 'videoclaw_runtime.py', 'msvbench_qwen.py', 'generation_meter.py', 'videoclaw_fast.py', 'aard_qwen_pacing.py', 'rate_limit_policy.py')
    if not manifest.exists():
        if directory.exists():
            raise RuntimeError('Incomplete source snapshot; inspect before reusing this run')
        directory.mkdir()
        shutil.copytree(ROOT / 'memory', directory / 'memory', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (directory / 'host_scripts').mkdir()
        for name in host_names:
            shutil.copy2(ROOT / 'scripts' / name, directory / 'host_scripts' / name)
        save(manifest, {'created_at': time.time(), 'memory': {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (directory / 'memory').rglob('*.py')}, 'host': {name: hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest() for name in host_names}})
    provenance = json.loads(manifest.read_text())
    for relative, expected in provenance['memory'].items():
        if hashlib.sha256((directory / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen memory source changed: ' + relative)
    for name, expected in provenance['host'].items():
        if hashlib.sha256((ROOT / 'scripts' / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Host transport changed; use a new run or matching archived host: ' + name)
    sys.path.insert(0, str(directory))
    package = importlib.import_module('memory')
    if Path(package.__file__).resolve() != directory / 'memory/__init__.py':
        raise RuntimeError('A different memory package was already imported')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--integration', choices=['unified'], default='unified')
    parser.add_argument('--max-candidates', type=int, default=2)
    parser.add_argument('--reference-candidates', type=int, default=2)
    parser.add_argument('--no-mapo', action='store_true')
    parser.add_argument('--fresh-reference-images', action='store_true')
    parser.add_argument('--stages', nargs='+', choices=['reference_generation', 'video_generation'], default=['video_generation'])
    parser.add_argument('--judge-concurrency', type=int, choices=[1, 2], default=1)
    parser.add_argument('--pacing-directory', type=Path)
    parser.add_argument('--selection', choices=['strict', 'best_available'], default='strict')
    parser.add_argument('--experience-repository', type=Path)
    parser.add_argument('--allow-unverified-state', action='store_true', help='Explicitly relax the default critical-state gate; defects remain recorded')
    args = parser.parse_args()
    source, run = (args.session.resolve(strict=True), args.run.resolve())
    run.mkdir(parents=True, exist_ok=True)
    with (run / 'source.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        activate_snapshot(run)
    from memory import Policy
    from memory.assets.checkpoint import Checkpoint as MemoryStore
    snapshot = json.loads(source.read_text())
    policy = Policy(frame_candidates=args.max_candidates, video_candidates=args.max_candidates, reference_candidates=args.reference_candidates, fresh_reference_images=args.fresh_reference_images, selection=args.selection, critical_state_gate=not args.allow_unverified_state, experience_repository=str(args.experience_repository.resolve()) if args.experience_repository else '')
    config = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'policy': asdict(policy), 'integration': args.integration, 'stages': args.stages, 'judge_concurrency': args.judge_concurrency, 'pacing_directory': str(args.pacing_directory.resolve()) if args.pacing_directory else None, 'selection_semantics': 'Best candidate can retain explicitly reported defects'}
    with MemoryStore(run / 'runner_lock'):
        if (run / 'config.json').exists() and json.loads((run / 'config.json').read_text()) != config:
            raise ValueError('Frozen run configuration changed')
        save(run / 'config.json', config)
        if not args.execute:
            print(json.dumps({'prepared': str(run), 'api_calls': 0}))
            return
        save(run / 'status.json', {'status': 'RUNNING', 'updated_at': time.time()})
        try:
            asyncio.run(execute(run, snapshot, policy, args.integration, args.stages, args.judge_concurrency, args.pacing_directory.resolve() if args.pacing_directory else None))
        except BaseException as exc:
            save(run / 'status.json', {'status': 'BLOCKED', 'error_type': type(exc).__name__, 'detail': str(exc)[:500], 'updated_at': time.time()})
            raise
        finally:
            usage(run)
            timing_report(run)
if __name__ == '__main__':
    main()
