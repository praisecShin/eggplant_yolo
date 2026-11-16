# AGENTS.md — 가지 자동 라벨링 (Eggplant) v4.32.0 운영 · v4.33 개발 중

이 저장소에서 일하는 코딩 에이전트(Codex 등)를 위한 안내입니다. **v4.33 검토는 `docs/`의 문서(설계·배포 계획·구현 설명·최근 검토 요청)를 봅니다.** v4.32까지의 점검 항목은 `docs/archived/REVIEW_CHECKLIST_v4.31.8.md`(전체 점검)와 `docs/archived/REVIEW_REQUEST_v4.31.9.md`(1차 수정)·`docs/archived/REVIEW_REQUEST_v4.31.10.md`(R1~R5)·`docs/archived/REVIEW_REQUEST_v4.31.11.md`(R6~R10)·`docs/archived/REVIEW_REQUEST_v4.31.12.md`(R11~R13)·`docs/archived/REVIEW_REQUEST_v4.31.13.md`(R14~R16)·`docs/archived/REVIEW_REQUEST_v4.32.0.md`(2차-1 F3·F14), 설치·변경 내용은 `README_v4.32.0_설치.md`에 있습니다. 앱 이름: **LC앱**(가지 라벨링 관리) · **AA앱**(가지 재처리 — 코드에서는 relabel·재처리로 부름).

## 1. 역할

- 이 저장소에서 당신의 기본 역할은 **검토자**입니다. 요청이 따로 없으면 코드를 고치지 말고 발견한 것만 보고하세요.
- 고치라는 요청을 받은 경우에도 아래 3장의 약속을 바꾸는 수정은 하지 말고, 그런 수정이 필요하면 이유와 함께 보고만 하세요.
- 주석, 출력 문구, 문서는 한국어입니다. 새로 쓰는 보고서도 한국어로 씁니다.

## 2. 저장소 구조

지금 운영 중인 것은 v4.32.0이고, v4.33(경합 통제)은 개발 중입니다. 폴더는 **어느 계정·어디에서 실행되는가**로 나눴습니다.
계정: **A0** 재웅님 Google 계정(공유 폴더 소유·앱·Colab·Kaggle 보조), **K** Kaggle 실행 계정, **G** Apps Script 계정 (설계 '계정 역할').

```
drive/                       Google Drive eggplant_yolo/ 에 올라가는 것
  scripts/*.py               노트북·작업자가 불러 쓰는 부품 (Drive scripts/에 그대로; v4.33부터는 관리자 폴더 deploy/로 배포)
    cvat_task_tools.py (ctt) · web_bridge.py (wb) · relabel_bridge.py (rb) · train_sim.py · yolo_track_to_cvat.py · cvat_backup.py …   v4.32
    arbiter.py · access.py · arb_io.py · arb_master.py · executor.py · worker_cpu.py · master_main.py                                    v4.33
  scripts/notebook_cells.json  작업자가 실행하는 셀 코드 사본 (노트북과 글자까지 같아야 함)
  notebooks/                 계정별 (Drive에는 하위 폴더 없이 notebooks/에 올림)
    A0_colab/   eggplant_yolo_colab_v4.32.0.ipynb        사람이 쓰는 노트북 (0번 셀 먼저 → 필요한 셀). 30번 = 작업자, 33번 = 학습 계획 연구
    A0_kaggle/  eggplant_kaggle_train_v4.31.0.ipynb      A0 Kaggle 학습 (지금은 K의 보조)
    K_kaggle/   eggplant_kaggle_cpu_master_v4.32.0.ipynb · kaggle_cpu_master.py · kernel-metadata-cpu-master.json   CPU 상주 마스터 (v4.32)
                eggplant_kaggle_gpu_worker_v4.32.0.ipynb · kernel-metadata-gpu-worker.json   GPU 작업자 (A0 Kaggle 보조도 같은 노트북)
                master_boot_v4.33.py                     v4.33 마스터 뿌리 노트북의 셀 원본 (dev_tools/build_deploy.py가 노트북으로 만듦)
    KAGGLE.md                                            Kaggle 쓰는 법
apps_script/                 Google Apps Script — 계정·프로젝트별 (프로젝트마다 appsscript.json)
  G_collector/  Collector.gs · Uld.gs     v4.33 수집기 (CVAT 수집·자동 요청·ULD 확장). 웹앱 아님
  G_keeper/     Keeper.gs                 v4.33 Keeper (심판 자격·마스터 깨우기·감시·메일·푸시). 웹앱 아님
  K_legacy_v4.32/ Code.gs                 지금 운영 중인 수집기+배정기 (전환 때 끔). 운영 프로젝트에는 Uld.gs도 같이 있음 (G_collector/Uld.gs와 같은 파일)
apps/                        claude.ai에 게시하는 앱 (A0)
  ctrl/index.html            CTRL앱 (시스템 감시·제어) — LC앱·AA앱은 아직 이 저장소에 없음
dev_tools/                   개발 기계에서만 쓰는 도구 (Drive에 올리지 않음)
  setup.sh                   시험 환경 준비 (rclone·Node.js)
  build_deploy.py            v4.33 배포 묶음 만들기 (배포 목록·뿌리 노트북 고정 해시·Keeper용 해시)
docs/                        지금 검토에 쓰는 설계·계획·구현 설명·검토 요청 — 지난 것은 docs/archived/
tests/                       가짜 Drive·가짜 CVAT·가짜 Kaggle 시험
```

v4.32 통신은 Google Drive의 파일(요청 `requests/REQ_<id>__<kind>__<status>.json`, 배정 `requests/assign/`, 상태 `web/state.json`·`relabel/state.json`)입니다. v4.33은 여기에 심판의 판정 파일(`arb/`)과 신호(`jobs/signals/`)를 더합니다 (`docs/DESIGN_v4.33.md`).

## 3. 반드시 지켜야 할 약속 (리뷰의 최우선 기준)

위반은 심각도 '치명' 또는 '높음'으로 보고합니다.

1. **비밀 값:** CVAT 토큰·비밀번호·`RCLONE_CONF`·`KAGGLE_KEY`는 Colab·Kaggle 보안 비밀(Apps Script는 Script Properties)에서만 읽습니다. 도구가 설정 파일을 요구하는 경우(rclone, kaggle 명령)에만 **세션 임시 폴더의 본인 전용 파일(권한 0600)**에 둘 수 있습니다(v4.31.9 확정 · v4.31.10: Kaggle에서는 환경 변수를 먼저 읽지 않고, 파일은 `os.open(..., 0o600)`으로 처음부터 만들어 `RCLONE_CONFIG`·`KAGGLE_CONFIG_DIR`로 연결 — 홈 폴더 `~/.config/rclone`·`~/.kaggle`에 쓰지 않음). 코드, 출력, 로그, Drive 파일, 저장소, 요청·상태 파일, 예외 메시지에 남으면 안 됩니다. 보안 비밀이 없을 때 직접 입력받는 것은 Colab에서 사람이 셀을 직접 실행할 때만 허용하고, Kaggle·작업자 실행에서는 멈춰야 합니다. Apps Script에는 `doGet`/`doPost`(웹앱 배포)가 없어야 합니다.
2. **올리기 전 백업:** 라벨을 CVAT에 올리는 모든 경로는 먼저 그 TASK의 라벨을 export해 둡니다.
3. **사람 라벨 보호:** 기존 라벨이 있는 TASK는 명시적 설정(`ALLOW_REPLACE`, `TRACK_UPLOAD_REPLACE`, `AA_EXISTING='replace'`) 없이 덮어쓰지 않습니다. 예외는 이름이 `_uld` 또는 `_AA`(`_AA_rN`)로 끝나는 TASK이며, 이때도 백업한 뒤 교체합니다.
4. **이름:** 앱이 기존 TASK 이름을 바꾸는 경우는 라벨을 올린 뒤 `…_uld` → `…_uld_AA` 하나뿐입니다. 예외: 백업으로 **새로 복원한** TASK에 붙이는 이름 꼬리표(16번 셀 `RS_SUFFIX`, 기본 `_test`)는 허용합니다(v4.31.9 확정).
5. **CVAT_UpLoader는 읽기 전용:** 그 폴더에 쓰지 않습니다. Kaggle에서 받은 clip은 작업 폴더 밖 임시 폴더에 두고, Colab에서는 Drive의 원본 clip을 지우지 않습니다.
6. **TASK를 지우지 않습니다.**
7. **거짓 완료 금지:** 처리하지 않은 요청을 '완료'로 표시하지 않습니다. 한 요청은 한 작업자만 처리하고, 배정(`requests/assign`)을 따릅니다. 같은 TASK의 요청은 보낸 차례대로 하나씩 처리합니다.
8. **고정 시험 TASK:** `config/test_tasks.json`의 TASK와 같은 그루·촬영일 TASK는 학습·val에서 빠져야 합니다(15번 셀 `USE_TEST_SET`).
9. **공유 파일은 쓰는 사람이 하나 (v4.32.0):**
   - 상태 파일(`web/state.json`·`relabel/state.json`·`relabel/tracked.json`·`web/label_stats.json`·`web/corrections.json`)은 취합자(`jobs/STATE_OWNER.json` 임대를 가진 작업자)만 씁니다. 순위는 CPU 마스터 3 > 30번 셀 2이고, GPU 워커(0)는 맡지 않습니다. 취합자가 아니면 `jobs/DIRTY_<세션>.json`만 남깁니다. 숨기기·다시 보이기·새로 고침 요청도 취합자만 처리합니다.
   - 요청 파일은 받은 세션만 씁니다. 받은 뒤 다시 읽어 확인하고, 상태를 쓰기 직전에 Drive의 요청이 아직 이 세션 것인지 확인합니다(`wb.request_owned`). '받는 중' 요청은 받은 세션이 꺼졌을 때만 넘겨받고(`wb.may_adopt`), 넘겨받았다는 기록을 남깁니다.
   - TASK 기록(`relabel/tasks/<id>.json`)은 최신본을 받아 고친 뒤 그 파일만 올립니다(`rb.sync_record`). `relabel/**`·`relabel/tasks` 폴더를 통째로 올리지 않습니다.
   - 남은 틈: 다시 읽기와 쓰기 사이 몇 초는 Drive에 '비교 후 쓰기'가 없어 남습니다. 이 틈 자체는 보고하지 않아도 됩니다. `backup_status.csv`·작업보드는 세션별 백업 색인에서 다시 만들어지는 파생 파일이라, 백업을 실행한 작업자가 씁니다.

상태 이름 묶음(의도된 동작): `vf` = vf·vf_r1·vf_r2, `vfdf` = vf_r2df, `vfdf_ok` = vf_r2df_ok, `AA` = AA·AA_rN, `_test` = 상태 없는 기본 계열.

## 4. 실행·시험 방법

필요한 것: Python 3.10 이상, `numpy`, `Pillow`, `rclone`(test_master 계열), Node.js(js 시험). **준비: `bash dev_tools/setup.sh`** (sudo 없이 사용자 폴더에 설치). **실제 CVAT·Google Drive·Kaggle에는 접속하지 마세요.** 토큰은 없고, 모든 시험은 가짜 환경으로 돕니다.

```bash
pip install numpy pillow pyflakes          # rclone은 OS 패키지로 (apt install rclone 등)

# 저장소 맨 위에서
python3 tests/test_arbiter_433.py drive    # v4.33: 심판 판정 함수 (1a)
python3 tests/test_access_433.py drive     # v4.33: 접근 통제·배포 검증 도구 (1a)
python3 tests/test_master_433.py drive     # v4.33: 저장소·마스터 루프·실행기 뼈대 (1b)
python3 tests/test_master_main_433.py drive   # v4.33: 배포 묶음·뿌리 노트북·마스터 본체 (2a)
python3 tests/test_fuzz_433.py drive         # v4.33: 무작위 입력 시험 — 어떤 입력에도 판정 회차가 예외 없이 끝나는지 (약 15초)
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # v4.33: 수집기 (배정·깨우기를 뺀 Code.gs) + Uld.gs — Keeper 시험보다 먼저 (생존 기록 산출물을 남김)
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs   # v4.33: Keeper
node tests/test_ctrl_app.js apps/ctrl/index.html   # v4.33: CTRL앱 (jsdom 필요: npm i jsdom)
python3 tests/test_fix_4320.py drive       # v4.32.0: 취합자 임대·요청 소유 확인·받는 중 넘겨받기·TASK 기록 줄·마스터 받기 확인
python3 tests/test_fix_43113.py drive      # v4.31.13: TASK 기록은 sync_task_record로만 — 받기 실패 시 쓰지 않음(R14)·상태 갱신/AA 작업이 통째로 올리지 않음(R15)
python3 tests/test_fix_43112.py drive      # v4.31.12: TASK 기록 통째 올리기 없앰(R11)·실패만 남은 track 마무리(R12)·시험 노트북 고르기(R13)
python3 tests/test_fix_43111.py drive      # v4.31.11: GPU 워커 생존·쓰기 직전 재확인(R6)·누적 최종 상태(R7)·CVAT_TOKEN 없으면 멈춤(R8)·실패 track 깨움(R9)·경로 없는 최신(R10)
python3 tests/test_fix_43110.py drive      # v4.31.10: 백업 판정 공용(R1)·보안 비밀 파일(R2)·0번 셀 이름 겹침(R3)·마스터 받는 중 백업(R4)·13번 0건 멈춤(R5)
python3 tests/test_fix_4319.py drive       # v4.31.9 1차 수정: 진행 중 요청 소유·깨진 배정·ULD 교체 연결·백업 판정
python3 tests/test_sim.py drive            # 학습 계획 연구·고정 시험 TASK·사라진 TASK·ULD 교체 연결
python3 tests/test_worker30.py drive       # 30번 셀 통합 작업자: 공정 차례·GPU 줄·두 앱 요청
python3 tests/test_worker_gpu.py drive     # GPU 워커(W_ROLE='gpu'): kaggle_gpu 배정만·학습·스스로 종료
python3 tests/test_uld.py drive            # ULD 사진 TASK·이름 규칙
python3 tests/test_state_uld.py drive      # 앱 상태의 ULD 표시·Drive 목록 기반 모델 목록
MASTER_TEST_SEC=90 python3 tests/test_master.py drive   # CPU 마스터 순환 (rclone 필요 · 기본 40초, 느린 환경은 90)
python3 tests/test_master_gpu.py drive     # CPU 마스터가 GPU 워커를 올리는지 (가짜 kaggle 명령)
python3 tests/test_master_stop.py drive    # CPU 마스터 정지 표시
node tests/test_auto.js apps_script/K_legacy_v4.32/Code.gs
node tests/test_dispatch.js apps_script/K_legacy_v4.32/Code.gs
```

- 각 시험은 `✅`/`❌` 줄과 마지막 `RESULT True`(또는 `통과`)를 출력합니다. 지금은 모두 통과합니다.
- 시험은 `tests/_work*` 폴더를 만들고 지웁니다. 저장소의 다른 파일은 바꾸지 않습니다.
- 노트북 셀은 IPython 전용 줄(`!`, `%`)을 빼면 일반 파이썬입니다. 정적 점검 예:
  ```bash
  python3 -m pyflakes drive/scripts/*.py drive/notebooks/K_kaggle/kaggle_cpu_master.py
  ```
  셀 코드는 0번 셀(공통 설정·함수)이 먼저 실행된다고 가정하므로, 셀 단독으로 '정의되지 않은 이름'이 나오면 0번 셀에 있는지 먼저 확인하세요.
- 노트북을 셀 단위로 실행하지 마세요. 0번 셀은 Google Drive를 붙이거나 rclone으로 Drive에 접속하려고 합니다.

## 5. 리뷰 기준

우선순위 순입니다.

1. 3장의 약속 위반
2. 요청이 처리되지 않거나, 두 번 처리되거나, 잘못된 결과를 '완료'로 남기는 경로 (특히 30번 셀의 스레드·주 스레드 동시 실행, 작업자 여럿이 Drive 파일을 함께 쓰는 경우)
3. 데이터 손실: Drive 파일 덮어쓰기, 세션별 기록(shard) 합치기, 옛 이름 요청 파일이 되살아나는 경우
4. 해결해 온 이슈의 재발 (`docs/archived/REVIEW_CHECKLIST_v4.31.8.md` 4장, `docs/archived/REVIEW_REQUEST_v4.31.9.md`, `docs/archived/REVIEW_REQUEST_v4.31.10.md`, `docs/archived/REVIEW_REQUEST_v4.31.11.md`, `docs/archived/REVIEW_REQUEST_v4.31.12.md`, `docs/archived/REVIEW_REQUEST_v4.31.13.md`, `docs/archived/REVIEW_REQUEST_v4.32.0.md`)
5. v4.31.8~9 새 코드의 정확성 (`train_sim.py`, 33번 셀, 15번 셀의 시험 TASK 제외, 사라진 TASK, ULD 교체 연결)
6. 일관성: `notebook_cells.json` ↔ 노트북 셀, GPU 워커 노트북 ↔ Colab 노트북(`W_ROLE` 한 줄만 다름), 버전 문자열 4.32.0 (`Code.gs`는 바뀌지 않아 `COLLECTOR_VERSION` 4.31.9 그대로)

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
