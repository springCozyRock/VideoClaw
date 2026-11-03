#!/usr/bin/env python3
"""Check actual staged/committed blobs without printing credential values."""
import argparse,os,re,subprocess,sys
from pathlib import Path,PurePosixPath
MAX_BYTES=10*1024*1024
LOCAL_ROOTS={'experiments','datasets','result','results','img_logs','.venvs','.venv','.cache','.migration','runs','outputs','checkpoints','models'}
BINARY_SUFFIXES={'.pt','.pth','.ckpt','.safetensors','.onnx','.bin','.mp4','.mov','.webm','.avi','.wav','.mp3','.sqlite','.sqlite3','.db'}
SECRET_PATTERNS=[re.compile(rb'\bhf_[A-Za-z0-9]{20,}\b'),re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),re.compile(rb'\bAIza[0-9A-Za-z_-]{30,}\b'),re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}\b'),re.compile(rb'(?i)(?:https?://)[^\s/:@]+:[^\s/@]+@')]
def git(*args):return subprocess.check_output(['git',*args])
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tracked',action='store_true');args=parser.parse_args()
 raw=git('ls-tree','-r','--name-only','-z','HEAD') if args.tracked else git('diff','--cached','--name-only','--diff-filter=ACMR','-z')
 names=[x.decode('utf-8','surrogateescape') for x in raw.split(b'\0') if x];errors=[];secrets=[]
 if Path('.env').is_file():
  for line in Path('.env').read_text().splitlines():
   if '=' in line and not line.lstrip().startswith('#'):
    key,value=line.split('=',1);value=value.strip().strip('\"\'')
    if any(k in key.upper() for k in ('KEY','TOKEN','SECRET','PASSWORD')) and len(value)>=20:secrets.append(value.encode())
 process=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
 try:
  for name in names:
   path=PurePosixPath(name);parts=path.parts
   if (parts[0] in LOCAL_ROOTS or '__pycache__' in parts or any(p.startswith(('._','.next')) for p in parts) or path.name=='.DS_Store' or (path.name.startswith('.env') and path.name!='.env.example') or path.suffix.lower() in BINARY_SUFFIXES|{'.pem','.key','.pyc','.pyo'} or path.name in {'.netrc','.pypirc','id_rsa','id_ed25519'}):
    errors.append(name+': local artifact or credential file');continue
   spec=('HEAD:' if args.tracked else ':')+name;process.stdin.write(spec.encode()+b'\n');process.stdin.flush()
   header=process.stdout.readline().split()
   if len(header)!=3:errors.append(name+': missing Git blob');continue
   size=int(header[2]);blob=process.stdout.read(size);process.stdout.read(1)
   if size>MAX_BYTES:errors.append(name+': exceeds 10 MiB');continue
   if any(p.search(blob) for p in SECRET_PATTERNS) or any(value in blob for value in secrets):errors.append(name+': possible credential; inspect locally')
 finally:
  process.stdin.close();process.stdout.close();process.wait()
 if errors:
  print('Repository checks failed:\n'+'\n'.join(errors),file=sys.stderr);return 1
 print('Repository checks passed ({} files).'.format(len(names)));return 0
if __name__=='__main__':raise SystemExit(main())
