# v4.33 구현 2c — 사람용 셀

계획과 결정(11/17)은 `docs/IMPL_STEP2C_PLAN_v4.33.md`에 있습니다.

## 2c-1 기반 — 0번 셀 (v4.33.0z4)

**새 파일:**
- `drive/scripts/cells_base.py`: 분석 모드 기반. 시험할 수 있도록 0번 셀에서 모듈로 뺐습니다.
- `drive/notebooks/A0_colab/cells_v4.33/cell00.py`: v4.33 0번 셀 원문. 노트북 조립은 2c-6에서 합니다.

**고친 파일:**
- `access.py`: 실행 범위 `exec_scope()`·`in_exec_scope()`를 추가했습니다.
- `exec_host.py`:
  - `run_loop`가 한 걸음마다 실행 범위 안에서 돕니다.
  - `main_colab`은 끝날 때 `EGG_ACCESS`를 원래 값으로 되돌립니다.

| 장치 | 내용 |
| --- | --- |
| 모드 | 사람용 셀은 `EGG_ACCESS`가 비었거나 `analysis`일 때만 시작합니다. `exec`·모르는 값(12번 셀의 `cli` 등)이면 시작하지 않습니다. `OPERATOR`(사람 ID)가 없어도 시작하지 않습니다 |
| 분석 폴더 | `analysis/<사람>/<YYMMDD_HHMM>_<세션>/` (`OUT`, `out_path()`). 세션 기록(`_session.json`)도 여기에 씁니다. 옛 `logs/versions.csv` 덧붙이기는 없앴습니다 |
| **쓰기 가드** | `open`(쓰기 모드)·`io.open`·`os.replace/rename/remove/unlink/rmdir/mkdir/makedirs/symlink/link/truncate`·`shutil.rmtree/move/copy/copy2/copyfile/copytree`를 감쌉니다. BASE 안에서 분석 폴더·좁은 API 밖이면 거절합니다. pathlib·pandas 저장도 같은 길을 지납니다. BASE 밖(Colab 로컬 디스크)은 그대로 씁니다. 이미 있는 폴더를 다시 만드는 것은 바꾸는 일이 아니므로 통과합니다 |
| **CVAT 가드 (전송 경계)** | `cvat_sdk`의 `RESTClientObject.request`와 `requests.Session.request`(cvat_backup)를 감쌉니다. CVAT 서버로 가는 요청은 GET·HEAD·OPTIONS, 로그인·로그아웃, 참조용 export 준비(`POST /api/tasks|jobs/<id>/dataset/export`)만 통과합니다. 다른 서버로 가는 요청은 그대로 둡니다. 메서드 이름 추측이 아니라 (방식, 경로) 허용 목록이고, 거절은 네트워크로 나가기 전에 합니다. cvat-cli는 `run()`에서 `task ls`·`project ls`·`task export-dataset`·`task frames`만 허용합니다 |
| 좁은 예외 API | `request(종류, TASK, params, name=…)`는 `requests/REQ_<id>__<종류>__pending.json`을 씁니다(복구 일 제외, 칸·JSON 검사). `signal(종류, …)`는 `jobs/signals/<종류>__<세션>__n.json`을 씁니다. 공유 폴더에 쓰는 것은 이 둘뿐입니다. 분석 세션의 생존 표시는 `workers/`에 쓰지 않습니다(심판이 실행기로 읽기 때문) |
| 모델·데이터셋 (점검표 D) | `S.model('latest' 또는 이름)`은 가장 최근에 채택된 모델의 best.pt를, `S.dataset(이름)`은 채택된 데이터셋 zip을 목록 해시와 대조해 Colab 로컬로 받습니다. 공유 `runs/`·`datasets/`는 읽기만 합니다 |
| 같은 커널의 30번 셀 | 실행기가 한 걸음을 처리하는 동안(`exec_scope`)만 두 가드를 비켜 갑니다. 실행기가 멈추면 다른 셀의 쓰기는 다시 막힙니다(점검표 A '30번 중단 뒤 다른 셀에서 쓰기 거절') |
| 옛 쓰기 함수 | `lock_run`·`run_training`·`upload_log`·`label_uploaded`·`req_use`·Kaggle 동기화는 부르면 이유와 바꿔 쓸 길(예: `request('train', …)`)을 알려 주며 거절합니다 |
| Colab 전용 | Kaggle 지원(약 400줄)을 뺐습니다. 보안 비밀은 Colab 보안 비밀에서만 읽고 출력하지 않습니다 |

**나머지 셀은 아직 옛 원문입니다.** 2c-2·2c-3에서 각 셀을 이 기반 위로 옮깁니다. 옛 셀이 공유 폴더에 쓰려고 하면 지금은 쓰기 가드가 이유와 함께 거절합니다.

**시험:** `tests/test_cells_433.py` 44개.
- 모드, 쓰기 가드(pandas 포함), 요청·신호 API와 심판 접수, CVAT 전송 가드(requests 세션 포함), cvat-cli, 실행 범위와 30번 중단 뒤 거절, 채택 모델·데이터셋 해시 대조, 다시 시작, 0번 셀 원문을 확인합니다.
- 돌연변이 확인: 쓰기 모드 확인 빼기, 모든 쓰기 방식 허용, 실행 범위 무시, cvat-cli 하위 명령 확인 빼기 → 각각 실패합니다.

**알려진 한계:**
- 가드는 실수 방지 장치입니다(설계 '신뢰 모델'). 다음 경로는 막지 않습니다.
  - `os.open`이나 다른 프로세스(셸 명령 `!cp` 등)로 직접 쓰는 것
  - CVAT 웹에서 직접 고치는 것 — 범위 밖이며, 정기 점검이 '알 수 없는 수정(CVAT)'으로 찾습니다
- 옛 CVAT API의 GET으로 서버 작업이 생기는 경로(예: 오래된 `GET /api/tasks/<id>/backup`)는 읽기로 통과합니다. 서버 2.79 기준으로는 백업 준비가 POST입니다.


## 2c-2 읽기 셀 (v4.33.0z5)

**새 셀 원문 15개** (`drive/notebooks/A0_colab/cells_v4.33/`): 2·3·4·7·8·11·18·19·20·21·22·24·25·26·32번.
모두 맨 위에 `[v4.33 분석 셀]` 표시가 있고, 분석 모드 기반(2c-1) 위에서 돕니다.

| 바꾼 것 | 내용 |
| --- | --- |
| 저장 위치 | 보고서·표(`reports/…`)는 `REPORTS` = 내 분석 폴더 `reports/`. TASK별 파일(export·비교·진단 그림)은 `task_dir()` = 분석 폴더 `tasks/<id>/` |
| 옛 기록 쓰기 | `cb.redirect_records`가 `ctt.shard_path`를 감쌉니다. 작업 대장·작업 기록·모델 비교 기록 같은 세션별 기록은 내 분석 폴더 `records/<원래 경로>`에 씁니다. 읽을 때는 옛 공유 기록(읽기만)과 내 세션 기록을 합쳐 읽습니다 |
| 통계 캐시 | `wb.compute_stats`·검토 수정량 캐시는 분석 폴더 `cache/`의 사본에 씁니다 (처음에 공유 캐시를 복사) |
| `job_start`·`job_end` | 0번 셀에 다시 둠. 기록은 내 분석 폴더로 갑니다 |
| 마지막 올린 라벨 | `last_upload(tid)`: v4.33 실행기 결과(심판 기록 + 복구 자료의 결과 파일)와 옛 작업 대장 중 나중 것. 올린 뒤 되돌리기가 끝났으면 그 업로드는 쓰지 않습니다. 7·11·19·20·32번이 씁니다 |
| 모델 | 2번은 채택 버전의 기록 폴더(`S.run_dir`), 3번은 그 모델을 학습한 데이터셋 버전(`S.dataset_of_model`), 24·32번은 `pick_model`(채택 버전을 해시 대조해 받음). 옛 `runs/<이름>/weights/best.pt` 직접 경로는 없앴습니다 |
| 영상 | 11·20번은 `S.video`: 공유 `videos/`(읽기) → 없으면 `backups/`에서 Colab 로컬로 꺼냄 |
| 25번 업로드 기록 | 옛 `logs/uploads.csv` + v4.33 실행기 결과(성공·실패 이유·요청자·모델). 상세는 복구 자료의 `result_plan.json`을 보입니다 |
| 26번 작업 기록 | 옛 `logs/activity.csv` + 실행기 결과를 TASK 줄로. `AC_IMPORT_OLD`(공유 `logs/`에 씀)는 없앴습니다 |
| 32번 모델 비교 | `FROM_REQUESTS`(앱 요청 받기)와 `rb.add_history`(공유 재처리 이력 쓰기)를 없앴습니다. 웹 화면의 비교 요청은 실행기 몫입니다 |
| 24번 | 정답 후보 '업로드 직전 백업'을 옛 `tasks/<id>/`(읽기)와 v4.33 복구 자료의 `before_upload.zip`에서 찾습니다 |
| Kaggle | `ON_KAGGLE`·`drive_pull`·`kg_sync_exports` 분기를 모두 없앴습니다 (Colab 전용) |

**처리기 보강 (`h_task.py`):** 올린 결과 파일도 복구 자료(`recovery/<TASK>/<작업번호>/result.<확장자>`)에 해시와 함께 게시합니다.
`result_plan.json`에 `result_file`·`result_sha256`·`model`을 적습니다 (DESIGN 확정 5단계 '올릴 결과 파일(해시)').
이것이 없으면 사람용 셀이 실행기가 올린 라벨과 비교할 기준이 없습니다.

**시험:** `tests/test_cells_433.py` 57개 (2c-2에서 13개 추가). `tests/test_handlers_433.py` 143개 (1개 추가).
- 15개 셀 원문 검사 (분석 셀 표시·Kaggle·공유 기록 쓰기·요청 받기·옛 모델 경로 없음)
- 0번 셀 원문의 도우미를 그대로 실행하고, 8·25·26·7·19번을 분석 모드에서 실제로 실행합니다 (가짜 CVAT·가짜 하위 스크립트).
  - 공유 폴더(분석 폴더 밖)의 파일이 하나도 바뀌지 않는지
  - 기록 줄이 내 분석 폴더 `records/`로 가고, 다시 읽을 때 합쳐지는지
- 돌연변이 확인: 기록 경로 돌리기 빼기, 되돌리기 무시 → 각각 실패합니다.

**알려진 한계:**
- 실행 시험은 5개 셀만입니다. 2·3·4·11·18·20·21·22·24·32번은 YOLO·영상·CVAT 프레임이 필요해 원문 검사(문법·금지어)만 합니다. 전 셀 분석 실행 시험은 2c-6에서 합니다.
- 옛 공유 `exports/_export_index.csv` 갱신은 가드가 막고 `scan_exports`가 조용히 넘깁니다. 분석 셀에서는 export 색인이 새로 저장되지 않아 다음 실행도 zip을 다시 엽니다 (느릴 뿐 결과는 같음).
- v4.33 실행기가 이번 변경 전에 만든 복구 자료에는 결과 파일이 없습니다. 그 TASK는 옛 작업 대장 기준으로 비교합니다 (지금은 배포 전이라 해당 없음).


## b28 반영 (v4.33.0z6)

결과: `docs/REVIEW_RESULT_v4.33.0z4_b28.md`. 결정(11/17): D10 취소는 지금대로(등록자 누구나), D11은 `last_adopted`.

| 발견 | 고친 것 | 시험 |
| --- | --- | --- |
| **V1** 0번 셀 재실행 실패 | 활성 세션을 모듈 전역이 아니라 `sys`에 둠(`_state()`) — `importlib.reload(cb)` 뒤에도 앞 세션을 찾음. 가드가 감싼 함수에 원래 함수 표시(`__egg_orig__`)를 달고, 새 가드는 언제나 진짜 원래 함수를 감쌈(가드가 겹치지 않음). 새 분석 폴더는 앞 가드가 켜진 채로 '이 스레드·이 폴더만' 허용해 만듦 | 실제 0번 셀 순서(reload → start), 활성 세션 유지, 원래 함수 한 겹 |
| **V2** 시작 실패가 가드를 풂 | `start`는 모드·사람 ID·BASE를 검사하고 새 세션을 다 준비한 **뒤에** 앞 가드를 바꿈. 바꾸다 실패하면 앞 가드를 다시 켬 | OPERATOR 없음·BASE 없음·모드 틀림 뒤에도 공유 폴더 쓰기와 CVAT 쓰기가 막힘 |
| **V3** 키워드 인자 | os·shutil 함수마다 인자 이름(`src`·`dst`·`path`)과 위치를 표로 두고 둘 다 검사. `dir_fd`·`src_dir_fd`·`dst_dir_fd`는 `/proc/self/fd`로 실제 경로를 풀어 검사, 못 풀면 거절 | 키워드 replace·rename·remove·unlink, dir_fd unlink·mkdir, BASE 밖 `shutil.rmtree`(안에서 dir_fd 씀)는 그대로 |
| **V4** 거짓 clean | 감독이 `PR_SET_CHILD_SUBREAPER` 반환값과 `PR_GET`으로 다시 읽은 값을 확인하고, `/proc` 관측을 확인. 하나라도 안 되면 학습 자식을 **띄우지 않고** `{"setup_failed", "child_started": false}`를 남김 → 실행기는 '학습 감독 준비 실패'(일반 실패). 띄운 것이 없어 남은 것도 없으므로 '확인 필요'로 보내지 않음 | prctl 실패를 주입한 감독으로 RealTrainer 실행(학습 자식이 안 뜸), prctl −1 반환 판정 |
| **V5** 링크 항목 | 지우기·옮기기·링크 만들기·폴더 만들기는 '부모만 풀고 마지막 이름은 그대로'인 항목 경로로 검사. 내용 쓰기(open·copy 대상·truncate)는 지금처럼 가리키는 곳으로 | BASE 안 링크(밖을 가리킴) 지우기·옮기기 거절, 내 분석 폴더 안 링크(공유 파일을 가리킴)는 지울 수 있고 공유 파일은 그대로 |
| **D11** | `S.model('last_adopted')` = 채택 시각이 가장 늦은 모델. `'latest'`는 거절(이유 안내). 채택 시각이 없으면 고르지 않음. 0번 셀 출력에 '(최근 채택 MM-DD HH:MM)' | 'latest' 거절, 시각 없음 거절 |

**시험:** `test_cells_433` 69개(+12), `test_hosts_433` 57개(+3). 돌연변이 확인: 시작 전 앞 세션 닫기, 모듈 전역 상태(reload로 초기화), 키워드 인자 무시, 항목 대신 끝까지 풀기, 원래 함수 표시 없애기 → 각각 실패합니다.

**알려진 한계 (그대로):** 가드는 실수 방지 장치입니다. `os.open`·하위 프로세스·직접 urllib3·`Session.send`는 지나지 않습니다(b28 C8). 공유 `scripts/`를 import할 때 생기던 `__pycache__`는 0번 셀이 `sys.dont_write_bytecode = True`로 막습니다(b28 B4).


## b29 반영 (v4.33.0z7)

결과: `docs/REVIEW_RESULT_v4.33.0z6_b29.md`.

| 발견 | 고친 것 | 시험 |
| --- | --- | --- |
| **W1** 세션을 바꾸는 동안 가드가 빔 | 감싸기 함수(open·io.open·os·shutil·CVAT 전송)는 프로세스에 **한 번** 깔고, 부를 때마다 '지금 활성 세션'(`sys`의 `_state()["active"]`)의 가드를 따릅니다. `install`·`uninstall`은 이제 그 가드를 켜고 끄기만 합니다. `start`는 새 가드를 켠 뒤 활성 세션을 **한 번의 대입**으로 바꾸고, 그다음에 앞 세션을 끕니다. 바꾸는 순간에도 앞 가드나 새 가드 중 하나가 늘 적용됩니다 | 앞 세션이 꺼지는 바로 그때 다른 스레드가 공유 폴더에 쓰기(결정적), 다른 스레드가 계속 쓰는 동안 15번 다시 시작 |
| **W2** 같은 날 기록 비교 | `_when()`: 옛 기록 'YYYY-MM-DD HH:MM:SS'(시간대 없음 = 한국 시각)와 실행기 '…T…+09:00'를 epoch 초로 바꿔 비교 | 같은 날 실행기 09:00 vs 옛 기록 11:00 → 옛 것 |
| **W3** 26번 셀 빈 열 | 표를 만든 뒤 `ctt.ACTIVITY_COLUMNS`(+source)에 없는 칸을 빈 값으로 채움 | 옛 activity.csv 0건 + 실행기 결과로 TASK·이력 보기 |
| **W4** 11번 셀 `.name` | `os.path.basename(str(video))` | 원문 검사 |
| **W5** 다른 사람 ID로 재시작 | 새 분석 폴더를 만드는 동안의 허용에 '그 폴더까지 이어지는 부모(`analysis/`·`analysis/<사람>/`)'를 넣음. 다른 사람 폴더·공유 폴더는 허용하지 않음 | 분석 폴더가 없는 M7로 재시작, 허용 범위 판정 |

**같이 고친 것:**
- 분석 폴더 이름과 요청 ID의 시각을 한국 시각으로 (Colab 서버 시계는 UTC).
- 0번 셀의 `BASE` 기본값을 비움. 적지 않으면 "BASE를 적으세요"로 멈춤 — 실수로 운영 폴더를 가리키지 않게 (Colab 시험에서 나온 일).

**시험:** `test_cells_433` 79개(+10). 돌연변이 확인: 활성 세션을 바꾸기 전에 앞 세션 끄기, 시각 글자 비교, 빈 칸 채우기 빼기, 부모 허용 빼기 → 각각 실패합니다.

**남은 한계:** 감싸기 함수가 프로세스에 남으므로, 마지막 세션을 닫은 뒤에는 그냥 원래 함수처럼 동작합니다(가드 없음 — 닫은 것이므로 의도). 실행기와 분석 셀이 같은 커널에 있을 때의 경계는 그대로 `exec_scope`입니다.


## b31 반영 (v4.33.0z8)

결과: `docs/REVIEW_RESULT_v4.33.0z7_b31.md`. **반영 확인은 따로 검토하지 않고 b30(2c-6 뒤 노트북 전체)에 합칩니다 (11/17 결정).**

| 발견 | 고친 것 | 시험 |
| --- | --- | --- |
| **X1** 규칙을 읽은 뒤 확인하는 틈 | 가드의 '켜짐' 표시를 없앰. `sys` 상태의 **규칙 묶음** `(쓰기 가드, CVAT 가드, 주인 세션)`을 감싸기가 **한 번만 읽어** 그대로 씀(`_policy()`·`_set_policy()`). 앞 세션의 가드 객체는 규칙에서 빠진 뒤에도 같은 규칙으로 검사하므로, 바뀌기 직전에 읽은 감싸기도 검사 없이 지나가지 않음. `start`는 묶음을 한 번 대입해 바꾸고 앞 세션을 끄지 않음(앞 세션의 `close`는 자기가 주인일 때만 규칙을 비움) | 규칙을 읽은 직후 세션이 바뀐 순서(쓰기·CVAT), 바뀐 뒤 앞 세션 닫기 |
| **X2** 다른 판 커널 | 가드 세대 `GUARD_GEN = 2`. 활성 세션이 다른 세대(0z6·0z7)면 아무것도 바꾸지 않고 "런타임을 다시 시작하세요"로 멈춤 — 갈아타기를 지원하지 않고 막음 | 다른 세대 세션이 남은 상태에서 시작 → 거절, 상태 그대로 |
| **X3** 부모 폴더 링크 | 시작할 때 `analysis/`와 `analysis/<사람>/`이 링크이거나 실제 경로가 다르면 거절. 만든 뒤에도 실제 위치 확인 | `analysis/M8` → `CVAT_UpLoader` 링크 → 거절, 그쪽에 아무것도 안 생김 |
| **X4** Python 3.10의 Z | `_when`이 끝의 `Z`를 `+00:00`으로 바꿔 읽음 | Z 시각 비교. (이 환경은 3.14라 돌연변이로는 잡히지 않음 — 3.10에서만 드러나는 차이) |
| 동시 시작 | 시작끼리 잠금(`sys` 상태의 RLock) | 두 스레드 동시 시작 → 둘 다 성공 |

**시험:** `test_cells_433` 84개(+5). 돌연변이 확인: 앞 가드는 검사 안 함, 세대 확인 빼기, 링크 확인 빼기, 잠금 빼기 → 각각 실패.


## 2c-3 바꾸는 셀 → 미리 보기·요청 (v4.33.0z9)

**새 셀 원문 14개** (`cells_v4.33/`): 1·5·6·9·10·13·14·15·16·17·23·28·29·33번. 모두 맨 위에 `[v4.33 바꾸는 셀]` 표시가 있습니다.
- 셀은 CVAT·공유 폴더를 직접 바꾸지 않습니다. 설정 → **미리 보기**(대상 표·확인할 점) → `SEND = True`일 때만 **요청 파일 하나**.
- params는 2b 처리기가 받는 이름 그대로입니다. 심판 접수까지 시험에서 확인합니다.

| 셀 | 요청 | 미리 보기에서 보이는 것 · params |
| --- | --- | --- |
| 1 학습 | `train` (model·dataset) · 채택 바꾸기 `force_new` | 모델·데이터셋·시험 TASK 설정의 지금 채택 버전. `train_from='current'`·epochs·patience·imgsz·lr0·optimizer, `TRAIN_ARGS`는 처리기 `TRAIN_ARG_KEYS`만(나머지는 빼고 알림). v4.32 FORCE_NEW(폴더 지우기)는 없앰 → `force_new`(채택만 바꿈) |
| 5 track | `track` | TASK별 기존 라벨 처리(uld·AA는 교체 가능, 그 밖은 보류 또는 `TRACK_REPLACE`), 마지막 자동 라벨. `model`·`conf`·`allow_replace`. 이미 v4.33 track이 있으면 뺌(선택) |
| 6 상태·취소 | 신호 `cancel` | 내가 보낸 요청 표(상태·접수·TASK별 결과). v4.33은 track을 만들고 바로 올리므로 '업로드 승인' 셀이 없어짐 |
| 9·10 자동 라벨 | `shape` | 9번이 대상·기존 라벨 처리, 10번이 요청. `model`·`conf`·`allow_replace` |
| 13 백업 | `backup` | 마지막으로 받은 백업. 그 뒤 CVAT에서 바뀌지 않은 TASK는 뺌(선택) |
| 14 export | `export` | 받은 export. 같은 형식이고 바뀌지 않은 TASK는 뺌(선택). `format`·`images` |
| 15 데이터셋 | `dataset` (name) | TASK별 export 유무, 시험 TASK·같은 그루·촬영일(실행기가 뺌), train/val(`VAL_RULE` 또는 `VAL_IDS`). export가 없는 TASK가 섞이면 보내지 않음. 학습은 채택 뒤 1번 셀로 따로 |
| 16·17 만들기 | `create16`·`create17` (name) | 새 이름·원본 경로·프로젝트·라벨. 앞선 만들기가 '확인 필요'였으면 `retry_confirmed` |
| 23 복원 | `restore23` | Drive 버전 기록(읽기)으로 사용자별 기호 A·B… 표. Colab Drive 인증 실행기(30번 셀)가 처리 |
| 28 웹 화면 | `refresh` | web/state.json 요약, 처리 중인 요청 |
| 29 정리 표시 | `cleanup29` | 버전 목록·채택 여부. 지우지 않음(34번 셀이 30일 뒤) |
| 33 시험 TASK | `test_tasks33` | 후보 TASK·그루·촬영일·지금 설정 |

**0번 셀 공통 도우미:** `pick_tasks(ids, query)`(읽기), `send(kind, tasks, params, go=SEND)`(미리 보기 또는 요청), `show_requests()`(내 요청 상태). `cells_base.Session.status(rid)`·`my_requests()`가 요청 파일 이름의 상태·접수·결과를 읽습니다.

**옮기지 않은 것 (뒤 단계):**
- 5·9·10번의 '셀에서 직접 계산해 보기'(분석)와 그 결과 올리기 → 2c-4 '이 결과 올리기'.
- 27번 앙상블 → 2c-4. 33번의 연구 단계(지문·성적·관계·분할안) → 분석 셀로 따로.
- v4.32 셀의 세부 설정(track의 fill_gaps·decoder, 자동 라벨의 타일·화질·병렬)은 실행기 설정(`config/exec.json`)을 씁니다.

**시험:** `test_cells_433` 103개(+19).
- 14개 셀 원문 검사(CVAT 쓰기·공유 기록 쓰기·옛 잠금 함수 없음).
- 셀을 분석 모드에서 실제 실행: `SEND = False`면 요청 파일이 없고, `SEND = True`면 종류·TASK·params가 맞는 요청 하나. 공유 폴더에는 요청·신호 파일 말고 바뀐 것이 없음.
- 만든 요청 13종을 깨끗한 폴더의 심판이 **모두 접수**.
- 돌연변이 확인: SEND 무시, export 건너뛰기 빼기, export 없는 TASK 무시 → 각각 실패.


## 2c-4 '이 결과 올리기' (v4.33.0z10)

**흐름:** 셀에서 직접 계산(분석) → 결과는 내 분석 폴더 → **6번 셀**이 미리 보기 → `SEND = True`면 고정 제출본 + `upload_submission` 요청 → 실행기가 제출본을 받아 다시 확인한 뒤 올림(업로드 전 백업·사람 라벨 보호·이름 규칙은 track과 같은 확정 절차).

| 셀 | 바뀐 것 |
| --- | --- |
| 5 track | `TRACK_LOCAL = True`면 요청 대신 이 Colab에서 `yolo_track_to_cvat.py`로 track을 만들어 봄 → `TRACK_RESULTS` (참조용 export·결과 XML은 분석 폴더 `tasks/<ID>/`). 사진 TASK(ULD 프레임맵)는 2c-5 |
| 10 자동 라벨 | `AA_LOCAL = True`면 요청 대신 `ctt.auto_annotate_frames(collect_only=True)`로 계산(CVAT에 쓰지 않음) → `AA_RESULTS`(`shapes.json`) |
| 27 앙상블 | 분석만. 모델은 `pick_model`(채택 버전·해시 대조). 채택 박스를 `shapes.json`으로 → `EN_RESULTS`. v4.32의 `EN_UPLOAD`(셀이 CVAT에 직접 올림)·`EN_EXISTING`은 없앰 → 6번 셀의 `UP_MODE`('append' = 덧붙임) |
| **6 이 결과 올리기** | `UP_FROM`('track'·'shape'·'ensemble'·'all')·`UP_IDS`·`UP_FILES`(직접 고른 내 분석 파일)·`UP_MODE`·`UP_REPLACE_HUMAN`. 표: 파일·개수·모델·TASK 프레임 수·방식·사람 라벨 처리. 아래에 내 요청 상태·취소(`SEND_CANCEL`) |

**제출본** (`cells_base.Session.submit` → `access.freeze_submission`):
- 위치: `submissions/<내 ID>/<제출ID>/` — 좁은 예외 API(`narrow`)에 `submissions/<내 ID>/`만 더함. 다른 사람 폴더·직접 쓰기는 거절.
- 내 분석 폴더(OUT)나 Colab 로컬의 파일만 낼 수 있음.
- `_submission.json`: 파일(이름·sha256·크기), `task_id`·`server`(CVAT 주소)·`frames`·`labels`(지금 CVAT TASK에서 읽음)·`mode`(replace/append)·`frame_range`·`frame_map_sha`(ULD 전에는 None의 지문)·`format`('CVAT 1.1'·'shapes-json')·`data`·`count`·`model`·`settings`·만든 세션.
- 올리기 요청은 `Session.request_upload` — 내 제출본만, `allow_replace`는 사람 라벨 교체 동의.
- 실행기(2b-3 `h_task._get_submission`)가 `access.verify_submission`으로 해시·TASK·서버·프레임 수·라벨 정의·프레임맵을 다시 확인하고 다르면 올리지 않음.

**시험:** `test_cells_433` 111개(+8).
- 6번 셀: 미리 보기면 제출본·요청 없음 / `SEND`면 제출본과 요청 하나, 제출 정보 칸 확인.
- 제출 뒤 분석 파일을 바꿔도 고정본은 그대로이고 검증 통과. TASK 프레임 수·라벨 정의·TASK 번호가 바뀌면 검증 실패.
- 남의 파일·공유 파일 제출, 모르는 방식, TASK 정보 없음, 남의 제출본 올리기 요청, 제출본 폴더 직접 쓰기 → 거절.
- 셀이 만든 `upload_submission` 요청도 심판이 접수.
- 원문 검사: 27번은 CVAT 쓰기 없음, 자동 라벨 계산은 `collect_only=True`로만.
- 돌연변이 확인: `collect_only` 빼기, 제출본 출처 검사 빼기 → 각각 실패.

**알려진 한계:** 5·10·27번의 실제 계산(YOLO·영상·CVAT 프레임)은 이 시험 환경에서 돌리지 않습니다 — 원문 검사와 2c-6 전 셀 시험, 예행 연습에서 확인합니다.
