"""Explicit, non-destructive legacy imports. Never resume unknown provider calls."""
import copy
import json
import shutil
import sqlite3
from pathlib import Path
from memory.assets.store import MemoryStore
from memory.assets.files import digest, media


def import_legacy(source, destination, story_id="imported"):
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Import into a new directory; never mutate a legacy run")
    destination.mkdir(parents=True)
    assets = destination / "imports"
    assets.mkdir()
    copies = {}

    def own(value):
        if isinstance(value, dict):
            result = {k: own(v) for k, v in value.items()}
            if value.get("path") and value.get("sha256"):
                old = Path(value["path"])
                if media(old)["sha256"] != value["sha256"]:
                    raise ValueError("Legacy media changed: " + str(old))
                target = assets / (value["sha256"] + old.suffix)
                if not target.exists():
                    shutil.copyfile(old, target)
                copies[str(old)] = str(target)
                result["path"] = str(target)
            return result
        if isinstance(value, list):
            return [own(v) for v in value]
        return value

    with MemoryStore(destination, story_id) as store:
        if source.suffix == ".json":
            raw = json.loads(source.read_text())
            if raw.get("schema") != 1 or "committed" not in raw:
                raise ValueError("Unsupported legacy controller schema")
            data = own(raw)
            store.data.update({k: v for k, v in data.items() if k not in ("schema", "committed", "operations")})
            store.data["committed"] = []
            store.data["story_revision"] = digest([story_id, data.get("inputs", {})])
            # Retain old receipts as evidence, not executable requests with rebased inputs.
            store.data["legacy_operations"] = data.get("operations", {})
            store.data["import_read_only"] = True
            store.save()
            for record in data["committed"]:
                store.commit(record)
        elif source.suffix in (".sqlite3", ".db"):
            with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as old:
                artifact_rows = old.execute("SELECT data FROM artifacts").fetchall()
                chosen = old.execute("SELECT story,slot,artifact FROM selections").fetchall()
                operations = old.execute("SELECT id,inputs,status,result FROM actions").fetchall()
            for (encoded,) in artifact_rows:
                artifact = own(json.loads(encoded))
                artifact["story_id"] = story_id
                store.journal.record(artifact)
            for _, slot, aid in chosen:
                store.journal.select(story_id, slot, aid)
            store.data["legacy_operations"] = operations
            store.data["import_read_only"] = True
            store.save()
        else:
            raise ValueError("Expected memory.json or artifacts.sqlite3")
        receipt = {"source": media(source), "owned_media": copies,
                   "semantics": "Historical evidence only; no automatic provider resume or inferred segment facts"}
        store.data["migration"] = receipt
        store.save()
        store.export(destination / "snapshot.json")
        return receipt
