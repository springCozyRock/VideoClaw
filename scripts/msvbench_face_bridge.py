"""Preserve DeepFace.verify arguments/results across a separate TF environment."""
import atexit,json,os,select,subprocess,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DeepFaceProxy:
 _lock=threading.Lock();_worker=None;_log=None
 @classmethod
 def verify(cls,img1_path,img2_path,**kwargs):
  with cls._lock:
   if cls._worker is None or cls._worker.poll() is not None:
    py=ROOT/'.venvs/msvbench_face/bin/python'
    if not py.exists():raise RuntimeError('DeepFace worker environment is missing')
    env=dict(os.environ,DEEPFACE_HOME=str(ROOT/'.cache/msvbench/deepface'),TF_FORCE_GPU_ALLOW_GROWTH='true')
    cls._log=(ROOT/'.cache/msvbench/face-worker.log').open('a')
    cls._worker=subprocess.Popen([str(py),str(ROOT/'scripts/msvbench_face_worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=cls._log,text=True,cwd=ROOT,env=env)
   request=dict(kwargs,img1_path=str(Path(img1_path).resolve()),img2_path=str(Path(img2_path).resolve()))
   cls._worker.stdin.write(json.dumps(request)+'\n');cls._worker.stdin.flush()
   if not select.select([cls._worker.stdout],[],[],300)[0]:cls.close();raise TimeoutError('DeepFace worker exceeded 300 seconds')
   line=cls._worker.stdout.readline()
   if not line:raise RuntimeError('DeepFace worker exited; see .cache/msvbench/face-worker.log')
   result=json.loads(line)
   if 'error' in result:raise RuntimeError(result['error'])
   return result['result']
 @classmethod
 def close(cls):
  if cls._worker is not None:
   cls._worker.terminate();cls._worker=None
  if cls._log is not None:cls._log.close();cls._log=None
atexit.register(DeepFaceProxy.close)
