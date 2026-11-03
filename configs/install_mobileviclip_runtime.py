from pathlib import Path
import subprocess, hashlib, json
root=Path('/mnt/data/bts/repos/LongVideoMemory'); repo=root/'third_party/mobileviclip'; out=root/'configs/mobileviclip';out.mkdir(parents=True,exist_ok=True)
files=['models/backbones/internvideo2/__init__.py','models/mobileviclip_small.py','models/mobileviclip_tiny.py']
for name in files:
 p=repo/name;backup=out/'upstream_originals'/name;backup.parent.mkdir(parents=True,exist_ok=True)
 if not backup.exists():backup.write_bytes(p.read_bytes())
init='''"""Lazy backbone exports: MobileViCLIP does not require InternVideo/FlashAttention."""
import importlib
_EXPORTS = {
    "internvl_clip_6b": ("internvl_clip_vision", "internvl_clip_6b"),
    "pretrain_internvideo2_1b_patch14_224": ("internvideo2", "pretrain_internvideo2_1b_patch14_224"),
    "pretrain_internvideo2_6b_patch14_224": ("internvideo2", "pretrain_internvideo2_6b_patch14_224"),
    "InternVideo2": ("internvideo2_clip_vision", "InternVideo2"),
    "LLaMA": ("internvideo2_clip_text", "LLaMA"),
    "Tokenizer": ("internvideo2_clip_text", "Tokenizer"),
    "TextTransformer": ("mobileclip", "TextTransformer"),
    "ClipTokenizer": ("mobileclip", "ClipTokenizer"),
}
__all__ = list(_EXPORTS)
def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attr = _EXPORTS[name]
    value = getattr(importlib.import_module("." + module, __name__), attr)
    globals()[name] = value
    return value
'''
(repo/files[0]).write_text(init)
for name in files[1:]:
 p=repo/name;s=p.read_text();s=s.replace('from .backbones.internvideo2 import InternVideo2, TextTransformer, ClipTokenizer','from .backbones.internvideo2 import TextTransformer, ClipTokenizer');p.write_text(s)
(out/'runtime-imports.patch').write_bytes(subprocess.check_output(['git','-C',str(repo),'diff','--',*files]))
print('patched imports; original model classes unchanged')
