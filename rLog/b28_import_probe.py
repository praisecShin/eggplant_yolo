"""가드 설치 후 BASE/scripts의 새 모듈 읽기(import)가 캐시 쓰기로 실패하는지. 임시 BASE만 사용."""
import pathlib,sys,tempfile,importlib,json,os
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb,access
with tempfile.TemporaryDirectory(prefix='b28_import_') as tmp:
 td=pathlib.Path(tmp);base=td/'base';(base/'scripts').mkdir(parents=True);(base/'scripts/b28_fresh_module.py').write_text('VALUE = 7\n')
 S=cb.start(str(base),'M1',[],local=str(td/'local'));old=sys.dont_write_bytecode;sys.dont_write_bytecode=False;sys.path.insert(0,str(base/'scripts'))
 try:
  try:importlib.import_module('b28_fresh_module');print(json.dumps({'import':'success','shared_bytecode_files':[str(p.relative_to(base)) for p in base.rglob('*.pyc')]}))
  except Exception as e:print(json.dumps({'error':type(e).__name__,'message':str(e)},ensure_ascii=False),flush=True)
 finally:
  sys.dont_write_bytecode=old;sys.path.remove(str(base/'scripts'));sys.modules.pop('b28_fresh_module',None);S.close();cb._ACTIVE=None
