"""활성 가드 조회/세션 교체의 스케줄을 고정. 모든 쓰기·전송은 가짜 환경."""
import sys,pathlib,tempfile,threading,json,types,builtins,io,os,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb

def emit(case,**kw):print(json.dumps(dict(case=case,**kw),ensure_ascii=False),flush=True)
# Python 추적으로 활성 세션/가드 지역변수를 읽은 직후만 스케줄을 멈춤.
# 가드 객체·enabled 값·설치/해제 함수는 바꾸지 않음.
def race(kind):
 with tempfile.TemporaryDirectory(prefix='b31_race_') as tmp:
  p=pathlib.Path(tmp);base=p/'base';base.mkdir();local=p/'local'
  s=cb.start(str(base),'M1',['https://fake.cvat'],local=str(local))
  paused=threading.Event();resume=threading.Event();result={}
  lookup=cb._active_writes if kind=='write' else cb._active_cvat
  variable='w' if kind=='write' else 'c'
  def trace(frame,event,arg):
   if frame.f_code is lookup.__code__ and event=='line' and variable in frame.f_locals and not paused.is_set():
    paused.set();resume.wait(10)
   return trace
  class Fake:
   def request(self,method,url):result['sent']=True;return 'fake response'
  if kind=='transport':s.cvat.patch_class(Fake)
  def writer():
   sys.settrace(trace)
   try:
    if kind=='write':(base/'shared.json').write_text('changed');result['wrote']=True
    else:Fake().request('DELETE','https://fake.cvat/api/tasks/1')
   except Exception as e:result['error']=repr(e)
  t=threading.Thread(target=writer);t.start();assert paused.wait(10)
  n=cb.start(str(base),'M1',['https://fake.cvat'],local=str(local))
  resume.set();t.join(10)
  emit('active_lookup_'+kind,**result,active_guard_enabled=(n.writes.enabled if kind=='write' else n.cvat.enabled))
  n.close()
race('write');race('transport')

# 0z6의 uninstall은 원래 함수를 전역에 되돌림. 그 구형 세션이 남은 커널의 수명주기를 모형화.
# 원본 0z6 파일 스냅샷은 없어 전체 구버전 실행이 아니라 구형 close 계약을 주입한 호환 모형임.
with tempfile.TemporaryDirectory(prefix='b31_upgrade_') as tmp:
 p=pathlib.Path(tmp);base=p/'base';base.mkdir()
 orig={'open':cb._orig(builtins.open),'io':cb._orig(io.open)}
 for n in [*cb.WriteGuard.OS_ARGS,'mkdir','makedirs']:orig['os.'+n]=cb._orig(getattr(os,n))
 for n in cb.WriteGuard.SH_ARGS:orig['sh.'+n]=cb._orig(getattr(shutil,n))
 s=cb.start(str(base),'M1',[],local=str(p/'local'))
 def legacy_close():
  builtins.open=orig['open'];io.open=orig['io']
  for k,v in orig.items():
   if k.startswith('os.'):setattr(os,k[3:],v)
   elif k.startswith('sh.'):setattr(shutil,k[3:],v)
  if cb._state().get('active') is s:cb._state()['active']=None
 s.close=legacy_close
 n=cb.start(str(base),'M1',[],local=str(p/'local'))
 try:(base/'upgrade_shared.json').write_text('changed');emit('legacy_uninstall_after_switch',shared_write_succeeded=True,active_is_new=cb.active() is n,new_enabled=n.writes.enabled)
 except Exception as e:emit('legacy_uninstall_after_switch',error=repr(e))
 n.close()

# 새 분석 부모가 기존 공유 폴더를 가리키는 링크인 경우, boot 허용의 실제 효과.
with tempfile.TemporaryDirectory(prefix='b31_boot_') as tmp:
 p=pathlib.Path(tmp);base=p/'base';base.mkdir();(base/'analysis').mkdir();(base/'CVAT_UpLoader').mkdir()
 (base/'analysis/M2').symlink_to(base/'CVAT_UpLoader',target_is_directory=True)
 s=cb.start(str(base),'M1',[],local=str(p/'local'))
 try:
  n=cb.start(str(base),'M2',[],local=str(p/'local'));emit('boot_parent_symlink',actual_output=str(n.out.resolve().relative_to(base)),protected_files=[str(f.relative_to(base)) for f in (base/'CVAT_UpLoader').rglob('*')]);n.close()
 except Exception as e:emit('boot_parent_symlink',error=repr(e))
 finally:s.close()
