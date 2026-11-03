#!/usr/bin/env python3
"""Run frozen-package tests with native host paths and no live generation."""
import argparse, json, sys, types, unittest
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True);a=p.parse_args()
source=a.source.resolve();root=a.root.resolve()
sys.path[:0]=[str(source),str(source/'tests'),str(root/'scripts'),str(root)]
import memory
assert Path(memory.__file__).resolve()==source/'memory/__init__.py'
suite=unittest.TestSuite()
paths=sorted((source/'tests').glob('test_*.py'))
if (root/'tests/test_generation_meter.py').exists():paths.append(root/'tests/test_generation_meter.py')
for path in paths:
    module=types.ModuleType(path.stem);module.__file__=str(root/'tests'/path.name);sys.modules[path.stem]=module
    exec(compile(path.read_text(),str(path),'exec'),module.__dict__)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
result=unittest.TextTestRunner(verbosity=1).run(suite)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'successful':result.wasSuccessful()}
(source.parent/'offline_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
