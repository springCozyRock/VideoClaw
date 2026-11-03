"""Bounded shared transport concurrency; explicit rate rejection still waits 5s."""

import contextlib
import fcntl
import hashlib
import json
import time
import uuid
from pathlib import Path
from rate_limit_policy import REQUEST_GAP_SECONDS


@contextlib.contextmanager
def request_slot(
    folder,
    key,
    minimum_gap=REQUEST_GAP_SECONDS,
    max_concurrent=1,
    metrics_directory=None,
):
    if max_concurrent < 1 or minimum_gap < 0:
        raise ValueError("Invalid transport concurrency/gap")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    waiting = time.monotonic()
    slot = None
    try:
        if max_concurrent > 1:
            while slot is None:
                for index in range(max_concurrent):
                    candidate = (folder / (key + ".slot-" + str(index))).open("a+")
                    try:
                        fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        slot = candidate
                        break
                    except BlockingIOError:
                        candidate.close()
                if slot is None:
                    time.sleep(0.1)
        gate = (folder / (key + ".lock")).open("a+")
        try:
            fcntl.flock(gate, fcntl.LOCK_EX)
            stamp = folder / (key + ".json")
            previous = json.loads(stamp.read_text()) if stamp.exists() else {}
            field = "started_at" if max_concurrent > 1 else "ended_at"
            delay = max(0, previous.get(field, 0) + minimum_gap - time.time())
            if delay:
                time.sleep(delay)
            started = time.time()
            active = time.monotonic()
            if max_concurrent > 1:
                temporary = stamp.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {"started_at": started, "minimum_gap_seconds": minimum_gap}
                    )
                )
                temporary.replace(stamp)
                fcntl.flock(gate, fcntl.LOCK_UN)
            try:
                yield
            finally:
                if max_concurrent == 1:
                    temporary = stamp.with_suffix(".tmp")
                    temporary.write_text(
                        json.dumps(
                            {
                                "ended_at": time.time(),
                                "minimum_gap_seconds": minimum_gap,
                            }
                        )
                    )
                    temporary.replace(stamp)
                if metrics_directory:
                    destination = Path(metrics_directory)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / (uuid.uuid4().hex + ".json")).write_text(
                        json.dumps(
                            {
                                "started_at": started,
                                "queue_wait_seconds": active - waiting,
                                "request_seconds": time.monotonic() - active,
                                "max_concurrent": max_concurrent,
                                "minimum_gap_seconds": minimum_gap,
                            }
                        )
                    )
        finally:
            gate.close()
    finally:
        if slot:
            slot.close()


def install(
    folder, minimum_gap=REQUEST_GAP_SECONDS, max_concurrent=1, metrics_directory=None
):
    from msvbench_qwen import QwenAPI

    @contextlib.contextmanager
    def paced(self):
        key = hashlib.sha256((self.base + "|" + self.model).encode()).hexdigest()
        with request_slot(folder, key, minimum_gap, max_concurrent, metrics_directory):
            yield

    QwenAPI.request_slot = paced
