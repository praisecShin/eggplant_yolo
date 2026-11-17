# 23. 덮어써진 학습 복원 요청 — Drive 버전 기록에서 사용자별 마지막 파일 → 새 모델 이름 <이름>_<A|B…> (원본은 그대로)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
RV_NAME  = ''          # 덮어써진 학습 이름 (옛 runs/ 아래 폴더 이름). 예: 'fruit_r2'
RV_USER  = ''          # 복원할 사람: 'A'·'B'… (아래 표의 기호) 또는 이메일 · '' = 표만 보기
RV_UNTIL = None        # 이 시각(한국 시각) 이전의 마지막 버전만. 예: '2026-10-29 18:30'
SEND     = False       # True = 복원 요청 (Colab Drive 인증이 있는 실행기 — 30번 셀이 처리)

import pandas as pd
from IPython.display import display
assert RV_NAME, 'RV_NAME을 적으세요'
import h_run as _HR
try:
    _rows = _HR.RealRevisions(BASE).rows(RV_NAME, RV_UNTIL)      # Drive 버전 기록 읽기만
except Exception as e:
    _rows = []
    print(f'⚠️ Drive 버전 기록을 읽지 못함: {e} (Colab에서 Drive 인증이 필요)')
_users = sorted({r['user'] for r in _rows}, key=lambda u: min(r['t'] for r in _rows if r['user'] == u))
_sfx = {u: chr(ord('A') + i) for i, u in enumerate(_users)}
if _rows:
    display(pd.DataFrame([{'기호': _sfx[r['user']], '사용자': r['user'], '파일': r['sub'], '시각': r['t']} for r in _rows])
            .sort_values(['기호', '파일']).set_index('기호'))
    print('복원하면 새 모델 이름:', ', '.join(f'{RV_NAME}_{s}' for s in _sfx.values()))
if RV_USER:
    RV_RID = send('restore23', [], {'name': RV_NAME, 'user': RV_USER, 'until': RV_UNTIL}, go=SEND,
                  note=f'새 모델 {RV_NAME}_{_sfx.get(RV_USER, RV_USER)} → 채택은 심판')
