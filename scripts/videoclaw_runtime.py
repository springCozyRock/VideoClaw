"""Project-scoped VideoClaw launcher; keeps credentials in the project .env."""
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from rate_limit_policy import RATE_LIMIT_RETRY_SECONDS, MAX_RATE_LIMIT_RETRIES, is_rate_limited
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'video-claw/video-claw/backend'
RUN = ROOT / 'experiments/videoclaw_smoke/narrative_074'
RUN.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')
    tmp.replace(path)


def media_url(path):
    if str(path).startswith(('http://', 'https://', 'data:')):
        return str(path)
    p = Path(str(path).removeprefix('file://')).resolve()
    mime = mimetypes.guess_type(str(p))[0] or 'image/png'
    from PIL import Image
    with Image.open(p) as im:
        mime = Image.MIME.get(im.format, mime)
    return 'data:' + mime + ';base64,' + base64.b64encode(p.read_bytes()).decode()


def configure():
    values = {}
    for line in (ROOT / '.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            values[k.strip().removeprefix('export ')] = v.strip().strip('"').strip("'")
    from config import Config
    Config.DASHSCOPE_API_KEY = values['DASHSCOPE_API_KEY']
    Config.LLM_API_KEY = Config.DASHSCOPE_API_KEY
    Config.DASHSCOPE_BASE_URL = values['DASHSCOPE_BASE_URL'].rstrip('/')
    # Keep Config.CONFIG free of the credential: GET /api/config returns it verbatim upstream.
    Config.CONFIG['api_providers']['dashscope']['base_url'] = Config.DASHSCOPE_BASE_URL
    import dashscope
    dashscope.api_key = Config.DASHSCOPE_API_KEY
    dashscope.base_http_api_url = Config.DASHSCOPE_BASE_URL
    return Config


def install_adapters(enable_last_frame=False):
    from config import Config
    import dashscope
    import requests
    from models.image_dashscope import DashScopeClient
    from models.video_dashscope import DashscopeVideoClient
    from models.llm_client import LLM
    from core.orchestrator import WorkflowEngine
    original_generate = DashScopeClient.generate_image
    original_edit = DashScopeClient.edit_image
    original_video = DashscopeVideoClient.generate_video
    original_query = LLM.query
    original_execute = WorkflowEngine.execute_stage

    def query(self, prompt, image_urls=[], model='qwen3.7-plus', safe_content=True, task_id=None, web_search=False):
        if model and model.startswith('qwen3.7'):
            # New Qwen Plus models use MultiModalConversation, including text-only input.
            return self.dashscope_vl_client.chat(text=prompt, images=image_urls, model=model, stream=False)
        return original_query(self, prompt, image_urls, model, safe_content, task_id, web_search)

    async def execute(self, state, stage, input_data, **kwargs):
        state.error = None
        return await original_execute(self, state, stage, input_data, **kwargs)

    def qwen_image(self, prompt, model, size, n, session_id, save_dir, images):
        content = [{'image': media_url(p)} for p in images] + [{'text': prompt}]
        # Qwen Image sizes differ from Wan Image; choose the supported landscape size.
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            rsp = dashscope.MultiModalConversation.call(
                api_key=self.api_key, model=model,
                messages=[{'role': 'user', 'content': content}],
                size='1280*720', n=1, watermark=False, prompt_extend=False,
            )
            # Retry only an explicit rejection; transport exceptions remain unresolved.
            if rsp.status_code == 200 or not is_rate_limited(f'{rsp.code}: {rsp.message}', rsp.status_code) or attempt == MAX_RATE_LIMIT_RETRIES:
                break
            time.sleep(RATE_LIMIT_RETRY_SECONDS)
        if rsp.status_code != 200:
            raise RuntimeError(f'Qwen Image: {rsp.code}: {rsp.message}')
        urls = [part['image'] for choice in rsp.output.choices
                for part in choice.message.content if isinstance(part, dict) and part.get('image')]
        if not urls:
            raise RuntimeError('Qwen Image returned no image')
        if not save_dir:
            return urls
        import uuid
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        paths = []
        for url in urls:
            path = Path(save_dir) / f'qwen_{session_id}_{uuid.uuid4().hex[:10]}.png'
            response = requests.get(url, timeout=180)
            response.raise_for_status()
            path.write_bytes(response.content)
            from PIL import Image
            with Image.open(path) as im:
                im.verify()
            paths.append(str(path))
        return paths

    def generate(self, prompt, model='wan2.7-image', size='1024*1024', n=1, session_id=None, save_dir=None):
        if model.startswith('qwen-image'):
            return qwen_image(self, prompt, model, size, n, session_id, save_dir, [])
        return original_generate(self, prompt, model, size, n, session_id, save_dir)

    def edit(self, prompt, image_urls, model='wan2.7-image', size='1920*1080', n=1, session_id=None, save_dir=None):
        if model.startswith('qwen-image'):
            return qwen_image(self, prompt, model, size, n, session_id, save_dir, image_urls)
        return original_edit(self, prompt, image_urls, model, size, n, session_id, save_dir)

    def video(self, prompt, image_path, save_path, model='wan2.7-i2v', duration=10, **kwargs):
        if not model.startswith('wan3.'):
            return original_video(self, prompt, image_path, save_path, model=model, duration=duration, **kwargs)
        if kwargs.get('last_image_path') and not enable_last_frame:
            raise ValueError('Wan3 last-frame input requires install_adapters(enable_last_frame=True)')
        if kwargs.get('reference_image_paths'):
            raise ValueError('This Wan3 runtime adapter does not implement multi-reference input')
        path = Path(save_path)
        ledger = RUN
        registry = ROOT / 'experiments/videoclaw_batch_fast/fast_sessions.json'
        if registry.exists():
            entry = json.loads(registry.read_text()).get(path.parent.name)
            if entry:
                ledger = Path(entry['run'])
        # Keep the logical output identity stable across storage symlink moves.
        task_path = ledger / 'tasks' / (hashlib.sha256(os.path.abspath(path).encode()).hexdigest()[:20] + '.json')
        legacy_path = ledger / 'tasks' / (hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20] + '.json')
        if not task_path.exists() and legacy_path.exists(): task_path = legacy_path
        payload = {'model': model, 'prompt': prompt,
                   'media': [{'type': 'first_frame', 'url': media_url(image_path)}],
                   'duration': int(duration), 'resolution': kwargs.get('resolution') or '720P',
                   'ratio': kwargs.get('video_ratio') or '16:9', 'audio': True,
                   'prompt_extend': False, 'watermark': False}
        if enable_last_frame and kwargs.get('last_image_path'):
            payload['media'].append({'type': 'last_frame', 'url': media_url(kwargs['last_image_path'])})
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        task = json.loads(task_path.read_text()) if task_path.exists() else None
        if task and task.get('request_sha256') != fingerprint:
            raise RuntimeError('Existing video task has different inputs; refusing a second submission')
        if task and task.get('status') == 'RATE_LIMITED' and not task.get('task_id'):
            task = None  # Only a recorded explicit rejection is safe to resubmit.
        if not task:
            task = {'status': 'SUBMITTING', 'request_sha256': fingerprint, 'save_path': str(path.resolve()),
                    'model': model, 'duration_sec': duration, 'created_at': time.time()}
            dump(task_path, task)
            # Never retry submission: a transport failure may already have created a paid task.
            for attempt in range(6):
                rsp = dashscope.VideoSynthesis.async_call(api_key=self.api_key, **payload)
                dump(task_path.with_suffix('.response.json'), dict(rsp))
                if rsp.status_code == 200:
                    break
                error = f'{rsp.code}: {rsp.message}'
                if is_rate_limited(error, rsp.status_code):
                    task.update(status='RATE_LIMITED', error=error)
                    dump(task_path, task)
                    if attempt == 5:
                        raise RuntimeError(error)
                    time.sleep(RATE_LIMIT_RETRY_SECONDS)
                    task.update(status='SUBMITTING')
                    dump(task_path, task)
                    continue
                break
            if rsp.status_code != 200:
                task.update(status='REJECTED', error=f'{rsp.code}: {rsp.message}')
                dump(task_path, task)
                raise RuntimeError(task['error'])
            task.update(task_id=rsp.output.get('task_id'), status=rsp.output.get('task_status'))
            dump(task_path, task)
        if not task.get('task_id'):
            raise RuntimeError('Video submission outcome is uncertain or rejected; manual reconciliation required')
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            try:
                rsp = requests.get(self.base_url.rstrip('/') + '/tasks/' + task['task_id'],
                                   headers={'Authorization': 'Bearer ' + self.api_key}, timeout=90)
                rsp.raise_for_status()
                result = rsp.json()
            except (requests.Timeout, requests.ConnectionError):
                time.sleep(15)
                continue
            output = result.get('output', {})
            task.update(status=output.get('task_status'), updated_at=time.time())
            dump(task_path, task)
            dump(task_path.with_suffix('.response.json'), result)
            if task['status'] == 'SUCCEEDED':
                url = output['video_url']
                path.parent.mkdir(parents=True, exist_ok=True)
                # A download failure is safe to retry on the next run using the persisted task_id.
                for attempt in range(4):
                    try:
                        response = requests.get(url, timeout=240)
                        response.raise_for_status()
                        path.write_bytes(response.content)
                        return url
                    except requests.RequestException:
                        if attempt == 3:
                            raise
                        time.sleep(5)
            if task['status'] in ('FAILED', 'CANCELED', 'UNKNOWN'):
                raise RuntimeError(f'Wan3 task {task["task_id"]}: {task["status"]}: {output.get("message", "")}')
            time.sleep(15)
        raise RuntimeError('Wan3 polling timed out; resume the existing task_id')

    DashScopeClient.generate_image = generate
    DashScopeClient.edit_image = edit
    DashscopeVideoClient.generate_video = video
    LLM.query = query
    WorkflowEngine.execute_stage = execute
    from videoclaw_fast import install
    install()


if __name__ == '__main__':
    configure()
    install_adapters()
    import uvicorn
    uvicorn.run('api.app:app', host='127.0.0.1', port=8000, access_log=False)
