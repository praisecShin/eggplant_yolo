"""b26 좁은 범위 지정 시험·b25 원본 재현 재실행. 실제 서비스 접속 없음."""
from pathlib import Path
import os,subprocess,json,time
root=Path(__file__).resolve().parents[1]
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PATH='/tmp/b24_venv/bin:'+os.environ['PATH'])
cmds=[(n,['/tmp/b24_venv/bin/python',f'tests/test_{n}_433.py','drive']) for n in ['hosts','handlers','e2e','master']]

status=[]
for n,cmd in cmds:
 t=time.time()
 with (root/f'rLog/b27_{n}.log').open('w') as f:r=subprocess.run(cmd,cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
 status.append(dict(name=n,command=cmd,rc=r.returncode,seconds=round(time.time()-t,1)))
 (root/'rLog/b27_test_status.json').write_text(json.dumps(status,indent=2))
 print(status[-1],flush=True)
