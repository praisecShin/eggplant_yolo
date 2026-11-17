# 15. 데이터셋 만들기 요청 — 받은 export(14번 셀)로 실행기(CPU)가 데이터셋 버전을 만듦 → 심판이 채택 → 1번 셀로 학습
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
DS_NAME     = ''        # 데이터셋 이름 (datasets/<이름>) · '' = 'default'
DS_IDS      = []        # 쓸 TASK ID · 비우면 아래 검색어
DS_QUERY    = ''        # TASK 이름 검색 (모든 셀 같은 규칙). 예: 'G1|G3 date=261019.. vf*'
DS_EXPORT_RID = ''      # 특정 export 요청(14번 셀의 요청 ID)의 것만 · '' = TASK마다 가장 나중에 받은 export
VAL_IDS     = []        # val TASK를 ID로 고정 · 비우면 0번 셀 VAL_RULE로 고름
CONVERT     = {'MERGE_HEALTH': True, 'KEEP_CLASSES': ['healthy_fruit'], 'OCCLUDED_POLICY': 'keep', 'VAL_RATIO': 0.2}   # cvat_to_yolo 설정
SEND        = False
# 학습은 데이터셋이 채택된 뒤 1번 셀로 따로 요청 (함께 보내면 학습이 옛 데이터셋으로 시작할 수 있음)

import pandas as pd
from IPython.display import display
import h_mgmt as _HM
_hits = pick_tasks(DS_IDS, DS_QUERY, label='데이터셋 TASK', show=False)
_ids = [str(t['task_id']) for t in _hits]
_have = _HM.export_inputs(S.store, _ids, DS_EXPORT_RID or None) if _ids else {}
try:
    _test = _HM.current_test(S.store)
except Exception as e:
    raise SystemExit(f'⛔ 시험 TASK 설정을 읽지 못함 ({e}) — 실행기도 데이터셋을 만들지 않습니다')
_val = [str(v) for v in VAL_IDS] or [str(t['task_id']) for t in _hits if task_role(t['name']) == 'val']
_rows, DS_TASKS = [], []
for t in _hits:
    tid, k = str(t['task_id']), _HM.task_key(t['name'])
    why = ('export 없음 → 14번 셀' if tid not in _have else
           '시험 TASK' if tid in _test['ids'] else '같은 그루·촬영일 (시험)' if k and k in _test['keys'] else '')
    if tid in _have:
        DS_TASKS.append(tid)
    _rows.append({'task_id': tid, 'TASK 이름': t['name'], 'export': (_have.get(tid) or {}).get('result_file', ''),
                  '역할': 'val' if tid in _val else 'train', '빠짐': why})
if _rows:
    display(pd.DataFrame(_rows).set_index('task_id'))
_miss = [r['task_id'] for r in _rows if r['빠짐'].startswith('export 없음')]
if _miss:
    print(f'⚠️ export가 없는 TASK {len(_miss)}개는 실행기가 데이터셋을 만들지 않습니다(실패) — 14번 셀로 먼저 받거나 빼세요: {_miss[:10]}')
print(f"시험 TASK 설정 {_test['version'] or '없음'}: 시험 TASK·같은 그루·촬영일은 실행기가 뺌")
_p = {'val_ids': [v for v in _val if v in DS_TASKS], 'convert': CONVERT}
if DS_EXPORT_RID:
    _p['export_rid'] = DS_EXPORT_RID
DS_RID = send('dataset', DS_TASKS, _p, go=SEND and bool(DS_TASKS) and not _miss, name=DS_NAME or 'default') \
    if DS_TASKS else print('export가 있는 TASK가 없습니다 — 14번 셀 먼저')
