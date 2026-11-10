#!/usr/bin/env python3
"""Install the official integrity-checked Claude native npm binary, without sudo remotely."""
import json
import shlex
import subprocess

script=r'''
import base64,hashlib,io,json,os,platform,tarfile,urllib.request
from pathlib import Path
assert platform.machine()=='x86_64','Inspect architecture before installing'
home=Path.home();link=home/'.local/bin/claude'
if link.exists() or link.is_symlink():raise SystemExit('Claude launcher exists; refusing to replace it')
version='2.1.319'
url='https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.319.tgz'
expected='FO4Sd23BO1VCQPiJe5vG3bNnmV5+YiTau7o1lqK3Fr5VlE4TLdKiyYpwQRwEXO91kE2l12Ep2i7J19T8Md2oOQ=='
data=urllib.request.urlopen(url,timeout=90).read()
assert base64.b64encode(hashlib.sha512(data).digest()).decode()==expected,'Package integrity mismatch'
target=home/'.local/share/claude/versions'/version
target.parent.mkdir(parents=True,exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(data)) as archive:
    members=[m for m in archive.getmembers() if m.isfile() and m.name.endswith('/claude')]
    assert len(members)==1,'Unexpected native package layout'
    with target.open('wb') as out:out.write(archive.extractfile(members[0]).read())
target.chmod(0o755);link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(target)
import subprocess
print(subprocess.check_output([str(link),'--version'],text=True).strip())
print('Installed in the SSH owner account; no API key or authentication file copied.')
'''
cmd='python3 -c '+shlex.quote(script)
home='/var/lib/personal-agent-research'
args=['runuser','-u','personal-agent-research','--','env','HOME='+home,'CLOUDSDK_CONFIG='+home+'/.config/gcloud',
      '/opt/personal-agents/google-cloud-sdk/bin/gcloud','--configuration=researcher-invoker-srinitish',
      '--project=avid-renderer-503311-n6','--quiet','compute','ssh','srinitish_srinivasan@petase-design',
      '--zone=us-central1-c','--strict-host-key-checking=yes','--ssh-key-file='+home+'/.ssh/google_compute_engine',
      '--ssh-flag=-oBatchMode=yes','--ssh-flag=-oConnectTimeout=12','--command='+cmd]
subprocess.run(args,check=True,timeout=220)
