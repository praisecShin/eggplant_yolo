# 21. TASK별 개체 수 통계 — fruit·bud가 TASK마다 몇 개인지 (CVAT 지금 라벨, 읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
LOGIN      = None     # None = 지금 접속 중인 계정 · 또는 0번 셀 CVAT_PROFILES의 이름 (예: 'B')
CNT_QUERY  = ''       # TASK 이름 검색. '' = 전체. 예: '261019', 'G6 vf_r2df_ok', 'tag=AA*'
# 검색어 규칙(모든 셀 같음): 공백=그리고 · |=또는 · ,=묶음 또는 · 앞에 -=빼기 · 칸=값(gh date row plant state tag) · 칸=a..b 범위 · * 와일드카드 · 검토=검토 완료(0번 셀 REVIEWED_RULE, -검토=미검토)
CNT_IDS    = []       # 또는 TASK ID 직접, 예: [2700651, 2704421] (넣으면 CNT_QUERY 무시)
CNT_LIMIT  = 500      # 최근 TASK 몇 개까지 볼지
CNT_SAVE   = True     # True = 내 분석 폴더 reports/task_counts_<시각>.csv로 저장
CNT_PRINT  = True     # True = 인쇄용 HTML(A4 가로)도 만들어 내려받기 → 브라우저에서 열고 Ctrl+P (PDF 저장도 가능)

import pandas as pd
from IPython.display import display
use_cvat(LOGIN)
if CNT_IDS:
    targets = [{'task_id': t, 'name': ''} for t in ctt.as_task_ids(CNT_IDS)]
else:
    targets = ctt.select_tasks(ctt.list_tasks(CLIENT, limit=CNT_LIMIT), CNT_QUERY, label='집계 대상')
print(f"대상 TASK {len(targets)}개" + (f" (검색어 '{CNT_QUERY}')" if CNT_QUERY and not CNT_IDS else ''))
if not targets:
    raise SystemExit(f"검색어 '{CNT_QUERY}'에 맞는 TASK가 없습니다 → 4번 셀 TASK_QUERY로 먼저 확인 "
                     "(예: 'vf*' = 상태가 vf로 시작, 'vf_r2df_ok', '261019 G6')")
LABELS = ['healthy_fruit', 'disease_fruit', 'healthy_bud', 'disease_bud']
rows = []
for i, t in enumerate(targets, 1):
    try:
        task = CLIENT.tasks.retrieve(t['task_id'])
        per, kind = ctt.count_objects(task)
        f = ctt.parse_task_name(task.name) or {}
        r = {'task_id': task.id, 'TASK 이름': task.name, '온실': f.get('gh', ''), '촬영일': f.get('date', ''),
             '라인': f.get('row', ''), '그루': f.get('plant', ''), '상태': f.get('state', ''), '표시': f.get('tag', ''),
             '라벨 종류': kind, '프레임': task.size}
        # 개체 수: track이면 track 수, 프레임별 박스만 있으면 '한 프레임 최대 박스 수'(하한)
        for lab in sorted(set(LABELS) | set(per)):
            x = per.get(lab, {'track': 0, 'box': 0, 'max_frame': 0, 'occluded_track': 0})
            r[lab] = x['track'] + (x['max_frame'] if x['track'] == 0 else 0)
            r[f'{lab} 박스'] = x['box']
        r['fruit 합계'] = sum(r.get(l, 0) for l in r if l.endswith('_fruit'))
        r['bud 합계'] = sum(r.get(l, 0) for l in r if l.endswith('_bud'))
        r['비고'] = '프레임별 박스 → 한 프레임 최대 수(하한)' if kind == '박스' else ('track + 프레임별 박스 섞임' if kind == '혼합' else '')
        rows.append(r)
    except Exception as e:
        rows.append({'task_id': t['task_id'], 'TASK 이름': t.get('name', ''), '비고': f'❌ {ctt.api_error(e)}'})
    if i % 20 == 0:
        print(f'  {i}/{len(targets)} …')
df = pd.DataFrame(rows)
for c_ in ['비고', '온실', '촬영일'] + LABELS + ['fruit 합계', 'bud 합계']:      # 모두 실패해도 표가 깨지지 않게
    if c_ not in df.columns:
        df[c_] = 0 if c_ in LABELS or c_.endswith('합계') else ''
num = [c for c in df.columns if c == '프레임' or c.endswith(('_fruit', '_bud', '박스', '합계'))]
df[num] = df[num].fillna(0).astype(int)
df = df.fillna('')
main = ['task_id', 'TASK 이름', '온실', '촬영일', '라인', '그루', '상태', '표시', '라벨 종류', '프레임',
        'healthy_fruit', 'disease_fruit', 'fruit 합계', 'healthy_bud', 'disease_bud', 'bud 합계', '비고']
pd.set_option('display.max_rows', 500)
display(df[[c for c in main if c in df.columns]])
ok = df[~df['비고'].astype(str).str.startswith('❌')]
print(f"\n합계 (TASK {len(ok)}개): fruit {int(ok['fruit 합계'].sum())} (healthy {int(ok['healthy_fruit'].sum())} · disease {int(ok['disease_fruit'].sum())}) · "
      f"bud {int(ok['bud 합계'].sum())} (healthy {int(ok['healthy_bud'].sum())} · disease {int(ok['disease_bud'].sum())})")
named = ok[ok['온실'].astype(str) != '']
if len(named):
    print('\n온실·촬영일별 합계:')
    display(named.groupby(['온실', '촬영일'])[['healthy_fruit', 'disease_fruit', 'fruit 합계', 'healthy_bud', 'disease_bud', 'bud 합계']].sum().astype(int))
print('개체 수 = track 수 (track 하나 = 열매/봉오리 하나). 같은 개체가 track 2개로 끊겨 있으면 2로 셈 → CVAT에서 Merge 후 다시 실행')
if CNT_PRINT:
    import html as _h, datetime
    from zoneinfo import ZoneInfo
    cols = [c for c in main if c in df.columns]
    def _tbl(d, index=False):
        return d.to_html(index=index, border=0, classes='t', na_rep='', justify='center')
    grp = (named.groupby(['온실', '촬영일'])[['healthy_fruit', 'disease_fruit', 'fruit 합계', 'healthy_bud', 'disease_bud', 'bud 합계']]
           .sum().astype(int)) if len(named) else None
    cond = f"검색어 '{CNT_QUERY}'" if CNT_QUERY and not CNT_IDS else (f'TASK ID {CNT_IDS}' if CNT_IDS else '전체')
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>TASK별 개체 수</title>
<style>
@page {{ size: A4 landscape; margin: 10mm; }}
body {{ font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; font-size: 10px; color: #000; }}
h1 {{ font-size: 16px; margin: 0 0 4px; }} h2 {{ font-size: 13px; margin: 14px 0 4px; }}
.meta {{ color: #444; margin-bottom: 8px; }}
table.t {{ border-collapse: collapse; width: 100%; }}
table.t th, table.t td {{ border: 1px solid #888; padding: 2px 4px; text-align: center; white-space: nowrap; }}
table.t th {{ background: #e8e8e8; }}
table.t tr {{ page-break-inside: avoid; }} thead {{ display: table-header-group; }}
.sum {{ font-weight: bold; margin: 6px 0; }}
.note {{ color: #444; margin-top: 8px; }}
</style></head><body>
<h1>TASK별 fruit · bud 개체 수</h1>
<div class="meta">CVAT {_h.escape(str(CVAT_SERVER))} · 대상 {_h.escape(cond)} · TASK {len(ok)}개 ·
출력 {datetime.datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M')}</div>
<div class="sum">합계: fruit {int(ok['fruit 합계'].sum())} (healthy {int(ok['healthy_fruit'].sum())} · disease {int(ok['disease_fruit'].sum())}) ·
bud {int(ok['bud 합계'].sum())} (healthy {int(ok['healthy_bud'].sum())} · disease {int(ok['disease_bud'].sum())})</div>
{_tbl(df[cols])}
{('<h2>온실·촬영일별 합계</h2>' + _tbl(grp.reset_index())) if grp is not None else ''}
<div class="note">개체 수 = track 수 (track 하나 = 열매/봉오리 하나). 라벨 종류가 '박스'인 TASK는 한 프레임 최대 박스 수(하한).</div>
</body></html>'''
    hp = f'{REPORTS}/task_counts_{ctt.stamp()}.html'
    open(hp, 'w', encoding='utf-8').write(page)
    print('인쇄용:', os.path.relpath(hp, BASE), '→ 내려받은 파일을 브라우저에서 열고 Ctrl+P (A4 가로, PDF로 저장도 가능)')
    try:
        from google.colab import files
        files.download(hp)
    except Exception:
        print('  (Colab 밖이면 위 경로에서 직접 내려받기)')
if CNT_SAVE:
    out = f'{REPORTS}/task_counts_{ctt.stamp()}.csv'
    df.to_csv(out, index=False, encoding='utf-8-sig')
    print('저장:', os.path.relpath(out, BASE), '(Google 스프레드시트로 열림)')
