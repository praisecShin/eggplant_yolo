"""신규 커널의 설치 실패·동시 start·boot 스레드 범위를 가짜 폴더에서 검사."""
import pathlib,tempfile,sys,threading,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb

def emit(case,**kw):print(json.dumps(dict(case=case,**kw),ensure_ascii=False),flush=True)
with tempfile.TemporaryDirectory(prefix='b31_boundary_') as td:
 p=pathlib.Path(td);base=p/'base';base.mkdir();s=cb.start(str(base),'M1',[],local=str(p/'local'))
 original=cb.TransportGuard.install
 def fail(self):raise RuntimeError('injected install failure')
 cb.TransportGuard.install=fail
 try:
  try:cb.start(str(base),'M1',[],local=str(p/'local'))
  except RuntimeError:pass
  try:(base/'after_failed_install').write_text('changed');blocked=False
  except cb.AnalysisRefused:blocked=True
  emit('install_failure',active_is_previous=cb.active() is s,shared_write_blocked=blocked)
 finally:cb.TransportGuard.install=original
 # 동시 start: boot 설정과 mkdir 사이에서 두 스레드를 기다리게 함.
 mkdir=pathlib.Path.mkdir;ready=[threading.Event(),threading.Event()];go=[threading.Event(),threading.Event()];ids={};results={}
 def delayed(self,*a,**k):
  ix=ids.get(threading.get_ident())
  if ix is not None and self.parent==base/'analysis/M1':
   ready[ix].set();go[ix].wait(10)
  return mkdir(self,*a,**k)
 pathlib.Path.mkdir=delayed
 def run(ix):
  ids[threading.get_ident()]=ix
  try:results[ix]=cb.start(str(base),'M1',[],local=str(p/'local'))
  except Exception as e:results[ix]=repr(e)
 a=threading.Thread(target=run,args=(0,));a.start();assert ready[0].wait(10)
 b=threading.Thread(target=run,args=(1,));b.start();assert ready[1].wait(10)
 go[0].set();a.join(10);go[1].set();b.join(10);pathlib.Path.mkdir=mkdir
 try:(base/'after_concurrent').write_text('changed');blocked=False
 except cb.AnalysisRefused:blocked=True
 emit('concurrent_start',results={k:str(v) for k,v in results.items()},shared_write_blocked=blocked,active_is_previous=cb.active() is s)
 # boot 허용을 둔 스레드 이외에는 허용하지 않음.
 target=base/'analysis/M2/new';cb._state()['boot']=(threading.get_ident(),target,base/'analysis')
 got=[]
 t=threading.Thread(target=lambda:got.append(s.writes._booting(target)));t.start();t.join()
 emit('boot_other_thread',allowed=got[0],outside_allowed=s.writes._booting(base/'shared'))
 cb._state()['boot']=None;s.close()
