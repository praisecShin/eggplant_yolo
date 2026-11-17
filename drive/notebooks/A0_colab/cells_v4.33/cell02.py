# 2. 학습 결과 보기 — 마지막 줄의 precision / recall / mAP50 확인
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'

import pandas as pd
from IPython.display import Image, display
assert RUN_DIR and os.path.exists(f'{RUN_DIR}/results.csv'), f'학습 기록(results.csv)이 없습니다: {RUN_DIR or "모델 없음"}'
print('모델', model_label(), '·', os.path.relpath(RUN_DIR, BASE))
df = pd.read_csv(f'{RUN_DIR}/results.csv')
df.columns = [c.strip() for c in df.columns]
display(df[['epoch', 'metrics/precision(B)', 'metrics/recall(B)', 'metrics/mAP50(B)', 'metrics/mAP50-95(B)']].tail(5))
for f in ['results.png', 'val_batch0_pred.jpg']:
    if os.path.exists(f'{RUN_DIR}/{f}'):
        display(Image(f'{RUN_DIR}/{f}', width=900))