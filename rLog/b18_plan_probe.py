from pathlib import Path
src=Path('tests/test_arbiter_433.py').read_text().split('# ======================================================== 자격')[0]
exec(compile(src,'tests/test_arbiter_433.py','exec'))
s=approved_sim();s.kill('E1');s.tick(200);s.round();lk=s.lock(7)
sid=s.signal('confirm_choice',owner=M2A,task='7',decision=lk['decision'],choice='ok',force=True)
r=s.round(crash_after=1);plan=s.o(A.P_PLAN+sid+'.json')
print('paused_writes',[(w.path,w.why) for w in r.writes],'saved_done',s.done(sid),'saved_admin',plan['admin'],'state',s.lock(7)['state'])
control=copy.deepcopy(s);control.round();print('normal_done',control.done(sid),'normal_state',control.lock(7)['state'])
plan['admin']=True;s.put(A.P_PLAN+sid+'.json',plan)
r=s.round();print('changed_admin_protect',r.protect,'changed_admin_done',s.done(sid),'state',s.lock(7)['state'])
