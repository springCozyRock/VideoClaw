#!/usr/bin/env python3
"""Run an immutable memory package snapshot against the installed native host."""
import argparse
import importlib
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--memory-source',type=Path,required=True)
    args, remaining=parser.parse_known_args()
    source=args.memory_source.resolve(strict=True)
    manifest=source.parent/'code_provenance.json'
    if manifest.exists():
        hashes=json.loads(manifest.read_text())
        for relative,expected in hashes['host_sha256'].items():
            if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('Native host file changed: '+relative)
        for relative,expected in hashes['snapshot_sha256'].items():
            if hashlib.sha256((source/relative).read_bytes()).hexdigest()!=expected:
                raise RuntimeError('Snapshot file changed: '+relative)
    if not (source/'memory/__init__.py').is_file():raise ValueError('Snapshot must contain a memory package')
    sys.path.insert(0,str(source))
    package=importlib.import_module('memory')
    if Path(package.__file__).resolve() != source/'memory/__init__.py':
        raise RuntimeError('Wrong memory package was imported')
    sys.argv=[str(ROOT/'scripts/run_memory_aard_v5.py')]+remaining
    runpy.run_path(str(ROOT/'scripts/run_memory_aard_v5.py'),run_name='__main__')

if __name__=='__main__':main()
