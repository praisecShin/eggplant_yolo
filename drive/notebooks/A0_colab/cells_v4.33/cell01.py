# 1. 학습 요청 — 데이터셋(채택된 버전)으로 모델 학습을 실행기(GPU)에 요청 · 채택 바꾸기(v4.32 FORCE_NEW 대신)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
TRAIN_MODEL    = ''       # 학습 결과 모델 이름 (runs/<이름>) · '' = 0번 셀에서 고른 모델 이름
TRAIN_DATASET  = ''       # 데이터셋 이름 (datasets/<이름>, 15번 셀로 만든 것) · '' = 'default'
TRAIN_FROM     = 'base'   # 'base' = 0번 셀 MODEL(사전학습)에서 처음부터 · 'current' = 이 모델의 지금 채택 버전에서 이어 학습
TRAIN_EPOCHS   = None     # None = 0번 셀 EPOCHS · 이어 학습은 보통 짧게 (30~60)
TRAIN_PATIENCE = None     # None = 0번 셀 PATIENCE
TRAIN_LR0      = None     # 학습률 · None = 자동
TRAIN_OPTIMIZER = 'auto'  # 'auto' · 'SGD' · 'AdamW' ('auto'는 학습률을 무시하므로 TRAIN_LR0를 정하면 AdamW로)
TRAIN_ARGS     = {}       # 그 밖의 학습 설정: lrf · warmup_epochs · freeze · batch · imgsz · device
SEND           = False    # True = 학습 요청을 보냄 (실행기가 데이터셋을 해시 대조해 받고 학습 → 끝나면 심판이 채택 판단)

# ---- 채택 바꾸기: 파일은 옮기지 않고 어느 버전을 쓸지(CURRENT)만 바꿈 — v4.32의 FORCE_NEW(폴더 지우기)는 없앰
ADOPT_TYPE     = ''       # 'model' 또는 'dataset' · '' = 채택은 바꾸지 않음
ADOPT_NAME     = ''       # 모델·데이터셋 이름
ADOPT_VERSION  = None     # 쓸 버전 ID (예 'train_ab12cd34') · None = 채택 해제
SEND_ADOPT     = False

import json
from IPython.display import display
import pandas as pd
import arbiter as A_
_mname = TRAIN_MODEL or NAME or 'default'
_dname = TRAIN_DATASET or 'default'
def _cur(kind, n):
    try:
        return S.store.read_json(A_.CURRENT_OF[kind].format(n=n)) or {}
    except Exception:
        return {}
_mc, _dc, _tc = _cur('model', _mname), _cur('dataset', _dname), _cur('test_tasks', '')
print(f"모델 {_mname}: 지금 채택 {_mc.get('version') or '없음'}" + (" → 'current'로 이어 학습하려면 채택 버전이 있어야 함" if TRAIN_FROM == 'current' and not _mc.get('version') else ''))
print(f"데이터셋 {_dname}: 지금 채택 {_dc.get('version') or '없음 — 15번 셀로 먼저 만들기'}")
print(f"시험 TASK 설정: {_tc.get('version') or '없음 (33번 셀)'} — 데이터셋이 시험 TASK와 겹치면 심판이 학습을 시작하지 않음")
import h_run as _HR
_args = {'epochs': int(TRAIN_EPOCHS or EPOCHS), 'patience': int(TRAIN_PATIENCE or PATIENCE), 'imgsz': int(IMGSZ)}
if TRAIN_LR0:
    _args['lr0'] = float(TRAIN_LR0)
_opt = 'AdamW' if (TRAIN_LR0 and TRAIN_OPTIMIZER == 'auto') else TRAIN_OPTIMIZER
if _opt != 'auto':
    _args['optimizer'] = _opt
_drop = sorted(k for k in TRAIN_ARGS if k not in _HR.TRAIN_ARG_KEYS)
_args.update({k: v for k, v in TRAIN_ARGS.items() if k in _HR.TRAIN_ARG_KEYS})
if _drop:
    print(f'⚠️ 실행기가 받지 않는 학습 설정은 뺌: {_drop} (받는 것: {", ".join(_HR.TRAIN_ARG_KEYS)})')
if TRAIN_FROM not in ('base', 'current'):
    raise SystemExit("TRAIN_FROM은 'base' 또는 'current' (v4.33은 채택된 버전에서만 이어 학습)")
_params = dict(_args, **({'train_from': 'current'} if TRAIN_FROM == 'current' else {}))
TRAIN_RID = send('train', [], _params, go=SEND, model=_mname, dataset=_dname,
                 note='데이터셋·시작 모델은 심판이 배정할 때의 채택 버전으로 고정')

if ADOPT_TYPE:
    assert ADOPT_TYPE in ('model', 'dataset') and ADOPT_NAME, "ADOPT_TYPE은 'model'·'dataset', ADOPT_NAME 필요"
    _c = _cur(ADOPT_TYPE, ADOPT_NAME)
    print(f"채택 바꾸기: {ADOPT_TYPE} {ADOPT_NAME} — 지금 {_c.get('version') or '없음'} → {ADOPT_VERSION or '해제'}")
    ADOPT_RID = send('force_new', [], {'type': ADOPT_TYPE, 'name': ADOPT_NAME, 'version': ADOPT_VERSION}, go=SEND_ADOPT,
                     note='버전 목록·해시가 맞는 버전만 채택됨')
