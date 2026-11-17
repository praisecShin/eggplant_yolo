# 19. 자동 라벨링 현황 · 자동 track ↔ CVAT 반영 결과 비교 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
LOGIN    = None     # None = 지금 접속 중인 계정 · 또는 0번 셀 CVAT_PROFILES의 이름 (예: 'B')
CMP_IDS  = []       # 비교할 TASK ID (비우면 현황표만), 예: [2704421]
SAME_IOU = 0.95     # 이만큼 겹치면 '같음', 0.5~0.95는 '수정'(위치·크기 고침)
SHOW_FRAMES = 20    # 차이가 있는 프레임을 몇 줄까지 보여 줄지

import pandas as pd
from IPython.display import display
use_cvat(LOGIN)

# (1) 이 계정(서버)의 자동 라벨링 현황 — 작업 대장 기준
rows = [r for r in ctt.read_registry(REGISTRY) if ctt.same_server(r, CVAT_SERVER)]   # 옛 작업 대장 (v4.33 실행기 결과는 25번 셀)
by = {}
for r in rows:
    d = by.setdefault(r['task_id'], {'task_id': r['task_id'], 'task_name': '', 'track 생성': 0, '마지막 track': '',
                                     'track 수': '', '정밀도': '', '업로드': '', '업로드 시각': '', '검수 수집': ''})
    d['task_name'] = r.get('task_name') or d['task_name']
    if r['action'] == 'track 생성' and r['status'].startswith('완료'):
        d['track 생성'] += 1
        d.update({'마지막 track': r['run_time'], 'track 수': r.get('tracks', ''), '정밀도': r.get('precision', '')})
    elif r['action'] == '업로드':
        d.update({'업로드': r['status'], '업로드 시각': r['run_time'] if r['status'] == '업로드 완료' else d['업로드 시각']})
    elif r['action'] == '검수 수집':
        d['검수 수집'] = r['status']
st = pd.DataFrame(by.values())
print(f'▶ 자동 라벨링 현황 · {CVAT_SERVER} · TASK {len(st)}개')
if len(st):
    print(f"  track 생성 {int((st['track 생성'] > 0).sum())}개 · 업로드 완료 {int((st['업로드 시각'] != '').sum())}개 · "
          f"검수 수집 {int((st['검수 수집'] != '').sum())}개")
    display(st)
else:
    print('  이 계정으로 기록된 작업이 없습니다 (5번 셀 track 생성부터).')

# (2) TASK별 비교 — 올린 track XML(로컬) vs 지금 CVAT에 있는 라벨
for tid in ctt.as_task_ids(CMP_IDS):
    print('=' * 70)
    try:
        src = last_upload(tid, include_track=True)       # v4.33 실행기 결과 + 옛 작업 대장
        up = src if src and src.get('status') == '업로드 완료' else None
        if not src or not src.get('result_file'):
            print(f'TASK {tid}: track 기록 없음 → 5번 셀 먼저'); continue
        task = CLIENT.tasks.retrieve(tid)
        snap = f'{task_dir(tid)}/compare_{ctt.stamp()}.zip'
        ctt.export_annotations(task, snap)                       # 지금 CVAT 라벨 (기록으로 남음)
        local, cvat = ctt.load_annotations(f"{BASE}/{src['result_file']}"), ctt.load_annotations(snap)
        rows_l, total, frows = ctt.compare_annotations(local, cvat, same_iou=SAME_IOU)
        print(f"TASK {tid} '{task.name}' · CVAT 마지막 수정 {str(task.updated_date)[:19]} UTC")
        print(f"  로컬: {src['result_file']} ({'업로드한 파일 ' + up['run_time'] if up else '아직 업로드 안 함'})")
        print('  ' + ' · '.join(f'{k} {v}' for k, v in total.items()))
        display(pd.DataFrame(rows_l))
        if frows:
            print(f'  차이가 있는 프레임 {len(frows)}개 (앞 {SHOW_FRAMES}개):')
            display(pd.DataFrame(frows[:SHOW_FRAMES]).fillna(0).astype(int))
        if not up:
            v = '→ 아직 올리지 않았으므로 CVAT 라벨과 다른 것이 정상 (6번 셀로 업로드)'
        elif total['로컬 박스'] and total['같음'] == total['로컬 박스'] == total['CVAT 박스']:
            v = '→ 올린 그대로 CVAT에 있음 (검수로 바뀐 것 없음)'
        elif total['CVAT 박스'] == 0:
            v = '→ CVAT에 라벨이 없음: 업로드 후 지워졌거나 다른 TASK에 올림 — 6번 셀 기록·TASK ID 확인'
        else:
            v = '→ 업로드 후 CVAT에서 바뀜 (검수 수정이면 정상 — 7번 셀로 수집해 검증 3단계)'
        print('  ' + v)
        print(f'  기록: {os.path.relpath(snap, BASE)}')
    except Exception as e:
        print(f'❌ TASK {tid}: {ctt.api_error(e)}')
