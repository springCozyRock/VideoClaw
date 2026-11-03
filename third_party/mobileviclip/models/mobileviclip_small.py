import logging
import os
import json

import torch
from torch import nn
import numpy as np
from PIL import Image
import torchvision.transforms as transforms
from torchvision.transforms import InterpolationMode

import torch.utils.checkpoint as checkpoint
from .backbones.internvideo2 import TextTransformer, ClipTokenizer
from .criterions import VTC_VTM_Loss

import copy
from functools import partial
from typing import List, Tuple, Optional, Union
from timm.data import IMAGENET_DEFAULT_MEAN, IMAGENET_DEFAULT_STD
from timm.models.layers import DropPath, trunc_normal_
from timm.models import register_model
from .backbones.internvideo2.mobileclip.modules.common.mobileone import MobileOneBlock,MobileOneBlock_1d
from .backbones.internvideo2.mobileclip.modules.image.replknet import ReparamLargeKernelConv

from .backbones.internvideo2.pos_embed import get_3d_sincos_pos_embed,get_1d_sincos_pos_embed

logger = logging.getLogger(__name__)


class MobileViCLIP_Small(nn.Module):
    def __init__(self, config, tokenizer=None, is_pretrain=True):
        super().__init__()

        self.config = config
        self.tokenizer = tokenizer
        self.is_pretrain = is_pretrain

        # create modules.
        text_encoder_cfg = json.load(
            open(os.path.join(
                "./models/backbones/internvideo2/mobileclip/configs/" + \
                f"{self.config.model.text_encoder.name}.json"))
        )
        if tokenizer is None:
            self.tokenizer = ClipTokenizer(text_encoder_cfg)
        self.vision_encoder = self.build_vision_encoder()

        self.text_encoder = self.build_text_encoder(cfg=text_encoder_cfg['text_cfg'], projection_dim=text_encoder_cfg["embed_dim"])
        # adopt 1 / 100. as in ViCLIP
        self.temp = nn.parameter.Parameter(torch.ones([]) * config.model.temp)
        self.temp_min = config.model.temp_min
        
        # freeze model
        if self.config.model.freeze_vision:
            for name, p in self.vision_encoder.named_parameters():
                if self.config.model.open_vision_clip_projector and hasattr(name, '_1d'):
                    logger.info(f"Unfreeze {name}")
                elif  "mixer_1d" in name or "norm_1d" in name or "layer_scale_1d" in name:
                    logger.info(f"Unfreeze {name}")
                else:
                    logger.info(f"Freeze {name}")
                    p.requires_grad = False
        if self.config.model.freeze_text:
            for name, p in self.text_encoder.named_parameters():
                if self.config.model.open_text_projection and name.startswith('projection_layer'):
                    logger.info(f"Unfreeze {name}")
                else:
                    logger.info(f"Freeze {name}")
                    p.requires_grad = False

        img_size = self.config.model.vision_encoder.img_size
        self.transform = transforms.Compose(
            [
                transforms.Resize(
                    (img_size, img_size),
                    interpolation=InterpolationMode.BICUBIC,
                ),
                transforms.Lambda(lambda x: x.float().div(255.0)),
                transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
            ]
        )
        # load pretrained models
        self.load_checkpoint(
            config.model.vision_ckpt_path, config.model.text_ckpt_path, 
            config.model.get("extra_ckpt_path", None)
        )
        
        # criterions
        self.clip_loss = VTC_VTM_Loss(False)

    def no_weight_decay(self):
        ret = {"temp"}
        ret.update(
            {"vision_encoder." + k for k in self.vision_encoder.no_weight_decay()}
        )
        # no weight decay for LLM if training
        ret.update(
            {"text_encoder." + k for k, _ in self.text_encoder.named_parameters()}
        )

        return ret
    
    @torch.no_grad()
    def clip_contrastive_temperature(self):
        """Seems only used during pre-training"""
        self.temp.clamp_(min=self.temp_min)

    def forward(self, image, text, idx):
        """forward and calculate loss.

        Args:
            image (torch.Tensor): The input images. Shape: [B,T,C,H,W].
            text (dict): TODO
            idx (torch.Tensor): TODO

        Returns: TODO

        """
        self.clip_contrastive_temperature()
        vision_embeds = self.encode_vision(image)
        text_embeds = self.encode_text(text)

        # VTC loss
        loss_vtc = self.clip_loss.vtc_loss(
            vision_embeds, text_embeds, idx, self.temp, all_gather=True
        )

        return dict(
            loss_vtc=loss_vtc,
        )

    def encode_vision(self, image, test=False):
        """encode image / videos as features.

        Args:
            image (torch.Tensor): The input images.
            test (bool): Whether testing.

        Returns: tuple.
            - vision_embeds (torch.Tensor): The features of all patches. Shape: [B,C].

        """
        T = image.shape[1]
        # use_image = True if T == 1 else False
        image = image.permute(0, 2, 1, 3, 4) # [B,T,C,H,W] -> [B,C,T,H,W]

        vision_embeds = self.vision_encoder(image) 
        return vision_embeds

    def encode_text(self, text):
        """encode text.
        Args:
            text (dict): The output of huggingface's `PreTrainedTokenizer`. contains keys:
                - input_ids (torch.Tensor): Token ids to be fed to a model. Shape: [B,L].
                - attention_mask (torch.Tensor): The mask indicate padded tokens. Shape: [B,L]. 0 is padded token.
                - other keys refer to "https://huggingface.co/docs/transformers/v4.21.2/en/main_classes/tokenizer#transformers.PreTrainedTokenizer.__call__".
        Returns: tuple.
            - text_embeds (torch.Tensor): The features of all tokens. Shape: [B,C].

        """
        text_embeds = self.text_encoder(text)
        return text_embeds

    def build_vision_encoder(self):
        """build vision encoder
        Returns: (vision_encoder, vision_layernorm). Each is a `nn.Module`.

        """
        # return vision_encoder
        layers = [4, 12, 24, 4]
        embed_dims = [80, 160, 320, 640]
        mlp_ratios = [3, 3, 3, 3]
        downsamples = [True, True, True, True]
        se_downsamples = [False, False, True, True]
        pos_embs = [None, None, None, partial(RepCPE, spatial_shape=(7, 7))]
        token_mixers = ("repmixer", "repmixer", "repmixer", "attention")
        model = FastViT(
            layers,
            token_mixers=token_mixers,
            embed_dims=embed_dims,
            pos_embs=pos_embs,
            mlp_ratios=mlp_ratios,
            downsamples=downsamples,
            se_downsamples=se_downsamples,
            clip_embed_dim=self.config.model.vision_encoder.clip_embed_dim,
            attn_pool_num_heads=self.config.model.vision_encoder.attn_pool_num_heads,
            head_drop_path_rate=self.config.model.vision_encoder.head_drop_path_rate,
            pretrained_cfg=None,
            pretrained_cfg_overlay=None,
            projection_dim=512,
        )
        return model

    def build_text_encoder(self, cfg, projection_dim):
        """build text_encoder and possiblly video-to-text multimodal fusion encoder.
        Returns: nn.Module. The text encoder

        """
        text_encoder = TextTransformer(cfg, projection_dim)

        return text_encoder

    def load_checkpoint(self, vision_ckpt_path=None, text_ckpt_path=None, extra_ckpt_path=None):
        assert vision_ckpt_path is not None, "No vision_encoder checkpoint"
        assert text_ckpt_path is not None, "No text_encoder checkpoint"

        new_ckpt = {}

        # load vision_encoder
        logger.info(f"Load vision_encoder checkpoint from {vision_ckpt_path}")
        vision_ckpt = torch.load(vision_ckpt_path, map_location='cpu')
        ckpt_new={}
        for k,v in vision_ckpt.items():
            if "image_encoder.model" in k:
                k_temp=k.replace("image_encoder.model.","")
                ckpt_new[k_temp]=v
        vision_ckpt = ckpt_new
        if self.config.model.get('load_vision_ckpt_from_internvideo2_stage2', False):
            from .backbones.internvideo2.pos_embed import interpolate_pos_embed
            orig_t_size = self.config.model.get('vision_ckpt_t_size', 4)
            interpolate_pos_embed(vision_ckpt, self.vision_encoder, orig_t_size=orig_t_size) # 4 for InternVideo2 stage2
            for k, v in vision_ckpt.items():
                if k.startswith('vision_encoder.'):
                    if 'clip_decoder' in k or 'final_clip_decoder' in k:
                        continue
                    elif 'clip_pos_embed' in k or 'clip_img_pos_embed' in k or 'img_pos_embed' in k :
                        continue
                    else:
                        new_ckpt[k] = v
                else:
                    continue
        else:
            for k, v in vision_ckpt.items():
                if k.startswith('clip_decoder.') or k.startswith('mae_decoder.') or k.startswith('final_clip_decoder.'):
                    continue
                elif k in ['clip_pos_embed', 'mae_pos_embed']:
                    continue
                else:
                    new_k = 'vision_encoder.' + k
                    new_ckpt[new_k] = v

        # load text_encoder
        logger.info(f"Load text_encoder checkpoint from {text_ckpt_path}")
        test_ckpt = torch.load(text_ckpt_path, map_location='cpu')
        if 'module' in test_ckpt.keys():
            test_ckpt = test_ckpt['module']
        for k, v in test_ckpt.items():
            if k.startswith('text_encoder.'):
                new_ckpt[k] = v

        # load extra checkpoint
        # often when post-pretrain after previous pretraining, thus the keys are same
        if extra_ckpt_path is not None:
            logger.info(f"Load extra checkpoint from {extra_ckpt_path}")
            extra_ckpt = torch.load(extra_ckpt_path, map_location='cpu')
            if 'module' in extra_ckpt.keys():
                extra_ckpt = extra_ckpt['module']
            for k, v in extra_ckpt.items():
                new_ckpt[k] = v
        
        msg = self.load_state_dict(new_ckpt, strict=False)
        logger.info(msg)

def _cfg(url="", **kwargs):
    return {
        "url": url,
        "num_classes": 1000,
        "input_size": (3, 256, 256),
        "pool_size": None,
        "crop_pct": 0.95,
        "interpolation": "bicubic",
        "mean": IMAGENET_DEFAULT_MEAN,
        "std": IMAGENET_DEFAULT_STD,
        "classifier": "head",
        **kwargs,
    }


default_cfgs = {
    "fastvit_t": _cfg(crop_pct=0.9),
    "fastvit_s": _cfg(crop_pct=0.9),
    "fastvit_m": _cfg(crop_pct=0.95),
}


def convolutional_stem(
    in_channels: int, out_channels: int, inference_mode: bool = False
) -> nn.Sequential:
    """Build convolutional stem with MobileOne blocks.

    Args:
        in_channels: Number of input channels.
        out_channels: Number of output channels.
        inference_mode: Flag to instantiate model in inference mode. Default: ``False``

    Returns:
        nn.Sequential object with stem elements.
    """
    return nn.Sequential(
        MobileOneBlock(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=3,
            stride=2,
            padding=1,
            groups=1,
            inference_mode=inference_mode,
            use_se=False,
            num_conv_branches=1,
        ),
        MobileOneBlock(
            in_channels=out_channels,
            out_channels=out_channels,
            kernel_size=3,
            stride=2,
            padding=1,
            groups=out_channels,
            inference_mode=inference_mode,
            use_se=False,
            num_conv_branches=1,
        ),
        MobileOneBlock(
            in_channels=out_channels,
            out_channels=out_channels,
            kernel_size=1,
            stride=1,
            padding=0,
            groups=1,
            inference_mode=inference_mode,
            use_se=False,
            num_conv_branches=1,
        ),
    )


class MHSA(nn.Module):
    """Multi-headed Self Attention module.

    Source modified from:
    https://github.com/rwightman/pytorch-image-models/blob/master/timm/models/vision_transformer.py
    """

    def __init__(
        self,
        dim: int,
        head_dim: int = 32,
        qkv_bias: bool = False,
        attn_drop: float = 0.0,
        proj_drop: float = 0.0,
    ) -> None:
        """Build MHSA module that can handle 3D or 4D input tensors.

        Args:
            dim: Number of embedding dimensions.
            head_dim: Number of hidden dimensions per head. Default: ``32``
            qkv_bias: Use bias or not. Default: ``False``
            attn_drop: Dropout rate for attention tensor.
            proj_drop: Dropout rate for projection tensor.
        """
        super().__init__()
        assert dim % head_dim == 0, "dim should be divisible by head_dim"
        self.head_dim = head_dim
        self.num_heads = dim // head_dim
        self.scale = head_dim**-0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # shape = x.shape
        # B, C, H, W = shape
        # N = H * W
        # if len(shape) == 4:
        #     x = torch.flatten(x, start_dim=2).transpose(-2, -1)  # (B, N, C)
        # qkv = (
        #     self.qkv(x)
        #     .reshape(B, N, 3, self.num_heads, self.head_dim)
        #     .permute(2, 0, 3, 1, 4)
        # )
        # q, k, v = qkv.unbind(0)  # make torchscript happy (cannot use tensor as tuple)

        # # trick here to make q@k.t more stable
        # attn = (q * self.scale) @ k.transpose(-2, -1)
        # attn = attn.softmax(dim=-1)
        # attn = self.attn_drop(attn)

        # x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        # x = self.proj(x)
        # x = self.proj_drop(x)
        # if len(shape) == 4:
        #     x = x.transpose(-2, -1).reshape(B, C, H, W)

        # return x

        x = x.reshape(8,int(x.shape[0]/8),x.shape[1],x.shape[2],x.shape[3]) 
        shape = x.shape
        T, B, C, H, W = shape
        x = x.permute(1,2,0,3,4) #B,C,T,W,H
        N = T * H * W
        if len(shape) == 5:
            x = torch.flatten(x, start_dim=2).transpose(-2, -1)  # (B, N, C)
        qkv = (
            self.qkv(x)
            .reshape(B, N, 3, self.num_heads, self.head_dim)
            .permute(2, 0, 3, 1, 4)
        )
        q, k, v = qkv.unbind(0)  # make torchscript happy (cannot use tensor as tuple)

        # trick here to make q@k.t more stable
        attn = (q * self.scale) @ k.transpose(-2, -1)
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        if len(shape) == 5:
            x = x.transpose(-2, -1).reshape(B, C, T, H, W)
        x = x.permute(2,0,1,3,4).reshape(T*B,C,H,W)

        return x


class PatchEmbed(nn.Module):
    """Convolutional patch embedding layer."""

    def __init__(
        self,
        patch_size: int,
        stride: int,
        in_channels: int,
        embed_dim: int,
        inference_mode: bool = False,
        use_se: bool = False,
    ) -> None:
        """Build patch embedding layer.

        Args:
            patch_size: Patch size for embedding computation.
            stride: Stride for convolutional embedding layer.
            in_channels: Number of channels of input tensor.
            embed_dim: Number of embedding dimensions.
            inference_mode: Flag to instantiate model in inference mode. Default: ``False``
            use_se: If ``True`` SE block will be used.
        """
        super().__init__()
        block = list()
        block.append(
            ReparamLargeKernelConv(
                in_channels=in_channels,
                out_channels=embed_dim,
                kernel_size=patch_size,
                stride=stride,
                groups=in_channels,
                small_kernel=3,
                inference_mode=inference_mode,
                use_se=use_se,
            )
        )
        block.append(
            MobileOneBlock(
                in_channels=embed_dim,
                out_channels=embed_dim,
                kernel_size=1,
                stride=1,
                padding=0,
                groups=1,
                inference_mode=inference_mode,
                use_se=False,
                num_conv_branches=1,
            )
        )
        self.proj = nn.Sequential(*block)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.proj(x)
        return x


class RepMixer(nn.Module):
    """Reparameterizable token mixer.

    For more details, please refer to our paper:
    `FastViT: A Fast Hybrid Vision Transformer using Structural Reparameterization <https://arxiv.org/pdf/2303.14189.pdf>`_
    """

    def __init__(
        self,
        dim,
        kernel_size=3,
        use_layer_scale=True,
        layer_scale_init_value=1e-5,
        inference_mode: bool = False,
    ):
        """Build RepMixer Module.

        Args:
            dim: Input feature map dimension. :math:`C_{in}` from an expected input of size :math:`(B, C_{in}, H, W)`.
            kernel_size: Kernel size for spatial mixing. Default: 3
            use_layer_scale: If True, learnable layer scale is used. Default: ``True``
            layer_scale_init_value: Initial value for layer scale. Default: 1e-5
            inference_mode: If True, instantiates model in inference mode. Default: ``False``
        """
        super().__init__()
        self.dim = dim
        self.kernel_size = kernel_size
        self.inference_mode = inference_mode

        if inference_mode:
            self.reparam_conv = nn.Conv2d(
                in_channels=self.dim,
                out_channels=self.dim,
                kernel_size=self.kernel_size,
                stride=1,
                padding=self.kernel_size // 2,
                groups=self.dim,
                bias=True,
            )
            self.reparam_conv_1d = nn.Conv1d(
                in_channels=self.dim,
                out_channels=self.dim,
                kernel_size=self.kernel_size,
                stride=1,
                padding=self.kernel_size // 2,
                groups=self.dim,
                bias=True,
            )
        else:
            self.norm = MobileOneBlock(
                dim,
                dim,
                kernel_size,
                padding=kernel_size // 2,
                groups=dim,
                use_act=False,
                use_scale_branch=False,
                num_conv_branches=0,
            )
            self.mixer = MobileOneBlock(
                dim,
                dim,
                kernel_size,
                padding=kernel_size // 2,
                groups=dim,
                use_act=False,
            )
            self.norm_1d = MobileOneBlock_1d(
                dim,
                dim,
                kernel_size,
                padding=kernel_size // 2,
                groups=dim,
                use_act=False,
                use_scale_branch=False,
                num_conv_branches=0,
            )
            self.mixer_1d = MobileOneBlock_1d(
                dim,
                dim,
                kernel_size,
                padding=kernel_size // 2,
                groups=dim,
                use_act=False,
            )
            self.use_layer_scale = use_layer_scale
            if use_layer_scale:
                self.layer_scale = nn.Parameter(
                    layer_scale_init_value * torch.ones((dim, 1, 1)), requires_grad=True
                )
                self.layer_scale_1d = nn.Parameter(
                    layer_scale_init_value * torch.ones((dim, 1)), requires_grad=True
                )
            
            self.apply(self._init_weights)

    def _init_weights(self, m: nn.Module) -> None:
        if isinstance(m, nn.Conv1d):
            trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # if hasattr(self, "reparam_conv"):
        #     x = self.reparam_conv(x)
        #     # x = self.tam(x)
        #     return x
        # else:
        #     if self.use_layer_scale:
        #         x = x + self.layer_scale * (self.mixer(x) - self.norm(x))
        #     else:
        #         x = x + self.mixer(x) - self.norm(x)
        #     return x
        if hasattr(self, "reparam_conv"): #x:TB,C,H,W
            # x = self.reparam_conv(x)
            x = x.reshape(8,int(x.shape[0]/8),x.shape[1],x.shape[2],x.shape[3])
            t,b,c,h,w = x.shape
            x = x.permute(1,3,4,2,0) #b,h,w,c,t
            x = x.reshape(b*h*w,c,t) #b*h*w,c,t
            x = self.reparam_conv_1d(x)
            x = x.reshape(b,h,w,c,t).permute(4,0,3,1,2).reshape(t*b,c,h,w)
            # x = self.tam(x)
            x = self.reparam_conv(x)
            return x
        else:
            if self.use_layer_scale:
                # print("1 x.shape:",x.shape) #torch.Size([512, 64, 64, 64])
                # print("2 x.shape:",x.shape) #torch.Size([512, 64, 64, 64])
                x = x.reshape(8,int(x.shape[0]/8),x.shape[1],x.shape[2],x.shape[3]) #t,b,c,h,w
                t,b,c,h,w = x.shape
                x = x.permute(1,3,4,2,0) #b,h,w,c,t
                x = x.reshape(b*h*w,c,t) #b*h*w,c,t
                x = x + self.layer_scale_1d * (self.mixer_1d(x) - self.norm_1d(x)) 
                #bxhxw,c,t->txb,c,h,w
                x = x.reshape(b,h,w,c,t).permute(4,0,3,1,2).reshape(t*b,c,h,w)
                x = x + self.layer_scale * (self.mixer(x) - self.norm(x))
                # assert 1==2
            else:
                x = x + self.mixer_1d(x) - self.norm_1d(x)
                x = x + self.mixer(x) - self.norm(x)
            return x

    def reparameterize(self) -> None:
        """Reparameterize mixer and norm into a single
        convolutional layer for efficient inference.
        """
        if self.inference_mode:
            return

        self.mixer.reparameterize()
        self.norm.reparameterize()
        self.mixer_1d.reparameterize()
        self.norm_1d.reparameterize()

        if self.use_layer_scale:
            w = self.mixer.id_tensor + self.layer_scale.unsqueeze(-1) * (
                self.mixer.reparam_conv.weight - self.norm.reparam_conv.weight
            )
            b = torch.squeeze(self.layer_scale) * (
                self.mixer.reparam_conv.bias - self.norm.reparam_conv.bias
            )
            w_1d = self.mixer_1d.id_tensor + self.layer_scale_1d.unsqueeze(-1) * (
                self.mixer_1d.reparam_conv.weight - self.norm_1d.reparam_conv.weight
            )
            b_1d = torch.squeeze(self.layer_scale_1d) * (
                self.mixer_1d.reparam_conv.bias - self.norm_1d.reparam_conv.bias
            )
        else:
            w = (
                self.mixer.id_tensor
                + self.mixer.reparam_conv.weight
                - self.norm.reparam_conv.weight
            )
            b = self.mixer.reparam_conv.bias - self.norm.reparam_conv.bias
            w_1d = (
                self.mixer_1d.id_tensor
                + self.mixer_1d.reparam_conv.weight
                - self.norm_1d.reparam_conv.weight
            )
            b_1d = self.mixer_1d.reparam_conv.bias - self.norm_1d.reparam_conv.bias

        self.reparam_conv = nn.Conv2d(
            in_channels=self.dim,
            out_channels=self.dim,
            kernel_size=self.kernel_size,
            stride=1,
            padding=self.kernel_size // 2,
            groups=self.dim,
            bias=True,
        )
        self.reparam_conv_1d = nn.Conv1d(
            in_channels=self.dim,
            out_channels=self.dim,
            kernel_size=self.kernel_size,
            stride=1,
            padding=self.kernel_size // 2,
            groups=self.dim,
            bias=True,
        )
        self.reparam_conv.weight.data = w
        self.reparam_conv.bias.data = b
        self.reparam_conv_1d.weight.data = w_1d
        self.reparam_conv_1d.bias.data = b_1d

        for para in self.parameters():
            para.detach_()
        self.__delattr__("mixer")
        self.__delattr__("norm")
        if self.use_layer_scale:
            self.__delattr__("layer_scale")
        self.__delattr__("mixer_1d")
        self.__delattr__("norm_1d")
        if self.use_layer_scale:
            self.__delattr__("layer_scale_1d")


class ConvFFN(nn.Module):
    """Convolutional FFN Module."""

    def __init__(
        self,
        in_channels: int,
        hidden_channels: Optional[int] = None,
        out_channels: Optional[int] = None,
        act_layer: nn.Module = nn.GELU,
        drop: float = 0.0,
    ) -> None:
        """Build convolutional FFN module.

        Args:
            in_channels: Number of input channels.
            hidden_channels: Number of channels after expansion. Default: None
            out_channels: Number of output channels. Default: None
            act_layer: Activation layer. Default: ``GELU``
            drop: Dropout rate. Default: ``0.0``.
        """
        super().__init__()
        out_channels = out_channels or in_channels
        hidden_channels = hidden_channels or in_channels
        self.conv = nn.Sequential()
        self.conv.add_module(
            "conv",
            nn.Conv2d(
                in_channels=in_channels,
                out_channels=out_channels,
                kernel_size=7,
                padding=3,
                groups=in_channels,
                bias=False,
            ),
        )
        self.conv.add_module("bn", nn.BatchNorm2d(num_features=out_channels))
        self.fc1 = nn.Conv2d(in_channels, hidden_channels, kernel_size=1)
        self.act = act_layer()
        self.fc2 = nn.Conv2d(hidden_channels, out_channels, kernel_size=1)
        self.drop = nn.Dropout(drop)
        self.apply(self._init_weights)

    def _init_weights(self, m: nn.Module) -> None:
        if isinstance(m, nn.Conv2d):
            trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        x = self.fc1(x)
        x = self.act(x)
        x = self.drop(x)
        x = self.fc2(x)
        x = self.drop(x)
        return x


class RepCPE(nn.Module):
    """Implementation of conditional positional encoding.

    For more details refer to paper:
    `Conditional Positional Encodings for Vision Transformers <https://arxiv.org/pdf/2102.10882.pdf>`_

    In our implementation, we can reparameterize this module to eliminate a skip connection.
    """

    def __init__(
        self,
        in_channels: int,
        embed_dim: int = 768,
        spatial_shape: Union[int, Tuple[int, int]] = (7, 7),
        inference_mode=False,
    ) -> None:
        """Build reparameterizable conditional positional encoding

        Args:
            in_channels: Number of input channels.
            embed_dim: Number of embedding dimensions. Default: 768
            spatial_shape: Spatial shape of kernel for positional encoding. Default: (7, 7)
            inference_mode: Flag to instantiate block in inference mode. Default: ``False``
        """
        super(RepCPE, self).__init__()
        if isinstance(spatial_shape, int):
            spatial_shape = tuple([spatial_shape] * 2)
        assert isinstance(spatial_shape, Tuple), (
            f'"spatial_shape" must by a sequence or int, '
            f"get {type(spatial_shape)} instead."
        )
        assert len(spatial_shape) == 2, (
            f'Length of "spatial_shape" should be 2, '
            f"got {len(spatial_shape)} instead."
        )

        self.spatial_shape = spatial_shape
        self.embed_dim = embed_dim
        self.in_channels = in_channels
        self.groups = embed_dim

        if inference_mode:
            self.reparam_conv = nn.Conv2d(
                in_channels=self.in_channels,
                out_channels=self.embed_dim,
                kernel_size=self.spatial_shape,
                stride=1,
                padding=int(self.spatial_shape[0] // 2),
                groups=self.embed_dim,
                bias=True,
            )
        else:
            self.pe = nn.Conv2d(
                in_channels,
                embed_dim,
                spatial_shape,
                1,
                int(spatial_shape[0] // 2),
                bias=True,
                groups=embed_dim,
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if hasattr(self, "reparam_conv"):
            x = self.reparam_conv(x)
            return x
        else:
            x = self.pe(x) + x
            return x

    def reparameterize(self) -> None:
        # Build equivalent Id tensor
        input_dim = self.in_channels // self.groups
        kernel_value = torch.zeros(
            (
                self.in_channels,
                input_dim,
                self.spatial_shape[0],
                self.spatial_shape[1],
            ),
            dtype=self.pe.weight.dtype,
            device=self.pe.weight.device,
        )
        for i in range(self.in_channels):
            kernel_value[
                i,
                i % input_dim,
                self.spatial_shape[0] // 2,
                self.spatial_shape[1] // 2,
            ] = 1
        id_tensor = kernel_value

        # Reparameterize Id tensor and conv
        w_final = id_tensor + self.pe.weight
        b_final = self.pe.bias

        # Introduce reparam conv
        self.reparam_conv = nn.Conv2d(
            in_channels=self.in_channels,
            out_channels=self.embed_dim,
            kernel_size=self.spatial_shape,
            stride=1,
            padding=int(self.spatial_shape[0] // 2),
            groups=self.embed_dim,
            bias=True,
        )
        self.reparam_conv.weight.data = w_final
        self.reparam_conv.bias.data = b_final

        for para in self.parameters():
            para.detach_()
        self.__delattr__("pe")


class RepMixerBlock(nn.Module):
    """Implementation of Metaformer block with RepMixer as token mixer.

    For more details on Metaformer structure, please refer to:
    `MetaFormer Is Actually What You Need for Vision <https://arxiv.org/pdf/2111.11418.pdf>`_
    """

    def __init__(
        self,
        dim: int,
        kernel_size: int = 3,
        mlp_ratio: float = 4.0,
        act_layer: nn.Module = nn.GELU,
        drop: float = 0.0,
        drop_path: float = 0.0,
        use_layer_scale: bool = True,
        layer_scale_init_value: float = 1e-5,
        inference_mode: bool = False,
        with_cp: bool = False,
        use_flash_attn: bool = False,
        use_fused_rmsnorm: bool = False,
        use_fused_mlp: bool = False,
    ):
        """Build RepMixer Block.

        Args:
            dim: Number of embedding dimensions.
            kernel_size: Kernel size for repmixer. Default: 3
            mlp_ratio: MLP expansion ratio. Default: 4.0
            act_layer: Activation layer. Default: ``nn.GELU``
            drop: Dropout rate. Default: 0.0
            drop_path: Drop path rate. Default: 0.0
            use_layer_scale: Flag to turn on layer scale. Default: ``True``
            layer_scale_init_value: Layer scale value at initialization. Default: 1e-5
            inference_mode: Flag to instantiate block in inference mode. Default: ``False``
        """

        super().__init__()

        self.token_mixer = RepMixer(
            dim,
            kernel_size=kernel_size,
            use_layer_scale=use_layer_scale,
            layer_scale_init_value=layer_scale_init_value,
            inference_mode=inference_mode,
        )

        assert mlp_ratio > 0, "MLP ratio should be greater than 0, found: {}".format(
            mlp_ratio
        )
        mlp_hidden_dim = int(dim * mlp_ratio)
        self.convffn = ConvFFN(
            in_channels=dim,
            hidden_channels=mlp_hidden_dim,
            act_layer=act_layer,
            drop=drop,
        )

        # Drop Path
        self.drop_path = DropPath(drop_path) if drop_path > 0.0 else nn.Identity()

        # Layer Scale
        self.use_layer_scale = use_layer_scale
        if use_layer_scale:
            self.layer_scale = nn.Parameter(
                layer_scale_init_value * torch.ones((dim, 1, 1)), requires_grad=True
            )
        
        self.with_cp = with_cp
        self.use_fused_rmsnorm = use_fused_rmsnorm

    def forward(self, x):
        def _inner_forward(x):
            if self.use_layer_scale:
                # print("1 x.shape:",x.shape) #torch.Size([64(bsxT), 64(C), 64(H), 64(W)])
                x = self.token_mixer(x)
                # print("2 x.shape:",x.shape) #torch.Size([64, 64, 64, 64])
                x = x + self.drop_path(self.layer_scale * self.convffn(x))
                # print("3 x.shape:",x.shape) #torch.Size([64, 64, 64, 64])
                # assert 1==2
            else:
                x = self.token_mixer(x)
                x = x + self.drop_path(self.convffn(x))
            return x

        if self.with_cp:
            return checkpoint.checkpoint(_inner_forward, x)
        else:
            return _inner_forward(x)


class AttentionBlock(nn.Module):
    """Implementation of metaformer block with MHSA as token mixer.

    For more details on Metaformer structure, please refer to:
    `MetaFormer Is Actually What You Need for Vision <https://arxiv.org/pdf/2111.11418.pdf>`_
    """

    def __init__(
        self,
        dim: int,
        mlp_ratio: float = 4.0,
        act_layer: nn.Module = nn.GELU,
        norm_layer: nn.Module = nn.BatchNorm2d,
        drop: float = 0.0,
        drop_path: float = 0.0,
        use_layer_scale: bool = True,
        layer_scale_init_value: float = 1e-5,
        with_cp: bool = False,
        use_flash_attn: bool = False,
        use_fused_rmsnorm: bool = False,
        use_fused_mlp: bool = False,
    ):
        """Build Attention Block.

        Args:
            dim: Number of embedding dimensions.
            mlp_ratio: MLP expansion ratio. Default: 4.0
            act_layer: Activation layer. Default: ``nn.GELU``
            norm_layer: Normalization layer. Default: ``nn.BatchNorm2d``
            drop: Dropout rate. Default: 0.0
            drop_path: Drop path rate. Default: 0.0
            use_layer_scale: Flag to turn on layer scale. Default: ``True``
            layer_scale_init_value: Layer scale value at initialization. Default: 1e-5
        """

        super().__init__()

        self.norm = norm_layer(dim)
        self.token_mixer = MHSA(dim=dim)

        assert mlp_ratio > 0, "MLP ratio should be greater than 0, found: {}".format(
            mlp_ratio
        )
        mlp_hidden_dim = int(dim * mlp_ratio)
        self.convffn = ConvFFN(
            in_channels=dim,
            hidden_channels=mlp_hidden_dim,
            act_layer=act_layer,
            drop=drop,
        )

        # Drop path
        self.drop_path = DropPath(drop_path) if drop_path > 0.0 else nn.Identity()

        # Layer Scale
        self.use_layer_scale = use_layer_scale
        if use_layer_scale:
            self.layer_scale_1 = nn.Parameter(
                layer_scale_init_value * torch.ones((dim, 1, 1)), requires_grad=True
            )
            self.layer_scale_2 = nn.Parameter(
                layer_scale_init_value * torch.ones((dim, 1, 1)), requires_grad=True
            )
        
        self.with_cp = with_cp
        self.use_fused_rmsnorm = use_fused_rmsnorm

        self.temporal_embedding = nn.Parameter(torch.zeros(1, 640, 8))

    def forward(self, x):
        x = x.reshape(8,int(x.shape[0]/8),x.shape[1],x.shape[2],x.shape[3])
        t,b,c,h,w = x.shape
        x = x.permute(1,3,4,2,0) #b,h,w,c,t
        x = x.reshape(b*h*w,c,t) #b*h*w,c,t

        x = x + self.temporal_embedding

        x = x.reshape(b,h,w,c,t).permute(4,0,3,1,2).reshape(t*b,c,h,w)

        def _inner_forward(x):
            if self.use_layer_scale:
                x = x + self.drop_path(self.layer_scale_1 * self.token_mixer(self.norm(x)))
                x = x + self.drop_path(self.layer_scale_2 * self.convffn(x))
            else:
                x = x + self.drop_path(self.token_mixer(self.norm(x)))
                x = x + self.drop_path(self.convffn(x))
            return x

        if self.with_cp:
            return checkpoint.checkpoint(_inner_forward, x)
        else:
            return _inner_forward(x)


def basic_blocks(
    dim: int,
    block_index: int,
    num_blocks: List[int],
    token_mixer_type: str,
    kernel_size: int = 3,
    mlp_ratio: float = 4.0,
    act_layer: nn.Module = nn.GELU,
    norm_layer: nn.Module = nn.BatchNorm2d,
    drop_rate: float = 0.0,
    drop_path_rate: float = 0.0,
    use_layer_scale: bool = True,
    layer_scale_init_value: float = 1e-5,
    inference_mode=False,
    with_cp=False,
    use_flash_attn=False,
    use_fused_rmsnorm=False,
    use_fused_mlp=False,
) -> nn.Sequential:
    """Build FastViT blocks within a stage.

    Args:
        dim: Number of embedding dimensions.
        block_index: block index.
        num_blocks: List containing number of blocks per stage.
        token_mixer_type: Token mixer type.
        kernel_size: Kernel size for repmixer.
        mlp_ratio: MLP expansion ratio.
        act_layer: Activation layer.
        norm_layer: Normalization layer.
        drop_rate: Dropout rate.
        drop_path_rate: Drop path rate.
        use_layer_scale: Flag to turn on layer scale regularization.
        layer_scale_init_value: Layer scale value at initialization.
        inference_mode: Flag to instantiate block in inference mode.

    Returns:
        nn.Sequential object of all the blocks within the stage.
    """
    blocks = []
    for block_idx in range(num_blocks[block_index]):
        block_dpr = (
            drop_path_rate
            * (block_idx + sum(num_blocks[:block_index]))
            / (sum(num_blocks) - 1)
        )
        if token_mixer_type == "repmixer":
            blocks.append(
                RepMixerBlock(
                    dim,
                    kernel_size=kernel_size,
                    mlp_ratio=mlp_ratio,
                    act_layer=act_layer,
                    drop=drop_rate,
                    drop_path=block_dpr,
                    use_layer_scale=use_layer_scale,
                    layer_scale_init_value=layer_scale_init_value,
                    inference_mode=inference_mode,
                    with_cp=with_cp,
                    use_flash_attn=use_flash_attn,
                    use_fused_rmsnorm=use_fused_rmsnorm,
                    use_fused_mlp=use_fused_mlp,
                )
            )
        elif token_mixer_type == "attention":
            blocks.append(
                AttentionBlock(
                    dim,
                    mlp_ratio=mlp_ratio,
                    act_layer=act_layer,
                    norm_layer=norm_layer,
                    drop=drop_rate,
                    drop_path=block_dpr,
                    use_layer_scale=use_layer_scale,
                    layer_scale_init_value=layer_scale_init_value,
                    with_cp=with_cp,
                    use_flash_attn=use_flash_attn,
                    use_fused_rmsnorm=use_fused_rmsnorm,
                    use_fused_mlp=use_fused_mlp,
                )
            )
        else:
            raise ValueError(
                "Token mixer type: {} not supported".format(token_mixer_type)
            )
    blocks = nn.Sequential(*blocks)

    return blocks

class FastViT(nn.Module):
    """
    This class implements `FastViT architecture <https://arxiv.org/pdf/2303.14189.pdf>`_
    """

    def __init__(
        self,
        layers,
        token_mixers: Tuple[str, ...],
        embed_dims=None,
        mlp_ratios=None,
        downsamples=None,
        se_downsamples=None,
        repmixer_kernel_size=3,
        norm_layer: nn.Module = nn.BatchNorm2d,
        act_layer: nn.Module = nn.GELU,
        num_classes=1000,
        pos_embs=None,
        down_patch_size=7,
        down_stride=2,
        drop_rate=0.0,
        drop_path_rate=0.0,
        use_layer_scale=True,
        layer_scale_init_value=1e-5,
        init_cfg=None,
        pretrained=None,
        cls_ratio=2.0,
        inference_mode=False,
        clip_embed_dim=512,
        attn_pool_num_heads=16,
        head_drop_path_rate=0,
        **kwargs,
    ) -> None:

        super().__init__()

        self.num_classes = num_classes
        if pos_embs is None:
            pos_embs = [None] * len(layers)

        if se_downsamples is None:
            se_downsamples = [False] * len(layers)

        # Convolutional stem
        self.patch_embed = convolutional_stem(3, embed_dims[0], inference_mode)

        # Build the main stages of the network architecture
        network = []
        for i in range(len(layers)):
            # Add position embeddings if requested
            if pos_embs[i] is not None:
                network.append(
                    pos_embs[i](
                        embed_dims[i], embed_dims[i], inference_mode=inference_mode
                    )
                )
            stage = basic_blocks(
                embed_dims[i],
                i,
                layers,
                token_mixer_type=token_mixers[i],
                kernel_size=repmixer_kernel_size,
                mlp_ratio=mlp_ratios[i],
                act_layer=act_layer,
                norm_layer=norm_layer,
                drop_rate=drop_rate,
                drop_path_rate=drop_path_rate,
                use_layer_scale=use_layer_scale,
                layer_scale_init_value=layer_scale_init_value,
                inference_mode=inference_mode,
                with_cp=True,
                use_flash_attn=True,
                use_fused_rmsnorm=True,
                use_fused_mlp=True,
            )
            network.append(stage)
            if i >= len(layers) - 1:
                break

            # Patch merging/downsampling between stages.
            if downsamples[i] or embed_dims[i] != embed_dims[i + 1]:
                network.append(
                    PatchEmbed(
                        patch_size=down_patch_size,
                        stride=down_stride,
                        in_channels=embed_dims[i],
                        embed_dim=embed_dims[i + 1],
                        inference_mode=inference_mode,
                        use_se=se_downsamples[i + 1],
                    )
                )
        self.network = nn.ModuleList(network)

        # Classifier head
        self.conv_exp = MobileOneBlock(
            in_channels=embed_dims[-1],
            out_channels=int(embed_dims[-1] * cls_ratio),
            kernel_size=3,
            stride=1,
            padding=1,
            groups=embed_dims[-1],
            inference_mode=inference_mode,
            use_se=True,
            num_conv_branches=1,
        )
        self.head = GlobalPool2D(in_dim=int(embed_dims[-1] * cls_ratio),out_dim=512)
        self.apply(self.cls_init_weights)
        self.init_cfg = copy.deepcopy(init_cfg)
    
    @torch.jit.ignore
    def no_weight_decay(self):
        return {
            'pos_embed', 
            'pos_embed_spatial', 
            'pos_embed_temporal', 
            'pos_embed_cls',
            'cls_token'
        }

    def cls_init_weights(self, m: nn.Module) -> None:
        """Init. for classification"""
        if isinstance(m, nn.Linear):
            trunc_normal_(m.weight, std=0.02)
            if isinstance(m, nn.Linear) and m.bias is not None:
                nn.init.constant_(m.bias, 0)

    def forward_embeddings(self, x: torch.Tensor) -> torch.Tensor:
        x = self.patch_embed(x)
        return x

    def forward_tokens(self, x: torch.Tensor) -> torch.Tensor:
        for idx, block in enumerate(self.network):
            x = block(x)
        # output only the features of last layer for image classification
        return x

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.permute(2,0,1,3,4) 
        T,B,_,H,W=x.shape
        #尝试直接将bs和T混在一块
        x = x.reshape(T*B,3,H,W)
        x_temp = self.forward_embeddings(x)
        x_temp = self.forward_tokens(x_temp)
        x_temp = self.conv_exp(x_temp) 
        x_temp = self.head(x_temp)
        x_new_stack = x_temp.reshape(T,B,x_temp.shape[-1])
        #时序暴力平均
        x_new_stack = x_new_stack.mean(0, keepdim=False) 
        return  x_new_stack

class GlobalPool2D(nn.Module):
    """This class implements global pooling with linear projection."""

    def __init__(self, in_dim, out_dim, *args, **kwargs):
        super().__init__()
        scale = in_dim**-0.5
        self.pool = GlobalPool(pool_type="mean", keep_dim=False)
        self.proj = nn.Parameter(scale * torch.randn(size=(in_dim, out_dim)))
        self.in_dim = in_dim
        self.out_dim = out_dim

    def forward(self, x, *args, **kwargs):
        # x is of shape [batch, in_dim]
        assert (
            x.dim() == 4
        ), "Input should be 4-dimensional (Batch x in_dim x in_height x in_width). Got: {}".format(
            x.shape
        )
        # [batch, in_dim, in_height, in_width] --> [batch, in_dim]
        x = self.pool(x)
        # [batch, in_dim]  x [in_dim, out_dim] --> [batch, out_dim]
        x = x @ self.proj
        return x

class GlobalPool(nn.Module):
    """
    This layers applies global pooling over a 4D or 5D input tensor

    Args:
        pool_type (Optional[str]): Pooling type. It can be mean, rms, or abs. Default: `mean`
        keep_dim (Optional[bool]): Do not squeeze the dimensions of a tensor. Default: `False`

    Shape:
        - Input: :math:`(N, C, H, W)` or :math:`(N, C, D, H, W)`
        - Output: :math:`(N, C, 1, 1)` or :math:`(N, C, 1, 1, 1)` if keep_dim else :math:`(N, C)`
    """

    pool_types = ["mean", "rms", "abs"]

    def __init__(
        self,
        pool_type = "mean",
        keep_dim = False,
        *args,
        **kwargs
    ) -> None:
        super().__init__()
        if pool_type not in self.pool_types:
            logger.error(
                "Supported pool types are: {}. Got {}".format(
                    self.pool_types, pool_type
                )
            )
        self.pool_type = pool_type
        self.keep_dim = keep_dim

    def _global_pool(self, x, dims):
        if self.pool_type == "rms":  # root mean square
            x = x**2
            x = torch.mean(x, dim=dims, keepdim=self.keep_dim)
            x = x**-0.5
        elif self.pool_type == "abs":  # absolute
            x = torch.mean(torch.abs(x), dim=dims, keepdim=self.keep_dim)
        else:
            # default is mean
            # same as AdaptiveAvgPool
            x = torch.mean(x, dim=dims, keepdim=self.keep_dim)
        return x

    def forward(self, x):
        if x.dim() == 4:
            dims = [-2, -1]
        elif x.dim() == 5:
            dims = [-3, -2, -1]
        else:
            raise NotImplementedError("Currently 2D and 3D global pooling supported")
        return self._global_pool(x, dims=dims)

import torch.nn.functional as F

class AttentiveBlock(nn.Module):
    def __init__(self, dim, num_heads, qkv_bias=False, qk_scale=None, drop=0., attn_drop=0.,
                 drop_path=0., norm_layer=nn.LayerNorm, attn_head_dim=None, out_dim=None):
        super().__init__()
        self.norm1_q = norm_layer(dim)
        self.norm1_k = norm_layer(dim)
        self.norm1_v = norm_layer(dim)
        self.cross_attn = CrossAttention(
            dim, num_heads=num_heads, qkv_bias=qkv_bias, qk_scale=qk_scale, attn_drop=attn_drop,
            proj_drop=drop, attn_head_dim=attn_head_dim, out_dim=out_dim)
        if drop_path > 0.:
            logger.info(f"Use DropPath in projector: {drop_path}")
        self.drop_path = DropPath(drop_path) if drop_path > 0. else nn.Identity()
    def forward(self, x_q, x_kv, pos_q, pos_k, bool_masked_pos, rel_pos_bias=None):
        x_q = self.norm1_q(x_q + pos_q)
        x_k = self.norm1_k(x_kv + pos_k)
        x_v = self.norm1_v(x_kv)
        x = self.cross_attn(x_q, k=x_k, v=x_v)
        return x
class CrossAttention(nn.Module):
    def __init__(
            self, dim, num_heads=8, qkv_bias=False, qk_scale=None, attn_drop=0.,
            proj_drop=0., attn_head_dim=None, out_dim=None):
        super().__init__()
        if out_dim is None:
            out_dim = dim
        self.num_heads = num_heads
        head_dim = dim // num_heads
        if attn_head_dim is not None:
            head_dim = attn_head_dim
        all_head_dim = head_dim * self.num_heads
        self.scale = qk_scale or head_dim ** -0.5
        assert all_head_dim == dim
        
        self.q = nn.Linear(dim, all_head_dim, bias=False)
        self.k = nn.Linear(dim, all_head_dim, bias=False)
        self.v = nn.Linear(dim, all_head_dim, bias=False)
        
        if qkv_bias:
            self.q_bias = nn.Parameter(torch.zeros(all_head_dim))
            self.k_bias = nn.Parameter(torch.zeros(all_head_dim))
            self.v_bias = nn.Parameter(torch.zeros(all_head_dim))
        else:
            self.q_bias = None
            self.k_bias = None
            self.v_bias = None
        
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(all_head_dim, out_dim)
        self.proj_drop = nn.Dropout(proj_drop)
    
    def forward(self, x, k=None, v=None):
        B, N, C = x.shape
        N_k = k.shape[1]
        N_v = v.shape[1]
        
        q_bias, k_bias, v_bias = None, None, None
        if self.q_bias is not None:
            q_bias = self.q_bias
            k_bias = self.k_bias
            v_bias = self.v_bias
        
        q = F.linear(input=x, weight=self.q.weight, bias=q_bias)
        q = q.reshape(B, N, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)  # (B, N_head, N_q, dim)
        
        k = F.linear(input=k, weight=self.k.weight, bias=k_bias)
        k = k.reshape(B, N_k, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)
        
        v = F.linear(input=v, weight=self.v.weight, bias=v_bias)
        v = v.reshape(B, N_v, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)
        
        q = q * self.scale
        attn = (q @ k.transpose(-2, -1))  # (B, N_head, N_q, N_k)
        
        attn = attn.softmax(dim=-1)
        attn = self.attn_drop(attn)
        
        x = (attn @ v).transpose(1, 2).reshape(B, N, -1)
        x = self.proj(x)
        x = self.proj_drop(x)
        
        return x

class AttentionPoolingBlock(AttentiveBlock):
    def forward(self, x):
        x_q = x.mean(1, keepdim=True)
        x_kv, pos_q, pos_k = x, 0, 0
        x = super().forward(x_q, x_kv, pos_q, pos_k, bool_masked_pos=None, rel_pos_bias=None)
        x = x.squeeze(1)
        return x

