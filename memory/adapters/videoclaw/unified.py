"""VideoClaw delegates segment generation; Memory owns modes and selection."""
import asyncio
from pathlib import Path
from memory.runtime.service import Memory
from memory.contracts.policy import Policy
from memory.adapters.videoclaw.unified_backend import UnifiedBackend as VideoClawBackend
from memory.adapters.videoclaw.session import convert


class VideoClawMemory:
    def __init__(self, engine, session_id, directory, policy=None, backend_factory=VideoClawBackend):
        from core.orchestrator import WorkflowStage
        from core.agents.video_agent import VideoDirectorAgent
        self.engine, self.session_id = engine, session_id
        self.memory = Memory(directory, session_id, policy)
        self.stage = WorkflowStage.VIDEO_GENERATION
        self.original = engine.agent_factories[self.stage]
        self.metadata = {}
        self.backend = None
        handle = self

        class MemoryAgent(VideoDirectorAgent):
            async def process(agent, input_data, intervention=None):
                if input_data.get("session_id") != session_id:
                    native = handle.original()
                    native.set_progress_callback(agent.progress_callback)
                    native.set_cancellation_check(agent.cancellation_check)
                    return await native.process(input_data, intervention=intervention)
                if intervention:
                    raise ValueError("Use handle.reselect() for explicit version selection; register changed story in a new revision")
                data = agent._merge_session_params(input_data)
                for episode in agent._session_artifacts(data).get("storyboard", {}).get("episodes", []):
                    for position, segment in enumerate(episode.get("segments", []), 1):
                        handle.metadata[segment["segment_id"]] = {
                            "episode": episode.get("episode_number", 1),
                            "index": segment.get("segment_number", position)}
                segments, references = convert(agent, data)
                handle.memory.register_story(segments, references)
                backend = backend_factory(agent, data, Path(directory))
                handle.backend = backend

                def publish(record):
                    agent._report_progress("Memory", "Selected " + record["segment"]["id"],
                        int(100 * (record["index"] + 1) / len(segments)),
                        {"memory_segment_ready": record["segment"]["id"]})

                def execute():
                    agent._check_cancel()
                    if hasattr(backend, "plan_story"):
                        from memory.assets.store import MemoryStore
                        with MemoryStore(directory, session_id) as store:
                            existing_plan = store.data.get("plan")
                        if existing_plan:
                            handle.memory.register_story(existing_plan["segments"], references)
                        else:
                            handle.memory.plan(
                                {"script": agent._session_artifacts(data).get("script", {}),
                                 "storyboard_draft": [__import__("dataclasses").asdict(s) for s in segments]},
                                backend, constraints={"preserve_segment_ids_and_durations": True},
                                references=references)
                    from memory.assets.store import MemoryStore
                    with MemoryStore(directory, session_id) as store:
                        prior = list(store.data.get("committed", []))
                    for record in prior:
                        agent._report_progress("Memory", "Awaiting sequence validation", 0,
                            {"asset_complete": {"type": "clips", **handle.clip(record), "status": "pending"}, "persist": True})
                    try:
                        records = handle.memory.generate(backend, publish, agent._check_cancel)
                    except BaseException:
                        snapshot = handle.memory.snapshot()
                        stale = {v["segment_id"] for v in snapshot["M"] if v["stale"]}
                        for record in prior:
                            agent._report_progress("Memory", "Sequence not certified", 0,
                                {"asset_complete": {"type": "clips", **handle.clip(record),
                                    "status": "stale" if record["segment"]["id"] in stale else "pending"}, "persist": True})
                        raise
                    for record in records:
                        agent._report_progress("Memory", "Sequence validated", 100,
                            {"asset_complete": {"type": "clips", **handle.clip(record)}, "persist": True})
                    return records

                records = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: execute())
                return {"payload": {"session_id": session_id,
                    "clips": [handle.clip(r) for r in records],
                    "memory": {"schema": "aard.memory/2", "checkpoint": str(handle.memory.directory) + "/artifacts.sqlite3"}},
                    "stage_completed": True}

        self.factory = MemoryAgent
        engine.agent_factories[self.stage] = self.factory

    def clip(self, record):
        from memory.assets.store import MemoryStore
        with MemoryStore(self.memory.directory, self.session_id) as store:
            versions = [c["media"]["path"] for c in store.data["candidates"].values()
                        if c.get("selection_context", {}).get("segment", {}).get("id") == record["segment"]["id"]]
        return {"id": record["segment"]["id"], "name": record["segment"]["id"],
                "index": record["index"] + 1, "episode": 1,
                "duration": record["segment"]["duration"], "description": record["segment"]["context"],
                "selected": record["video"]["path"], "versions": list(dict.fromkeys(versions + [record["video"]["path"]])),
                "status": "done", "memory_quality": record["quality_status"],
                **self.metadata.get(record["segment"]["id"], {})}

    def reselect(self, state, segment_id, candidate_key):
        if self.backend is None:
            raise ValueError("Load the configured backend before selecting a candidate")
        revision = self.memory.select_candidate(segment_id, candidate_key, self.backend)
        from memory.assets.store import MemoryStore
        with MemoryStore(self.memory.directory, self.session_id) as store:
            selected = {s["segment_id"]: s for s in store.selected(True)}
            assets = {a["id"]: a for a in store.journal.all_artifacts()}
        with self.engine._state_lock:
            for clip in state.artifacts.get("video_generation", {}).get("clips", []):
                item = selected.get(clip["id"])
                if item:
                    clip["selected"] = assets[item["V"]]["path"]
                    clip["status"] = "stale" if item["stale"] else "pending"
        self.sync(state)
        return revision

    def sync(self, state):
        """Acknowledge only selections actually merged into native state."""
        selected = {c["id"]: c.get("selected") for c in state.artifacts.get("video_generation", {}).get("clips", [])}
        snapshot = self.memory.snapshot()
        from memory.assets.store import MemoryStore
        with MemoryStore(self.memory.directory, self.session_id) as store:
            artifacts = {a["id"]: a for a in store.journal.all_artifacts()}
        current = {s["segment_id"]: s for s in snapshot["M"] if not s["stale"]}
        if snapshot["delivery"]["status"] not in ("passed", "local_only"):
            return
        for event in self.memory.pending_publications():
            segment = current.get(event["segment_id"])
            if segment and event["revision_id"] == segment["revision_id"] and selected.get(segment["segment_id"]) == artifacts[segment["V"]]["path"]:
                with MemoryStore(self.memory.directory, self.session_id) as store:
                    store.journal.publish(artifacts[segment["V"]], selected[segment["segment_id"]])
                self.memory.acknowledge(event["event_id"])

    def uninstall(self):
        if self.engine.agent_factories.get(self.stage) is self.factory:
            self.engine.agent_factories[self.stage] = self.original

    __call__ = uninstall


def install(engine, session_id, directory, policy=None, backend_factory=VideoClawBackend):
    return VideoClawMemory(engine, session_id, directory, policy, backend_factory)
