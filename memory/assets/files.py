"""Content fingerprints and verified media paths shared across stores."""
import hashlib
import json
from pathlib import Path

def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def media(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Empty or missing media: " + str(path))
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return {"path": str(path), "sha256": sha.hexdigest()}


def verify_media(item):
    if media(item["path"]) != item:
        raise RuntimeError("Media changed since checkpoint: " + item["path"])


