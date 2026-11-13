# 가지 자동 라벨링 앱 v4.28.2 — Kaggle에서 쓰기

v4.28.2 노트북 하나로 **Colab과 Kaggle 모두** 돌아갑니다. 0번 셀이 실행 환경을 알아보고 다음처럼 다르게 동작합니다.

- **Colab:** 지금처럼 Drive를 연결합니다. v4.11과 같습니다.
- **Kaggle:** Drive를 붙일 수 없으므로 rclone으로 Drive `eggplant_yolo/`에서 필요한 것만 받고, 셀이 끝날 때마다 바뀐 파일을 올립니다.

원본은 언제나 Drive입니다. Kaggle 안의 작업 폴더(`/tmp/eggplant_yolo`)는 세션이 끝나면 사라집니다.

---

## 1. 한 번만: Google OAuth 클라이언트 만들기 (PC, 브라우저)

rclone의 공용 클라이언트 ID는 2026년 중 종료될 예정이므로, 자기 것을 만듭니다. 사람(Google 계정)마다 한 번씩 합니다.

1. https://console.cloud.google.com 에서 새 프로젝트를 만듭니다 (예: `eggplant-rclone`).
2. **API 및 서비스 → 라이브러리 → Google Drive API → 사용**.
3. **OAuth 동의 화면**에서 외부를 고르고, 앱 이름과 본인 Gmail을 넣습니다.
   - 끝나면 **게시 상태를 '프로덕션'으로** 바꿉니다.
   - '테스트' 상태로 두면 토큰이 **7일 뒤 만료**되어 Kaggle에서 Drive가 안 열립니다.
4. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**를 누르고, 유형은 **데스크톱 앱**으로 합니다. 나오는 클라이언트 ID와 보안 비밀을 적어 둡니다.

## 2. 한 번만: rclone 설정 → Kaggle 보안 비밀 (PC)

1. PC에 rclone을 설치합니다 (https://rclone.org/downloads/). Windows는 zip을 풀고 `rclone.exe`를 씁니다.
2. 명령창에서 `rclone config`를 실행합니다.
   - `n` (새 원격), 이름은 **`gdrive`**, 저장소는 `drive`
   - `client_id`와 `client_secret`에 1장에서 만든 값을 넣습니다.
   - `scope`는 `1` (drive), `service_account_file`은 빈칸입니다. 서비스 계정은 개인 Drive에 파일을 못 올리므로 쓰지 않습니다.
   - 브라우저가 열리면 Google 로그인을 합니다. '확인되지 않은 앱' 경고가 나오면 **고급 → 이동**을 누릅니다.
   - Shared Drive 질문은 `n`입니다.
3. 접근 범위를 eggplant_yolo 폴더로 좁힙니다.
   - `rclone config file`로 설정 파일 위치를 확인하고, 메모장으로 엽니다.
   - `[gdrive]` 아래에 `root_folder_id = <폴더 ID>` 한 줄을 넣습니다.
   - 폴더 ID는 Drive에서 eggplant_yolo 폴더를 열었을 때 주소 `drive.google.com/drive/folders/` **뒤의 글자**입니다.
   - 공유받은 사람(james)도 **같은 폴더 ID**를 씁니다.
4. 확인: `rclone lsf gdrive:scripts`를 실행해 .py 목록이 나오면 됩니다.
5. 설정 파일 **내용 전체**를 복사해 Kaggle 보안 비밀 `RCLONE_CONF`에 붙여 넣습니다 (4장).
   - Kaggle 보안 비밀 칸은 줄바꿈을 없애 한 줄로 저장합니다. v4.12.1부터 0번 셀이 자동으로 줄을 다시 나누므로 그대로 붙여 넣으면 됩니다.
   - 이 안에 Drive 접근 토큰이 들어 있습니다. PAT와 똑같이 다룹니다.
   - 코드, 노트북, 대화, Drive에 두지 않습니다. 필요 없어지면 Google 계정 → 보안 → 타사 앱 접근에서 끊습니다.

## 3. 한 번만: Kaggle 계정

1. kaggle.com에 가입합니다.
2. **Settings → Phone verification**을 합니다. 해야 인터넷과 GPU를 쓸 수 있습니다.
3. 같은 화면에서 주간 GPU 한도(보통 약 30시간)를 확인합니다. 세션 하나는 최대 12시간입니다.

## 4. 노트북 올리기와 설정

1. **Create → New Notebook → File → Import Notebook**에서 `eggplant_yolo_colab_v4.28.2.ipynb`를 올립니다.
2. 오른쪽 **Session options**:
   - Accelerator: **GPU T4 x2** 또는 **GPU P100**. 학습은 GPU 1개만 쓰므로 T4 x2의 두 번째 GPU는 놀게 됩니다.
   - **Internet: On**
3. **Add-ons → Secrets**에 아래 이름으로 넣고, 각각 **이 노트북에 체크(Attach)** 합니다.
   - `RCLONE_CONF` (필수)
   - `CVAT_TOKEN` · `CVAT_TOKEN_B` · `CVAT_USER` · `CVAT_PASS` (쓰는 것만)
4. 노트북은 **Private**으로 둡니다 (기본값).
5. 0번 셀 설정:
   - `OPERATOR`: 예 `'A-재웅-kaggle'`. 어디서 학습했는지 기록에 남습니다.
   - `KAGGLE_REMOTE = 'gdrive:'`: 2장에서 root_folder_id를 넣었을 때입니다. 안 넣었으면 `'gdrive:eggplant_yolo'`.

## 5. 쓰는 법 — Colab과 같음 + 자동 동기화

0번 셀부터 실행하고, 필요한 셀로 건너뜁니다.

| 시점 | Kaggle에서 일어나는 일 |
|---|---|
| 0번 셀 | rclone 설치. 그다음 Drive에서 `scripts/` · `config/` · `logs/` · 대장 · 백업/export 색인 · `exports/` · `runs/*`의 작은 파일과 `best.pt` · `datasets/*.sig`를 받음. **영상·백업·last.pt는 받지 않음** |
| 셀 실행 전 | 공유 기록(logs/, 작업 대장, backup_*.csv, pending_*.csv, export 색인)의 Drive 최신본을 받음 |
| 셀 실행 후 | 그 셀에서 바뀐 파일만 Drive에 올림 → `☁️ Drive 반영: 올림 n개`. 셀에서 지운 파일은 Drive에서도 지움(휴지통). 단 `videos/` · `backups/`는 지우지 않음 |
| 영상이 필요할 때 (5·9·10·11·15·20·24·27번) | 그 TASK의 영상만 Drive `videos/`에서 받음. 없으면 `backups/<이름>/`의 가장 최근 백업 zip만 받음 |
| TASK 폴더 (`tasks/<ID>/`) | 그 TASK를 처음 다룰 때 받음 |
| 학습 (1·15번) | 잠금(`RUNNING.json`)을 Drive와 주고받음. 잠금을 잡을 때 `runs/<이름>`을 받아 이어서 학습 가능. 에폭마다 `runs/<이름>`을 Drive에 올림 |
| 16·17번 | `RS_QUERY`/`RS_FILES`, `VC_QUERY`/`VC_FILES`로 고른 백업·영상만 받음 |

직접 다루기:

- `drive_pull('runs/fruit_1920')`, `drive_pull('datasets/exp_x.zip')`: Drive에서 받기 (파일·폴더·`*` 패턴)
- `drive_get_videos('G6 date=261019')`: 영상을 검색어로 받기 (TASK 이름 규칙)
- `drive_push('reports')`: 올리기
- `drive_sync_now()`: 자동 동기화를 끈 경우(`KAGGLE_AUTO_SYNC = False`) 바뀐 것 올리기
- 2·3번 셀(학습 결과·검증 1단계)에 데이터셋이 필요하면 0번 셀 `KAGGLE_PULL_DATASET = True`
- 웹 관리 화면의 요청(`requests/`)도 셀마다 받고, 셀이 바꾼 요청 상태를 올립니다 (v4.17).
- 보안 비밀을 나중에 붙였다면 0번 셀만 다시 실행하면 읽힙니다 (v4.17).
- 13번 셀의 작업보드는 v4.20부터 `reports/작업보드.xlsx` 파일이라 Kaggle에서도 갱신됩니다 (Drive로 올라감). `BK_BOARD = 'sheet'`(Google 스프레드시트)는 Colab에서만.
- 21번 인쇄용 HTML은 오른쪽 **Output(/kaggle/working)**에서 내려받습니다.

**GPU 한도 아끼기:** GPU가 필요 없는 셀(4, 8, 13, 14, 16~19, 21, 22, 25, 26)만 할 때는 Accelerator를 **None**으로 두고 실행합니다. 바꾸면 세션이 다시 시작되므로 0번부터 실행합니다.

## 6. 긴 학습은 Save & Run All로 (브라우저를 닫아도 계속)

`eggplant_kaggle_train_v4.28.2.ipynb`는 0번 셀 + 15번 셀 + 마지막 올리기 셀만 있는 학습 전용 노트북입니다.

1. Kaggle에 따로 올리고, 4장과 같이 GPU, Internet On, `RCLONE_CONF`를 붙입니다.
2. 15번 셀 맨 위(`EXP_DIR`, `EXP_QUERY`, `TRAIN_NAME` …)와 0번 셀 `OPERATOR`를 정합니다.
3. **Save Version → Save & Run All (Commit)**. 최대 12시간 동안 무인으로 실행됩니다.
4. 결과는 에폭마다 Drive `runs/<이름>/`에 올라갑니다. 끝나면 어디서든 0번 셀 `MODEL_CHOICE = 'latest'`로 씁니다.
5. 끊기면 같은 설정으로 다시 Save & Run All → 마지막 에폭부터 이어서 학습합니다.

주의: 0번 셀이나 15번 셀을 본 노트북에서 고치면 학습 전용 노트북의 같은 셀도 똑같이 고쳐야 합니다.

## 7. 함께 쓸 때 주의 (Colab과 Kaggle, 두 사람)

- **같은 이름으로 동시에 학습하지 않기.** 잠금은 Drive를 통해 통하지만 Kaggle 쪽은 1분 간격으로 주고받습니다. 동시에 학습하면 `TRAIN_NAME`을 다르게 (예: 끝에 `_K`).
- **기록 CSV가 덮어써질 수 있음.** Colab과 Kaggle이 **같은 몇 분 안에** 같은 CSV(`logs/activity.csv`, `task_registry.csv` 등)를 고치면, 나중에 올린 쪽이 앞의 것을 덮어쓸 수 있습니다. 동시에 CVAT 작업 셀을 돌리지 않는 것이 안전합니다. 덮어써졌으면 Colab 23번 셀처럼 Drive 버전 기록에서 되찾을 수 있습니다.
- **23번 셀(Drive 버전 복원)은 Colab에서만** 됩니다.
- **프레임 캐시**(`raw_images/`, `cvat_frames/`)는 Kaggle에서 올리지도 받지도 않습니다. 15번이 데이터셋을 새로 만들 때 다시 뽑습니다.
- **디스크:** Kaggle 작업 폴더의 여유 공간은 0번 셀 '실행 환경' 줄에 나옵니다. 영상을 많이 받았으면 Kaggle에서 지워도 됩니다. `videos/` · `backups/`는 Drive에서 지워지지 않습니다.

## 8. 처음 실환경 시험 순서 (작게)

1. 0번 셀 → '실행 환경: Kaggle', 'scripts/ 모두 있음' 확인
2. 4번 셀 → CVAT 접속과 TASK 목록
3. 8번·26번 셀 → Drive 기록이 보이는지
4. 작은 TASK 하나로 14번 export (`EX_PREVIEW`부터) → **Drive `exports/`에 새 폴더가 생겼는지 Drive 웹에서 확인**
5. 15번: `LIST_ONLY = True` → 그다음 `EPOCHS`를 3 정도로 짧게 학습 → Drive `runs/<이름>/`이 에폭마다 늘어나는지
6. 학습 전용 노트북으로 같은 것을 Save & Run All
7. 중요하지 않은 TASK로 5→6번 (`UPLOAD_PREVIEW = True`만)

문제를 알릴 때는 셀 번호, 설정값, 출력 전문, 0번 셀의 '실행 환경'·'앱 버전'·'scripts/' 줄을 함께 붙여 주세요.

## 9. 시험 범위

- **시험한 것 (가짜 Drive = rclone alias 원격, 가짜 ctt, 가짜 torch/ultralytics):**
  - 0번 셀 받기 범위와 수정 시각 보존('latest' 모델 선택)
  - Kaggle 보안 비밀 읽기, 토큰이 출력에 안 나옴
  - 셀 전후 자동 동기화 (올림·지움·영상 보호·공유 기록 받기)
  - 영상/백업 자동 받기, task_dir 받기
  - 학습 잠금 (Drive 경유 잡기·빼앗김 감지·풀기·확인 대기)
  - 0번 셀 다시 실행 시 훅·감싸기 중복 없음
  - 23번 차단
  - Colab 모드가 v4.11과 같게 동작
- **시험 못 한 것:**
  - 실제 Kaggle, 실제 Google Drive, 실제 CVAT
  - 실제 YOLO 학습의 에폭별 올리기
  - 15번 데이터셋 만들기
  - Save & Run All(Batch)에서의 자동 동기화
  - 실제 `ctt.find_video`의 이름 맞춤 방식과의 일치 (가짜는 '기본 이름 = 파일 이름' 규칙)

  이 항목들은 8장 순서로 처음 쓸 때 확인이 필요합니다.

---

바뀐 점은 앱의 `CHANGELOG.md`를 보세요.

## export zip과 여러 세션 (v4.23)
- 0번 셀은 시작할 때 `exports/`를 받아 둡니다(`KAGGLE_PULL`). 그 뒤에 **다른 세션·컴퓨터(Colab 포함)가 받은 export zip**은 예전에는 이 세션에 보이지 않아, 14번 셀이 대기 목록의 '받음' 줄을 '파일 없음'으로 보고 다시 받으려다 CVAT에서 '만료'를 받았습니다.
- v4.23부터 export를 읽는 셀(4·14·15·22·24·28)이 시작할 때 `kg_sync_exports()`로 Drive의 새 zip을 받아 둡니다 (이미 있는 것은 건너뜀).
- 14·28번 셀은 파일이 Drive에 있는데 '만료'·'실패'로 적힌 줄을 '받음'으로 되돌리고, 그 때문에 '실패'가 된 웹 요청도 다시 확인해 완료로 바꿉니다.
- **v4.26.0 고침**: 셀이 끝날 때 Drive로 올리는 파일을 '셀 안에서 수정 시각이 바뀐 파일'로만 골라서, 14번 셀이 이전 export를 **복사(수정 시각 보존)** 한 zip은 올라가지 않았습니다. 대기 목록에는 '받음'으로 남아 다음 세션에서 '파일 없음 → 다시 받기 → 만료'가 되었습니다. 이제 셀이 새로 만들거나 바꾼 파일은 모두 올리고, 셀 안에서 Drive에서 받은 그대로인 파일만 뺍니다. 받은 기록만 있고 파일이 없는 줄은 원본 export가 있으면 다시 복사하고, 없으면 '만료'로 정리합니다 (CVAT에 다시 묻지 않음) — 같은 검색어로 14번 셀을 다시 실행하면 됩니다.


## LC 작업자(31번 셀)를 Kaggle에서 (v4.26.0)
- 0번 셀 → 31번 셀을 실행해 두면 LC앱 요청을 처리합니다. 요청 파일은 `LC_POLL_SEC`마다 Drive에서 받고, 상태가 바뀐 요청은 바로 Drive로 올리며 이름이 바뀐 예전 파일(대기·진행 중)은 Drive에서 지웁니다. 작업자 상태 `web/worker.json`도 1분마다 올립니다.
- Kaggle 세션은 대화형이면 브라우저를 닫은 뒤 얼마 지나 멈추고, 최대 실행 시간이 있습니다 → LC앱 위쪽 '응답 없음'이면 세션이 끊긴 것입니다. 다음에 켜면 멈춘 요청을 다시 대기로 돌려 처리합니다.
- 30번(재처리)과 31번(LC)을 같이 켜려면 Kaggle 노트북 두 개(세션 두 개)로 나눕니다. 한 세션은 셀 하나씩 실행합니다.
