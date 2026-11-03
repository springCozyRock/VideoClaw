"""Download pinned Whisper weights over regular HTTPS, with SHA256 checks."""

import sys as _sys
from pathlib import Path as _Path
_CODEX = _Path(__file__).resolve().parents[1]
_sys.path[:0] = [str(_CODEX / _name) for _name in ('generation', 'evaluation', 'operations', 'setup', 'diagnostics')] + [str(_CODEX)]

import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
from workspace_paths import BASELINE_ROOT, RUN_ROOT, CACHE_ROOT, load_json
ROOT = BASELINE_ROOT
TARGET=(CACHE_ROOT / 'faster-whisper-large-v3')
STATUS=(RUN_ROOT / 'evaluation/asr_environment.json')
REV='edaa852ec7e145841d8ffdb056a99866b5f0a478'
MODEL='Systran/faster-whisper-large-v3'

def save(value):
 STATUS.parent.mkdir(parents=True,exist_ok=True);tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(STATUS)
def checksum(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def main():
 save({'status':'SETTING_UP','revision':REV});TARGET.mkdir(parents=True,exist_ok=True)
 cache=Path('/mnt/data/bts/models/faster-whisper/models--Systran--faster-whisper-large-v3')
 cached_tree=cache/'trees'/(REV+'.json')
 if cached_tree.exists():
  tree=load_json(cached_tree)['files']
  metadata={'siblings':[dict(rfilename=name,size=value.get('size'),blob_id=value.get('blob_id'),lfs={'sha256':value.get('lfs_sha256'),'size':value.get('lfs_size')}) for name,value in tree.items()]}
 else:
  with urllib.request.urlopen('https://hf-mirror.com/api/models/'+MODEL+'/revision/'+REV,timeout=30) as response:metadata=json.load(response)
 records=[]
 for item in metadata['siblings']:
  name=item['rfilename']
  if name not in ['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.json','vocabulary.txt']:continue
  target=TARGET/name;partial=TARGET/(name+'.partial');expected=item.get('lfs',{}).get('sha256');size=item.get('size',item.get('lfs',{}).get('size'))
  blob=cache/'blobs'/str(item.get('blob_id'))
  if blob.exists() and not target.exists():
   import shutil
   shutil.copy2(blob,target)
  if target.exists() and ((size and target.stat().st_size!=size) or (expected and checksum(target)!=expected)):raise RuntimeError('Cached file failed fixed-revision check: '+name)
  if not target.exists():
   last=None
   for attempt in range(6):
    host='hf-mirror.com' if attempt<4 else 'huggingface.co'
    url='https://'+host+'/'+MODEL+'/resolve/'+REV+'/'+name
    if attempt>0:url+='?download=true&lvm_attempt='+str(int(time.time()))
    offset=partial.stat().st_size if partial.exists() else 0
    headers={'Range':'bytes=%d-'%offset} if offset else {}
    print('Downloading',name,'attempt',attempt,'resume_bytes',offset,flush=True)
    try:
     with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=45) as response:
      append=response.status==206 and offset>0
      with partial.open('ab' if append else 'wb') as output:
       while True:
        chunk=response.read(1024*1024)
        if not chunk:break
        output.write(chunk)
     if size and partial.stat().st_size!=size:raise RuntimeError('Incomplete fixed-revision file')
     if expected and checksum(partial)!=expected:partial.unlink();raise RuntimeError('SHA256 mismatch')
     partial.replace(target);break
    except Exception as ex:last=str(ex);print('Download error',last,flush=True);time.sleep(3)
   if not target.exists():raise RuntimeError(name+': '+str(last))
  records.append({'file':name,'bytes':target.stat().st_size,'sha256':checksum(target),'expected_lfs_sha256':expected})
 if not (TARGET/'model.bin').exists():raise RuntimeError('Fixed model.bin not found in metadata')
 env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';env['OMP_NUM_THREADS']='4';env['HF_HUB_DISABLE_XET']='1'
 subprocess.run(['/mnt/data/bts/envs/directorbench/bin/python','-c','from faster_whisper import WhisperModel; model=WhisperModel('+repr(str(TARGET))+',device="cpu",compute_type="int8",local_files_only=True);print("WHISPER_LOAD_OK")'],env=env,check=True,timeout=180)
 (TARGET/'manifest.json').write_text(json.dumps({'model':MODEL,'revision':REV,'files':records},indent=2)+'\n')
 save({'status':'READY','model':'large-v3','local_model_path':str(TARGET),'revision':REV,'files':records,'validation':'WhisperModel CPU int8 local_files_only load successful; formal decoding remains CUDA float16 beam5'})
if __name__=='__main__':
 try:main()
 except Exception as ex:save({'status':'FAILED','error':str(ex),'revision':REV});raise
