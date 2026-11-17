# 13. CVAT TASK 백업 요청 — 실행기(CPU)가 서버에 백업 준비를 요청하고 준비되면 backups/<요청ID>/에 받음
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
BK_TASK_IDS = []      # TASK ID 직접 · 비우면 아래 검색어
BK_QUERY    = ''      # TASK 이름 검색. 예: '261019 vf_r2', 'G6 uld tag='
BK_SKIP_SAME = True   # True = 이미 받은 백업이 있고 그 뒤 CVAT에서 바뀌지 않은 TASK는 뺌
SEND        = False

import pandas as pd
from IPython.display import display
_hits = pick_tasks(BK_TASK_IDS, BK_QUERY, label='백업 대상', show=False)
_last = {}
try:
    for _e in S.store.list('backups/pending/', False):
        try:
            _r = S.store.read_json(_e.path)
        except Exception:
            continue
        if isinstance(_r, dict) and _r.get('status') == '받음':
            _t = str(_r.get('task'))
            if _t not in _last or float(_r.get('published_at') or 0) > float(_last[_t].get('published_at') or 0):
                _last[_t] = _r
except Exception:
    pass
BK_TARGETS, _rows = [], []
for t in _hits:
    _r = _last.get(str(t['task_id']))
    _same = bool(_r and str(_r.get('task_updated', ''))[:19] == str(t.get('updated_utc', ''))[:19])
    _skip = BK_SKIP_SAME and _same
    if not _skip:
        BK_TARGETS.append(t)
    _rows.append({'task_id': t['task_id'], 'TASK 이름': t['name'], '마지막 백업': (_r or {}).get('result_file', ''),
                  '이번': '건너뜀 (바뀐 것 없음)' if _skip else '요청'})
if _rows:
    display(pd.DataFrame(_rows).set_index('task_id'))
BK_RID = send('backup', BK_TARGETS, {}, go=SEND and bool(BK_TARGETS)) if BK_TARGETS else print('요청할 TASK가 없습니다')
