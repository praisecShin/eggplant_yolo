"""0z2: poll 사이에 리더가 먼저 끝난 새 세션 손자의 추적. 실제 GPU·서비스 없음."""
import pathlib,sys,os,time,tempfile,signal,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR
with tempfile.TemporaryDirectory(prefix='b27_orphan_') as tmp:
 td=pathlib.Path(tmp);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
 child=td/'child.py';child.write_text('''import subprocess,sys,json,os
from pathlib import Path
s=json.load(open(sys.argv[1]));w=Path(s['project'])
g=subprocess.Popen([sys.executable,'-c',"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(90)"],start_new_session=True,stdout=subprocess.PIPE,text=True)
g.stdout.readline();(w/'grand.pid').write_text(str(g.pid));(w/'leader.pid').write_text(str(os.getpid()));sys.exit(3)
''')
 # 첫 poll에서는 리더만 있고, 다음 poll 전에는 새 세션 손자 생성과 리더 종료가 끝나게 함.
 def pause(n):
  for _ in range(100):
   if (td/'out/grand.pid').exists():
    time.sleep(.15);break
   time.sleep(.01)
 tr=HR.RealTrainer(child=str(child),sleep=pause);tr.KILL_WAIT=.1
 err=None
 try:tr.train(str(ds),'no-model',{},str(td/'out'),lambda n:None)
 except Exception as e:err=type(e).__name__
 pid=int((td/'out/grand.pid').read_text());st=HR._stat(pid)
 try:print(json.dumps({'exception':err,'grandchild_live':bool(st and st[2]!='Z'),'grandchild_ppid':st[0] if st else None,'executor_pid':os.getpid(),'adopted_by_executor':bool(st and st[0]==os.getpid())}),flush=True)
 finally:
  if st and st[2]!='Z':os.kill(pid,signal.SIGKILL)
  try:os.waitpid(pid,0)
  except ChildProcessError:pass
