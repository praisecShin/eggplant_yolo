# 20. 단계별 원인 찾기 — 손으로 라벨한 TASK 하나로 ①프레임 맞춤 ②모델 ③영상 프레임 ④track XML 점검 (읽기만 함)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
LOGIN      = None    # 그 TASK가 있는 계정 · 0번 셀 CVAT_PROFILES의 이름
DG_TASK_ID = 0       # ← 사람이 라벨을 끝낸 영상 TASK (예: vf_r2df_ok). 학습에 쓴 TASK도 됨
DG_CONF    = 0.25    # 모델 신뢰도 하한 (track 생성과 같게)
DG_SAMPLES = 6       # 시험할 프레임 수 (라벨이 있는 프레임에서 고르게)
DG_TRACK   = True    # True: 이 TASK에 5번 셀 track 결과가 있으면 ④도 점검

use_cvat(LOGIN)
DG_TASK_ID = ctt.as_task_id(DG_TASK_ID)              # 2696411 또는 '2696411' 모두 됨
assert DG_TASK_ID, 'DG_TASK_ID를 넣으세요'
dg = load_script('diagnose_pipeline.py')
task = CLIENT.tasks.retrieve(DG_TASK_ID)
folder = task_dir(DG_TASK_ID)
gt = ctt.export_annotations(task, f'{folder}/diag_gt_{ctt.stamp()}.zip')      # 지금 라벨 = 정답(GT)
meta = ctt.read_export(gt)
video = S.video(meta['source'], task.name)
assert video, f"원본 영상을 못 찾음: videos/ 또는 backups/에 {meta['source']}"
last = last_upload(DG_TASK_ID, include_track=True) if DG_TRACK else None
txml = f"{BASE}/{last['result_file']}" if last and last.get('result_file') else None
print(f"TASK {DG_TASK_ID} '{task.name}' · 영상 {os.path.relpath(str(video), BASE)} · 모델 {model_label()} · IMGSZ {IMGSZ}")
print(f"track XML: {os.path.relpath(txml, BASE) if txml else '없음 (④ 생략)'}")
DG_RESULT = dg.run_diagnosis(task, gt, video, BEST, imgsz=IMGSZ, conf=DG_CONF, samples=DG_SAMPLES, track_xml=txml,
                             out_png=f'{folder}/diag_pipeline_{ctt.stamp()}.png')
