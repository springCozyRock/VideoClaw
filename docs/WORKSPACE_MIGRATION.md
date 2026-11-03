# Workspace migration

The development root is `/mnt/data/bts/repos/VideoClaw`. VideoClaw retains its native `video-claw/video-claw/` layout. Memory, scripts, tests, configurations and evaluation adapters are real files in this Git repository. Benchmark source snapshots include licenses, upstream commit IDs, retained local adaptations and file hashes in `benchmarks/SOURCES.json`; they are not opaque nested Git repositories.

Migration preserves the target's existing `uv.lock` contents. Pre-migration tracked files, its original diff and the transfer manifest are under the ignored `.migration/` directory. Original LongVideoMemory source code and historical results are retained.

The backend virtual environment, frontend node_modules and eight evaluation environments were moved within the same filesystem. Old environment paths are compatibility symlinks. Text launchers, activation files and editable-package path files were updated for the new root. The managed base Python installation remains shared. Runtime versions and package inventories are in `environments/manifest.json`.

The server had approximately 12 GB free at migration time. Dataset, model-weight, cache and historical-output storage therefore uses explicit ignored resource symlinks rather than duplicate tens of gigabytes. Their locations are listed in `environments/migration.local.json`. New experiment directories live under the new root; `experiments/legacy` links historical experiments. Existing historical JSON, API responses, prompts and evidence are not rewritten.

Provider credentials were copied locally into ignored files with restricted permissions. They are not in source manifests, commits or GitHub uploads.

The initial migration and the subsequent instruction-language changes are separate commits. Migration does not restart services, trigger paid generation or rerun expensive benchmark models.

## Fresh clone

Install Python 3.11 and FFmpeg. Create the backend environment using the native backend pyproject/uv.lock or requirements file. Restore evaluator environments according to `environments/manifest.json` and each benchmark's own dependency requirements. Run `npm ci` in the frontend. Obtain authorized benchmark data and model weights and configure local resource paths; do not commit local resource mounts. Copy `.env.example` to `.env` and fill credentials locally. Run `scripts/doctor_workspace.py` followed by the offline test entrypoint.
