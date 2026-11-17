"""2c-1 쓰기 경계: 일반 저장 경로·reload·Drive 별도 경로 모형. 실제 Drive/CVAT 없음."""
import sys,pathlib,tempfile,os,importlib,json,builtins,io,shutil,sqlite3
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb,access
from PIL import Image
original={'open':builtins.open,'io':io.open,**{'os.'+n:getattr(os,n) for n in ['replace','rename','remove','unlink','rmdir','mkdir','makedirs','symlink','link','truncate']},**{'sh.'+n:getattr(shutil,n) for n in ['rmtree','move','copy','copy2','copyfile','copytree']}}
def reset():
 builtins.open=original['open'];io.open=original['io']
 for k,v in original.items():
  if k.startswith('os.'):setattr(os,k[3:],v)
  if k.startswith('sh.'):setattr(shutil,k[3:],v)
def attempt(name,fn):
 try:fn();print(json.dumps({'case':name,'blocked':False}),flush=True)
 except Exception as e:print(json.dumps({'case':name,'blocked':isinstance(e,access.AccessError),'error':type(e).__name__,'message':str(e)[:100]},ensure_ascii=False),flush=True)
with tempfile.TemporaryDirectory(prefix='b28_guard_') as tmp:
 td=pathlib.Path(tmp);base=td/'base';base.mkdir();(base/'shared').mkdir();local=td/'local';os.environ.pop(access.MODE_VAR,None)
 S=cb.start(str(base),'M1',[],local=str(local))
 try:
  attempt('Path.touch',lambda:(base/'shared/touch').touch())
  def tempwrite():
   with tempfile.NamedTemporaryFile(dir=base/'shared') as f:f.write(b'changed')
  attempt('tempfile',tempwrite)
  attempt('PIL.Image.save',lambda:Image.new('RGB',(2,2)).save(base/'shared/image.png'))
  attempt('sqlite3',lambda:sqlite3.connect(str(base/'shared/state.db')).close())
  import numpy as np,zipfile
  attempt('np.save',lambda:np.save(base/'shared/array.npy',np.array([1])))
  def zipwrite():
   with zipfile.ZipFile(base/'shared/out.zip','w') as z:z.writestr('x','value')
  attempt('ZipFile_w',zipwrite)
  # 키워드 인자는 일반 Python API 사용이며 저수준 우회 함수를 직접 부르지 않음.
  (local/'replace.txt').write_text('replacement')
  attempt('os.replace_keywords',lambda:os.replace(src=str(local/'replace.txt'),dst=str(base/'shared/target')))
  (local/'move.txt').write_text('move')
  attempt('shutil.move_keywords',lambda:shutil.move(src=str(local/'move.txt'),dst=str(base/'shared/moved.txt')))
  # cell00의 실제 순서: importlib.reload(cb) → cb.start(...)
  importlib.reload(cb)
  attempt('cell00_reload_start',lambda:cb.start(str(base),'M1',[],local=str(local)))
 finally:reset();cb._ACTIVE=None
 S=cb.start(str(base),'M1',[],local=str(local))
 try:
  attempt('failed_start',lambda:cb.start(str(base),'',[],local=str(local)))
  attempt('write_after_failed_start',lambda:(base/'shared/after_failed_start').write_text('changed'))
 finally:reset();cb._ACTIVE=None
 external=td/'external';external.write_text('outside');link=base/'shared/external_link';link.symlink_to(external)
 S=cb.start(str(base),'M1',[],local=str(local))
 try:attempt('unlink_symlink_entry',lambda:link.unlink())
 finally:S.close();reset();cb._ACTIVE=None
 # 일반 심볼릭 링크는 resolve로 확인. Drive 별도 FUSE 경로는 실물 미검증.
 alias=td/'alias';alias.symlink_to(base,target_is_directory=True)
 S=cb.start(str(base),'M1',[],local=str(local))
 try:attempt('symlink_alias',lambda:(alias/'shared/linked.txt').write_text('x'))
 finally:S.close();reset();cb._ACTIVE=None
