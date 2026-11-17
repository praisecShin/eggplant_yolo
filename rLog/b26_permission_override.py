"""정리 PermissionError가 원래 AuthorityLost를 덮는지. 신호 권한 오류는 모형, 자식은 직접 정리."""
import pathlib,sys,tempfile,time,json
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR,access
with tempfile.TemporaryDirectory(prefix='b26_permission_') as tmp:
 td=pathlib.Path(tmp);ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
 child=td/'child.py';child.write_text('import time;time.sleep(90)\n')
 class Denied(HR.RealTrainer):
  proc=None
  def _kill(self,proc,signal):
   self.proc=proc
   with patch.object(HR.os,'killpg',side_effect=PermissionError('denied')):super()._kill(proc,signal)
 tr=Denied(child=str(child),sleep=lambda n:time.sleep(.01))
 def tick():raise access.AuthorityLost('original')
 try:tr.train(str(ds),'x',{},str(td/'out'),lambda n:None,on_tick=tick)
 except Exception as e:print(json.dumps({'raised':type(e).__name__,'original_context':type(e.__context__).__name__}),flush=True)
 finally:
  if tr.proc is not None:
   if tr.proc.poll() is None:tr.proc.kill()
   tr.proc.wait(timeout=10)
