"""Single-version preview policy, scoped to registered fast-batch sessions."""
import inspect
import json
from pathlib import Path
from rate_limit_policy import RATE_LIMIT_RETRY_SECONDS, MAX_RATE_LIMIT_RETRIES, is_rate_limited
import threading
import time
import asyncio

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'experiments/videoclaw_batch_fast/fast_sessions.json'
IMAGE_SLOTS = threading.BoundedSemaphore(3)
VIDEO_SLOTS = threading.BoundedSemaphore(6)
POST_SLOTS = asyncio.Semaphore(2)
RATE_LOCK = threading.Lock()
LAST_IMAGE_START = 0.0


def registered(sid):
    if not REGISTRY.exists():
        return False
    return str(sid) in json.loads(REGISTRY.read_text())


def install():
    from models.image_client import ImageClient
    from models.video_client import VideoClient
    from core.agents.character_agent import CharacterDesignerAgent
    from core.agents.reference_agent import ReferenceGeneratorAgent
    from core.orchestrator import WorkflowEngine

    def limit_versions(original, key):
        signature = inspect.signature(original)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            if registered(bound.arguments.get('sid')):
                bound.arguments[key] = 1
            return original(*bound.args, **bound.kwargs)
        return wrapped

    CharacterDesignerAgent._generate_one = limit_versions(CharacterDesignerAgent._generate_one, 'max_iterations')
    ReferenceGeneratorAgent._generate_one = limit_versions(ReferenceGeneratorAgent._generate_one, 'max_versions')
    original_image = ImageClient.generate_image
    original_video = VideoClient.generate_video
    original_best = ReferenceGeneratorAgent._select_best_with_vlm
    original_execute = WorkflowEngine.execute_stage

    def image(self, *args, **kwargs):
        global LAST_IMAGE_START
        if registered(kwargs.get('session_id')):
            with IMAGE_SLOTS:
                for attempt in range(6):
                    with RATE_LOCK:
                        time.sleep(max(0, 3 - (time.monotonic() - LAST_IMAGE_START)))
                        LAST_IMAGE_START = time.monotonic()
                    try:
                        return original_image(self, *args, **kwargs)
                    except Exception as exc:
                        message = str(exc).lower()
                        if not is_rate_limited(message) or attempt == 5:
                            raise
                        # Retry only explicit rejected quota responses, never uncertain transport outcomes.
                        time.sleep(RATE_LIMIT_RETRY_SECONDS)
        return original_image(self, *args, **kwargs)

    def video(self, *args, **kwargs):
        sid = Path(kwargs.get('save_path', '')).parent.name
        if registered(sid):
            with VIDEO_SLOTS:
                return original_video(self, *args, **kwargs)
        return original_video(self, *args, **kwargs)

    def best(self, image_paths, *args, **kwargs):
        if len(image_paths) == 1 and any(registered(part) for part in Path(image_paths[0]).parts):
            return image_paths[0], {'score': 0, 'is_acceptable': False,
                'hard_failures': [], 'issues': ['Single-version preview; original VLM opinion preserved in server.log; no quality pass claimed.']}
        return original_best(self, image_paths, *args, **kwargs)

    async def execute(self, state, stage, input_data, **kwargs):
        if registered(state.session_id) and stage.value == 'post_production':
            async with POST_SLOTS:
                return await original_execute(self, state, stage, input_data, **kwargs)
        return await original_execute(self, state, stage, input_data, **kwargs)

    ImageClient.generate_image = image
    VideoClient.generate_video = video
    ReferenceGeneratorAgent._select_best_with_vlm = best
    WorkflowEngine.execute_stage = execute
