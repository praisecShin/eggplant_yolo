"""b26 프로세스 경계의 새 감독 구조 호환 재현. 이전 비공개 메서드를 호출하지 않음."""
import sys,pathlib,tempfile,time,os,signal,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR,access
with tempfile.TemporaryDirectory(prefix='b28_prior_') as tmp:
 td=pathlib.Path(tmp);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
 child=td/'child.py';child.write_text('''import subprocess,sys,json,time,os
from pathlib import Path
s=json.load(open(sys.argv[1]));mode=s['args']['mode'];w=Path(s['project'])
code="pass" if mode=='zombie' else "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(120)"
g=subprocess.Popen([sys.executable,'-c',code],start_new_session=True,stdout=subprocess.PIPE,text=True)
if mode!='zombie':g.stdout.readline()
(w/'grand.pid').write_text(str(g.pid))
if mode=='fail':os._exit(3)
time.sleep(120)
''')
 for mode in ['lost','fail','zombie']:
  wd=td/mode;tr=HR.RealTrainer(child=str(child),sleep=lambda n:time.sleep(.03));tr.GRACE=.2;tr.KILL_WAIT=4
  def tick():
   if (wd/'grand.pid').exists():raise access.AuthorityLost('compatibility')
  err=None
  try:tr.train(str(ds),'no-model',{'mode':mode},str(wd),lambda n:None,on_tick=tick if mode!='fail' else lambda:None)
  except Exception as e:err=type(e).__name__
  pid=int((wd/'grand.pid').read_text());st=HR._stat(pid)
  try:
   print(json.dumps({'mode':mode,'error':err,'grandchild_live':bool(st and st[2]!='Z'),'status':json.loads((wd/'supervisor.json').read_text())}),flush=True)
  finally:
   if st and st[2]!='Z':os.killpg(pid,signal.SIGKILL)
