# 14. 라벨 export 요청 — 실행기(CPU)가 준비를 요청하고 받아 exports/<요청ID>/에 둠 (15번 셀 데이터셋의 입력)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
EX_IDS     = []                               # TASK ID 직접 (22번 셀의 EXPORT_TODO_IDS 등) · 비우면 검색어
EX_QUERY   = ''                               # TASK 이름 검색. 예: '261015 vf|vf_r2, 261019 vf_r2'
EX_FORMAT  = 'CVAT for images 1.1'            # export 형식 (데이터셋은 'CVAT for images 1.1' 또는 'CVAT for video 1.1')
EX_IMAGES  = False                            # 이미지 포함 (무료 플랜은 거부됨)
EX_SKIP_SAME = True                           # True = 같은 형식으로 받은 export가 있고 그 뒤 CVAT에서 바뀌지 않은 TASK는 뺌
SEND       = False

import pandas as pd
from IPython.display import display
import h_mgmt as _HM
_hits = pick_tasks(EX_IDS, EX_QUERY, label='export 대상', show=False)
try:
    _have = _HM.export_inputs(S.store, [str(t['task_id']) for t in _hits], None)
except Exception:
    _have = {}
EX_TARGETS, _rows = [], []
for t in _hits:
    _r = _have.get(str(t['task_id']))
    _same = bool(_r and _r.get('format') == EX_FORMAT and str(_r.get('task_updated', ''))[:19] == str(t.get('updated_utc', ''))[:19])
    _skip = EX_SKIP_SAME and _same
    if not _skip:
        EX_TARGETS.append(t)
    _rows.append({'task_id': t['task_id'], 'TASK 이름': t['name'], '받은 export': (_r or {}).get('result_file', ''),
                  '이번': '건너뜀 (바뀐 것 없음)' if _skip else '요청'})
if _rows:
    display(pd.DataFrame(_rows).set_index('task_id'))
EX_RID = send('export', EX_TARGETS, {'format': EX_FORMAT, 'images': bool(EX_IMAGES)}, go=SEND and bool(EX_TARGETS)) \
    if EX_TARGETS else print('요청할 TASK가 없습니다')
