"""가짜 폴더·기록으로 재시작 경계와 읽기 셀을 재현. 외부 접속 없음."""
import sys, pathlib, tempfile, threading, types, ast, json, os
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'drive/scripts'))
import cells_base as cb
C=ROOT/'drive/notebooks/A0_colab/cells_v4.33'
def emit(case,**kw): print(json.dumps(dict(case=case,**kw),ensure_ascii=False),flush=True)
with tempfile.TemporaryDirectory(prefix='b29_extra_') as td:
 p=pathlib.Path(td);base=p/'base';base.mkdir();(base/'shared').mkdir()
 s=cb.start(str(base),'M1',[],local=str(p/'local'))
 # 원래 close 이후, 새 install 이전에 다른 스레드를 실행하는 스케줄을 고정.
 closed=threading.Event();resume=threading.Event();orig=s.close
 def close(): orig();closed.set();resume.wait(5)
 s.close=close
 result={}
 def restart():
  try:result['s']=cb.start(str(base),'M1',[],local=str(p/'local'))
  except Exception as e:result['error']=repr(e)
 t=threading.Thread(target=restart);t.start();closed.wait(5)
 try:(base/'shared/during_restart').write_text('changed');emit('restart_thread_gap',shared_write_succeeded=True)
 except Exception as e:emit('restart_thread_gap',error=repr(e))
 finally:resume.set();t.join();result.get('s',s).close()
 # 새 사람의 analysis 부모가 없는 상태에서 재시작.
 s=cb.start(str(base),'M1',[],local=str(p/'local'))
 try:
  n=cb.start(str(base),'M2',[],local=str(p/'local'));emit('switch_person',success=True);n.close()
 except Exception as e:emit('switch_person',success=False,error=repr(e))
 finally:s.close()
# 0번 셀 원문 함수를 그대로 추출.
node=next(n for n in ast.parse((C/'cell00.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='last_upload')
old={'task_id':'1','result_file':'old.xml','action':'업로드','status':'업로드 완료','run_time':'2026-11-17 11:00:00'}
new={'kind':'track','status':'done','result_file':'new.xml','time':'2026-11-17T10:00:00+09:00'}
ns={'S':types.SimpleNamespace(uploads=lambda tid:[new]),'ctt':types.SimpleNamespace(read_registry=lambda p:[old]),'REGISTRY':'unused'}
exec(compile(ast.Module(body=[node],type_ignores=[]),'cell00','exec'),ns)
emit('same_day_last_upload',selected=ns['last_upload'](1),expected='old.xml')
# S.video 실제 반환형과 cell11 print 원문.
video_node=next(n for n in ast.parse((C/'cell11.py').read_text()).body if isinstance(n,ast.Expr) and 'video.name' in ast.get_source_segment((C/'cell11.py').read_text(),n))
try:exec(compile(ast.Module(body=[video_node],type_ignores=[]),'cell11','exec'),dict(video='/tmp/video.mp4',vw=10,vh=10,fps=30.,vn=20,meta={'start':0,'stop':19,'step':1}))
except Exception as e:emit('cell11_video_string',error=repr(e))
# 新 결과만 존재할 때의 26번 셀: 모형 pandas 표 입력, 기본 jobs 및 tasks/history.
import cvat_task_tools as ctt
h={'1':[dict(time='2026-11-17T10:00:00+09:00',job='J1',kind='track',status='done',task_name='task')]}
prior=sys.modules.get('h_agg');sys.modules['h_agg']=types.SimpleNamespace(result_history=lambda st:h)
for view in ['jobs','tasks','history']:
 src=(C/'cell26.py').read_text();src=src.replace("AC_VIEW   = 'jobs'",f"AC_VIEW   = '{view}'").replace("AC_SAVE   = True","AC_SAVE   = False").replace("AC_TASK   = ''","AC_TASK   = '1'")
 env=dict(BASE='/tmp/base',ctt=types.SimpleNamespace(read_sharded=lambda p:[],as_task_ids=ctt.as_task_ids),S=types.SimpleNamespace(store=None),V433_STATUS=str)
 try:exec(compile(src,'cell26','exec'),env);emit('cell26_'+view,rows=len(env['V']))
 except Exception as e:emit('cell26_'+view,error=repr(e))
if prior:sys.modules['h_agg']=prior
