"""Five concurrent DirectorBench previews using VideoClaw's asset/video/edit agents."""
import concurrent.futures
import fcntl
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'video-claw/video-claw/backend'
BASE = ROOT / 'experiments/videoclaw_batch_fast'
IDS = ['action_006', 'cinematic_008', 'educational_008', 'music_004', 'narrative_074']
API = 'http://127.0.0.1:8000'
MUTEX = threading.RLock()
SESSION_LOCK = threading.Lock()
ASSETS = {
 'action_006': ('写实动作电影', [('英雄', '成年东亚男青年，短黑发，深蓝短夹克、灰色T恤、黑裤、白鞋'), ('逃跑者', '成年男子，红色连帽夹克、黑裤、黑鞋')], [('连续城市屋顶', '相邻的灰色平屋顶，固定水箱、通风管、铁栏杆，傍晚高反差光，空场景，不含人物')]),
 'cinematic_008': ('写实电影，黄金时刻暖金色', [('女性', '成年女性，短黑发，米色长风衣')], [('城市街道', '安静城市街道，石质建筑、固定路灯和长椅，左后方夕阳与长阴影，空场景，不含人物')]),
 'educational_008': ('二维矢量电力科普动画，明亮蓝白科技UI', [], [('业务中台图纸', '业务资源建模界面，白底蓝色UI，极I红色、极II蓝色、主线黄色，杆塔和档距段简洁示意；不是电气接线图，不含人物')]),
 'music_004': ('原创电子音乐MV，霓虹紫蓝舞台', [('歌手', '成年东亚女歌手，银白短发、黑色短款舞台夹克、紫色内搭、黑色长裤')], [('霓虹舞台', '固定紫蓝霓虹舞台、几何灯墙与演唱区域，空场景，不含人物')]),
 'narrative_074': ('暗黑3D动画，Q版软萌与赛博战斗反差', [('企鹅女孩', 'Q版企鹅主题女孩，大黑眼睛、黑白企鹅连帽服、短小橙色脚、粉色小围裙，仅展示日常形态，不混入战斗装备，非写实真人'), ('奶牛猫', 'Q版3D黑白奶牛猫，白色毛、黑左耳、右眼周黑斑、黑尾巴，仅展示同一只猫的视图，无血迹或伤口')], [('日系公寓', '暖色日系小公寓厨房，窗在灶台右侧、木色台面、奶白色锅、三文鱼粥、小凳子，空场景，无任何人物'), ('城市上空', '灰暗城市、居民楼与屋顶，战斗电蓝高反差光，空场景，不含猫或人物')]),
}


def dump(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with MUTEX:
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        temp.replace(path)


def api(method, path, body=None):
    response = requests.request(method, API + path, json=body, timeout=60)
    response.raise_for_status()
    return response.json()


def execute(folder, sid, stage, intervention=None):
    dump(folder / 'status.json', {'status': 'RUNNING', 'stage': stage, 'session_id': sid, 'updated_at': time.time()})
    url = f'/api/project/{sid}/execute/{stage}'
    body = {'resolution': '720P'}
    if intervention:
        url = f'/api/project/{sid}/intervene'
        body = {'stage': stage, 'modifications': intervention}
    print(folder.name, stage, 'import' if intervention else 'generate', flush=True)
    with requests.post(API + url, json=body, stream=True, timeout=(30, 3600)) as response:
        response.raise_for_status()
        with (folder / f'{stage}.sse').open('a') as log:
            for line in response.iter_lines():
                if line:
                    log.write(line.decode(errors='replace') + '\n')
                    log.flush()
    state = api('GET', f'/api/project/{sid}/status')
    dump(folder / f'{stage}.json', state['artifacts'].get(stage, {}))
    if state.get('error') or state['status'].get(stage) in ('error', 'stopped'):
        raise RuntimeError(state.get('error') or state['status'][stage])
    return state['artifacts'].get(stage, {})


def selected(artifact, keys, count=None):
    entries = [e for key in keys for e in artifact.get(key, [])]
    if not entries or (count is not None and len(entries) != count):
        raise RuntimeError('Incomplete asset list')
    for entry in entries:
        path = entry.get('selected')
        if not path or not (BACKEND / path).is_file():
            raise RuntimeError(f'Missing selected asset: {entry.get("id")}')
    return entries


def validate(path, seconds):
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], text=True))
    video = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
    audio = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
    if not video or not audio or video['width'] != 1280 or video['height'] != 720 or abs(float(probe['format']['duration']) - seconds) > .5:
        raise RuntimeError(f'Media validation failed: {path}')
    return probe


def run_case(batch, cid, record):
    folder = batch / cid
    folder.mkdir(exist_ok=True)
    sid = None
    try:
        if (folder / 'status.json').exists() and json.loads((folder / 'status.json').read_text()).get('status') == 'PASSED':
            return
        source_plan = ROOT / 'experiments/codex_original_720p/inputs' / cid / 'plan.json'
        plan = json.loads(source_plan.read_text())
        assert sum(s['duration_sec'] for s in plan['shots']) == record['duration_sec']
        dump(folder / 'original.json', record)
        dump(folder / 'plan.json', plan)
        dump(folder / 'provenance.json', {'benchmark_source': 'benchmarks/directorbench/data/metadata/dataset_original.jsonl', 'supplemental_plan': str(source_plan), 'plan_sha256': hashlib.sha256(source_plan.read_bytes()).hexdigest(), 'mode': 'VideoClaw fast preview: import supplied shots; single-version images; no automatic quality redraw; original durations preserved', 'image_model': 'wan2.7-image', 'video_model': 'wan3.0-video'})
        style, chars, settings = ASSETS[cid]
        payload = {'idea': f'DirectorBench fast preview {cid}\n' + record['main_instruction'], 'style': style,
                   'video_ratio': '16:9', 'video_resolution': '720P', 'episodes': 1,
                   'expand_idea': False, 'llm_model': 'qwen3.7-plus', 'vlm_model': 'qwen3-vl-plus',
                   'image_t2i_model': 'wan2.7-image', 'image_it2i_model': 'wan2.7-image',
                   'video_model': 'wan3.0-video', 'video_first_frame_model': 'wan3.0-video',
                   'video_generation_mode': 'first_frame', 'enable_concurrency': True, 'web_search': False}
        dump(folder / 'request.json', payload)
        if (folder / 'session.json').exists():
            sid = json.loads((folder / 'session.json').read_text())['session_id']
        else:
            with SESSION_LOCK:
                session = api('POST', '/api/project/start', payload)
                time.sleep(.02)
            sid = session['session_id']
            dump(folder / 'session.json', session)
        with MUTEX:
            registry_path = BASE / 'fast_sessions.json'
            registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
            registry[sid] = {'run': str(folder), 'case_id': cid}
            dump(registry_path, registry)
        character_data = [{'character_id': f'char_{i}', 'name': name, 'description': desc, 'species': '幻想角色' if cid == 'narrative_074' else '人类'} for i, (name, desc) in enumerate(chars, 1)]
        settings_data = [{'setting_id': f'set_{i}', 'name': name, 'description': desc} for i, (name, desc) in enumerate(settings, 1)]
        content = '\n\n'.join(f"片段{s['shot_id']}（{s['duration_sec']}秒）：{s['description']}" for s in plan['shots'])
        script = {'project_id': 'proj_' + sid, 'session_id': sid, 'title': cid,
                  'meta': {'original_text': content, 'benchmark_input_locked': True, 'fast_preview': True},
                  'characters': character_data, 'settings': settings_data,
                  'episodes': [{'episode_number': 1, 'act_title': cid, 'content': content}]}
        if not (folder / 'script_generation.json').exists():
            execute(folder, sid, 'script_generation', {'modified_script': script})
        if not (folder / 'character_design.done').exists():
            artifact = execute(folder, sid, 'character_design')
            selected(artifact, ['characters', 'settings'])
            (folder / 'character_design.done').touch()
        segments = []
        for index, shot in enumerate(plan['shots']):
            location = settings[-1][0] if cid == 'narrative_074' and index >= 3 else settings[0][0]
            segments.append({'segment_id': f'seg_1_{index+1}', 'segment_number': index+1,
                             'total_duration': shot['duration_sec'], 'location': location,
                             'characters': [c['name'] for c in character_data],
                             'scene_context': shot['description'],
                             'shots': [{'shot_number': 1, 'duration': shot['duration_sec'], 'shot_type': '按原始镜头要求',
                                        'content': plan['bible'] + '\n本片段：' + shot['description']}]})
        if not (folder / 'storyboard.json').exists():
            execute(folder, sid, 'storyboard', {'modified_storyboard': [{'episode_number': 1, 'episode_title': cid, 'segments': segments}]})
        if not (folder / 'reference_generation.done').exists():
            artifact = execute(folder, sid, 'reference_generation')
            selected(artifact, ['scenes'], len(segments))
            (folder / 'reference_generation.done').touch()
        if not (folder / 'video_generation.done').exists():
            artifact = execute(folder, sid, 'video_generation')
            clips = selected(artifact, ['clips'], len(segments))
            by_id = {c['id']: c for c in clips}
            for segment in segments:
                validate(BACKEND / by_id[segment['segment_id']]['selected'], segment['total_duration'])
            (folder / 'video_generation.done').touch()
        if not (folder / 'post_production.json').exists():
            execute(folder, sid, 'post_production')
        output = BACKEND / 'code/result/video' / sid / 'output' / f'{sid}_ep1.mp4'
        probe = validate(output, record['duration_sec'])
        final = BACKEND / 'code/result/batches' / batch.name / f'{cid}.mp4'
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, final)
        dump(folder / 'probe.json', probe)
        dump(folder / 'status.json', {'status': 'PASSED', 'stage': 'completed', 'session_id': sid,
             'duration_sec': float(probe['format']['duration']), 'video': str(final),
             'video_url': f'http://127.0.0.1:8000/code/result/batches/{batch.name}/{cid}.mp4',
             'sha256': hashlib.sha256(final.read_bytes()).hexdigest(), 'updated_at': time.time(),
             'scope': 'Technical preview only; see VLM warnings in server.log; no benchmark quality scores'})
        print(cid, 'PASSED', final, flush=True)
    except Exception as exc:
        previous = json.loads((folder / 'status.json').read_text()) if (folder / 'status.json').exists() else {}
        previous.update(status='FAILED', session_id=sid, error=str(exc), updated_at=time.time())
        dump(folder / 'status.json', previous)
        print(cid, 'FAILED', str(exc), flush=True)


def publish(batch):
    cases = {}
    cards = []
    for cid in IDS:
        path = batch / cid / 'status.json'
        state = json.loads(path.read_text()) if path.exists() else {'status': 'PREPARING'}
        sid = state.get('session_id')
        clips = []
        images = []
        clips_total = 0
        if sid:
            try:
                snapshot = api('GET', f'/api/project/{sid}/status')
                all_clips = snapshot.get('artifacts', {}).get('video_generation', {}).get('clips', [])
                clips = [c for c in all_clips if c.get('selected')]
                clips_total = len(all_clips)
                images = snapshot.get('artifacts', {}).get('reference_generation', {}).get('scenes', [])
            except requests.RequestException:
                pass
        state['clips_ready'] = len(clips)
        state['clips_total'] = clips_total
        state['reference_images_ready'] = sum(bool(i.get('selected')) for i in images)
        state['reference_images_total'] = len(images)
        cases[cid] = state
        links = ''.join(f'<p><a href="/{html.escape(c["selected"])}">片段 {html.escape(c["id"])}</a></p>' for c in clips)
        video = f'<video controls preload="metadata" src="{cid}.mp4"></video>' if state['status'] == 'PASSED' else ''
        cards.append(f'<article><h2>{cid}</h2><p>{html.escape(state["status"])} · {html.escape(state.get("stage", ""))} · {len(clips)} 个片段完成</p>{video}{links}<p>{html.escape(state.get("error", ""))}</p></article>')
    done = sum(s['status'] == 'PASSED' for s in cases.values())
    terminal = all(s['status'] in ('PASSED', 'FAILED') for s in cases.values())
    summary = {'status': 'PASSED' if done == 5 else ('PARTIAL_FAILURE' if terminal else 'RUNNING'), 'completed': done, 'total': 5, 'cases': cases, 'updated_at': time.time()}
    dump(batch / 'summary.json', summary)
    gallery = BACKEND / 'code/result/batches' / batch.name / 'index.html'
    gallery.parent.mkdir(parents=True, exist_ok=True)
    gallery.write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta http-equiv="refresh" content="10"><title>VideoClaw 五样例预览</title><style>body{font:16px system-ui;background:#10141c;color:#eee;margin:32px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}article{background:#1e2532;padding:20px;border-radius:12px}video{width:100%}a{color:#86c8ff}</style><h1>VideoClaw · DirectorBench 五样例</h1><p>wan2.7-image → wan3.0-video · 720P · 并发预览 · ' + str(done) + '/5 成片完成</p><p>单版素材优先出片；技术校验与内容质量分开记录。每10秒刷新。</p><main>' + ''.join(cards) + '</main></html>')
    return terminal


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    batch = BASE / '20261016_wan27_preview'
    batch.mkdir(exist_ok=True)
    dump(BASE / 'latest.json', {'run': str(batch), 'gallery_url': f'http://127.0.0.1:8000/code/result/batches/{batch.name}/index.html'})
    records = {r['meta_id']: r for r in map(json.loads, (ROOT / 'benchmarks/directorbench/data/metadata/dataset_original.jsonl').read_text().splitlines())}
    dump(batch / 'manifest.json', {'cases': IDS, 'total_duration_sec': sum(records[c]['duration_sec'] for c in IDS), 'image_model': 'wan2.7-image', 'video_model': 'wan3.0-video', 'case_concurrency': 5, 'image_concurrency': 3, 'image_start_interval_sec': 3, 'video_concurrency': 6, 'single_version_images': True})
    with (batch / 'batch.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            jobs = [pool.submit(run_case, batch, cid, records[cid]) for cid in IDS]
            while not all(job.done() for job in jobs):
                publish(batch)
                time.sleep(5)
            for job in jobs:
                job.result()
        publish(batch)


if __name__ == '__main__':
    main()
