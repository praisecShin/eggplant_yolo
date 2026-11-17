# 9. 자동 라벨(프레임별 shape) 대상 점검 — 고른 TASK와 기존 라벨 처리를 확인 → 10번 셀이 요청
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
AA_TASK_IDS = []        # ← 자동 라벨링할 TASK ID 목록, 예: [2700651, 2700652]
AA_QUERY    = ''        # 또는 TASK 이름 검색 (AA_TASK_IDS가 비었을 때). 예: 'G6 261019 row=2 uld tag='
AA_EXISTING = 'skip'    # 사람이 단 라벨이 있는 TASK(이름이 …_uld·…_AA가 아님): 'skip' = 보류 · 'replace' = 백업한 뒤 교체
AA_MODEL    = None      # None = 0번 셀에서 고른 모델 · 모델 이름 (실행기가 그 모델의 채택 버전을 씀)
AA_CONF_REQ = None      # None = 0번 셀 AA_CONF
# v4.32의 프레임 읽기(영상/CVAT)·타일·화질·병렬 설정은 실행기 설정을 씀 — 셀에서 바꾸지 않음

import pandas as pd
from IPython.display import display
assert AA_EXISTING in ('skip', 'replace'), "AA_EXISTING은 'skip' 또는 'replace'"
_hits = pick_tasks(AA_TASK_IDS, AA_QUERY, label='자동 라벨 대상', show=False)
AA_TARGETS = list(_hits)
AA_PARAMS = {'model': AA_MODEL or NAME, 'conf': float(AA_CONF_REQ or AA_CONF), 'allow_replace': AA_EXISTING == 'replace'}
assert AA_PARAMS['model'], '모델이 없습니다 — AA_MODEL을 적거나 0번 셀 MODEL_CHOICE'
display(pd.DataFrame([{'task_id': t['task_id'], 'TASK 이름': t['name'],
                       '기존 라벨': '교체 가능 (uld·AA)' if str(t['name']).endswith(('uld', 'AA')) else
                       ('교체 (replace)' if AA_EXISTING == 'replace' else '있으면 보류 (사람 라벨 보호)')} for t in _hits]).set_index('task_id')
        if _hits else '대상 없음')
print(f"자동 라벨 대상 {len(AA_TARGETS)}개 · 모델 {AA_PARAMS['model']} · conf {AA_PARAMS['conf']} → 10번 셀에서 SEND = True")
