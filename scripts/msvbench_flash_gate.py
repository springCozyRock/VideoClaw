from pathlib import Path
import json,time,os
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'experiments/msvbench_repair_20261019'
evidence=R/'formal-flash-validation-v3/videoclaw/01/story_video_consistency/status.json'
deadline=time.time()+6*3600
while time.time()<deadline:
 if evidence.exists():
  d=json.loads(evidence.read_text())
  gate={'status':'PASSED' if d['status']=='SCORED' else 'FAILED','evidence':str(evidence),'native_status':d['status'],'time':time.time()}
  p=R/'full_story_flash_gate.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(gate,indent=2));tmp.replace(p)
  break
 time.sleep(10)
