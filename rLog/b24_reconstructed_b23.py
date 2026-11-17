"""b23 보고서의 S1~S7 조건 재구성. 잃어버린 b23 원본이 아님.
실행: PYTHONDONTWRITEBYTECODE=1 python rLog/b24_reconstructed_b23.py
실제 CVAT·Drive·모델·영상에 접속하지 않음.
"""
import pathlib, sys, json, shutil, subprocess, os, types
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.argv=['tests/test_handlers_433.py','drive']
ns={'__file__':str(ROOT/'tests/test_handlers_433.py')}
src=(ROOT/'tests/test_handlers_433.py').read_text()
exec(compile(src.split('# ======================================================== 2b-1 등록부')[0],ns['__file__'],'exec'),ns)
World,TMP=ns['World'],ns['TMP']
H,X,A,IO,FakeCvat=[ns[n] for n in ['H','X','A','IO','FakeCvat']]
import h_task as HT
H.load_all()
checks=[]
def check(name,condition,**evidence):
    checks.append({'name':name,'passed':bool(condition),'evidence':evidence})
    print(json.dumps(checks[-1],ensure_ascii=False),flush=True)
class Engine:
    def make_track(self,info,ref,wd,params,progress):
        f=pathlib.Path(wd)/'new.json';f.write_text(json.dumps({'tracks':[{'id':i} for i in range(3)]}))
        return {'file':str(f),'fmt':HT.IMPORT_FMT,'count':3}
def world():
    w=World();cv=FakeCvat(clock=w.clk)
    env=H.Env(w.store,H.ScopedCvat(cv,False,None),tmp=str(TMP/f'work{World.n}'),clock=w.clk)
    env.engine=Engine();w.executor('E',['gpu'],H.Dispatch(env=env))
    return w,cv,env
def results(w,rid):
    return [w.j(e.path) for e in w.store.list(A.P_RESULTS,False) if w.j(e.path).get('rid')==rid]
try:
    # S1: 구분자 없는 이름+shape, 일반 이름+tags-only.
    for name,ann in [('humanAA',{'shapes':[{'human':1}],'tags':[],'tracks':[]}),('human_vf',{'shapes':[],'tags':[{'human':1}],'tracks':[]})]:
        w,cv,env=world();cv.add_task(1,name,ann=ann);w.request('protect','track',[1]);w.tick(10)
        r=results(w,'protect')
        check('S1_'+name,r and r[0]['result']=='held:human_labels' and not cv.writes() and cv.tasks[1]['ann']==ann,result=r,writes=cv.writes())
    # S2: 첫 가져오기는 서버에서 started, 응답만 TimeoutError.
    w,cv,env=world();cv.add_task(1,'x_uld',ann={'shapes':[{'human':1}],'tracks':[],'tags':[]})
    imp=cv.import_annotations
    def timeout_import(*a,**k):
        cv.hang_imports=True;imp(*a,**k);raise TimeoutError('접수 뒤 응답 유실')
    cv.import_annotations=timeout_import;w.request('timeout','track',[1]);w.tick(10)
    imports=[c for c in cv.calls if c[0]=='import_annotations'];removes=[c for c in cv.calls if c[0]=='remove_annotations']
    active=[j for j in cv.jobs if j.startswith('import') and cv.import_status(j)=='started']
    check('S2_timeout_restore',len(imports)==len(removes)==1 and bool(active) and w.lock(1).get('state')=='quarantine' and not results(w,'timeout'),writes=cv.writes(),lock=w.lock(1).get('state'),started=active)
    # S3: 되돌리기 삭제 직후 TASK 권한 상실.
    w,cv,env=world();cv.add_task(1,'x_uld',ann={'shapes':[{'human':1}],'tracks':[],'tags':[]});cv.import_fail.add(1)
    rm=cv.remove_annotations;count={'n':0}
    def lose_on_restore(tid):
        count['n']+=1;rm(tid)
        if count['n']==2:
            lk=w.lock(tid);lk['state']='quarantine';w.store.write_json(A.P_LOCK_TASK+f'{tid}.json',lk)
    cv.remove_annotations=lose_on_restore;w.request('lost','track',[1]);w.tick(10)
    imports=[c for c in cv.calls if c[0]=='import_annotations']
    check('S3_restore_authority',count['n']==2 and len(imports)==1 and w.lock(1).get('state')=='quarantine' and not results(w,'lost'),writes=cv.writes(),lock=w.lock(1).get('state'))
    # S4: old 게시 후 corrupt 재게시 시도. 새 정책은 파일 쓰기 전에 거절.
    class Corrupt(IO.LocalStore):
        corrupt=False
        def put_file(self,local,path):
            super().put_file(local,path)
            if self.corrupt:(self.root/path).write_bytes(b'corrupt')
    store=Corrupt(TMP/'republish');f=TMP/'a.bin';f.write_bytes(b'old')
    H.publish_version(store,'model','m','v1',{'a.bin':str(f)});before=store.read_json('runs/m/v/v1/_files.json')
    f.write_bytes(b'new');store.corrupt=True;error=None
    try:H.publish_version(store,'model','m','v1',{'a.bin':str(f)})
    except H.VerifyError as e:error=type(e).__name__
    check('S4_republish',error=='VerifyError' and (store.root/'runs/m/v/v1/a.bin').read_bytes()==b'old' and store.read_json('runs/m/v/v1/_files.json')==before and H.verify_version(store,'model','m','v1'),error=error,file=(store.root/'runs/m/v/v1/a.bin').read_text())
    # S5: 실제 CLI 파서. ultralytics 자리의 가짜 모듈은 모델 생성 직전에 중단.
    stub=TMP/'parser_stub';stub.mkdir();(stub/'ultralytics.py').write_text("def YOLO(*a, **k):\n    raise RuntimeError('B24_PARSER_PASSED_NO_MODEL_LOAD')\n")
    eng=HT.RealEngine(ROOT/'drive/scripts',None,lambda p:'missing.pt',lambda i,r:('missing.mp4',None))
    args=eng.track_args('missing.pt','missing.mp4','missing.zip',TMP/'out',{})
    proc_env=dict(os.environ,PYTHONPATH=str(stub),PYTHONDONTWRITEBYTECODE='1')
    def run_cli(a):return subprocess.run(a,capture_output=True,text=True,cwd=TMP,env=proc_env)
    pr=run_cli(args)
    custom=HT.RealEngine(ROOT/'drive/scripts',None,None,None,settings={'near':1,'box_source':'tracker'})
    check('S5_engine_cli','B24_PARSER_PASSED_NO_MODEL_LOAD' in pr.stderr and pr.returncode!=2 and custom.s['near']==1 and custom.s['box_source']=='tracker',near=args[args.index('--near')+1],box_source=args[args.index('--box-source')+1],returncode=pr.returncode)
    for key,bad in [('--near','0.5'),('--box-source','track')]:
        negative=list(args);negative[negative.index(key)+1]=bad;pr=run_cli(negative)
        check('S5_negative_'+key,pr.returncode==2 and 'B24_PARSER_PASSED_NO_MODEL_LOAD' not in pr.stderr,returncode=pr.returncode)
    # S6: 첫 import는 failed, 다음 백업 import는 성공. 형식은 기존 ctt와 대조.
    import cvat_task_tools as ctt
    w,cv,env=world();original={'shapes':[{'human':1}],'tracks':[],'tags':[]};cv.add_task(1,'x_uld',ann=original)
    imp=cv.import_annotations;n={'value':0}
    def fail_once(*a,**kw):
        n['value']+=1
        if n['value']==1:cv.import_fail.add(1)
        else:cv.import_fail.discard(1)
        return imp(*a,**kw)
    cv.import_annotations=fail_once
    status=cv.import_status
    cv.import_status=lambda job: 'failed' if job==next((j for j in cv.jobs if j.startswith('import')),None) else status(job)
    w.request('formats','track',[1]);w.tick(10)
    fmts=[c[2] for c in cv.calls if c[0]=='import_annotations'];exports=[c[2] for c in cv.calls if c[0]=='request_export'];r=results(w,'formats')
    check('S6_import_format',fmts==[ctt.IMPORT_FORMAT]*2 and exports==[ctt.EXPORT_FORMAT]*2 and cv.tasks[1]['ann']==original and r and r[0]['result']=='failed:import(restored)',imports=fmts,exports=exports,result=r,ann=cv.tasks[1]['ann'])
    # S7: 범위 밖 TASK의 SDK 공개 경로를 통한 삭제 시도.
    cv=FakeCvat();cv.add_task(61,'production_vf',project_id=9)
    cv.client=lambda:types.SimpleNamespace(tasks=types.SimpleNamespace(retrieve=lambda tid:types.SimpleNamespace(remove_annotations=lambda:cv.remove_annotations(tid))))
    sc=H.ScopedCvat(cv,True,7)
    for key,fn in [('wrapped',lambda:sc.remove_annotations(61)),('client',lambda:sc.client().tasks.retrieve(61).remove_annotations()),('session',lambda:sc.session),('ops',lambda:sc.ops)]:
        blocked=False
        try:fn()
        except H.ScopeError:blocked=True
        check('S7_scope_'+key,blocked and not cv.writes(),blocked=blocked,writes=cv.writes())
finally:
    shutil.rmtree(TMP,ignore_errors=True)
    (ROOT/'rLog/b24_reconstructed_b23_status.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
print('RESULT',bool(checks) and all(c['passed'] for c in checks))
sys.exit(0 if checks and all(c['passed'] for c in checks) else 1)
