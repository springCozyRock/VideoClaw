#!/usr/bin/env python3
"""Run current memory tests offline; --source validates an isolated checkout."""
import argparse, json, os, sys, unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--host-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    host = args.host_root.resolve()
    os.environ["MEMORY_HOST_ROOT"] = str(host)
    sys.path[:0] = [str(source), str(source / "tests/memory"), str(host / "scripts")]
    import memory

    if Path(memory.__file__).resolve() != source / "memory/__init__.py":
        raise RuntimeError("Wrong memory source loaded")
    suite = unittest.defaultTestLoader.discover(str(source / "tests/memory"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
