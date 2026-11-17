"""0z 학습 프로세스 묶음 종료 경계. 실제 GPU·서비스 사용 없음. 재현이 만든 프로세스만 정리."""
import pathlib,sys,tempfile,time,os,signal,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR, access

def alive(pid):
    try:return pathlib.Path(f'/proc/{pid}/stat').read_text().split()[2]!='Z'
    except FileNotFoundError:return False
with tempfile.TemporaryDirectory(prefix='b25_process_') as td:
    td=pathlib.Path(td);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('path: /old\n')
    child=td/'child.py'
    child.write_text('''import subprocess,sys,os,time,json
from pathlib import Path
spec=json.load(open(sys.argv[1]));wd=Path(spec['project'])
code="import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(120)"
g=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,text=True)
g.stdout.readline()
(wd/'grand.pid').write_text(str(g.pid))
(wd/'leader.pid').write_text(str(os.getpid()))
if spec['args'].get('early_exit'):sys.exit(3)
time.sleep(120)
''')
    tr=HR.RealTrainer(child=str(child),sleep=lambda n:time.sleep(.05));tr.KILL_WAIT=.2
    for early in (False,True):
        wd=td/str(early)
        def tick():
            if (wd/'grand.pid').exists():raise access.AuthorityLost('probe')
        err=None
        try:tr.train(str(ds),'no-model',{'early_exit':early},str(wd),lambda n:None,on_tick=tick if not early else lambda:None)
        except Exception as e:err=type(e).__name__
        pid=int((wd/'grand.pid').read_text());time.sleep(.1)
        try:
            print(json.dumps({'early_exit':early,'error':err,'grandchild_alive_after_return':alive(pid)},ensure_ascii=False),flush=True)
        finally:
            if alive(pid):os.kill(pid,signal.SIGKILL)
