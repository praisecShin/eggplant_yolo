from pathlib import Path
src=Path('tests/test_arbiter_433.py').read_text().split('# ======================================================== 자격')[0]
exec(compile(src,'tests/test_arbiter_433.py','exec'))
s=approved_sim();s.kill('E1');s.tick(200);s.round();lk=s.lock(7)
sid=s.signal('confirm_choice',owner=A0,task='7',decision=lk['decision'],choice='ok',force=True)
s.round(crash_after=1);p=A.P_SIGNALS+sid+'.json';s.f[p].owner=''
r=s.round();print('owner_unknown protect',r.protect,'done',s.done(sid),'lock',s.lock(7)['state'])
s.f[p].owner=A0;s.tick(20);s.round();print('owner_restored done',s.done(sid),'lock',s.lock(7)['state'])
s=basic();s.round();stop=s.signal('stop');s.round();origin=s.signal('wake',release_stop=stop);rel=s.signal('release',owner=G,stop_id=stop,origin_signal=origin)
s.round(crash_after=1);print('G_release_paused_done',s.done(rel),'active',s.o(A.P_HOLD+stop+'.json')['active'])
s.people=[dict(PEOPLE[0],perms=['request']),PEOPLE[1]]
r=s.round();print('G_release_revoked protect',r.protect,'done',s.done(rel),'hold',s.o(A.P_HOLD+stop+'.json'))
