# 25. 업로드 기록 보기 — 누가·언제·어떤 모델·설정으로 무엇을 올렸고 기존 라벨이 어떻게 바뀌었나 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
UL_TASK   = ''          # TASK ID (하나 또는 '123, 456') · '' = 전체
UL_QUERY  = ''          # TASK 이름 검색 (모든 셀 같은 규칙) · '' = 전체
UL_SINCE  = ''          # 이 날짜 이후만, 예 '2026-10-30'
UL_METHOD = ''          # 'track' / 'shape' / '' = 둘 다
UL_DETAIL = None        # 상세 로그를 펼칠 log_id (아래 표의 log_id) 또는 -1 = 표의 마지막 건

import pandas as pd, json
from IPython.display import display
p = f'{BASE}/logs/uploads.csv'
_ul_rows = ctt.read_sharded(p) if hasattr(ctt, 'read_sharded') else []   # 옛 업로드 기록 (읽기만)
for _tid, _hs in __import__('h_agg').result_history(S.store).items():      # v4.33 실행기 결과 (심판 기록)
    for _h in _hs:
        _ul_rows.append({'log_id': f"v4.33:{_h.get('job', '')}", 'start': str(_h.get('time', ''))[:19].replace('T', ' '), 'sec': '',
                         'status': V433_STATUS(_h.get('status')),
                         'method': _h.get('kind', ''), 'mode': 'v4.33 실행기', 'task_id': str(_tid), 'task_name': _h.get('task_name', ''),
                         'task_name_after': '', 'operator': _h.get('by') or '', 'cvat_user': '', 'model': _h.get('model', ''),
                         'model_time': '', 'before_total': '', 'after_total': '', 'uploaded': '',
                         'detail_json': '', 'recovery': f"recovery/{_tid}/{_h.get('job', '')}/"})
if not _ul_rows:
    print('아직 기록이 없습니다 (옛 logs/uploads.csv · v4.33 실행기 결과 모두 없음)')
else:
    df = pd.DataFrame(_ul_rows, dtype=str).fillna('').sort_values('start', kind='stable')   # 옛 기록과 실행기 결과를 시각 순으로
    if UL_TASK:
        df = df[df['task_id'].isin([str(i) for i in ctt.as_task_ids(UL_TASK)])]
    if UL_QUERY:
        df = df[[bool(ctt.match_name(n or a, UL_QUERY)[0]) for n, a in zip(df['task_name'], df['task_name_after'])]]
    if UL_SINCE:
        df = df[df['start'] >= UL_SINCE]
    if UL_METHOD:
        df = df[df['method'] == UL_METHOD]
    print(f'업로드 기록 {len(df)}건 (전체 파일 {p})')
    cols = ['log_id', 'start', 'sec', 'status', 'method', 'mode', 'task_id', 'task_name', 'operator', 'cvat_user',
            'model', 'model_time', 'before_total', 'after_total', 'uploaded', 'recovery']
    pd.set_option('display.max_rows', 300); pd.set_option('display.max_colwidth', 60)
    display(df[[c for c in cols if c in df]])
    if UL_DETAIL is not None and len(df):
        r = df.iloc[-1] if UL_DETAIL == -1 else df[df['log_id'] == str(UL_DETAIL)].iloc[0]
        if str(r.get('log_id', '')).startswith('v4.33:'):
            print('=' * 70); print('v4.33 실행기 결과 — 복구 자료 폴더:', r['recovery'])
            try:
                print(json.dumps(S.store.read_json(r['recovery'] + 'result_plan.json'), ensure_ascii=False, indent=1))
            except Exception as e:
                print('  result_plan.json 없음:', e)
        else:
            lp = f"{BASE}/{r['detail_json'][:-5]}.log" if r.get('detail_json') else ''
            print('=' * 70)
            print(open(lp, encoding='utf-8').read() if lp and os.path.exists(lp) else f'상세 로그 파일 없음: {lp}')
