from pathlib import Path
import sys,os,json,torch,runpy
ROOT=Path(__file__).resolve().parents[1]
MONST=ROOT/'benchmarks/msvbench/Metrics/MotionQuality/tools/monst3r'
sys.path.insert(0,str(MONST))
import dust3r.cloud_opt.optimizer as optimizer
original=optimizer.smooth_L1_loss_fn
report={'calls':0}
def checked(estimate,gt,mask,beta=1.,per_pixel_thre=50.):
 report['calls']+=1
 raw=torch.nn.functional.smooth_l1_loss(estimate*mask,gt*mask,beta=beta,reduction='none')
 valid=(raw<per_pixel_thre)*mask if per_pixel_thre>0 else mask
 count=int(valid.sum().item())
 finite=bool(torch.isfinite(estimate).all() and torch.isfinite(gt).all())
 if count==0 or not finite:
  report.update(valid_pixel_count=count,estimate_finite=bool(torch.isfinite(estimate).all()),gt_finite=bool(torch.isfinite(gt).all()),mask_pixels=int(mask.sum().item()),shape=list(mask.shape))
  (ROOT/'experiments/msvbench_repair_20261019/camera_loss_diagnostic.json').write_text(json.dumps(report,indent=2))
  raise RuntimeError('MonST3R diagnostic: nonfinite flow input or empty valid-pixel denominator: '+json.dumps(report))
 return original(estimate,gt,mask,beta,per_pixel_thre)
optimizer.smooth_L1_loss_fn=checked
sys.path.insert(0,str(ROOT/'scripts'))
runpy.run_path(str(ROOT/'scripts/run_msvbench.py'),run_name='__main__')
