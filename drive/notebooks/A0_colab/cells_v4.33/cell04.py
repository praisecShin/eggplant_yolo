# 4. CVAT 접속 · TASK 목록 · TASK 이름 검색 확인 — PAT 서버 또는 공동 아이디 서버
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'

LOGIN = None        # None = 지금 접속 중인 서버(처음이면 0번 셀 CVAT_AUTH) · 또는 0번 셀 CVAT_PROFILES의 이름 ('token', 'password', 'B' …)
TASK_QUERY = ''     # TASK 이름 검색어 확인 (비우면 전체). 예: '261019 vf_r2', 'G6 uld -tag=AA*', 'G2 plant=6..10 uld', '*AA_r1*'
# 검색어 규칙(모든 셀 같음): 공백=그리고 · |=또는 · ,=묶음 또는 · 앞에 -=빼기 · 칸=값(gh date row plant state tag) · 칸=a..b 범위 · * 와일드카드 · 검토=검토 완료(0번 셀 REVIEWED_RULE, -검토=미검토)
TASK_STATS = True   # 검색 결과에 프레임 수·클래스별 박스 수 통계 (검색어가 있을 때, uld로 끝나는 TASK는 세지 않음)
STATS_CVAT = 20     # 통계가 없거나 export 뒤에 바뀐 TASK를 CVAT에서 셀 수 (0 = 28번 셀이 세어 둔 것만)
STATS_BY   = 'gh date'   # 합계를 묶을 칸: 'gh' · 'gh date' · 'date' · 'row' · 'plant' · 'state' … ('' = 전체 합계만)
STATS_SAVE = False  # True = 표를 내 분석 폴더 reports/task_stats_<시각>.csv로 저장

assert ctt, 'scripts/cvat_task_tools.py가 없습니다 (Drive scripts/에 올린 뒤 0번 셀 다시)'
import pandas as pd
from IPython.display import display
use_cvat(LOGIN)                              # 이후 셀은 LOGIN=None이면 이 서버를 그대로 씀
tasks = ctt.list_tasks(CLIENT, limit=5000)
if not tasks:
    print('태스크가 없습니다 → 0번 셀 CVAT_ORG·CVAT_PROJECT(기본 조직·프로젝트)를 확인하세요')
elif TASK_QUERY:
    pd.set_option('display.max_rows', 300)
    _hits = ctt.select_tasks(tasks, TASK_QUERY, display=None if TASK_STATS else display, show_all=not TASK_STATS,
                             label='검색어 확인')   # 통계를 볼 때는 맞는 TASK만 (아래 표)
    if TASK_STATS and _hits:
        assert wb is not None, 'scripts/web_bridge.py가 없습니다 (v4.16 이상 scripts)'
        _st = wb.compute_stats(BASE, _hits, client=CLIENT if STATS_CVAT else None, cvat_max=STATS_CVAT)
        try:                                          # 28번 셀이 만든 '같은 온실·촬영일과 비교' 결과가 있으면 함께
            _peer = {str(t['id']): t.get('peer') or {} for t in json.load(open(f'{BASE}/web/state.json', encoding='utf-8'))['tasks']}
        except Exception:
            _peer = {}
        _labels = sorted({k for s in _st.values() for k in (s.get('by_label') or {})})
        _rows = []
        for t in _hits:
            s, f = _st.get(str(t['task_id'])) or {}, ctt.parse_task_name(t['name']) or {}
            r = {'task_id': t['task_id'], 'TASK': t['name'], **{k: f.get(k, '') for k in ('gh', 'date', 'row', 'plant', 'state')},
                 '프레임': s.get('frames', t.get('frames', '')), '박스 있는 프레임': s.get('labeled', ''), '빈 프레임': s.get('zero', '')}
            for lab in _labels:
                r[lab] = (s.get('by_label') or {}).get(lab, 0) if s.get('frames') else ''
            r.update({'박스 합': s.get('total', ''), '프레임당': s.get('total_mean', ''), '프레임당 최대': s.get('total_max', ''),
                      '최대 프레임': (f"{s['max_idx']} (원본 {s['max_frame']})" if s.get('max_idx') is not None else ''),
                      '변동': s.get('cv', ''), '가림': s.get('occluded', ''),
                      '출처': ('uld (세지 않음)' if t['name'].lower().endswith('uld') else
                              s.get('error') or ('CVAT' if s.get('src') == 'cvat' else 'export' + (' (오래됨)' if s.get('stale') else '')) if s else '아직 못 셈'),
                      '같은 온실·촬영일과': ' · '.join((_peer.get(str(t['task_id'])) or {}).get('flags') or [])})
            _rows.append(r)
        TASK_STATS_DF = pd.DataFrame(_rows)
        print(f"\n■ TASK별 통계 ({len(_rows)}개) — 클래스 열 = 박스 수 (track은 프레임마다 보이는 박스로 셈)")
        display(TASK_STATS_DF)
        _ok = TASK_STATS_DF[pd.to_numeric(TASK_STATS_DF['프레임'], errors='coerce').notna() & (TASK_STATS_DF['박스 합'] != '')]
        if len(_ok):
            _num = ['프레임', '박스 있는 프레임', '빈 프레임', *_labels, '박스 합']
            _ok = _ok.assign(**{c: pd.to_numeric(_ok[c], errors='coerce').fillna(0).astype(int) for c in _num})
            _by = [c for c in STATS_BY.split() if c in _ok.columns]
            _g = (_ok.groupby(_by)[_num].sum() if _by else _ok[_num].sum().to_frame('합계').T)
            _g.insert(0, 'TASK', _ok.groupby(_by).size() if _by else len(_ok))
            for lab in _labels:
                _g[f'{lab}/프레임'] = (_g[lab] / _g['프레임'].where(_g['프레임'] > 0)).round(2)
            _g['박스/프레임'] = (_g['박스 합'] / _g['프레임'].where(_g['프레임'] > 0)).round(2)
            print(f"■ 합계{' — ' + ' × '.join(_by) + '별' if _by else ''} (통계가 있는 TASK {len(_ok)}개)")
            display(_g)
        _miss = [r['task_id'] for r in _rows if r['출처'] == '아직 못 셈']
        if _miss:
            print(f"아직 못 센 TASK {len(_miss)}개 — export가 없고 CVAT로 셀 수({STATS_CVAT})를 넘음 → 셀을 다시 실행하거나 STATS_CVAT를 늘리세요")
        if STATS_SAVE:
            _p = f'{REPORTS}/task_stats_{ctt.stamp()}.csv'
            TASK_STATS_DF.to_csv(_p, index=False, encoding='utf-8-sig')
            print('저장:', os.path.relpath(_p, BASE))
else:
    display(pd.DataFrame(tasks))
