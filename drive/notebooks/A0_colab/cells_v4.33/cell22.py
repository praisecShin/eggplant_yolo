# 22. export 현황 — 검색어로 고른 TASK가 몇 개인지, 이미 받은 export가 지금 CVAT 라벨과 같은지 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
LOGIN      = None      # TASK가 있는 계정 · 0번 셀 CVAT_PROFILES의 이름
XS_QUERY   = 'G1|G3 date=261019.. vf*, G5|G6 date=261019.. vf*'   # 볼 TASK (모든 셀 같은 규칙). 쉼표로 여러 그룹
XS_GROUPS  = {'G1·G3': 'G1|G3', 'G5·G6': 'G5|G6'}                   # 요약표의 그룹 (이름: 검색어). {} = 온실별
XS_FORMAT  = 'CVAT for video 1.1'   # 쓸 export 형식 (14번 EX_FORMAT과 같게)
XS_IMAGES  = True                   # True = 이미지가 들어 있는 export만 '있음'으로 셈 (이미지 없는 export는 영상에서 뽑을 수 있으면 False)
XS_TRAIN   = 'all'                  # v4.13 학습 상태로 거르기: 'all' · 'new' = 검토 완료인데 학습에 안 씀 · 'changed' = 학습 뒤 라벨 바뀜 · 'todo' = new + changed
# 검색어 규칙(모든 셀 같음): 공백=그리고 · |=또는 · ,=묶음 또는 · 앞에 -=빼기 · 칸=값(gh date row plant state tag) · 칸=a..b 범위 · * 와일드카드 · 검토=검토 완료(0번 셀 REVIEWED_RULE, -검토=미검토)

import pandas as pd
from IPython.display import display
use_cvat(LOGIN)
pd.set_option('display.max_rows', 500)
hits = ctt.select_tasks(ctt.list_tasks(CLIENT, limit=5000), XS_QUERY, label='대상 TASK')
print('exports/ 폴더 읽는 중 …')
SCAN = ctt.scan_exports(f'{BASE}/exports', names=[t['name'] for t in hits])   # 대상 TASK 이름의 zip만, 한 번 읽은 것은 기억
kind = 'video' if 'video' in XS_FORMAT.lower() else 'images'
rows = []
LAST_TRAIN = ctt.last_trained(BASE)              # TASK → 가장 최근에 들어간 학습 (logs/train_tasks.csv)
for t in hits:
    ex, st = ctt.best_export(SCAN, t['task_id'], t.get('updated_utc'), kind=kind, need_images=XS_IMAGES)
    f = ctt.parse_task_name(t['name']) or {}
    grp = next((g for g, q in XS_GROUPS.items() if ctt.match_name(t['name'], q)[0]), '') if XS_GROUPS else f.get('gh', '')
    rows.append({'그룹': grp, 'task_id': t['task_id'], 'TASK 이름': t['name'], 'CVAT 수정(UTC)': t.get('updated', ''),
                 '상태': {'최신': '✅ 받은 것 그대로 사용', '수정됨': '🔄 다시 받기 (CVAT에서 바뀜)', '없음': '⬇️ 새로 받기'}[st],
                 'export 폴더': ex['folder'] if ex else '', 'export 기준(UTC)': (str(ex['updated'])[:16] or '파일 시각') if ex else '',
                 '이미지': ('있음' if ex['images'] else '없음') if ex else '',
                 '검토': '✅' if task_reviewed(t['name']) else '⏳', '역할': task_role(t['name']) or '무작위',
                 '마지막 학습': (f"{LAST_TRAIN[str(t['task_id'])]['model']} ({LAST_TRAIN[str(t['task_id'])]['role']})"
                                 + ('' if os.path.exists(f"{BASE}/runs/{LAST_TRAIN[str(t['task_id'])]['model']}/TRAINING_DONE") else ' · 학습 전')
                                 if str(t['task_id']) in LAST_TRAIN else ''),
                 '학습 뒤': (ctt.train_change(t.get('updated_utc'), LAST_TRAIN.get(str(t['task_id'])))
                             if task_reviewed(t['name']) else '')})
XS = pd.DataFrame(rows)
if len(XS) and XS_TRAIN != 'all':
    _want = {'new': ['🆕 학습 안 함'], 'changed': ['🔁 라벨 바뀜'], 'todo': ['🆕 학습 안 함', '🔁 라벨 바뀜']}[XS_TRAIN]
    print(f"XS_TRAIN = '{XS_TRAIN}' → {int(XS['학습 뒤'].isin(_want).sum())}/{len(XS)}개")
    XS = XS[XS['학습 뒤'].isin(_want)]
if len(XS):
    print('■ 학습 데이터 상태 (검토 완료 TASK) — 그룹 × 역할')
    _rv = XS[XS['검토'] == '✅']
    if len(_rv):
        display(_rv.pivot_table(index='그룹', columns='역할', values='task_id', aggfunc='count', fill_value=0, margins=True, margins_name='합계'))
        display(_rv.pivot_table(index='역할', columns='학습 뒤', values='task_id', aggfunc='count', fill_value=0))
    print(f"미검토 TASK {int((XS['검토'] != '✅').sum())}개 (학습에 안 씀)")
    print('\n■ 그룹별 요약')
    smry = XS.groupby('그룹')['상태'].value_counts().unstack(fill_value=0)
    smry['TASK 합계'] = smry.sum(axis=1)
    display(smry)
    print('■ TASK별')
    display(XS.sort_values(['그룹', '상태', 'TASK 이름']))
    EXPORT_TODO_IDS = [int(r['task_id']) for _, r in XS.iterrows() if not r['상태'].startswith('✅')]
    TRAIN_TODO_IDS = [int(r['task_id']) for _, r in XS.iterrows() if r['검토'] == '✅' and r['학습 뒤'] in ('🆕 학습 안 함', '🔁 라벨 바뀜')]
    print(f"학습에 새로 넣거나 다시 넣을 TASK {len(TRAIN_TODO_IDS)}개 (🆕·🔁) → TRAIN_TODO_IDS. 다시 받아야 하면 14번 EX_IDS = TRAIN_TODO_IDS")
    REUSE_FOLDERS = sorted({r['export 폴더'] for _, r in XS.iterrows() if r['상태'].startswith('✅')})
    print(f"\n다시 받거나 새로 받을 TASK {len(EXPORT_TODO_IDS)}개 → 14번 셀: EX_IDS = EXPORT_TODO_IDS (이 세션에 저장됨)")
    print(f"그대로 쓸 수 있는 export가 있는 폴더 {len(REUSE_FOLDERS)}개: {REUSE_FOLDERS}")
    print("14번 셀을 EX_REUSE = True로 실행하면, 대상 전체를 새 폴더 하나에 모으면서 '받은 것 그대로'인 TASK는 서버에 요청하지 않고 복사합니다.")
else:
    print('대상 TASK가 없습니다.')
