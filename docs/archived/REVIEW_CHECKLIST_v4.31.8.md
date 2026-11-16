# 가지 자동 라벨링 v4.31.8 — 독립 코드 점검 요청서

이 문서는 이 코드를 쓰지 않은 검토자(Codex 등)에게 주는 점검 요청서입니다. 같은 폴더의 `README_v4.31.8_설치.md`와 함께 읽으세요.

## 검토자에게

- **할 일:** 아래 5~7장의 점검 항목을 코드에서 확인하고, 8장의 형식으로 결과를 적습니다.
- **하지 말 것:** 코드를 고치지 마세요. 발견한 것만 보고합니다. 고칠지는 이 앱의 작성자가 판정합니다.
- **실행:** `tests/`의 시험은 가짜 Drive·가짜 CVAT로 돌아갑니다(`python3 tests/<파일> drive`, js는 `node tests/<파일> apps_script/Code.gs`). 실제 CVAT·Drive·Kaggle에는 접속하지 마세요. 토큰도 없습니다.
- **의도된 동작과 버그를 구분하세요.** 3장의 '약속'은 의도된 동작입니다. 약속과 다르게 동작하는 코드를 찾는 것이 가장 가치 있는 발견입니다.
- 주석과 출력 문구는 한국어입니다. 문구의 어색함은 점검 대상이 아닙니다.

## 1. 앱의 목적

온실(G1~G6)에서 찍은 가지 영상에서 열매와 꽃봉오리를 건강·병해로 나눠 **세는 것**이 최종 목표입니다. 이 앱은 그 목표를 위한 라벨링과 학습의 순환을 돌립니다.

1. 영상(또는 영상에서 자른 사진)을 CVAT TASK로 올립니다. 올리는 일은 별도 앱(ULD, `CVAT_UpLoader/`)이 하고, 이 앱은 그 기록을 읽기만 합니다.
2. 학습한 YOLO 모델이 초안 라벨을 만들어 CVAT에 올립니다(shape 또는 track).
3. 사람이 CVAT에서 검토하고 고칩니다.
4. 검토가 끝난 라벨을 export해서 모델을 다시 학습합니다.
5. 고정 시험 TASK로 새 모델과 기존 모델을 비교합니다.

## 2. 구성과 실행 관계

| 구성 | 위치 | 역할 |
|---|---|---|
| Colab·Kaggle 노트북 | `drive/notebooks/eggplant_yolo_colab_v4.31.8.ipynb` | 사람이 실행. 0번 셀(공통 설정·함수)을 먼저 실행한 뒤 필요한 셀을 실행 |
| scripts | `drive/scripts/*.py` (13개) | 노트북이 불러 쓰는 부품. `cvat_task_tools.py`(ctt), `web_bridge.py`(wb, LC앱 요청·상태), `relabel_bridge.py`(rb, 재처리 앱 요청·상태), `yolo_track_to_cvat.py`, `cvat_backup.py`, `cvat_to_yolo.py`, `train_sim.py` 등 |
| 셀 코드 사본 | `drive/scripts/notebook_cells.json` | 작업자(30번 셀)가 꺼내 실행하는 5·9·10·13·14·15·28·29·32번 셀 코드. 노트북의 같은 셀과 글자까지 같아야 함 |
| 작업자 | 노트북 30번 셀 | 두 웹앱의 요청 파일을 받아 처리. `W_ROLE = 'all'`(사람이 켬) 또는 `'gpu'`(Kaggle GPU 워커) |
| Kaggle CPU 마스터 | `drive/notebooks/kaggle_cpu_master.py` (+ 같은 내용의 ipynb) | GPU 없이 상주. 백업·export 처리. `kaggle_gpu` 배정 요청이 있으면 GPU 워커 노트북을 Kaggle API로 시작 |
| Kaggle GPU 워커 | `drive/notebooks/eggplant_kaggle_gpu_worker_v4.31.8.ipynb` | 0번 셀 + 30번 셀(`W_ROLE='gpu'`). 할 일이 5분 없으면 스스로 끝남 |
| Apps Script | `apps_script/Code.gs` | CVAT TASK 목록 수집(`collect`), 요청 배정(`dispatch` → `requests/assign/ASSIGN_<id>.json`), `_AA`가 된 TASK의 자동 export·백업 요청 |
| 웹앱 2개 | 이 묶음에 없음 (claude.ai 아티팩트) | LC앱 '가지 라벨링 관리', 재처리 앱 '가지 재처리'. Drive에 요청 파일을 쓰고 상태 파일을 읽음 |

**통신은 모두 Google Drive의 파일입니다.**
- LC앱 요청: `requests/REQ_<id>__<kind>__<status>.json`. 재처리 앱 요청: `relabel/requests/` 아래 같은 형식. 상태가 바뀌면 파일 이름이 바뀝니다.
- 상태: `web/state.json`(LC앱), `relabel/state.json`(재처리 앱).
- 작업자 생존 신호: `web/worker.json`, `relabel/WORKER.json`. GPU 워커는 `web/worker_gpu.json`, `relabel/WORKER_gpu.json`. CPU 마스터는 `*_cpu_master.json`.
- Colab은 Drive를 직접 붙여 쓰고, Kaggle은 rclone으로 받고 올립니다(0번 셀의 `drive_pull`, `drive_push`, 셀 실행 전후 자동 동기화).

## 3. 지켜야 할 약속 (위반을 찾으면 가장 중요한 발견)

**보안**
- P1. PAT·비밀번호·`RCLONE_CONF`·`KAGGLE_KEY`는 Colab·Kaggle 보안 비밀에서만 읽습니다. 코드, 노트북 출력, Drive 파일, 로그, 요청·상태 파일, 예외 메시지에 값이 남으면 안 됩니다.
- P2. Kaggle 보안 비밀을 데이터셋이나 다른 노트북으로 넘기지 않습니다.
- P3. Apps Script의 CVAT 토큰은 Script Properties에만 둡니다. 웹앱으로 배포하지 않습니다(`doGet`·`doPost`가 없어야 함).

**데이터 보호**
- P4. 라벨을 CVAT에 올리기 전에 반드시 그 TASK의 라벨을 백업(export)합니다.
- P5. 사람이 라벨링한 TASK에는 명시적 설정(`ALLOW_REPLACE`, `TRACK_UPLOAD_REPLACE`, `AA_EXISTING='replace'`) 없이 덮어쓰지 않습니다. 예외는 이름이 `_uld` 또는 `_AA`(`_AA_rN` 포함)로 끝나는 TASK로, 백업한 뒤 교체합니다.
- P6. `CVAT_UpLoader/` 폴더에는 아무것도 쓰지 않습니다. 읽기만 합니다. Kaggle에서 받은 clip은 작업 폴더 밖 임시 폴더에 두고, Drive `eggplant_yolo/`로 올라가면 안 됩니다. Colab에서는 Drive의 원본 clip을 지우면 안 됩니다.
- P7. 이 앱은 CVAT TASK를 지우지 않습니다.

**이름 규칙**
- P8. 앱이 TASK 이름을 바꾸는 경우는 하나뿐입니다. 라벨을 올린 뒤 `…_uld` → `…_uld_AA`. `_AA`·`_vf` 등 다른 이름은 그대로 둡니다.
- P9. 상태 묶음: `vf` = vf·vf_r1·vf_r2, `vfdf` = vf_r2df, `vfdf_ok` = vf_r2df_ok, `AA` = AA·AA_rN. `_test`는 상태 없는 기본 TASK 계열. 검토 완료 판정은 0번 셀 `REVIEWED_RULE`(기본 'vf').

**요청 처리**
- P10. 한 요청은 한 작업자만 처리합니다. 처리하지 않은 요청을 '완료'로 표시하면 안 됩니다(거짓 완료 금지).
- P11. 배정(`requests/assign`)을 따릅니다. GPU 워커는 배정 파일이 있고 `kaggle_gpu`로 배정된 요청만 받습니다. CPU 마스터는 `kaggle_cpu`로 배정된 백업·export만 받습니다.
- P12. 같은 TASK의 요청은 보낸 차례대로 하나씩 처리합니다.
- P13. 고정 시험 TASK(`config/test_tasks.json`)와 같은 그루·촬영일 TASK는 15번 셀이 학습·val에서 뺍니다(`USE_TEST_SET = True`일 때).

## 4. 해결해 온 이슈 (다시 생기지 않았는지 확인)

| # | 이슈 | 고친 판 | 확인할 곳 |
|---|---|---|---|
| I1 | CPU 마스터가 `rclone sync`로 다른 작업자가 쓴 새 요청·배정 파일을 지움 | 4.31.4 | `kaggle_cpu_master.py`에 요청 폴더 대상 `sync`가 없어야 함. `pull_requests`, `push_req` |
| I2 | 처리하지 않는 종류의 요청을 받아 '완료'로 표시 | 4.31.4, 4.31.7 | CPU 마스터 `CPU_DIRECT_KINDS`·`AA_DIRECT_KINDS` 밖의 종류. 예전 GPU 워커 스크립트(`kaggle_gpu_worker.py`)가 묶음에 없어야 함 |
| I3 | 같은 이름의 TASK 둘을 한 요청으로 export하면 같은 zip 경로로 실패 | 4.31.4 | `_zip_names`, 14번 셀 |
| I4 | 시간대 없는 시각(KST)을 UTC로 읽어 '오래됨' 판정이 틀림 | 4.31.4 | `wb.age_hours`, `wb.fair_order`의 `created` 비교 |
| I5 | 작업자가 시작할 때 다른 세션이 진행 중인 요청을 되돌림 | 4.31.4 | 30번 셀의 '멈춘 요청을 다시 대기로' 두 곳(재처리·LC) |
| I6 | 모델마다 아는 라벨이 달라 비교 기준 박스 수가 달라짐 | 4.31.4 | 32번 셀 `CMP_LABELS` 공통 라벨 |
| I7 | Kaggle rclone 설정 파싱 실패(JSON 안의 `[ ]`를 섹션으로 읽음) | 4.31.5 | 0번 셀 `_kg_fix_conf` |
| I8 | 사진 TASK(ULD가 영상에서 자른 것)에 track을 못 만듦 | 4.31.5 | `yolo_track_to_cvat.py --frame-map`, 5번 셀·30번 셀의 `_fm` 경로, `uld_mismatch` |
| I9 | 9번 셀이 10번 셀의 설정 `AA_FRAMES`를 먼저 읽어 새 세션에서 NameError | 4.31.7 | 9번 셀, `notebook_cells.json`의 '9' |
| I10 | 5번 셀 자동 업로드가 왜 안 됐는지 출력이 없음 · 뒤 스레드 오류가 안 보임 | 4.31.6 | 5번 셀 끝부분 |
| I11 | Kaggle 0번 셀이 모든 모델의 best.pt를 받아 느림 | 4.31.6 | 0번 셀 `KAGGLE_PULL_ALL_BEST`, `need_file`. best.pt를 쓰는 모든 곳이 필요할 때 받는지 |

## 5. 작성자가 불안하게 보는 곳 (우선 점검)

**A. 30번 셀의 동시 실행** (`drive/notebooks/…colab_v4.31.8.ipynb`의 `# 30.` 셀)
- A1. 재처리 요청은 뒤 스레드(`_w_aa_loop` → `_rl_dispatch` → 스레드 풀)에서, LC 요청은 주 스레드에서 `get_ipython().run_cell`로 실행합니다. 두 쪽이 전역 변수를 함께 씁니다. LC 셀(특히 15번 학습, 5번, 9·10번)이 `NAME`, `BEST`, `RUN_DIR`, `CLIENT`, `CVAT_SCOPE`, `IMGSZ`, `TRACK_*`, `AA_*` 같은 전역 변수를 바꾸면 그 순간 돌고 있는 재처리 스레드가 잘못된 값을 읽을 수 있는지 확인하세요.
- A2. 0번 셀 `use_cvat`, `req_use`의 `_SCOPE_TMP`(요청의 조직으로 잠깐 바꿈)가 재처리 스레드의 CVAT 호출 범위에 영향을 주는지.
- A3. 15번 셀이 요청으로 학습을 끝낸 뒤 `NAME`·`BEST`가 새 모델로 바뀐 채 남으면, 뒤에 오는 LC track·자동 라벨 요청이 의도와 다른 모델을 쓰는지.
- A4. GPU 줄 계산: `_W['lc_gpu']`, `_w_wait_gpu`, `_rl_dispatch`의 `gpu_free`. 학습이 모든 줄을 맡는 동안 재처리 GPU 일이 새로 시작되지 않는지, 예외가 나도 `lc_gpu`가 0으로 돌아오는지, `_rl_track_resume`(백업을 받은 뒤 track 마저 만들기)도 이 제한을 따르는지.
- A5. 공정 차례: `wb.fair_order`, `_w_served`, `W_USER_MAX`. 한 사람의 요청만 있을 때 막히지 않는지, `by`가 없는 요청, 요청자 이름에 괄호가 있는 경우.
- A6. 멈출 때(`finally`): `KeyboardInterrupt`가 여러 번 와도 진행 중인 요청이 'taken'으로 남아 영영 처리되지 않는 일이 없는지. `_aa_th.join(timeout=120)` 뒤에도 스레드가 살아 있을 때의 동작.
- A7. GPU 워커 종료 조건(`W_EXIT_IDLE_MIN`): '받는 중'(waiting) 백업을 기다리는 track 요청이 있는데 워커가 끝나 버리는지. 끝나기 직전에 들어온 요청은 어떻게 되는지.
- A8. `_lc_do`가 실패 처리할 요청 id를 고르는 조건. 다른 세션이 진행 중인 요청을 '실패'로 바꾸지 않는지.

**B. Kaggle 파일 동기화**
- B1. `drive_pull`/`drive_push`는 `--update`(더 새 것만)로 복사합니다. 작업자 둘(Colab 30번 셀과 GPU 워커, 또는 CPU 마스터)이 같은 파일(`relabel/tracked.json`, `relabel/state.json`, `task_registry.csv`, `logs/`)을 쓸 때 한쪽의 변경이 사라지는 경로가 있는지.
- B2. GPU 워커는 `relabel/**`를 통째로 올리는 곳이 있습니다(`_rl_push('relabel/**')`). 워커가 받아 온 뒤에 다른 작업자가 바꾼 요청 파일을 옛 내용으로 덮어쓰는지, 이름이 바뀐 요청의 옛 이름 파일이 되살아나는지.
- B3. 세션별 기록(shard): `ctt.shard_path`, `read_sharded`, `compact_shards`. 합치는 도중에 다른 세션이 쓰면 줄이 사라지는지.

**C. CPU 마스터가 GPU 워커를 시작하는 부분** (`start_gpu_worker_if_needed`, `gpu_pending`)
- C1. `kaggle kernels push`가 실패했을 때 10분 대기(`gpu_start_t`)에 걸려 재시도가 늦어지는지, 성공했지만 워커가 바로 실패한 경우는.
- C2. 가장 새 워커 노트북을 고르는 정렬(버전 숫자). 파일이 없을 때.
- C3. `KAGGLE_KEY`가 출력·로그·임시 파일에 남는지. 임시 폴더에 올리는 파일에 비밀이 섞이지 않는지.
- C4. 워커가 이미 돌고 있는지 확인하는 `is_gpu_kernel_running`의 문자열 판정.

**D. v4.31.8에서 새로 쓴 코드**
- D1. `scripts/train_sim.py`: `evaluate`의 짝짓기(같은 라벨 IoU ≥ 0.5, 탐욕), `count_mae`·`count_rel`·`count_bias` 정의가 주석과 맞는지. `relation`의 능형 회귀·부트스트랩(표준화, `in_train` 처리, TASK 수가 적을 때). `simulate`의 덮임 기준과 `pred_recall` 계산에서 `rel["keys"]`와 `REL_KEYS`의 순서가 맞는지. 0으로 나누기, 빈 입력.
- D2. `image_stats`: 박스 좌표 스케일, 박스가 화면 전체를 덮을 때, 바닥 영역이 모두 박스 안일 때(`fl &= …` 줄의 연산 순서).
- D3. 33번 셀: `_sim_models`, 이미 한 TASK를 건너뛰는 조건, `in_train` 값(학습 대장의 역할 문자열)과 `relation`이 읽는 값의 일치. 시험 TASK를 저장할 때 후보가 0개인 경우.
- D4. `ctt.read_test_tasks`/`write_test_tasks`/`test_conflict`/`test_key`: 날짜 8자리와 6자리, 규칙 밖 이름, 이름이 없는 id.
- D5. 15번 셀의 시험 TASK 제외 블록이 `VAL_IDS`로 고정한 val, `EXP_IDS`, 데이터 서명(`sig`) 계산과 어긋나지 않는지. 시험 TASK 목록이 바뀌면 같은 이름의 예전 데이터셋을 다시 쓰는 문제가 생기는지.
- D6. 사라진 TASK: `wb.gone_tasks`, `wb.build_state`의 gone 블록, `rb.update_tracked`의 gone 처리. `update_tracked`는 잠금(`_locked`, RLock) 안에서 `add_history`를 부릅니다. 수집기 파일이 없거나 깨졌을 때.
- D7. ULD 교체 연결: 0번 셀 `uld_index`의 `lineage`(처음 이름에서 `_AA` 꼬리를 떼고 묶음). 서로 다른 구간인데 이름이 같은 TASK를 잘못 묶을 가능성. `created_at` 형식이 섞일 때의 정렬.
- D8. `uld_video`와 5번·30번 셀의 `_uvid` 경로: ULD 영상 TASK에서 디코더를 pyav, 프레임 오프셋을 0으로 고정하는 것이 맞는지. clip을 지우는 `uld_clip_done`이 Colab에서 원본을 지우지 않는지(P6).
- D9. 13번 셀 `BK_SKIP_ULD`: 요청으로 실행할 때와 직접 실행할 때의 분기.

**E. 일관성**
- E1. `notebook_cells.json`의 각 셀 코드가 노트북의 같은 번호 셀과 글자까지 같은지. GPU 워커 노트북의 0번·30번 셀이 Colab 노트북의 것과 `W_ROLE` 한 줄만 다른지.
- E2. 버전 문자열이 모두 4.31.8인지(0번 셀 `APP_VERSION`, 각 py의 `__version__`, `notebook_cells.json`). `Code.gs`의 `COLLECTOR_VERSION`은 4.31.5가 맞습니다(이번에 안 바뀜).
- E3. 30번 셀이 실행하는 셀들이 0번 셀과 30번 셀에 없는 이름을 쓰는지(다른 셀을 먼저 실행해야만 생기는 전역 변수).
- E4. `LC_SET`으로 셀 설정을 바꾸는 정규식(`_lc_src`)이 여러 줄 설정이나 같은 이름이 두 번 나오는 셀에서 엉뚱한 줄을 바꾸는지.

## 6. 약속별 점검 (3장을 코드에서 확인)

- P1~P3: 저장소 전체에서 토큰·비밀번호·`RCLONE_CONF`·`KAGGLE_KEY` 값이 `print`, 로그 파일, json 쓰기, 예외 문자열, subprocess 인자 출력으로 새는 경로. `cvat_backup.py`가 받는 `CREDENTIALS`의 수명.
- P4·P5: 라벨을 올리는 모든 경로를 찾아(5번 `_upload_one`, 6번, 10번, 27번, 30번 `_rl_shape_one`·`_rl_upload_one`, `ctt.import_tracks`, `ctt.auto_annotate_frames`) 각각 올리기 전에 백업이 있고, 기존 라벨이 있을 때 조건이 P5와 같은지. `auto_task()`의 판정.
- P6: `ULD_DIR`, `uld_pull`, `uld_clip`, `uld_clip_done`, `uld_images`. `CVAT_UpLoader`를 대상으로 하는 rclone 명령이 `copy`(받기)뿐인지.
- P7: `tasks.remove`, `DELETE /api/tasks` 같은 호출이 없는지(16·17번 복원 셀 포함).
- P8: `task.update({'name': …})`를 부르는 모든 곳과 `ctt.aa_name_after_upload`.
- P9: `ctt.parse_task_name`, `_split_state`, `state_group`, `match_name`, `is_reviewed`, `rb.is_target`, `Code.gs`의 이름 파싱이 서로 같은 판정을 하는지.
- P10~P12: `wb.take`, `wb.set_status`, `wb._assigned_to_me`, 30번 셀 `_w_mine`, CPU 마스터 `mine`·`claim`·`still_pending`. 두 작업자가 거의 동시에 같은 요청을 받는 창이 얼마나 되는지.
- P13: D5와 같음.

## 7. 실제 환경에서만 확인할 수 있는 것 (검토자는 하지 않음, 참고용)

가짜 시험으로는 확인하지 못한 경로입니다. 코드를 읽다가 이 경로에서 실패할 만한 것이 보이면 알려 주세요.

1. CPU 마스터가 API로 GPU 워커의 새 버전을 올릴 때 워커에 붙여 둔 Kaggle 보안 비밀이 유지되는지.
2. GPU 워커에서 0번 셀 → 30번 셀이 사람 없이 끝까지 도는지(입력 대기, Colab 전용 코드).
3. 학습 요청: 30번 셀이 15번 셀을 실행해 학습을 끝내고 요청을 '완료'로 바꾸는지.
4. 33번 셀 전체(CVAT에서 프레임 받기, 모델 탐지).
5. 5번 셀·30번 셀의 ULD 사진 TASK·영상 TASK 경로.
6. 두 웹앱이 새 상태 파일의 칸(`uld`, `gone_at`, `replaced_by`, `replaces`, `img: "uld"`, 단계 'CVAT에서 사라짐')을 읽는 것.

## 8. 보고 형식

발견마다 아래 칸을 채워 주세요. 심각도 순으로 정렬합니다.

| 칸 | 내용 |
|---|---|
| 번호 | F1, F2 … |
| 심각도 | 치명(데이터 손실·비밀 노출·거짓 완료) / 높음(요청이 처리되지 않거나 잘못된 결과) / 보통 / 낮음 |
| 관련 항목 | 이 문서의 항목 번호(P4, A1, D5 등) 또는 '새 발견' |
| 위치 | 파일, 함수 또는 셀 번호, 줄 |
| 무엇이 문제인가 | 한두 문장 |
| 일어나는 조건 | 어떤 입력·순서에서 일어나는지. 재현 방법이 있으면 함께 |
| 확신 | 확인함(코드로 추적했거나 실행해 봄) / 추정 |
| 제안 | 고치는 방향(코드는 쓰지 않아도 됨) |

마지막에 두 가지를 덧붙여 주세요.
- 점검했지만 문제가 없던 항목의 번호 목록.
- 시간이 모자라 보지 못한 항목의 번호 목록.
