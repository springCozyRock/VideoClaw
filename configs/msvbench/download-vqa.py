import os,json,shutil,time
from pathlib import Path
os.environ.update(HF_ENDPOINT='https://hf-mirror.com',HF_HUB_DISABLE_XET='1',HF_HUB_DOWNLOAD_TIMEOUT='120',HF_HUB_ETAG_TIMEOUT='30')
from huggingface_hub import HfApi,snapshot_download
root=Path('/mnt/data/bts/repos/LongVideoMemory')
cache=root/'benchmarks/msvbench/Metrics/StoryVideoAlignment/tools/t2v_metrics/weights/clip-flant5-xxl'
status=root/'configs/msvbench/vqa-download.json'
prior=json.loads(status.read_text()) if status.exists() else {}
revisions={x['repo']:x['revision'] for x in prior.get('models',[]) if x.get('revision')}
revisions['zhiqiulin/clip-flant5-xxl']='89bad6fffe1126b24d4360c1e1f69145eb6103aa'
api=HfApi(endpoint='https://hf-mirror.com')
items=[('zhiqiulin/clip-flant5-xxl',['*.json','spiece.model','pytorch_model*.bin']),('google/flan-t5-xxl',['*token*','spiece.model','config.json','added_tokens.json']),('openai/clip-vit-large-patch14-336',['config.json','preprocessor_config.json','pytorch_model.bin','model.safetensors'])]
record={'status':'DOWNLOADING','started':time.time(),'models':[],'pid':os.getpid()}
def save():
 tmp=status.with_suffix('.tmp');tmp.write_text(json.dumps(record,indent=2));tmp.replace(status)
save()
try:
 for repo,patterns in items:
  revision=revisions.get(repo) or api.model_info(repo).sha
  entry={'repo':repo,'revision':revision,'status':'DOWNLOADING'};record['models'].append(entry);save()
  for attempt in range(5):
   try:
    if shutil.disk_usage(root).free<20*1024**3:raise RuntimeError('Free disk below20GiB; downloads stopped')
    entry.update(status='DOWNLOADING',attempt=attempt);save()
    path=snapshot_download(repo,revision=revision,cache_dir=str(cache),allow_patterns=patterns,ignore_patterns=['trainer_state.json'],max_workers=3)
    entry.update(status='DOWNLOADED',path=path);save();break
   except Exception as ex:
    entry.update(status='RETRYING',error=str(ex));save()
    if attempt==4 or 'below20GiB' in str(ex):raise
    time.sleep(min(30,5*(attempt+1)))
 record['status']='DOWNLOADED_NOT_INFERENCE_VERIFIED';save()
except Exception as ex:
 record.update(status='FAILED',error=str(ex));save();raise
