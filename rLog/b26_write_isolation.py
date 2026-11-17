"""실제 train_child/RealTrainer + 공개 Ultralytics의 경로·JSON 저장 함수만 실행. 모델·서비스 없음.
기본 소스: 이전 검토에서 내려받은 ultralytics 8.4.215 wheel의 utils/__init__.py.
"""
import pathlib,sys,tempfile,os,time,json,hashlib
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import h_run as HR
source=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/b24_sources/unpacked/ultralytics/utils/__init__.py')
print(json.dumps({'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}),flush=True)
with tempfile.TemporaryDirectory(prefix='b26_isolation_') as tmp:
    td=pathlib.Path(tmp);stub=td/'stub';stub.mkdir();ds=td/'ds';ds.mkdir();(ds/'data.yaml').write_text('names: [x]\n')
    (stub/'ultralytics.py').write_text('''import ast,pathlib,os,contextlib,tempfile,stat,platform,json,logging
from threading import Lock
from pathlib import Path
src=Path(os.environ['B26_ULTRA_SOURCE']);tree=ast.parse(src.read_text())
ns={'os':os,'Path':Path,'contextlib':contextlib,'tempfile':tempfile,'stat':stat,'platform':platform,'LINUX':True,'WINDOWS':False,'MACOS':False,'LOGGER':logging.getLogger('probe'),'Lock':Lock,'json':json}
for node in tree.body:
    if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in ('get_user_config_dir','JSONDict'):
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(src),'exec'),ns)
class YOLO:
    def __init__(self,start):self.start=start
    def train(self,project,name,**kw):
        cfg=ns['get_user_config_dir']()/'settings.json'
        j=ns['JSONDict'](cfg);j.update(last_run=self.start)
        d=Path(project)/name;(d/'weights').mkdir(parents=True);(d/'weights/best.pt').write_bytes(b'W')
        (Path(project)/'config_used.json').write_text(json.dumps({'settings':str(cfg),'last_run':self.start}))
        return None
''')
    trainer=HR.RealTrainer(sleep=lambda n:time.sleep(.02));paths=[]
    env={'PYTHONPATH':str(stub),'XDG_CONFIG_HOME':str(td/'common_config'),'B26_ULTRA_SOURCE':str(source)}
    with patch.dict(os.environ,env):
        os.environ.pop('YOLO_CONFIG_DIR',None)
        for role in ['A','B']:
            wd=td/role
            trainer.train(str(ds),role,{},str(wd),lambda n:None)
            paths.append(json.loads((wd/'config_used.json').read_text())['settings'])
    print(json.dumps({'same_settings_path':paths[0]==paths[1],'outside_both_workdirs':all(not pathlib.Path(paths[0]).is_relative_to(td/role) for role in ['A','B']),'final_shared_settings':json.loads(pathlib.Path(paths[0]).read_text())}),flush=True)
