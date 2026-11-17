"""b24 추가 재현. 실제 서비스·모델·영상에 접속하지 않음."""
import sys, pathlib, tempfile, json, types, shutil, logging
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'drive/scripts'), str(ROOT/'tests')]
import arbiter as A, arb_io as IO, executor as X, handlers as H, h_task as HT, h_run as HR, h_agg as HA, exec_host as EH, cvat_ops as CO
from fake_cvat import FakeCvat
from cvat_sdk.api_client.exceptions import ApiException
from cvat_sdk.core.exceptions import BackgroundRequestException
from cvat_sdk.core.client import Client
H.load_all()
class Auth:
    def ensure(self): pass
    def call(self, name, fn): return fn()
def context(store, cv, wd, kind='track', **kw):
    env=H.Env(store, cv, tmp=str(wd));env.clock=lambda: 10000000000
    c=X.Ctx(rid='r',kind=kind,lane='task',assign='a',chunk=1,decision='d',task='1',job='j',run='run',auth=lambda phase:Auth(),env=env)
    for k,v in kw.items():setattr(c,k,v)
    return c
with tempfile.TemporaryDirectory(prefix='b24_probe_') as td:
    td=pathlib.Path(td);store=IO.LocalStore(td/'store')
    # T1: SDK가 이미 접수한 작업의 상태 조회가 401이면 분명한 거절로 잘못 분류.
    class PollCvat(FakeCvat):
        accepted=False
        def import_annotations(self, tid, path, fmt, **kw):
            if self.accepted:return super().import_annotations(tid,path,fmt,**kw)
            self.accepted=True
            rc=CO.RealCvat('https://invalid.local','unused')
            def sdk_import(*a):
                print('T1 server_job=started; polling GET returns 401')
                client=types.SimpleNamespace(config=types.SimpleNamespace(status_check_period=0),api_client=types.SimpleNamespace(requests_api=types.SimpleNamespace(retrieve=lambda rid: (_ for _ in ()).throw(ApiException(status=401)))),logger=logging.getLogger('probe'))
                Client.wait_for_completion(client,'accepted-job')
            rc._client=types.SimpleNamespace(tasks=types.SimpleNamespace(retrieve=lambda tid:types.SimpleNamespace(import_annotations=sdk_import)))
            return rc.import_annotations(tid,path,fmt,**kw)
    cv=PollCvat();cv.add_task(1,'x_AA',ann={'shapes':[{'original':True}],'tracks':[],'tags':[]})
    f=td/'new.json';f.write_text(json.dumps({'shapes':[{'new':True}]}))
    c=context(store,cv,td/'commit');c.prepared={'info':cv.get_task(1),'file':str(f),'fmt':HT.IMPORT_FMT,'count':1,'mode':'replace'}
    result=HT.commit(c)
    print('T1 result=',result,'writes=',cv.writes(),'first_server_job_still_started=',cv.accepted)
    # 서버가 failed 상태를 명확히 알려도 BackgroundRequestException은 거절로 변환되지 않음.
    rc=CO.RealCvat('https://invalid.local','unused')
    rc._client=types.SimpleNamespace(tasks=types.SimpleNamespace(retrieve=lambda tid:types.SimpleNamespace(import_annotations=lambda *a: (_ for _ in ()).throw(BackgroundRequestException('failed')))))
    try:rc.import_annotations(1,str(f),HT.IMPORT_FMT)
    except Exception as e:print('S2 terminal failed classification=',type(e).__name__,'rejected=',CO._rejected(e))
    # T2: 복원 결과를 게시한 뒤 실제 소비 함수로 읽음.
    class Rev:
        def rows(self,*a):return [{'sub':'weights/best.pt','user':'u','t':1,'file_id':'f','rev_id':'v'}]
        def download(self,a,b,dest):pathlib.Path(dest).write_bytes(b'model')
    c=context(store,cv,td/'restore',kind='restore23',intake={'params':{'name':'m','user':'A'}})
    c.env.revisions=Rev();store.write_json(A.P_LOCK_MGMT,{'run':'run'})
    print('T2 restore=',HR.run_restore23(c))
    store.write_json('runs/m_A/CURRENT.json',{'version':'run'})
    try:print('T2 media=',EH.Media(store,str(td/'media')).model('m_A'))
    except Exception as e:print('T2 consume=',type(e).__name__,str(e))
    # T3: 만들기 예외가 세션 전체에 남음.
    sc=H.ScopedCvat(cv,test=True,project_id=7)
    tid=sc.create_task('REH_created',project_id=7)
    cv.tasks[tid].update(name='production_vf',project_id=99)
    sc.remove_annotations(tid)
    print('T3 test writes outside scope=',cv.writes()[-1],cv.get_task(tid))
    # T4: 현재 SDK의 DDP 콜백 직렬화 방식. 실행기 progress는 threading.Lock을 잡은 self를 참조.
    import cloudpickle
    ex=X.Executor(store,'e','fp',['gpu'],{},H.Dispatch())
    c.progress=ex._progress
    def on_epoch(n):c.progress(str(n));c.auth('publish').ensure()
    callback=lambda tr:on_epoch(tr.epoch+1)
    try:cloudpickle.dumps(callback);print('T4 callback pickled')
    except Exception as e:print('T4 DDP callback serialization=',type(e).__name__,str(e))
    valid=td/'best.pt';valid.write_bytes(b'valid-weight-artifact')
    H.publish_version(store,'model','trained','v1',{'best.pt':str(valid)})
    store.write_json('runs/trained/CURRENT.json',{'version':'v1'})
    # T5: 실제 WebState.build가 wb.build_state에 모델 목록을 주는지 (CVAT 읽기만 가짜).
    import cvat_task_tools as ctt, web_bridge as wb
    old={n:getattr(ctt,n) for n in ['set_scope','list_tasks_all','whoami']}
    originals={n:getattr(wb,n) for n in ['compute_stats','compute_corrections','snapshots']}
    ctt.set_scope=lambda *a:{};ctt.list_tasks_all=lambda *a,**k:([],{});ctt.whoami=lambda *a:'fake'
    wb.compute_stats=lambda *a,**k:{};wb.compute_corrections=lambda *a,**k:{};wb.snapshots=lambda *a,**k:[]
    raw=types.SimpleNamespace(client=lambda:object())
    web=EH.WebState(store,str(td/'web'),raw,{'cvat_host':'https://invalid.local'})
    outs=web.build(lambda *a:None)
    print('T5 real WebState models=',outs['web/state.json']['models'],'remote models=',[e.path for e in store.list('runs/',True)])
    for n,v in old.items():setattr(ctt,n,v)
    for n,v in originals.items():setattr(wb,n,v)
    # T6: 새 결과만 있는 TASK에 기존 이력은 0으로 표시.
    store.write_json('recovery/1/j/result_plan.json',{'task':'1','kind':'track','rid':'r','count':1})
    store.write_json(A.P_RESULTS+'r__1.json',{'rid':'r','task':'1','job':'j','result':'done'})
    row=HA.task_summary('1',{'name':'x_AA'}, {'history':[]}, {}, {})
    print('T6 after successful job summary=',{k:row[k] for k in ['last','runs','worked']})
