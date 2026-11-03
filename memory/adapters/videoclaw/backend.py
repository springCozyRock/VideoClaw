"""Public VideoClaw backend composed from transport, planning, inspection and media services."""

import hashlib
from pathlib import Path
from memory.harness.optimization.semantic import CachedEmbeddings
from memory.adapters.videoclaw.transport import StructuredTransport
from memory.adapters.videoclaw.planning import Planning
from memory.adapters.videoclaw.inspection import Inspection
from memory.adapters.videoclaw.media import MediaIO


class VideoClawBackend:
    def __init__(self, agent, settings, run):
        from msvbench_qwen import QwenAPI

        from prompting.language import project_language
        settings = {**settings, **project_language(settings, agent._session_artifacts(settings) if hasattr(agent, '_session_artifacts') else {})}
        self.agent, self.settings, self.run = agent, settings, Path(run)
        self.media = MediaIO(agent, settings)
        self.judge = QwenAPI()
        self.judge.out = self.run / "judge_calls"
        self.judge.retry_delays = ()
        self.judge._video = self.media._sample_video
        self.transport = StructuredTransport(agent, self.judge, settings["story_language"])
        self.planning = Planning(self.transport)
        self.inspection = Inspection(self.transport, self.media)
        self.embedding_model = settings.get(
            "memory_embedding_model", "text-embedding-v4"
        )
        self.embeddings = CachedEmbeddings(
            self.run / "embeddings", self._embedding_transport, self.embedding_model
        )

    def identity(self):
        import msvbench_qwen
        import videoclaw_runtime
        import rate_limit_policy

        files = list(Path(__file__).resolve().parents[2].rglob("*.py"))
        import prompting.language
        files += list(Path(prompting.language.__file__).parent.rglob('*.py'))
        files += [
            Path(module.__file__)
            for module in (msvbench_qwen, videoclaw_runtime, rate_limit_policy)
        ]
        return {
            "adapter": "videoclaw-memory",
            "prompt_policy_version": self.settings.get('prompt_policy_version'),
            "story_language": self.settings.get('story_language'),
            "video_model": self.media.video_model,
            "image_model": self.media.image_model,
            "text_image_model": self.media.text_image_model,
            "judge": self.judge.model,
            "video_observation": "uniform_4fps_plus_actual_boundaries",
            "capabilities": {
                "first_frame": True,
                "last_frame": self.media.video_model.startswith("wan3."),
            },
            "ratio": self.settings.get("video_ratio", "16:9"),
            "resolution": self.settings.get("video_resolution", "720P"),
            "embedding_model": self.embedding_model,
            "embedding_dimensions": 1024,
            "state_observation": "independent_attribute_predicates_with_actual_boundaries",
            "appearance_planning": "global_state_registry_and_segment_bindings",
            "sources": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
            },
        }

    def _embedding_transport(self, payload):
        import requests
        import time
        from rate_limit_policy import (
            is_rate_limited,
            RATE_LIMIT_RETRY_SECONDS,
            MAX_RATE_LIMIT_RETRIES,
        )

        base = self.settings.get("memory_embedding_base_url") or self.judge.base
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            self.agent._check_cancel()
            with requests.post(
                base.rstrip("/") + "/embeddings",
                headers={"Authorization": "Bearer " + self.judge.key},
                json=payload,
                timeout=(30, 120),
            ) as response:
                if response.status_code == 200:
                    return response.json()
                limited = is_rate_limited(response.text, response.status_code)
                if not limited or attempt == MAX_RATE_LIMIT_RETRIES:
                    raise RuntimeError(
                        (
                            "Embedding HTTP "
                            + str(response.status_code)
                            + ": "
                            + response.text[:600]
                        ).replace(self.judge.key, "[REDACTED]")
                    )
            # Retry only an explicit rejection; unknown transport outcomes propagate.
            time.sleep(RATE_LIMIT_RETRY_SECONDS)

    def embed_texts(self, texts):
        return self.embeddings(texts)

    def select_context(self, query):
        return self.planning.select_context(query)

    def plan_character_states(self, request):
        return self.planning.plan_character_states(request)

    def plan_global_references(self, request):
        return self.planning.plan_global_references(request)

    def prepare(self, context):
        return self.planning.prepare(context)

    def prepare_state_contract(self, context, decision):
        return self.planning.prepare_state_contract(context, decision)

    def choose_frame_action(self, candidate, request):
        return self.planning.choose_frame_action(candidate, request)

    def prepare_next_boundary(self, context, next_context):
        return self.planning.prepare_next_boundary(context, next_context)

    def select_temporal_history(self, context, candidates):
        return self.planning.select_temporal_history(context, candidates)

    def select_historical_boundary(self, context, source_record, extracted):
        return self.planning.select_historical_boundary(
            context, source_record, extracted
        )

    def refine_with_memory(self, kind, candidate, request, cases):
        return self.planning.refine_with_memory(kind, candidate, request, cases)

    def end_edit_prompt(self, segment, candidate, context):
        return self.planning.end_edit_prompt(segment, candidate, context)

    def observe(self, kind, path, segment):
        return self.inspection.observe(kind, path, segment)

    def observe_with_begin(self, path, segment, begin_asset, initial):
        return self.inspection.observe_with_begin(path, segment, begin_asset, initial)

    def review(self, kind, path, observation, request):
        return self.inspection.review(kind, path, observation, request)

    def inspect_state(
        self, kind, path, requested, segment, references, actual_bounds=None
    ):
        return self.inspection.inspect_state(
            kind, path, requested, segment, references, actual_bounds
        )

    def inspect_reference_state(self, state, asset, anchor, segment):
        return self.inspection.inspect_reference_state(state, asset, anchor, segment)

    def review_global_reference(self, node, asset, anchors):
        return self.inspection.review_global_reference(node, asset, anchors)

    def render_frame(self, segment, prompt, references, target):
        return self.media.render_frame(segment, prompt, references, target)

    def render_video(self, segment, prompt, begin, target):
        return self.media.render_video(segment, prompt, begin, target)

    def boundaries(self, video, directory):
        return self.media.boundaries(video, directory)

    def render_with_end(self, segment, prompt, begin, end, target):
        return self.media.render_with_end(segment, prompt, begin, end, target)
