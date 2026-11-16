from pathlib import Path
src=Path('tests/test_arbiter_433.py').read_text().split('# ======================================================== 자격')[0]
exec(compile(src,'tests/test_arbiter_433.py','exec'))
from arb_io import Entry,snapshot
s=basic();s.worker('E1',['gpu']);s.request('dup','track',[41]);p='requests/REQ_dup__track__pending.json'
class Store:
 def list(self,prefix,recursive,include=None):
  out=[Entry(k,r.owner,r.created,r.modified,1) for k,r in s.f.items() if k.startswith(prefix)]
  if prefix=='requests/':out+=[Entry(p,A0,s.now+1,s.now+1,1)]
  return out
 def read_json(self,p):return copy.deepcopy(s.f[p].obj)
f,u,t=snapshot(Store(),[('all','jobs/',True,None),('workers','workers/',True,None),('requests','requests/',False,None)],clock=lambda:s.now)
r=A.decide_round(Cfg(s.me,ACC,PEOPLE),Inputs(s.now,f,s.now,unknown=u))
print('listed_same_path',2,'snapshot_copies',sum(x==p for x in f),'unknown',u,'duplicate_alerts',[w.obj for w in r.writes if w.path.startswith(A.P_ALERT) and w.obj.get('kind')=='duplicate_request'])
