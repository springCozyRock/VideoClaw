"""Audited empty-observation guard; no replacement trajectories or metric scores."""
import contextlib
import json
from pathlib import Path
import torch


@contextlib.contextmanager
def finite_flow_guard(report_path):
    import dust3r.cloud_opt.optimizer as optimizer
    original = optimizer.smooth_L1_loss_fn
    report = {'guard': 'Skip only undefined 0/0 flow terms with zero valid pixels',
              'native_formula_for_nonempty_observations': True,
              'calls': 0, 'empty_observation_terms': 0, 'nonfinite_inputs': 0}

    def checked(estimate, gt, mask, beta=1.0, per_pixel_thre=50.0):
        report['calls'] += 1
        with torch.no_grad():
            if not torch.isfinite(estimate).all() or not torch.isfinite(gt).all():
                report['nonfinite_inputs'] += 1
                raise RuntimeError('Nonfinite MonST3R flow input; no trajectory substituted')
            raw = torch.nn.functional.smooth_l1_loss(estimate * mask, gt * mask,
                                                    beta=beta, reduction='none')
            valid = (raw < per_pixel_thre) * mask if per_pixel_thre > 0 else mask
            count = int(valid.sum().item())
        if count == 0:
            report['empty_observation_terms'] += 1
            return estimate.sum() * 0.0
        return original(estimate, gt, mask, beta=beta, per_pixel_thre=per_pixel_thre)

    optimizer.smooth_L1_loss_fn = checked
    try:
        yield report
    finally:
        optimizer.smooth_L1_loss_fn = original
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
