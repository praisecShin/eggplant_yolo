"""셀 요청·신호를 실제 심판에 전달: 등록된 다른 사람과 미등록 계정의 취소. 실제 Drive 없음."""
import pathlib,sys,tempfile,json,os
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb,arbiter as A,arb_io as IO,arb_master as M
with tempfile.TemporaryDirectory(prefix='b28_identity_') as tmp:
 td=pathlib.Path(tmp);base=td/'base';base.mkdir();S=cb.start(str(base),'M1',[],local=str(td/'local'),guard=False)
 st=IO.LocalStore(base,default_owner='a@x');st.write_json(A.P_GRANT,{'epoch':1,'session':'MASTER'},owner='g@x')
 people=[{'id':'M1','account':'a@x','role':'admin','perms':['request'],'status':'active'},{'id':'M2','account':'b@x','role':'user','perms':['request'],'status':'active'}]
 loop=M.MasterLoop(st,'MASTER','fp',lambda:{'accounts':{'A0':'a@x','G':'g@x'},'people':people})
 rid=S.request('track',[1],params={'conf':.3});loop.heartbeat();loop.run_once()
 S2=cb.start(str(base),'M2',[],local=str(td/'local'),guard=False)
 for owner in ['b@x','unregistered@x']:
  sid=S2.signal('cancel',rid=rid);st.owners[A.P_SIGNALS+sid+'.json']=owner
  loop.heartbeat();loop.run_once()
  print(json.dumps({'owner':owner,'signal_result':st.read_json(A.P_DONE+sid+'.json'),'intake_requester':st.read_json(A.P_INTAKE+rid+'.json')['requester']},ensure_ascii=False),flush=True)
 S2.close();cb._ACTIVE=None
