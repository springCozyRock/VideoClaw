from configs.data import *
from configs.model import *

# ========================= data ==========================
train_corpus = "internvid_all"
train_file = "${available_corpus[${train_corpus}]}"  # for lazy evaluation
test_file = dict(act_val=available_corpus["msrvtt_1k_test"]) 
test_types = ["ret_test"] 
num_workers = 6 

stop_key = None
best_key = ["msrvtt_1k_test_match", "t2v_r1"]
# ========================= input ==========================
num_frames = 8
num_frames_test = 8
batch_size = 64
batch_size_test = 64 
max_txt_l = 32

inputs = dict(
    image_res=256, 
    video_input=dict(
        num_frames="${num_frames}",
        sample_type="rand",
        num_frames_test="${num_frames_test}",
        sample_type_test="middle",
        random_aug=False,
    ),
    max_txt_l=dict(image="${max_txt_l}", video="${max_txt_l}"),
    batch_size=dict(image="${batch_size}", video="${batch_size}"),
    batch_size_test=dict(image="${batch_size_test}", video="${batch_size_test}"),
)

# ========================= model ==========================
model = dict(
    model_cls="MobileViCLIP_Small",
    vision_encoder=dict(
        name="mobileclip_s2",
        img_size=256, 
        head_drop_path_rate=0.,
        attn_pool_num_heads=16,
        clip_embed_dim=512, 
        align_dim=512,
    ),
    text_encoder=dict(
        name="mobileclip_s2"
    ),
    temp=1 / 100.0,
    temp_min=1 / 100.0,
    freeze_vision=False,
    open_vision_clip_projector=True,
    freeze_text=True,
    open_text_projection=True,
    open_text_lora=False,
    vision_ckpt_path="checkpoints/mobileclip_s2.pt",
    load_vision_ckpt_from_internvideo2_stage2=False,
    text_ckpt_path="checkpoints/mobileclip_s2.pt",
)

criterion = dict(
    loss_weight=dict(
        vtc=1.0, 
    ),  # 0: disabled.
)

optimizer = dict(
    opt="adamW",
    lr=1e-5,
    opt_betas=[0.9, 0.98],  # default
    weight_decay=0.2,
    max_grad_norm=-1,  # requires a positive float, use -1 to disable
    # use a different lr for some modules, e.g., larger lr for new modules
    different_lr=dict(enable=False, module_names=[], lr=1e-3),
)

scheduler = dict(sched="cosine", epochs=3, min_lr_multi=0.01, warmup_epochs=0.6)


evaluate = False
deep_fusion = False
evaluation = dict(
    eval_frame_ensemble="concat",  # [concat, max, mean, lse]
    eval_x_only=False,
    k_test=128,
    eval_offload=True,  # offload gpu tensors to cpu to save memory.
)

use_half_precision = True
use_bf16 = True
gradient_checkpointing = True

# ========================= wandb ==========================
wandb = dict(
    enable=False,
    entity="likunchang",  # username or team name to store the runs, see https://docs.wandb.ai/ref/python/init
    project="InternVideo2_CLIP",  # setup in your command line
)
dist_url = "env://"
device = "cuda"
mode = "pt"

# ========================= others ==========================
output_dir = "pretrain_mobileviclip_small_with_internvid" # output dir
resume = False  # if True, load optimizer and scheduler states as well
debug = False
log_freq = 1
seed = 42

save_latest = False
save_iter = 500
save_ckpt_iter = 500
auto_resume = False#True
pretrained_path = ""  # path to pretrained model weights, for resume only?

deepspeed = dict(
    enable=True,
    stage=1,
)
