#!/usr/bin/env python3
"""Run explicitly prepared cases with bounded case concurrency and no resubmission."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import threading
import time


def command(case, python, runner, queue):
    return [
        str(python),
        str(runner),
        "--session",
        case["session"],
        "--run",
        case["run"],
        "--integration",
        "plugin",
        "--stages",
        "reference_generation",
        "video_generation",
        "--fresh-reference-images",
        "--max-candidates",
        "2",
        "--reference-candidates",
        "2",
        "--selection",
        "strict",
        "--judge-concurrency",
        "2",
        "--pacing-directory",
        str(queue),
        "--execute",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    manifest = args.manifest.resolve(strict=True)
    directory = manifest.parent
    specification = json.loads(manifest.read_text())
    status_file = directory / "batch_status.json"
    lock = (directory / "batch.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if status_file.exists():
        raise RuntimeError(
            "Batch was already dispatched; inspect receipts instead of resubmitting"
        )
    states = {name: {"status": "QUEUED"} for name in specification["cases"]}
    guard = threading.Lock()
    started = time.time()

    def update(name, value):
        with guard:
            states[name] = value
            temporary = status_file.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "started_at": started,
                        "updated_at": time.time(),
                        "case_concurrency": args.workers,
                        "cases": states,
                    },
                    indent=2,
                )
            )
            temporary.replace(status_file)

    def run(name, case):
        update(name, {"status": "STARTING", "run": case["run"]})
        log = directory / (name + ".log")
        try:
            with log.open("w") as output:
                process = subprocess.Popen(
                    command(
                        case,
                        sys.executable,
                        Path(__file__).resolve().with_name("run_memory.py"),
                        directory / "transport_queue",
                    ),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
                update(
                    name,
                    {
                        "status": "RUNNING",
                        "pid": process.pid,
                        "run": case["run"],
                        "started_at": time.time(),
                    },
                )
                code = process.wait()
            final = Path(case["run"]) / "status.json"
            result = (
                json.loads(final.read_text())
                if final.exists()
                else {"status": "FAILED_WITHOUT_STATUS"}
            )
            update(
                name,
                {
                    "status": result["status"],
                    "exit_code": code,
                    "run": case["run"],
                    "result": result,
                    "finished_at": time.time(),
                },
            )
        except Exception as exc:
            update(
                name,
                {
                    "status": "DISPATCH_ERROR",
                    "run": case["run"],
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                },
            )

    with ThreadPoolExecutor(args.workers) as pool:
        futures = [
            pool.submit(run, name, case)
            for name, case in specification["cases"].items()
        ]
        for future in as_completed(futures):
            future.result()


if __name__ == "__main__":
    main()
