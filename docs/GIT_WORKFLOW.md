# Git workflow

`origin` is `git@github.com:springCozyRock/VideoClaw.git`. Keep `main` as the reviewed base. Development branches use `codex/`.

```bash
git switch -c codex/describe-change
# Make and test a focused change.
video-claw/video-claw/backend/.venv/bin/python scripts/test_workspace.py
git add <specific source paths>
python3 scripts/check_repo.py
git diff --cached --stat
git commit -m "feat(memory): describe behavior"
git push -u origin HEAD
```

Enable the local hook after cloning: `git config --local core.hooksPath .githooks`. The hook checks staged file contents for credential patterns, local runtime artifacts and files above 10 MiB. Review the actual staged diff too; this is not a comprehensive secret detector. Track product code, Memory, evaluation adapters and `benchmarks/SOURCES.json`. Benchmark source trees, FilmAgent, screenshots, third-party checkouts, environments, model weights, data, secrets and experiment results stay local and are ignored.

Use separate commits for workspace relocation, prompt-policy changes, architecture changes and evaluation changes. Record benchmark adaptations and upstream identities. Do not represent adapted benchmark runs as exact paper reproductions. Do not force-push or rewrite shared history.
