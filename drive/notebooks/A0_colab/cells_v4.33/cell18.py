# 18. 라벨 확인 — CVAT TASK의 현재 라벨 요약 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
LOGIN       = None      # None = 지금 접속 중인 계정 · 또는 0번 셀 CVAT_PROFILES의 이름
CHECK_IDS   = []        # 확인할 TASK ID, 예: [2704421]
SHOW_IMAGES = 6         # 그림 수 (0 = 그림 없이 표만)

import pandas as pd
from IPython.display import display
use_cvat(LOGIN)
for tid in ctt.as_task_ids(CHECK_IDS):
    print('=' * 70)
    try:
        task = CLIENT.tasks.retrieve(tid)
        info = ctt.task_basic(task)
        print(f"TASK {tid} '{task.name}' · {info['media']} · 프레임 {info['frames']} · 상태 {getattr(task, 'status', '')}")
        tmp = f'{task_dir(tid)}/check_{ctt.stamp()}.zip'
        ctt.export_annotations(task, tmp)                    # 현재 라벨 (이 파일이 그 시점 기록으로 남음)
        ann = ctt.load_annotations(tmp)
        label_rows, fsum, counts = ctt.annotation_tables(ann)
        print('  ' + ' · '.join(f'{k} {v}' for k, v in fsum.items()))
        display(pd.DataFrame(label_rows) if label_rows else '라벨 없음')
        if counts and any(counts):
            print('  프레임별 박스 수:', ' '.join(str(c) for c in counts[:60]) + (' …' if len(counts) > 60 else ''))
        if SHOW_IMAGES and label_rows:
            ctt.draw_annotations(ann, ctt.cvat_frame_getter(task, ann['meta']), n=SHOW_IMAGES,
                                 title=f"TASK {tid} current labels (yellow=healthy_fruit, red=disease_fruit, cyan=healthy_bud, magenta=disease_bud, white inner line=occluded, *=keyframe/direct)")
        print(f'  기록: {os.path.relpath(tmp, BASE)}')
    except Exception as e:
        print(f'❌ TASK {tid}: {ctt.api_error(e)}')
if not CHECK_IDS:
    print('CHECK_IDS에 TASK ID를 넣으세요.')
