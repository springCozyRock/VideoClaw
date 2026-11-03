## MobileViCLIP: An Efficient Video-Text Model for Mobile Devices

Our paper is available in [MobileViCLIP](https://arxiv.org/abs/2508.07312)

### News

[2025.10.8] The code is updated. <br>
[2025.6.28] Our MobileViCLIP has been accepted by ICCV2025. The code will be updated soon. <br>

### Environment preparation

**1:  Create environment**

```
conda env create -f requirements/mobileviclip.yml
```

**2:  Activate environment**

```
conda activate mobileviclip
```

### Data preparation

**1:  Download videos**

All datasets can be downloaded from the official website.

Supposing these videos are in the following path:

```
data
├── anet_1.3_video_val_resize
	├── _1vYKA7mNLI.avi
	└── .....
├── kinetics_400_val_10s_320p
	├── __lt03EF4ao.mp4
	└── .....
└── MSRVTT_Videos
	├── video0.mp4
	└── .....
```

**2:  Download annotations**

You can download the annotations of each datasets from Google Drive [link](https://drive.google.com/drive/folders/1grbR39KnMLpeHPNpX4MBYArhr6wASJza?usp=drive_link). Then, put them in the following path:

```
anno_downstream
└── InternVid
     └── InternVid-10M-flt_1.json
     ├── InternVid-10M-flt_2.json
     └── .....
├── anet_ret_val.json
└── .....
```

**3:  Prepare pretrained weights**

We adopt pre-trained MobileCLIP from [MobileCLIP](https://github.com/apple/ml-mobileclip). You can also download this model from Google Drive [link](https://drive.google.com/drive/folders/1ROJYwQeO8lt4mEfNjEIAIDWj736WIQq7?usp=drive_link).

We also provide our mobileviclip_tiny.pt and mobileviclip_small.pt from Google Drive [link](https://drive.google.com/drive/folders/1ROJYwQeO8lt4mEfNjEIAIDWj736WIQq7?usp=drive_link).

Then, put them in the following path:

```
checkpoints
└── mobileclip_s0.pt
├── mobileclip_s2.pt
├── mobileviclip_tiny.pt
└── mobileviclip_small.pt
```

# Train and test

Please run the following commad for training and inference

For Training,

``` 
bash scripts/pretraining/mobileviclip_<tiny or small>/run.sh
```

For Inference,

``` 
bash scripts/evaluation/clip/zero_shot/mobileviclip_<tiny or small>/eval_<dataset>.sh
```

# Credits

We especially thank the contributors of the  [MobileCLIP](https://github.com/apple/ml-mobileclip)  and  [InternVideo](https://github.com/OpenGVLab/InternVideo/) for providing helpful code.
