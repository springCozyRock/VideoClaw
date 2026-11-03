"""Atomic JSON checkpoint for cross-story experience imports and legacy recovery."""

import fcntl
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import uuid


from memory.assets.files import digest, media, verify_media

class Checkpoint:
    """One directory per story/run. Use as a context manager, including reads."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "memory.json"
        self.lock = None

    def __enter__(self):
        self.lock = (self.directory / "memory.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.data = (
                json.loads(self.path.read_text())
                if self.path.exists()
                else {"schema": 1, "operations": {}, "candidates": {}, "committed": []}
            )
            if self.data["schema"] != 1:
                raise ValueError("Unsupported memory schema")
        except BaseException:
            self.lock.close()
            self.lock = None
            raise
        return self

    def __exit__(self, *args):
        self.lock.close()
        self.lock = None

    def save(self):
        if self.lock is None:
            raise RuntimeError("MemoryStore requires exclusive context")
        tmp = self.path.with_name(".memory-" + uuid.uuid4().hex + ".tmp")
        try:
            with tmp.open("w") as out:
                json.dump(self.data, out, ensure_ascii=False, indent=2, allow_nan=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(str(tmp), str(self.path))
            fd = os.open(str(self.directory), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if tmp.exists():
                tmp.unlink()

