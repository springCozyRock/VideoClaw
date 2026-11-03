"""Read-only local environment and resource check; no API requests."""
import json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 checks={'root':str(ROOT),'python_prefix':sys.prefix,'backend':(ROOT/'video-claw/video-claw/backend/core/orchestrator.py').is_file(),'memory':(ROOT/'memory/__init__.py').is_file(),'ffmpeg':bool(shutil.which('ffmpeg')),'ffprobe':bool(shutil.which('ffprobe')),'node':bool(shutil.which('node')),'credentials_file_present':(ROOT/'.env').is_file()}
 checks['benchmark_sources']={n:(ROOT/'benchmarks'/n).is_dir() for n in ('msvbench','directorbench','directorbench_public','vbench','vistorybench')}
 local=ROOT/'environments/migration.local.json'
 if local.exists():
  records=json.loads(local.read_text());checks['broken_resource_mounts']=[r['path'] for r in records['resources'] if not (ROOT/r['path']).exists()]
 print(json.dumps(checks,indent=2))
 return int(not checks['backend'] or not checks['memory'] or bool(checks.get('broken_resource_mounts')))
if __name__=='__main__':raise SystemExit(main())
