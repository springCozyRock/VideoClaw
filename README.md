# VideoClaw + Memory

Independent workspace for VideoClaw architecture changes, long-video Memory and benchmark evaluation.

Server: `/mnt/data/bts/repos/VideoClaw`  
GitHub: https://github.com/springCozyRock/VideoClaw

| Directory | Purpose |
| --- | --- |
| `video-claw/video-claw/backend/` | Native VideoClaw workflow, four generation paradigms and provider adapters |
| `video-claw/video-claw/frontend/` | Native project UI |
| `memory/` | Current Memory implementation and VideoClaw integration |
| `prompting/` | Shared instruction/content-language policy |
| `scripts/run_memory.py` | Main Memory run entrypoint |
| `evaluation/` | Project evaluation adapters; no dependency on the Codex generation baseline |
| `benchmarks/SOURCES.json` | Upstream commit IDs and checksums for local benchmark trees |
| `tests/` | Offline Memory, generation, transport and evaluation checks |

Benchmark source trees (`benchmarks/msvbench`, `vbench`, `vistorybench`, `directorbench*`), `FilmAgent/`, README screenshots and `third_party/` stay on this machine for evaluation and archive use. They are gitignored; a fresh clone does not include them. Restore locally from the recorded upstream commits in `benchmarks/SOURCES.json`. Experiment snapshots such as `configs/msvbench_agents_20261018/` are likewise local-only.

```bash
cd /mnt/data/bts/repos/VideoClaw
video-claw/video-claw/backend/.venv/bin/python scripts/doctor_workspace.py
video-claw/video-claw/backend/.venv/bin/python scripts/test_workspace.py
video-claw/video-claw/backend/.venv/bin/python scripts/run_memory.py --help
bash scripts/directorbench_public.sh status
```

To start development services, use the backend environment from its working directory and `npm run dev` from the frontend directory. Environment secrets are in the ignored root `.env` and backend `config.yaml`; never commit them. Actual paid generation requires explicit execution flags. Migration and offline checks never submit model requests.

Large datasets, weights, caches and historical media remain local resource mounts. `environments/migration.local.json` records server-specific mounts and original locations; it is ignored by Git. A new clone contains the code, not these resources. See [migration](docs/WORKSPACE_MIGRATION.md), [Git workflow](docs/GIT_WORKFLOW.md) and [upstream VideoClaw](docs/UPSTREAM_VIDEOCLAW_README.md).
