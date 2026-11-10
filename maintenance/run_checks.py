"""Fixed test entrypoint. Only run under the isolated build identity."""
from pathlib import Path
import os
import subprocess
import sys

if os.geteuid()==0:raise SystemExit('Never run candidate tests as root')
root=Path(sys.argv[1]);os.chdir(root)
javascript=sorted((root/'tests').glob('*.test.mjs'))+sorted((root/'whatsapp-bridge').glob('*.test.mjs'))
if not javascript:raise SystemExit('Missing baseline JavaScript tests')
print('ISOLATED_BUILD uid='+str(os.geteuid()),flush=True)
commands=[[sys.executable,'-m','unittest','discover','-s','tests','-q'],
          ['/opt/personal-agents/bin/node','--test',*map(str,javascript)],
          ['/opt/personal-agents/bin/node','--check','mission-control/app.js']]
for path in sorted(root.rglob('*.py')):
    if '.git' not in path.parts:compile(path.read_text(),str(path),'exec')
for command in commands:
    print('CHECK: '+ ' '.join(command),flush=True)
    result=subprocess.run(command,timeout=100)
    if result.returncode:raise SystemExit(result.returncode)
print('MAINTENANCE_CHECKS_PASSED',flush=True)
