# 33. 고정 시험 TASK 정하기 요청 — 후보 TASK를 보고 시험 TASK 설정 버전을 만들어 채택 (학습·val에서 빠짐)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
TEST_IDS   = []                       # 시험 TASK ID · 비우면 아래 검색어
TEST_QUERY = 'date=261008|261013'     # 시험 TASK 후보 (U세트 — 모델 개입 없음)
TEST_NOTE  = 'U세트 (모델 개입 없음)'
SEND       = False                    # True = 시험 TASK 설정 요청 (바꾸면 바꾸기 전후 성적은 서로 비교하지 않음)
# v4.32 33번의 연구 단계(지문·성적·관계·분할안)는 분석 셀로 따로 옮김 (2c-4 이후)

import pandas as pd
from IPython.display import display
import h_mgmt as _HM
_hits = pick_tasks(TEST_IDS, TEST_QUERY, label='시험 TASK 후보', show=False)
try:
    _now = _HM.current_test(S.store)
except Exception as e:
    _now = {'version': f'읽지 못함 ({e})', 'ids': [], 'keys': []}
_keys = sorted({k for k in (_HM.task_key(t['name']) for t in _hits) if k})
display(pd.DataFrame([{'task_id': t['task_id'], 'TASK 이름': t['name'], '그루·촬영일': _HM.task_key(t['name']) or '(이름에서 못 읽음)',
                       '지금 시험 TASK': '✅' if str(t['task_id']) in _now['ids'] else ''} for t in _hits]).set_index('task_id')
        if _hits else '후보 없음')
print(f"지금 시험 TASK 설정: {_now['version'] or '없음'} ({len(_now['ids'])}개) → 바꾸면 {len(_hits)}개, 같은 그루·촬영일 {len(_keys)}개가 학습에서 빠짐")
TEST_RID = send('test_tasks33', _hits, {'ids': [str(t['task_id']) for t in _hits], 'note': TEST_NOTE},
                go=SEND and bool(_hits)) if _hits else None
