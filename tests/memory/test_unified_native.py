import asyncio
import copy
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from memory import Policy, Segment
from memory.adapters.videoclaw import install
from memory.adapters.videoclaw.media import MediaIO
from fakes import FakeBackend

ROOT = Path(
    os.environ.get("MEMORY_HOST_ROOT", str(Path(__file__).resolve().parents[2]))
)
BACKEND = ROOT / "video-claw/video-claw/backend"


@unittest.skipUnless(BACKEND.exists(), "Native VideoClaw checkout required")
class UnifiedNativeTests(unittest.TestCase):
    def test_provider_arguments_and_actual_boundary_decoding(self):
        sys.path.insert(0, str(BACKEND))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=64x64:r=4:d=2",
                    "-c:v",
                    "mpeg4",
                    str(fixture),
                ],
                check=True,
            )

            class Agent:
                def _check_cancel(self):
                    pass

            backend = MediaIO.__new__(MediaIO)
            backend.agent = Agent()
            backend.settings = {
                "session_id": "offline",
                "video_ratio": "16:9",
                "video_resolution": "720P",
            }
            backend.video_model = "offline-video"
            backend.image_model = "offline-edit"
            backend.text_image_model = "offline-image"
            seed, end = backend.boundaries(str(fixture), root / "bounds")
            self.assertGreater(Path(seed).stat().st_size, 0)
            self.assertGreater(Path(end).stat().st_size, 0)
            segment = Segment("s", "walk forwards", 2)
            with patch("models.image_client.ImageClient") as image_client:
                image_client.return_value.generate_image.return_value = [seed]
                frame = backend.render_frame(
                    segment, "keep red room", [end], root / "candidate.png"
                )
                self.assertEqual(
                    [
                        Path(p).read_bytes()
                        for p in image_client.return_value.generate_image.call_args.kwargs[
                            "image_paths"
                        ]
                    ],
                    [Path(end).read_bytes()],
                )
                self.assertEqual(
                    image_client.return_value.generate_image.call_args.kwargs["model"],
                    "offline-edit",
                )
            with patch("models.video_client.VideoClient") as video_client:
                video_client.return_value.generate_video.side_effect = (
                    lambda **kw: shutil.copyfile(fixture, kw["save_path"])
                )
                backend.render_video(
                    segment, "walk without repeating", frame, root / "candidate.mp4"
                )
                call = video_client.return_value.generate_video.call_args.kwargs
                self.assertEqual(call["image_path"], frame)
                self.assertEqual(call["duration"], 2)
                self.assertFalse(call["prompt_extend"])
                self.assertNotIn("last_image_path", call)

    def test_native_engine_accepts_memory_payload_and_keeps_default_factory(self):
        sys.path.insert(0, str(BACKEND))
        from core.orchestrator import WorkflowEngine, WorkflowStage
        from core.agents.video_agent import VideoDirectorAgent

        class IsolatedEngine(WorkflowEngine):
            def _load_sessions_from_disk(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.png"
            seed.write_text("deterministic reference")
            original_calls = []

            async def original_process(agent, data, intervention=None):
                original_calls.append(data["session_id"])
                return {"payload": {}, "stage_completed": True}

            engine = IsolatedEngine()
            engine._session_dir = str(root / "sessions")
            Path(engine._session_dir).mkdir()
            sid = "memory-test"
            engine.create_session(sid, {"style": "realistic"})
            state = engine.get_state(sid)
            state.artifacts = {
                "character_design": {
                    "characters": [
                        {
                            "id": "alice",
                            "name": "Alice",
                            "description": "dark hair",
                            "selected": str(seed),
                        }
                    ]
                },
                "reference_generation": {
                    "scenes": [
                        {"id": "seg_2_1", "selected": str(seed)},
                        {"id": "seg_2_2", "selected": str(seed)},
                    ]
                },
                "storyboard": {
                    "episodes": [
                        {
                            "episode_number": 2,
                            "segments": [
                                {
                                    "segment_id": "seg_2_1",
                                    "characters": ["Alice"],
                                    "location": "room",
                                    "shots": [
                                        {"content": "Alice places a key", "duration": 5}
                                    ],
                                    "total_duration": 5,
                                },
                                {
                                    "segment_id": "seg_2_2",
                                    "characters": ["Alice"],
                                    "location": "room",
                                    "shots": [
                                        {"content": "Alice walks away", "duration": 5}
                                    ],
                                    "total_duration": 5,
                                },
                            ],
                        }
                    ]
                },
            }
            original_artifacts = copy.deepcopy(state.artifacts)
            fake = FakeBackend(continuous=True)
            original_factory = engine.agent_factories[WorkflowStage.VIDEO_GENERATION]
            uninstall = install(
                engine, sid, root / "memory", backend_factory=lambda *args: fake
            )
            events = []
            def capture(*args, **kwargs):
                events.append((args, kwargs))
                def inspect(value):
                    if isinstance(value, dict):
                        if value.get("status") == "done" and "selected" in value:
                            self.assertIn(uninstall.memory.snapshot()["delivery"]["status"], ("passed", "local_only"))
                        for item in value.values(): inspect(item)
                    elif isinstance(value, (tuple, list)):
                        for item in value: inspect(item)
                inspect((args, kwargs))
            result = asyncio.run(
                engine.execute_stage(
                    state,
                    WorkflowStage.VIDEO_GENERATION,
                    {"session_id": sid},
                    progress_callback=capture,
                )
            )
            self.assertEqual(state.status["video_generation"], "completed")
            self.assertEqual(len(result["payload"]["clips"]), 2)
            self.assertEqual(result["payload"]["clips"][0]["episode"], 2)
            self.assertEqual(result["payload"]["clips"][1]["index"], 2)
            self.assertEqual(
                state.artifacts["storyboard"], original_artifacts["storyboard"]
            )
            self.assertTrue(events)
            calls = len(fake.calls)
            asyncio.run(
                engine.execute_stage(
                    state, WorkflowStage.VIDEO_GENERATION, {"session_id": sid}
                )
            )
            self.assertEqual(calls, len(fake.calls))
            with patch.object(VideoDirectorAgent, "process", original_process):
                agent = engine.agent_factories[WorkflowStage.VIDEO_GENERATION]()
                asyncio.run(agent.process({"session_id": "baseline-session"}))
            self.assertEqual(original_calls, ["baseline-session"])
            with self.assertRaises(ValueError):
                agent = engine.agent_factories[WorkflowStage.VIDEO_GENERATION]()
                asyncio.run(
                    agent.process(
                        {"session_id": sid}, intervention={"selected_clips": {}}
                    )
                )
            uninstall()
            self.assertIs(
                engine.agent_factories[WorkflowStage.VIDEO_GENERATION], original_factory
            )

    def test_native_engine_blocks_without_publishing_failed_clip(self):
        sys.path.insert(0, str(BACKEND))
        from core.orchestrator import WorkflowEngine, WorkflowStage

        class IsolatedEngine(WorkflowEngine):
            def _load_sessions_from_disk(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            engine = IsolatedEngine()
            engine._session_dir = tmp
            engine.create_session("blocked", {})
            state = engine.get_state("blocked")
            state.artifacts = {
                "storyboard": {
                    "episodes": [
                        {
                            "segments": [
                                {
                                    "segment_id": "s1",
                                    "total_duration": 5,
                                    "shots": [{"content": "place key"}],
                                }
                            ]
                        }
                    ]
                }
            }
            install(
                engine,
                "blocked",
                Path(tmp) / "memory",
                policy=Policy(selection="strict"),
                backend_factory=lambda *args: FakeBackend(unmet=True),
            )
            with self.assertRaises(RuntimeError):
                asyncio.run(
                    engine.execute_stage(
                        state, WorkflowStage.VIDEO_GENERATION, {"session_id": "blocked"}
                    )
                )
            self.assertEqual(state.status["video_generation"], "error")
            self.assertFalse(state.artifacts.get("video_generation", {}).get("clips"))

    def test_unified_backend_uses_native_image_agent_not_video_agent(self):
        from unittest.mock import Mock
        from memory.adapters.videoclaw.unified_backend import UnifiedBackend
        from core.agents.reference_agent import ReferenceGeneratorAgent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.png'
            source.write_bytes(b'provider-image')
            backend = UnifiedBackend.__new__(UnifiedBackend)
            backend.agent = Mock(spec=['_check_cancel', 'cancellation_check'])
            backend.agent.cancellation_check = lambda: False
            backend.settings = {'session_id': 'test', 'llm_model': 'judge'}
            backend.media = Mock(image_model='edit', text_image_model='image')
            with patch.object(ReferenceGeneratorAgent, '_generate_image_with_doctor',
                              return_value=([str(source)], 'doctor prompt', {})) as generate:
                path = backend.render_frame(Segment('s', 'frame', 5), 'original', [], root / 'result.png')
            self.assertEqual(Path(path).read_bytes(), source.read_bytes())
            self.assertEqual(generate.call_args.kwargs['model'], 'image')
            import json
            self.assertEqual(json.loads(Path(path + '.receipt.json').read_text())['used_prompt'], 'doctor prompt')
