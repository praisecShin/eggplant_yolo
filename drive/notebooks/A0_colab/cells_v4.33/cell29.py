# 29. 모델·데이터셋 정리 표시 요청 — 안 쓰는 버전에 '정리 대상' 표시만 (지우지 않음) · 실제 지우기는 34번 셀(30일 뒤)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
CLEAN_TYPE     = 'model'  # 'model' 또는 'dataset'
CLEAN_NAME     = ''       # 이름 (runs/<이름> · datasets/<이름>) · '' = 버전 목록만 보기
CLEAN_VERSIONS = []       # 표시할 버전 ID · 비우면 표만
SEND           = False

import pandas as pd
from IPython.display import display
import h_mgmt as _HM
import arbiter as A_
_vs = [v for v in _HM.versions(S.store) if v['type'] == CLEAN_TYPE and (not CLEAN_NAME or v['name'] == CLEAN_NAME)]
_cur = {}
for v in _vs:
    try:
        _cur[v['name']] = (S.store.read_json(A_.CURRENT_OF[CLEAN_TYPE].format(n=v['name'])) or {}).get('version')
    except Exception:
        _cur[v['name']] = None
display(pd.DataFrame([{'이름': v['name'], '버전': v['version'], '채택': '✅ 채택됨 (표시 안 됨)' if _cur.get(v['name']) == v['version'] else '',
                       '이번': '정리 표시' if v['version'] in CLEAN_VERSIONS else ''} for v in _vs]) if _vs else '버전 없음')
if CLEAN_NAME and CLEAN_VERSIONS:
    CLEAN_RID = send('cleanup29', [], {'type': CLEAN_TYPE, 'name': CLEAN_NAME, 'versions': [str(v) for v in CLEAN_VERSIONS]}, go=SEND,
                     note='채택·진행 중 학습·채택 대기 버전은 실행기가 빼고 이유를 남김')
