"""Run the DirectorBench narrative_074 case through the local VideoClaw API."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'video-claw/video-claw/backend'
RUN = ROOT / 'experiments/videoclaw_smoke/narrative_074'
API = 'http://127.0.0.1:8000'
RUN.mkdir(parents=True, exist_ok=True)


def dump(path, value):
    p = RUN / path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)


def api(method, path, body=None):
    rsp = requests.request(method, API + path, json=body, timeout=90)
    rsp.raise_for_status()
    return rsp.json()


def event(message):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), message, flush=True)


def execute(sid, stage, body=None, intervention=None):
    dump('status.json', {'status': 'RUNNING', 'stage': stage, 'session_id': sid, 'updated_at': time.time()})
    endpoint = f'/api/project/{sid}/execute/{stage}'
    if intervention:
        endpoint = f'/api/project/{sid}/intervene'
        body = {'stage': stage, 'modifications': intervention}
    event(('Intervene ' if intervention else 'Execute ') + stage)
    with requests.post(API + endpoint, json=body or {}, stream=True, timeout=(30, 2400)) as rsp:
        rsp.raise_for_status()
        with (RUN / 'logs' / f'{stage}{"_locked" if intervention else ""}.sse').open('a') as log:
            for line in rsp.iter_lines():
                if line:
                    log.write(line.decode(errors='replace') + '\n')
                    log.flush()
    snapshot = api('GET', f'/api/project/{sid}/status')
    dump(f'artifacts/{stage}{"_locked" if intervention else "_native"}.json', snapshot)
    if snapshot.get('error') or snapshot['status'].get(stage) in ('error', 'stopped'):
        raise RuntimeError(snapshot.get('error') or snapshot['status'][stage])
    return snapshot['artifacts'].get(stage, {})


def lock_script(record, native):
    text = record['modality_details']['text']
    visual = record['modality_details']['visual']
    script_map = {s['shot_id']: s for s in text['script']}
    lines = ['第1集 narrative_074', record['main_instruction']]
    for shot in visual['shots']:
        spoken = script_map[shot['shot_id']]
        lines += [f"镜头{shot['shot_id']}（{spoken['duration_sec']}秒）：{shot['description']}"]
        if spoken.get('dialogue'):
            lines += ['企鹅女孩：' + spoken['dialogue']]
    # Keep the original story resolution in the instruction, although shot 5 is less explicit.
    lines += ['结局要求：' + text['story_arc']['act3_resolution']]
    content = '\n'.join(lines)
    native['meta']['original_text'] = content
    native['meta']['benchmark_input_locked'] = True
    native['meta']['benchmark_asset_contract'] = 2
    native['characters'] = [
        {'character_id': 'char_bench_penguin', 'name': '企鹅女孩', 'species': 'Q版幻想角色',
         'description': '暗黑3D动画中的Q版企鹅女孩，企鹅服造型，头大身小的软萌卡通比例，日常形态围粉色小围裙，带小尾巴。变身后仍是同一角色，换成赛博风衣、战术眼镜和蓝色能量光刃。保留企鹅主题幻想角色设定，不改为写实成年女性或普通紧身衣人物。此资产展示日常形态，战斗形态在后续参考图中依据原始镜头变化。'},
        {'character_id': 'char_bench_cat', 'name': '巨型奶牛猫', 'species': '猫',
         'description': '暗黑3D动画中的黑白奶牛猫，巨型形态体型超过楼房，黑白相间的奶牛猫毛色，夸张但清晰的猫科身体轮廓。结尾缩小为同一花色的普通小奶猫。保持Q版动画风格，不按写实人类身体比例检查。'}]
    native['settings'] = [
        {'setting_id': 'set_bench_kitchen', 'name': '企鹅女孩公寓厨房', 'location_type': '室内',
         'description': '暗黑3D动画中的暖色日系普通小公寓厨房，台面摆三文鱼和大米，小凳子、煮粥的锅和可以看到对面城市居民楼的窗户。无人物的场景全景参考图，温暖柔和的日常光线。'},
        {'setting_id': 'set_bench_city', 'name': '灾变城市上空', 'location_type': '室外',
         'description': '暗黑3D动画城市，灰暗天空和遭到巨型猫破坏的居民楼，破碎城市轮廓；空中赛博战斗采用亮蓝电光、彩色粒子和高对比动态照明。无角色的场景全景参考图。'}]
    native['episodes'] = [{'episode_number': 1, 'act_title': 'narrative_074', 'content': content}]
    return native


def lock_storyboard(record, native, script):
    original = record['modality_details']
    spoken = {s['shot_id']: s for s in original['text']['script']}
    planned = [s for ep in native.get('episodes', []) for s in ep.get('segments', [])]
    names = [c['name'] for c in script.get('characters', [])]
    segments = []
    for index, shot in enumerate(original['visual']['shots']):
        item = spoken[shot['shot_id']]
        template = planned[min(index, len(planned)-1)] if planned else {}
        content = shot['description']
        if item.get('dialogue'):
            content += '\n企鹅女孩台词：' + item['dialogue'] + '。仅保留原始台词，不添加旁白。'
        if index == 4:
            content += '\n' + original['text']['story_arc']['act3_resolution']
        segments.append({'segment_id': f'seg_1_{index+1}', 'segment_number': index+1,
                         'total_duration': item['duration_sec'],
                         'location': '企鹅女孩公寓厨房' if index < 3 else '灾变城市上空',
                         'scene_time': template.get('scene_time', ''),
                         'scene_space': template.get('scene_space', ''),
                         'scene_context': shot['description'],
                         'characters': ['企鹅女孩'] if index in (0, 2) else names,
                         'shots': [{'shot_number': 1, 'shot_type': '原始镜头',
                                    'duration': item['duration_sec'], 'content': content}]})
    assert [s['total_duration'] for s in segments] == [10, 12, 12, 14, 12]
    return [{'episode_number': 1, 'episode_title': 'narrative_074', 'segments': segments}]


def verify_selected(artifact, keys, count=None):
    items = [v for key in keys for v in artifact.get(key, [])]
    if not items or (count is not None and len(items) != count):
        raise RuntimeError(f'Missing assets: expected {count}, got {len(items)}')
    for v in items:
        p = Path(v.get('selected') or '')
        if not v.get('selected') or not (p if p.is_absolute() else BACKEND / p).is_file():
            raise RuntimeError(f'Asset incomplete: {v.get("id")}')
    return items


def main():
    (RUN / 'logs').mkdir(exist_ok=True)
    source = ROOT / 'benchmarks/directorbench/data/metadata/dataset_original.jsonl'
    matches = [(n, json.loads(line)) for n, line in enumerate(source.read_text().splitlines(), 1)
               if json.loads(line).get('meta_id') == 'narrative_074']
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one narrative_074 record')
    line_number, record = matches[0]
    dump('inputs/original.json', record)
    dump('inputs/provenance.json', {'source': str(source), 'line': line_number,
         'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
         'videoclaw_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
         'mode': 'VideoClaw with original DirectorBench shot/duration locks via supported interventions'})
    payload = {'idea': '严格按以下 DirectorBench 原始规格制作一集60秒视频，保持5镜头及10/12/12/14/12秒时长；禁止额外台词、旁白、新人物、新剧情。只提取必要的角色和场景。\n' + json.dumps(record, ensure_ascii=False),
               'style': '暗黑3D动画，Q版企鹅女孩，萌爽反差；温暖日常与赛博战斗，保持三维风格和角色身份一致',
               'video_ratio': '16:9', 'video_resolution': '720P', 'episodes': 1,
               'expand_idea': False, 'llm_model': 'qwen3.7-plus', 'vlm_model': 'qwen3-vl-plus',
               'image_t2i_model': 'wan2.7-image', 'image_it2i_model': 'wan2.7-image',
               'video_model': 'wan3.0-video', 'video_first_frame_model': 'wan3.0-video',
               'video_generation_mode': 'first_frame', 'enable_concurrency': True, 'web_search': False}
    dump('inputs/request.json', payload)
    if (RUN / 'session.json').exists():
        sid = json.loads((RUN / 'session.json').read_text())['session_id']
    else:
        session = api('POST', '/api/project/start', payload)
        dump('session.json', session)
        sid = session['session_id']
    event('Session ' + sid)
    api('PATCH', f'/api/project/{sid}/models', {k: payload[k] for k in
        ('llm_model', 'vlm_model', 'image_t2i_model', 'image_it2i_model', 'video_model', 'video_first_frame_model', 'enable_concurrency')})
    # Only resume completed stages. A killed or uncertain paid stage requires inspection.
    def done(name):
        return (RUN / f'checkpoints/{name}.json').exists()
    def mark(name, data):
        dump(f'checkpoints/{name}.json', data)
    if not done('script_generation'):
        native = execute(sid, 'script_generation')
        if not native.get('characters') or not native.get('settings'):
            raise RuntimeError('Native script did not extract characters/settings')
        script = lock_script(record, native)
        execute(sid, 'script_generation', intervention={'modified_script': script})
        mark('script_generation', script)
    script = json.loads((RUN / 'checkpoints/script_generation.json').read_text())
    if script.get('meta', {}).get('benchmark_asset_contract') != 2:
        script = lock_script(record, script)
        execute(sid, 'script_generation', intervention={'modified_script': script})
        mark('script_generation', script)
    if not done('character_design'):
        artifact = execute(sid, 'character_design')
        verify_selected(artifact, ['characters', 'settings'])
        mark('character_design', artifact)
    if not done('storyboard'):
        native = execute(sid, 'storyboard')
        locked = lock_storyboard(record, native, script)
        artifact = execute(sid, 'storyboard', intervention={'modified_storyboard': locked})
        mark('storyboard', artifact)
    if not done('reference_generation'):
        artifact = execute(sid, 'reference_generation')
        verify_selected(artifact, ['scenes'], 5)
        mark('reference_generation', artifact)
    if not done('video_generation'):
        artifact = execute(sid, 'video_generation')
        clips = verify_selected(artifact, ['clips'], 5)
        for clip, seconds in zip(clips, [10, 12, 12, 14, 12]):
            validate((BACKEND / clip['selected']).resolve(), seconds)
        mark('video_generation', artifact)
    if not done('post_production'):
        artifact = execute(sid, 'post_production')
        mark('post_production', artifact)
    outputs = list((BACKEND / 'code/result/video' / sid / 'output').glob('*.mp4'))
    if len(outputs) != 1:
        raise RuntimeError('Expected one final video')
    probe = validate(outputs[0], 60)
    final = RUN / 'videos/narrative_074.mp4'
    final.parent.mkdir(exist_ok=True)
    shutil.copy2(outputs[0], final)
    dump('probe.json', probe)
    dump('status.json', {'status': 'PASSED', 'session_id': sid, 'video': str(final),
         'duration_sec': float(probe['format']['duration']), 'bytes': final.stat().st_size,
         'sha256': hashlib.sha256(final.read_bytes()).hexdigest(), 'updated_at': time.time(),
         'scope': 'Technical smoke test; no benchmark quality scores or human/lip-sync validation'})
    event('PASSED ' + str(final))


def validate(path, seconds):
    result = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], text=True))
    video = next((s for s in result['streams'] if s['codec_type'] == 'video'), None)
    audio = next((s for s in result['streams'] if s['codec_type'] == 'audio'), None)
    if not video or not audio or abs(float(result['format']['duration']) - seconds) > 0.3:
        raise RuntimeError(f'Invalid duration or missing video/audio: {path}')
    if video['width'] != 1280 or video['height'] != 720:
        raise RuntimeError(f'Expected 1280x720: {path}')
    return result


if __name__ == '__main__':
    with (RUN / 'runner.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            main()
        except Exception as exc:
            current = json.loads((RUN / 'status.json').read_text()) if (RUN / 'status.json').exists() else {}
            current.update(status='FAILED', error=str(exc), updated_at=time.time())
            dump('status.json', current)
            raise
