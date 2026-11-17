"""감독의 subreaper 설정 실패 경계. 모형 prctl만 실패시킴. 생성한 새 세션 손자는 직접 정리."""
import pathlib,sys,tempfile,time,json,os,signal
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR
with tempfile.TemporaryDirectory(prefix='b28_supervisor_') as tmp:
 td=pathlib.Path(tmp);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
 child=td/'child.py';child.write_text('''import subprocess,sys,json,os
from pathlib import Path
s=json.load(open(sys.argv[1]));g=subprocess.Popen([sys.executable,'-c',"import time;print('ready',flush=True);time.sleep(120)"],start_new_session=True,stdout=subprocess.PIPE,text=True);g.stdout.readline();(Path(s['project'])/'grand.pid').write_text(str(g.pid));os._exit(3)
''')
 sup=td/'supervisor_wrapper.py';sup.write_text('''import sys,types
sys.path.insert(0,%r)
import train_supervisor as ts
ts.ctypes.CDLL=lambda *a,**k:types.SimpleNamespace(prctl=lambda *a:-1)
sys.exit(ts.main(sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])))
''' % str(ROOT/'drive/scripts'))
 tr=HR.RealTrainer(child=str(child),sleep=lambda n:time.sleep(.2));tr.supervisor=str(sup);tr.GRACE=.1;tr.KILL_WAIT=2
 error=None
 try:tr.train(str(ds),'no-model',{},str(td/'out'),lambda n:None)
 except Exception as e:error=type(e).__name__
 status=json.loads((td/'out/supervisor.json').read_text())
 if not (td/'out/grand.pid').exists():
  print(json.dumps({'error':error,'status':status,'child_marker_absent':True}),flush=True)
  assert error == 'RuntimeError' and status.get('setup_failed') and status.get('child_started') is False
  sys.exit(0)
 pid=int((td/'out/grand.pid').read_text());st=HR._stat(pid)
 try:print(json.dumps({'error':error,'status':json.loads((td/'out/supervisor.json').read_text()),'grandchild_live':bool(st and st[2]!='Z')}),flush=True)
 finally:
  if st and st[2]!='Z':os.killpg(pid,signal.SIGKILL)
