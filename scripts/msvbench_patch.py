"""Idempotent path repairs only; keep native metric formulas/prompts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];repo=ROOT/'benchmarks/msvbench'
changes=[]
for p in (repo/'Metrics').glob('*/*.py'):
    if p.name.startswith('._'): continue
    old=p.read_text();s=old.replace('"../../../.."','"../.."')
    for name in ('VisualQuality','StoryVideoAlignment'):
        s=s.replace('BASE_DIR, "'+name+'"','BASE_DIR, "Metrics", "'+name+'"')
    s=s.replace('BASE_DIR, "Benchmark",','BASE_DIR, "Benchmarks",')
    s=s.replace('os.environ[\'HTTP_PROXY\'] = \'YOUR_PROXY_URL\'', '# Placeholder proxy removed: use caller environment')
    s=s.replace('os.environ[\'HTTPS_PROXY\'] = \'YOUR_PROXY_URL\'', '# Placeholder proxy removed: use caller environment')
    s=s.replace('from tools.RAFT.', 'from Metrics.MotionQuality.tools.RAFT.')
    if p.name=='ActionStrength.py' and 'sys.path.append(os.path.join(CURRENT_DIR, "tools", "RAFT"))' not in s:
        s=s.replace('from raft import RAFT', 'sys.path.append(os.path.join(CURRENT_DIR, "tools", "RAFT"))\nfrom raft import RAFT')
    if p.name=='Dover.py':
        s=s.replace('os.path.join(BASE_DIR, "Metrics", "VisualQuality", "tools", "DOVER")','os.path.join(BASE_DIR, "Benchmarks", "EvalCrafter", "metrics", "DOVER")')
        s=s.replace('torch.load(self.opt["test_load_path"], map_location=self.device)','torch.load(os.path.join(BASE_DIR, "Metrics", "VisualQuality", "checkpoints", "DOVER", "DOVER.pth"), map_location=self.device)')
    if p.name=='StyleConsistency.py':
        s=s.replace('"Benchmarks", "vistorybench"','"Benchmarks", "vistorybench"')
    if s!=old:p.write_text(s);changes.append(str(p.relative_to(repo)))
print('Path repairs:',len(changes))

p=repo/'Benchmarks/EvalCrafter/metrics/DOVER/dover/models/evaluator.py'
s=p.read_text().replace('convnext_3d_tiny(pretrained=True)','convnext_3d_tiny(pretrained=False)')
p.write_text(s)
