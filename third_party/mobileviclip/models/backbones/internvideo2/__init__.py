"""Lazy backbone exports: MobileViCLIP does not require InternVideo/FlashAttention."""
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
