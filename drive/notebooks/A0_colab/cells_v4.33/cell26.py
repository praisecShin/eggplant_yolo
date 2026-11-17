# 26. 작업 기록 보기 — 언제·누가·무슨 작업을 했고 TASK별로 라벨이 어떻게 바뀌었나 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
AC_VIEW   = 'jobs'      # 'jobs' = 작업(셀 실행) 목록 · 'tasks' = TASK별 줄 · 'history' = TASK 하나의 변화 이력 · 'daily' = 날짜별 건수
AC_TASK   = ''          # TASK ID (하나 또는 '123, 456') · 'history'는 이것 또는 AC_QUERY 필요
AC_QUERY  = ''          # TASK 이름 검색 (모든 셀 같은 규칙)
AC_SINCE  = ''          # 이 날짜·시각 이후, 예 '2026-10-28' 또는 '2026-10-30 09:00'
AC_UNTIL  = ''          # 이 날짜·시각 이전 (그날 포함하려면 '2026-10-30 23:59')
AC_ACTION = ''          # 작업 종류 일부: '백업' 'export' 'track' '업로드' '자동 라벨' '학습' '검수' … · '' = 전부
AC_WHO    = ''          # 작업자(OPERATOR) 일부 · '' = 전부
AC_JOB    = ''          # 작업 하나(job_id)의 TASK 줄만 보기 ('jobs' 표의 job_id)
# (v4.32의 AC_IMPORT_OLD는 공유 logs/에 쓰므로 v4.33 분석 셀에서는 없앰 — 옛 기록은 읽기만)
AC_SAVE   = True        # 보이는 표를 내 분석 폴더 reports/activity_<보기>_<시각>.csv로 저장

import pandas as pd, json as _json
from IPython.display import display
p = f'{BASE}/logs/activity.csv'
_ac_rows = ctt.read_sharded(p) if hasattr(ctt, 'read_sharded') else []   # 옛 작업 기록 (읽기만) + 이 세션 분석 기록
for _tid, _hs in __import__('h_agg').result_history(S.store).items():      # v4.33 실행기 결과 → TASK 줄 (작업 = 실행기 job)
    for _h in _hs:
        _ac_rows.append({'time': str(_h.get('time', ''))[:19].replace('T', ' '), 'row': 'TASK', 'job_id': f"v4.33:{_h.get('job', '')}",
                         'cell': '실행기', 'action': _h.get('kind', ''), 'status': V433_STATUS(_h.get('status')), 'task_id': str(_tid),
                         'task_name': _h.get('task_name', ''), 'who': _h.get('by') or '', 'server': '', 'model': _h.get('model', ''),
                         'summary': f"요청 {_h.get('request', '')}" + (f" · {_h.get('mode')}" if _h.get('mode') else ''), 'source': 'v4.33 실행기',
                         'file': f"recovery/{_tid}/{_h.get('job', '')}/"})
assert _ac_rows, '아직 작업 기록이 없습니다'
A = pd.DataFrame(_ac_rows, dtype=str).fillna('')
for _c in ctt.ACTIVITY_COLUMNS + ['source']:                 # 실행기 결과에는 없는 칸(박스 수 등)도 빈 값으로 (b29 W3)
    if _c not in A:
        A[_c] = ''
A = A.sort_values('time', kind='stable')
if AC_SINCE: A = A[A['time'] >= AC_SINCE]
if AC_UNTIL: A = A[A['time'] <= AC_UNTIL]
if AC_WHO:   A = A[A['who'].str.contains(AC_WHO, regex=False)]
if AC_ACTION: A = A[A['action'].str.contains(AC_ACTION, regex=False)]
pd.set_option('display.max_rows', 500); pd.set_option('display.max_colwidth', 70)
T = A[A['row'] == 'TASK']
if AC_TASK:
    T = T[T['task_id'].isin([str(i) for i in ctt.as_task_ids(AC_TASK)])]
if AC_QUERY:
    T = T[[bool(n) and bool(ctt.match_name(n, AC_QUERY)[0]) for n in T['task_name']]]
if AC_JOB:
    T = T[T['job_id'] == AC_JOB]

def _labels(s):
    try:
        d = _json.loads(s) if s.startswith('{') else None
    except Exception:
        d = None
    return ', '.join(f'{k} {v}' for k, v in d.items()) if isinstance(d, dict) else s

if AC_VIEW == 'jobs':
    J = A[A['row'].isin(['작업 시작', '작업 끝'])]
    g = []
    for jid, d in J.groupby('job_id', sort=False):
        s_ = d[d['row'] == '작업 시작']; e_ = d[d['row'] == '작업 끝']
        s0 = s_.iloc[0] if len(s_) else d.iloc[0]
        g.append({'job_id': jid, '시작': s0['time'], '끝': e_.iloc[-1]['time'] if len(e_) else '',
                  '셀': s0['cell'], '작업': s0['action'], '작업자': s0['who'], 'CVAT 계정': s0['server'],
                  '상태': e_.iloc[-1]['status'] if len(e_) else '끝 기록 없음 (중단 또는 실행 중)',
                  '초': e_.iloc[-1]['sec'] if len(e_) else '', 'TASK 줄': int((A['job_id'] == jid).sum() - len(d)),
                  'TASK': (lambda t: ', '.join(f"{a} {b}" for a, b in t[:3]) + (f' 외 {len(t) - 3}개' if len(t) > 3 else ''))(
                      list(A[(A['job_id'] == jid) & (A['row'] == 'TASK')][['task_id', 'task_name']].drop_duplicates().itertuples(index=False, name=None))),
                  '요약': e_.iloc[-1]['summary'] if len(e_) else s0['summary'], '모델': s0['model']})
    V = pd.DataFrame(g)
    old = A[(A['row'] == 'TASK') & (A['job_id'] == '')]
    print("TASK 줄을 자세히 보려면 AC_VIEW = 'tasks', AC_JOB = '<job_id>'")
    print(f'작업 {len(V)}개' + (f' · 작업 없이 기록된 TASK 줄(예전 기록 등) {len(old)}개 → AC_VIEW = "tasks"' if len(old) else ''))
elif AC_VIEW == 'tasks':
    V = T[['time', 'action', 'status', 'task_id', 'task_name', 'who', 'boxes_before', 'boxes', 'by_label', 'frames',
           'task_updated', 'file', 'summary', 'job_id', 'source']].copy()
    V['by_label'] = V['by_label'].map(_labels)
    print(f'TASK 줄 {len(V)}개')
elif AC_VIEW == 'history':
    assert AC_TASK or AC_QUERY, "'history'는 AC_TASK 또는 AC_QUERY로 TASK를 고르세요"
    rows = []
    for tid, d in T.groupby('task_id', sort=False):
        prev = None
        for _, r in d.iterrows():
            nb_ = r['boxes']
            change = ''
            if r['boxes_before'] != '' and nb_ != '':
                change = f"{r['boxes_before']}→{nb_}"
            elif nb_ != '' and prev is not None:
                change = f"{prev}→{nb_}" if prev != nb_ else '같음'
            if nb_ != '':
                prev = nb_
            rows.append({'TASK': tid, '시각': r['time'], '작업': r['action'], '상태': r['status'], '이름': r['task_name'],
                         '박스(라벨 수)': nb_, '변화': change, '라벨별': _labels(r['by_label']),
                         'CVAT 수정 시각': r['task_updated'], '작업자': r['who'], '파일': r['file'], '메모': r['summary'][:80]})
    V = pd.DataFrame(rows)
    print(f'TASK {T["task_id"].nunique()}개의 이력 {len(V)}줄 (시간순) — 박스 = 그 시점의 라벨 박스 수 (백업은 track 키프레임만)')
elif AC_VIEW == 'daily':
    T2 = T.assign(날짜=T['time'].str[:10])
    V = T2.pivot_table(index='날짜', columns='action', values='task_id', aggfunc='count', fill_value=0)
    V['합계'] = V.sum(axis=1)
    print('날짜별 TASK 줄 수 (작업 종류별)')
else:
    raise SystemExit("AC_VIEW는 'jobs' / 'tasks' / 'history' / 'daily'")
display(V)
if AC_SAVE and len(V):
    out = f'{REPORTS}/activity_{AC_VIEW}_{ctt.stamp()}.csv'
    V.to_csv(out, encoding='utf-8-sig', index=AC_VIEW == 'daily')
    print('저장:', os.path.relpath(out, BASE))
