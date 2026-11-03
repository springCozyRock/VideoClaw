"""Python 3.11 worker for unmodified DeepFace.verify (TF 2.15.1)."""
import contextlib,json,os,sys,traceback
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','2')
os.environ.setdefault('TF_FORCE_GPU_ALLOW_GROWTH','true')
with contextlib.redirect_stdout(sys.stderr):
 from deepface import DeepFace
for line in sys.stdin:
 try:
  request=json.loads(line)
  with contextlib.redirect_stdout(sys.stderr):result=DeepFace.verify(**request)
  print(json.dumps({'result':result},default=lambda v:v.tolist() if hasattr(v,'tolist') else v.item() if hasattr(v,'item') else str(v)),flush=True)
 except Exception as ex:
  print(json.dumps({'error':str(ex),'traceback':traceback.format_exc()}),flush=True)
