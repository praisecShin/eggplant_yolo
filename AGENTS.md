# AGENTS.md — 가지 자동 라벨링 (Eggplant) v4.31.8

이 저장소에서 일하는 코딩 에이전트(Codex 등)를 위한 안내입니다. 자세한 점검 항목은 `REVIEW_CHECKLIST_v4.31.8.md`, 설치·변경 내용은 `README_v4.31.8_설치.md`에 있습니다.

## 1. 역할

- 이 저장소에서 당신의 기본 역할은 **검토자**입니다. 요청이 따로 없으면 코드를 고치지 말고 발견한 것만 보고하세요.
- 고치라는 요청을 받은 경우에도 아래 3장의 약속을 바꾸는 수정은 하지 말고, 그런 수정이 필요하면 이유와 함께 보고만 하세요.
- 주석, 출력 문구, 문서는 한국어입니다. 새로 쓰는 보고서도 한국어로 씁니다.

## 2. 저장소 구조

```
apps_script/Code.gs            Apps Script — CVAT TASK 수집(collect), 요청 배정(dispatch), _AA 자동 요청
drive/scripts/*.py             노트북이 불러 쓰는 부품 (Google Drive eggplant_yolo/scripts/에 그대로 올라감)
  cvat_task_tools.py   (ctt)   CVAT 접속·TASK 이름 규칙·export·작업 대장·고정 시험 TASK
  web_bridge.py        (wb)    LC앱 요청·상태·공정 차례(fair_order)·사라진 TASK
  relabel_bridge.py    (rb)    재처리 앱 요청·상태·작업자 생존 신호
  train_sim.py                 학습 계획 연구(지문·성적·개수 오차·관계·분할안) — 33번 셀
  yolo_track_to_cvat.py        YOLO+BoT-SORT로 track XML 만들기 (--frame-map: ULD 사진 TASK)
  cvat_backup.py, cvat_to_yolo.py, compare_tracks.py 등
drive/scripts/notebook_cells.json  작업자가 실행하는 셀 코드 사본 (노트북과 글자까지 같아야 함)
drive/notebooks/
  eggplant_yolo_colab_v4.31.8.ipynb        사람이 쓰는 노트북 (0번 셀 먼저 → 필요한 셀). 30번 = 작업자, 33번 = 학습 계획 연구
  eggplant_kaggle_gpu_worker_v4.31.8.ipynb 0번 + 30번 셀(W_ROLE='gpu') — CPU 마스터가 Kaggle API로 시작
  eggplant_kaggle_cpu_master_v4.31.8.ipynb · kaggle_cpu_master.py   Kaggle CPU 상주 마스터 (ipynb 안의 코드 = py)
tests/                          가짜 Drive·가짜 CVAT 시험
```

통신은 모두 Google Drive의 파일(요청 `requests/REQ_<id>__<kind>__<status>.json`, 배정 `requests/assign/`, 상태 `web/state.json`·`relabel/state.json`)입니다. 웹앱 2개(LC앱, 재처리 앱)는 이 저장소에 없습니다.

## 3. 반드시 지켜야 할 약속 (리뷰의 최우선 기준)

위반은 심각도 '치명' 또는 '높음'으로 보고합니다.

1. **비밀 값:** CVAT 토큰·비밀번호·`RCLONE_CONF`·`KAGGLE_KEY`는 Colab·Kaggle 보안 비밀(Apps Script는 Script Properties)에서만 읽습니다. 코드, 출력, 로그, Drive 파일, 요청·상태 파일, 예외 메시지, 임시 파일에 남으면 안 됩니다. Apps Script에는 `doGet`/`doPost`(웹앱 배포)가 없어야 합니다.
2. **올리기 전 백업:** 라벨을 CVAT에 올리는 모든 경로는 먼저 그 TASK의 라벨을 export해 둡니다.
3. **사람 라벨 보호:** 기존 라벨이 있는 TASK는 명시적 설정(`ALLOW_REPLACE`, `TRACK_UPLOAD_REPLACE`, `AA_EXISTING='replace'`) 없이 덮어쓰지 않습니다. 예외는 이름이 `_uld` 또는 `_AA`(`_AA_rN`)로 끝나는 TASK이며, 이때도 백업한 뒤 교체합니다.
4. **이름:** 앱이 TASK 이름을 바꾸는 경우는 라벨을 올린 뒤 `…_uld` → `…_uld_AA` 하나뿐입니다.
5. **CVAT_UpLoader는 읽기 전용:** 그 폴더에 쓰지 않습니다. Kaggle에서 받은 clip은 작업 폴더 밖 임시 폴더에 두고, Colab에서는 Drive의 원본 clip을 지우지 않습니다.
6. **TASK를 지우지 않습니다.**
7. **거짓 완료 금지:** 처리하지 않은 요청을 '완료'로 표시하지 않습니다. 한 요청은 한 작업자만 처리하고, 배정(`requests/assign`)을 따릅니다. 같은 TASK의 요청은 보낸 차례대로 하나씩 처리합니다.
8. **고정 시험 TASK:** `config/test_tasks.json`의 TASK와 같은 그루·촬영일 TASK는 학습·val에서 빠져야 합니다(15번 셀 `USE_TEST_SET`).

상태 이름 묶음(의도된 동작): `vf` = vf·vf_r1·vf_r2, `vfdf` = vf_r2df, `vfdf_ok` = vf_r2df_ok, `AA` = AA·AA_rN, `_test` = 상태 없는 기본 계열.

## 4. 실행·시험 방법

필요한 것: Python 3.10 이상, `numpy`, `Pillow`, `rclone`(test_master 계열), Node.js(js 시험). **실제 CVAT·Google Drive·Kaggle에는 접속하지 마세요.** 토큰은 없고, 모든 시험은 가짜 환경으로 돕니다.

```bash
pip install numpy pillow pyflakes          # rclone은 OS 패키지로 (apt install rclone 등)

# 저장소 맨 위에서
python3 tests/test_sim.py drive            # 학습 계획 연구·고정 시험 TASK·사라진 TASK·ULD 교체 연결
python3 tests/test_worker30.py drive       # 30번 셀 통합 작업자: 공정 차례·GPU 줄·두 앱 요청
python3 tests/test_worker_gpu.py drive     # GPU 워커(W_ROLE='gpu'): kaggle_gpu 배정만·학습·스스로 종료
python3 tests/test_uld.py drive            # ULD 사진 TASK·이름 규칙
python3 tests/test_state_uld.py drive      # 앱 상태의 ULD 표시·Drive 목록 기반 모델 목록
python3 tests/test_master.py drive         # CPU 마스터 순환 (rclone 필요)
python3 tests/test_master_gpu.py drive     # CPU 마스터가 GPU 워커를 올리는지 (가짜 kaggle 명령)
python3 tests/test_master_stop.py drive    # CPU 마스터 정지 표시
node tests/test_auto.js apps_script/Code.gs
node tests/test_dispatch.js apps_script/Code.gs
```

- 각 시험은 `✅`/`❌` 줄과 마지막 `RESULT True`(또는 `통과`)를 출력합니다. 지금은 모두 통과합니다.
- 시험은 `tests/_work*` 폴더를 만들고 지웁니다. 저장소의 다른 파일은 바꾸지 않습니다.
- 노트북 셀은 IPython 전용 줄(`!`, `%`)을 빼면 일반 파이썬입니다. 정적 점검 예:
  ```bash
  python3 -m pyflakes drive/scripts/*.py drive/notebooks/kaggle_cpu_master.py
  ```
  셀 코드는 0번 셀(공통 설정·함수)이 먼저 실행된다고 가정하므로, 셀 단독으로 '정의되지 않은 이름'이 나오면 0번 셀에 있는지 먼저 확인하세요.
- 노트북을 셀 단위로 실행하지 마세요. 0번 셀은 Google Drive를 붙이거나 rclone으로 Drive에 접속하려고 합니다.

## 5. 리뷰 기준

우선순위 순입니다.

1. 3장의 약속 위반
2. 요청이 처리되지 않거나, 두 번 처리되거나, 잘못된 결과를 '완료'로 남기는 경로 (특히 30번 셀의 스레드·주 스레드 동시 실행, 작업자 여럿이 Drive 파일을 함께 쓰는 경우)
3. 데이터 손실: Drive 파일 덮어쓰기, 세션별 기록(shard) 합치기, 옛 이름 요청 파일이 되살아나는 경우
4. 해결해 온 이슈의 재발 (`REVIEW_CHECKLIST_v4.31.8.md` 4장)
5. v4.31.8 새 코드의 정확성 (`train_sim.py`, 33번 셀, 15번 셀의 시험 TASK 제외, 사라진 TASK, ULD 교체 연결)
6. 일관성: `notebook_cells.json` ↔ 노트북 셀, GPU 워커 노트북 ↔ Colab 노트북(`W_ROLE` 한 줄만 다름), 버전 문자열 4.31.8 (`Code.gs`의 `COLLECTOR_VERSION`은 4.31.5가 맞음)

보고하지 않아도 되는 것: 한국어 문구의 어색함, 코드 스타일·이름 짓기 취향, 성능 미세 조정, 이미 주석으로 한계라고 밝힌 것.

## 6. 보고 형식

결과는 `REVIEW_RESULT.md`(또는 요청받은 곳)에 아래 형식으로 씁니다. 심각도 순으로 정렬합니다.

| 칸 | 내용 |
|---|---|
| 번호 | F1, F2 … |
| 심각도 | 치명(데이터 손실·비밀 노출·거짓 완료) / 높음(요청 미처리·잘못된 결과) / 보통 / 낮음 |
| 관련 항목 | 3장 약속 번호, 점검표 항목(P4, A1, D5 등) 또는 '새 발견' |
| 위치 | 파일, 함수 또는 셀 번호(`# 30.`처럼 셀 첫 줄), 줄 |
| 무엇이 문제인가 | 한두 문장 |
| 일어나는 조건 | 어떤 입력·순서에서. 재현 방법이 있으면 함께 |
| 확신 | 확인함(코드로 추적했거나 실행해 봄) / 추정 |
| 제안 | 고치는 방향 (코드는 쓰지 않아도 됨) |

끝에 두 목록을 덧붙입니다: 점검했지만 문제가 없던 항목, 시간이 모자라 보지 못한 항목.
