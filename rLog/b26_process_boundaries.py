"""b26: 새 세션·좀비·권한 오류 경계. 직접 만든 프로세스만 종료·회수."""
import pathlib,sys,os,time,signal,subprocess,tempfile,json,ctypes
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR, access

def state(pid):
    try:return pathlib.Path(f'/proc/{pid}/stat').read_text().split()[2]
    except FileNotFoundError:return None
with tempfile.TemporaryDirectory(prefix='b26_bounds_') as tmp:
    td=pathlib.Path(tmp);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
    child=td/'child.py';child.write_text('''import subprocess,sys,json,time,os
from pathlib import Path
s=json.load(open(sys.argv[1]));w=Path(s['project'])
g=subprocess.Popen([sys.executable,'-c',"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(90)"],start_new_session=True,stdout=subprocess.PIPE,text=True)
g.stdout.readline();(w/'detached.pid').write_text(str(g.pid));(w/'leader.pid').write_text(str(os.getpid()));time.sleep(90)
''')
    tr=HR.RealTrainer(child=str(child),sleep=lambda n:time.sleep(.03));tr.KILL_WAIT=.1
    wd=td/'detached'
    def tick():
        if (wd/'detached.pid').exists():raise access.AuthorityLost('boundary')
    try:tr.train(str(ds),'no-model',{},str(wd),lambda n:None,on_tick=tick)
    except access.AuthorityLost:pass
    pid=int((wd/'detached.pid').read_text());leader=int((wd/'leader.pid').read_text())
    try:print(json.dumps({'case':'setsid','leader_pgid':leader,'detached_pgid':os.getpgid(pid),'detached_live':state(pid) not in (None,'Z'),'leader_group_alive':tr._group_alive(leader)}),flush=True)
    finally:
        if state(pid) not in (None,'Z'):os.killpg(pid,signal.SIGKILL)
    # 별도 reaper인 이 시험이 손자의 좀비를 일부러 거두기 전 그룹 검사.
    libc=ctypes.CDLL(None,use_errno=True);old=ctypes.c_int();assert libc.prctl(37,ctypes.byref(old),0,0,0)==0
    assert libc.prctl(36,1,0,0,0)==0
    zpid=None
    try:
        leader_code="import subprocess,sys;g=subprocess.Popen([sys.executable,'-c','pass']);print(g.pid,flush=True)"
        p=subprocess.Popen([sys.executable,'-c',leader_code],start_new_session=True,stdout=subprocess.PIPE,text=True)
        zpid=int(p.stdout.readline());p.wait();p.stdout.close()
        for _ in range(100):
            if state(zpid)=='Z':break
            time.sleep(.01)
        before=state(zpid);t=time.monotonic();err=None
        try:tr._kill(p,signal)
        except Exception as e:err=type(e).__name__+':'+str(e)
        print(json.dumps({'case':'zombie_only','state':before,'group_alive':tr._group_alive(p.pid),'error':err,'seconds':round(time.monotonic()-t,1)},ensure_ascii=False),flush=True)
    finally:
        if zpid:
            try:os.waitpid(zpid,0)
            except ChildProcessError:pass
        libc.prctl(36,old.value,0,0,0)
    # 권한 오류는 모형 신호 함수로만 재현. 다른 프로세스에 신호를 보내지 않음.
    with patch.object(HR.os,'killpg',side_effect=PermissionError('denied')):
        print(json.dumps({'case':'permission_zero','group_alive':tr._group_alive(999999)}),flush=True)
        try:tr._kill(type('Proc',(),{'pid':999999})(),signal)
        except Exception as e:print(json.dumps({'case':'permission_terminate','exception':type(e).__name__}),flush=True)
