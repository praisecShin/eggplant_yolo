# 3. 검증 1단계 — 가림/크기별 재현율 (val 이미지 기준)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'

assert BEST and os.path.exists(BEST) and DS, 'best.pt와 그 모델을 학습한 dataset이 필요합니다 (0번 셀 모델 선택 확인)'
print('모델', model_label(), '· 데이터셋(Colab 로컬 사본)', DS)
run([sys.executable, f'{SCRIPTS}/eval_occluded_recall.py', '--model', BEST, '--dataset', DS, '--imgsz', str(IMGSZ)])