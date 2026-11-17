# 6. 이 결과 올리기 · 요청 상태 — 분석 결과(5·10·27번 셀)를 고정 제출본으로 내고 올리기 요청 · 내 요청 상태·취소
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
UP_FROM      = 'all'     # 올릴 분석 결과: 'track'(5번 TRACK_RESULTS) · 'shape'(10번 AA_RESULTS) · 'ensemble'(27번 EN_RESULTS) · 'all'
UP_IDS       = []        # 그중 이 TASK만 · 비우면 전부
UP_FILES     = {}        # 또는 직접: {TASK ID: '내 분석 폴더 안 파일 경로'} (형식은 확장자로: .xml = track, .json = shape)
UP_MODE      = 'replace' # 'replace' = 기존 라벨을 지우고 바꿈 · 'append' = 덧붙임 (track은 replace만)
UP_REPLACE_HUMAN = False # True = 사람이 단 라벨(이름이 …_uld·…_AA가 아님)이 있어도 바꿈 · False = 실행기가 '보류'
SEND         = False     # True = 제출본을 고정하고 올리기 요청 (제출 뒤 분석 파일을 바꿔도 올라가는 것은 고정본)

SHOW_ALL   = False       # 요청 표: True = 이 사람의 다른 세션에서 보낸 요청도
CANCEL_RID = ''          # 취소할 요청 ID · '' = 취소하지 않음
SEND_CANCEL = False

import pandas as pd
from IPython.display import display
assert UP_MODE in ('replace', 'append'), "UP_MODE는 'replace' 또는 'append'"
_pool = {}
for _k, _g in (('track', 'TRACK_RESULTS'), ('shape', 'AA_RESULTS'), ('ensemble', 'EN_RESULTS')):
    if UP_FROM in (_k, 'all'):
        for tid, r in (globals().get(_g) or {}).items():
            _pool[int(tid)] = dict(r, kind=r.get('kind', _k))
for tid, f in (UP_FILES or {}).items():
    f = f if os.path.isabs(f) else f'{BASE}/{f}'
    _pool[int(tid)] = {'file': f, 'fmt': 'CVAT 1.1' if f.endswith('.xml') else 'shapes-json', 'count': 0, 'kind': 'file',
                       'model': model_label(), 'settings': {}}
if UP_IDS:
    _pool = {t: r for t, r in _pool.items() if t in {int(i) for i in ctt.as_task_ids(UP_IDS)}}
_rows, UP_ITEMS = [], []
for tid, r in sorted(_pool.items()):
    row = {'task_id': tid, '종류': r['kind'], '파일': os.path.relpath(r['file'], BASE), '개수': r.get('count', ''), '모델': r.get('model', '')}
    try:
        _inside = os.path.realpath(r['file']).startswith(os.path.realpath(OUT) + os.sep)
        if not _inside:
            row['확인'] = '❌ 내 분석 폴더(OUT) 밖의 파일'; _rows.append(row); continue
        task = CLIENT.tasks.retrieve(tid)
        info = {'frames': int(task.size), 'labels': [l.name for l in task.get_labels()]}
        mode = 'replace' if r['fmt'] == 'CVAT 1.1' else UP_MODE
        human = not str(task.name).endswith(('uld', 'AA'))
        row.update({'TASK 이름': task.name, '프레임': info['frames'], '방식': mode,
                    '확인': ('사람 라벨 있으면 교체 (UP_REPLACE_HUMAN)' if human and UP_REPLACE_HUMAN else
                           '사람 라벨 있으면 보류' if human else '교체 가능 (uld·AA)')})
        UP_ITEMS.append((tid, r, info, mode))
    except Exception as e:
        row['확인'] = f'❌ TASK를 읽지 못함: {e}'
    _rows.append(row)
if _rows:
    display(pd.DataFrame(_rows).set_index('task_id'))
else:
    print('올릴 분석 결과가 없습니다 (5번 TRACK_LOCAL · 10번 AA_LOCAL · 27번 셀로 먼저 만들기)')
UP_RIDS = []
for tid, r, info, mode in UP_ITEMS:
    if not SEND:
        print(f"▶ TASK {tid}: 제출본 {r['fmt']} · {mode} — 미리 보기입니다 (SEND = True로 다시 실행하면 고정하고 요청)")
        continue
    sub = S.submit(tid, info, r['file'], r['fmt'], mode, server=CVAT_HOST, model=r.get('model', ''), settings=r.get('settings') or {},
                   count=int(r.get('count') or 0), note=f"{r['kind']} · 6번 셀")
    rid = S.request_upload(tid, sub, allow_replace=bool(UP_REPLACE_HUMAN))
    UP_RIDS.append(rid)
    print(f'✅ TASK {tid}: 제출본 {sub} → 요청 {rid} (실행기가 해시·TASK 프레임 수·라벨 정의를 다시 확인한 뒤 올림)')

print('-' * 70)
show_requests(SHOW_ALL)
if CANCEL_RID:
    _st = S.status(CANCEL_RID)
    print(f"취소 대상 {CANCEL_RID}: {_st['kind'] or '?'} · 상태 {STATUS_KO.get(_st['status'], _st['status'])}")
    if _st['status'] in ('done', 'failed', 'canceled', 'needs_check'):
        print('   이미 끝난 요청이라 취소할 것이 없습니다')
    elif _st['status'] == '없음':
        print('   이 요청 ID를 찾지 못했습니다')
    elif not SEND_CANCEL:
        print('   미리 보기입니다 — SEND_CANCEL = True로 다시 실행하면 취소 신호를 보냄')
    else:
        print('   ✅ 취소 신호', signal('cancel', rid=_st['rid']), '보냄')
