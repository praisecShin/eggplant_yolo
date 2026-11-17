# 28. 웹 관리 화면 — 지금 상태(web/state.json) 보기 + 새로 고침 요청 (상태 파일은 취합 일이 씀)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
WEB_SHOW_REQUESTS = True   # True = 처리 중인 요청 목록도 (읽기만)
SEND = False               # True = 웹 상태 새로 고침 요청 (취합 일이 TASK 목록·통계·검토 수정량을 다시 셈)

import json, pandas as pd
from IPython.display import display
import arbiter as A_
try:
    _ws = json.load(open(f'{BASE}/web/state.json', encoding='utf-8'))
    print(f"web/state.json: {str(_ws.get('generated') or _ws.get('time') or '')[:19]} · TASK {len(_ws.get('tasks') or [])}개 · 모델 {len(_ws.get('models') or [])}개")
except Exception as e:
    print(f'web/state.json을 읽지 못함: {e}')
if WEB_SHOW_REQUESTS:
    _rq = []
    for _e in S.store.list('requests/', False):
        _pr = A_.parse_req_name(_e.path)
        if _pr and _pr[2] not in ('done', 'failed', 'canceled'):
            _rq.append({'요청': _pr[0], '종류': _pr[1], '상태': STATUS_KO.get(_pr[2], _pr[2])})
    display(pd.DataFrame(_rq).set_index('요청') if _rq else '처리 중인 요청 없음')
WEB_RID = send('refresh', [], {}, go=SEND)
