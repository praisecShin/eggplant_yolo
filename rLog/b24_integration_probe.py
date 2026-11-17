"""공식 World를 사용한 추가 경계 재현. 정의부만 재사용하며 시험 원본은 수정하지 않음."""
import pathlib, sys, json, shutil, tempfile, zipfile, cloudpickle, types
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.argv=['tests/test_handlers_433.py','drive']
ns={'__file__':str(ROOT/'tests/test_handlers_433.py')}
src=(ROOT/'tests/test_handlers_433.py').read_text()
exec(compile(src.split('# ======================================================== 2b-1 등록부')[0],ns['__file__'],'exec'),ns)
World, TMP = ns['World'],ns['TMP']
H,X,A,IO,FakeCvat=[ns[n] for n in ['H','X','A','IO','FakeCvat']]
import h_task as HT, h_agg as HA, h_run as HR
H.load_all()
class Engine:
    def make_track(self,info,ref,wd,params,progress):
        f=pathlib.Path(wd)/'new.json';f.write_text(json.dumps({'tracks':[{'id':1}]}));return {'file':str(f),'fmt':HT.IMPORT_FMT,'count':1}
try:
    # T6: 실제 처리기·실행기·심판으로 track 완료 → refresh
    w=World();cv=FakeCvat(clock=w.clk);cv.add_task(1,'eggplant_G6_261026_1_4_uld')
    env=H.Env(w.store,H.ScopedCvat(cv,False,None),tmp=str(TMP/'t6'),clock=w.clk);env.engine=Engine()
    w.executor('E',['gpu','agg'],H.Dispatch(env=env));w.request('track','track',[1]);w.tick(10)
    w.request('refresh','refresh',[]);w.tick(8)
    print('T6 actual results=',[w.j(e.path) for e in w.store.list(A.P_RESULTS,False)])
    st=w.j('relabel/state.json');print('T6 actual refreshed row=',{k:st['tasks'][0][k] for k in ['id','name','last','runs','worked']})
    # T7: raw 한도 1(5000과 동형) → 범위 필터가 0개로 줄이면 complete=true.
    w=World();cv=FakeCvat(clock=w.clk);cv.add_task(1,'production_uld',project_id=99);cv.add_task(2,'REH_test_uld',project_id=7)
    env=H.Env(w.store,H.ScopedCvat(cv,True,7),tmp=str(TMP/'t7'),test=True,clock=w.clk)
    w.executor('AG',['agg'],H.Dispatch(env=env));w.store.write_json('test/relabel/tracked.json',{'2':{'first_name':'REH_test_uld','in_cvat':True}})
    lim=HA.LIST_LIMIT;HA.LIST_LIMIT=1
    w.request('refresh','refresh',[]);w.tick(6);HA.LIST_LIMIT=lim
    print('T7 actual existing task=',cv.get_task(2),'tracked=',w.j('test/relabel/tracked.json'),'list_complete=',w.j('test/relabel/state.json')['list_complete'])
    # T4: run_train이 실제 생성한 on_epoch를 DDP와 같은 cloudpickle로 넘김.
    w=World();cv=FakeCvat();env=H.Env(w.store,cv,tmp=str(TMP/'t4'),clock=w.clk)
    ds=TMP/'ds.zip'
    with zipfile.ZipFile(ds,'w') as z:z.writestr('data.yaml','path: /tmp/ds\ntrain: train/images\nval: val/images\n')
    H.publish_version(w.store,'dataset','ds','v1',{'dataset.zip':str(ds)},extra={'task_keys':['G6|261026|1|4']})
    w.store.write_json('datasets/ds/CURRENT.json',{'version':'v1'})
    class SerializeTrainer:
        def train(self,ds,start,args,wd,on_epoch):
            try:cloudpickle.dumps(on_epoch)
            except Exception as e:print('T4 actual run_train on_epoch serialization=',type(e).__name__,str(e));raise
    env.trainer=SerializeTrainer();ex=w.executor('GPU',['gpu'],H.Dispatch(env=env))
    class Auth:
        def ensure(self):pass
    w.store.write_json(A.P_LOCK_TRAIN+'m.json',{'run':'training','model':'m','start_dataset_version':'v1'})
    c=X.Ctx(rid='train',kind='train',lane='train',assign='a',chunk=1,decision='d',run='training',env=env,progress=ex._progress,auth=lambda phase:Auth(),intake={'dataset':'ds','params':{'device':'0,1'}})
    try:HR.run_train(c)
    except Exception as e:print('T4 actual run_train failed=',type(e).__name__)
finally:shutil.rmtree(TMP,ignore_errors=True)
