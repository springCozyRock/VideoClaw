"""Expose native reference-image generation without dispatching workflow stages."""

from pathlib import Path
import shutil
from memory.assets.journal import file_hash


def unique_references(paths, directory):
    """Prevent provider upload collisions between identically named design images."""
    directory = Path(directory) / "upload_references"
    directory.mkdir(parents=True, exist_ok=True)
    result = []
    for i, source in enumerate(paths):
        source = Path(source)
        target = directory / (str(i) + "-" + file_hash(source)[:16] + source.suffix)
        shutil.copyfile(source, target)
        result.append(str(target))
    return result

