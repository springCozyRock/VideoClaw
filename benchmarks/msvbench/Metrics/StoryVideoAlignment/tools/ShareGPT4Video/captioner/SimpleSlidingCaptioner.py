"""Restore missing interface using the official ShareCaptioner sliding algorithm.

Reconstructed adapter; MSVBench author's unpublished wrapper is unavailable.
"""
from pathlib import Path
import ast,threading,torch,numpy as np,os
from PIL import Image,ImageDraw,ImageFont
from decord import VideoReader
from torchvision import transforms
from transformers import AutoModel,AutoTokenizer,AutoConfig,CLIPVisionModel,CLIPVisionConfig
from unittest.mock import patch
from contextlib import ExitStack
from transformers.dynamic_module_utils import get_class_from_dynamic_module
class SimpleSlidingCaptioner:
 _cache={};_lock=threading.RLock()
 def __init__(self,model_path,device='cuda'):
  self.model_path=str(Path(model_path).resolve());self.device=device
  official=Path(__file__).with_name('app.py')
  tree=ast.parse(official.read_text());functions=[]
  for node in tree.body:
   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
    node.decorator_list=[];functions.append(node)
  self.ns=dict(torch=torch,np=np,Image=Image,ImageDraw=ImageDraw,ImageFont=ImageFont,VideoReader=VideoReader,transforms=transforms,os=os)
  exec(compile(ast.Module(body=functions,type_ignores=[]),str(official),'exec'),self.ns)
  with self._lock:
   key=(self.model_path,device)
   if key not in self._cache:
    tok=AutoTokenizer.from_pretrained(self.model_path,trust_remote_code=True,local_files_only=True)
    cfg=AutoConfig.from_pretrained(self.model_path,trust_remote_code=True,local_files_only=True)
    backend=os.environ.get('MSVBENCH_CAPTION_ATTN','flash_attention_2')
    cfg.attn_implementation=backend;cfg._attn_implementation=backend
    root=next(x for x in Path(__file__).resolve().parents if (x/'configs/msvbench').is_dir())
    vision=root/'.cache/msvbench/sharecaptioner-vision/config.json'
    def architecture_only(*args,**kwargs):
     # The complete captioner checkpoint must supply every final vision tensor.
     tower=CLIPVisionModel(CLIPVisionConfig.from_pretrained(str(vision),local_files_only=True))
     # Official captioner checkpoint omits the pooled-output norm. The captioner
     # exclusively consumes hidden_states[-1] patch features, never pooled_output.
     tower.vision_model.post_layernorm=torch.nn.Identity()
     return tower
    model_class=get_class_from_dynamic_module(cfg.auto_map['AutoModel'],self.model_path,local_files_only=True)
    # This 2024 remote model implements InternLM2FlashAttention2, but predates
    # Transformers' capability flag. Patch only its own InternLM base class.
    with ExitStack() as stack:
     stack.enter_context(patch.object(CLIPVisionModel,'from_pretrained',side_effect=architecture_only))
     if backend=='flash_attention_2':
      base=next(c for c in model_class.__mro__ if c.__name__=='InternLM2PreTrainedModel')
      stack.enter_context(patch.object(base,'_supports_flash_attn_2',True))
     model,info=model_class.from_pretrained(self.model_path,config=cfg,attn_implementation=backend,torch_dtype=torch.float16,trust_remote_code=True,local_files_only=True,output_loading_info=True)
    if backend=='flash_attention_2' and 'FlashAttention' not in model.model.layers[0].attention.__class__.__name__:raise RuntimeError('Requested native FlashAttention implementation was not selected')
    if any(info.get(k) for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')):raise RuntimeError('ShareCaptioner checkpoint not complete: '+str(info))
    model=model.eval().to(device);model.tokenizer=tok
    self._cache[key]=(model,tok)
   self.ns['model'],self.ns['tokenizer']=self._cache[key]
 @torch.inference_mode()
 def __call__(self,video_path):
  with self._lock:
   model=self.ns['model'];head=model.output;native_forward=head.forward
   # Generation consumes only outputs.logits[:, -1, :]. Avoid allocating
   # [beam, every image/text token, 92544 vocabulary] logits during prefill.
   # All frames, visual tokens, beam count and generation lengths are retained.
   with patch.object(head,'forward',new=lambda hidden:native_forward(hidden[:, -1:, :])):
    return self.ns['generate_slidingcaptioning'](str(video_path))
