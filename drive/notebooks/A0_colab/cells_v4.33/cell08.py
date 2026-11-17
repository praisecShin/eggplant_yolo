# 8. 작업 대장 보기 (Drive의 task_registry.csv — Google 스프레드시트로도 열림)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'

SHOW_TASK = None        # 특정 TASK만 보려면 ID 입력
import pandas as pd
from IPython.display import display
rows = ctt.read_registry(REGISTRY) if ctt else []
df = pd.DataFrame(rows)
if len(df) and SHOW_TASK:
    df = df[df['task_id'].astype(str) == str(SHOW_TASK)]
pd.set_option('display.max_colwidth', 60)
display(df.tail(30) if len(df) else '기록 없음')