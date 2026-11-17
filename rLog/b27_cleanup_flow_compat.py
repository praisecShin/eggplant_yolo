"""실제 RealTrainer의 정리 실패가 실행기·심판에 남는 방식. 가짜 학습 자식/데이터셋 엔진만 사용."""
import ast,pathlib,sys,json,shutil,time
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.argv=['tests/test_handlers_433.py','drive']
path=ROOT/'tests/test_handlers_433.py';source=path.read_text();ns={'__file__':str(path)}
exec(compile(source.split('# ======================================================== 2b-1 등록부')[0],str(path),'exec'),ns)
import h_mgmt as HM,h_run as HR,handlers as H
ns['HM']=HM
for node in ast.parse(source).body:
    if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in ('FakeBuilder','add_export'):
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
H.load_all();TMP=ns['TMP'];w=ns['World']();cv=ns['FakeCvat']()
try:
    env=H.Env(w.store,cv,tmp=str(TMP/'run'),clock=w.clk);env.builder=ns['FakeBuilder']()
    child=TMP/'success.py';child.write_text('''import pathlib,json,sys
s=json.load(open(sys.argv[1]));d=pathlib.Path(s['project'])/s['name'];(d/'weights').mkdir(parents=True);(d/'weights/best.pt').write_bytes(b'W');pathlib.Path(s['done']).write_text('{}')
''')
    trainer=HR.RealTrainer(child=str(child),sleep=lambda n:time.sleep(.02))
    def cleanup_fail(proc,tree,signal):
        proc.wait(timeout=10)
        raise HR.CleanupUnknown('시험 정리 확인 불가')
    trainer._kill=cleanup_fail;env.trainer=trainer
    w.executor('CPU',['cpu'],H.Dispatch(env=env));gpu=w.executor('GPU',['gpu'],H.Dispatch(env=env))
    ns['add_export'](w,1,'eggplant_G6_261026_1_4_uld');w.request('ds','dataset',[1],name='ds');w.tick(8)
    w.request('tr','train',[],model='m',dataset='ds');w.tick(10)
    print(json.dumps({'results':[w.j(e.path) for e in w.store.list(ns['A'].P_RESULTS,False) if w.j(e.path).get('rid')=='tr'],
        'locks':[w.j(e.path) for e in w.store.list(ns['A'].P_LOCK_TRAIN,False)],
        'executor_output':[v.get('out') for k,v in gpu.mem.items() if k[0]=='run'],
        'request_files':[e.path for e in w.store.list('requests/',False) if 'REQ_tr__' in e.path]},ensure_ascii=False),flush=True)
finally:shutil.rmtree(TMP,ignore_errors=True)
