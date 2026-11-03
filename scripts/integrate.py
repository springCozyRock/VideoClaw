from pathlib import Path
root=Path('/mnt/data/bts/repos/VideoClaw');out=root/'configs/mobileviclip/integration_originals';out.mkdir(parents=True,exist_ok=True)
for name in ['directorbench_public_provider.py','directorbench_public.py']:
 p=root/'scripts'/name;backup=out/name
 if not backup.exists():backup.write_bytes(p.read_bytes())
 s=p.read_text()
 if name.endswith('provider.py'):
  old=" os.environ['MOBILEVICLIP_REPO']=str(Path(root)/'third_party/mobileviclip')\n os.environ['MOBILEVICLIP_SMALL_CKPT']=str(Path(root)/'.cache/directorbench_public/models/mobileviclip_small.pt')"
  new=' from mobileviclip_runtime import configure_mobileviclip\n configure_mobileviclip(root)'
  if old in s:s=s.replace(old,new)
  elif new not in s:raise RuntimeError('Provider changed; inspect before editing')
 else:
  marker=" tools={name:shutil.which(name) for name in ('ffmpeg','ffprobe')}"
  new=" from mobileviclip_runtime import model_provenance\n mobileviclip=model_provenance(ROOT)\n assets['mobileclip_s2_weights']={'path':str(ROOT/'.cache/directorbench_public/models/mobileclip_s2.pt'),'ready':(ROOT/'.cache/directorbench_public/models/mobileclip_s2.pt').is_file()}\n assets['mobileviclip_verified_runtime']=mobileviclip\n"+marker
  if 'assets[\'mobileviclip_verified_runtime\']' not in s:
   if marker not in s:raise RuntimeError('Runner changed; inspect before editing')
   s=s.replace(marker,new)
 p.write_text(s)
print('DirectorBench integration updated; published source untouched')
