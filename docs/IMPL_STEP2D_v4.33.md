# v4.33 구현 2d·2e(CTRL앱) — 수집기 나누기와 CTRL앱 (v4.33.0j, 0k에서 b17·0l에서 b18 반영)

배포 계획 5절의 2d와 2e 중 CTRL앱입니다. 0j(b16 반영·보호 모드)도 같은 판에 들어 있습니다 (`IMPL_STEP2A_v4.33.md`의 'b16 반영').

## 2d: 수집기 `apps_script/G_collector/Collector.gs` (G 계정 '수집기' 프로젝트)

지금 운영 중인 `Code.gs`(4.31.9)에서 수집 부분만 떼어 냈습니다. `Code.gs`는 운영용이라 고치지 않았습니다.

| 바뀐 것 | 내용 |
| --- | --- |
| 뺀 것 | `dispatch`·`dispatch_`(배정), 마스터 깨우기·정지·재개(`wakeUpCpuMaster_`·`wakeCpuMasterNow`·`stopCpuMasterNow`·`resumeCpuMasterNow`), 야간 승인(`approveNightRequests`), GPU 대기열·`STOP_GPU`, `dispatcher.json`, GitHub(`triggerGhDispatch_`), `installAllTriggers`. 배정은 심판이, 깨우기·감시는 Keeper가 함 |
| 자동 요청 규칙 (11/12 결정, 11/15 넣음) | **backup:** TASK가 `_uld`로 올라올 때. 원본이 이미 있으면 하지 않음 — videos/에 영상, ULD 기록(`registry/tasks/<ID>.json`), ULD 장부(`clips_registry.csv`) 중 하나라도 있으면. **export:** 이름이 검토 단계(vf·vf_r1·vf_r2·vfdf·vfdf_ok·vf_r2df·vf_r2df_ok)로 바뀔 때마다(vf → vfdf도 다시). **_AA 감지 요청은 그만둠.** 같은 TASK·같은 수정 시각은 다시 요청하지 않음. 끄기: `routing.json`의 `auto_requests`·`auto_backup_uld`·`auto_export_vf` |
| 자동 요청 범위 | `AUTO_PROJECT_ID` 프로젝트의 TASK만 (비우면 자동 요청 없음). `AUTO_NAME_PREFIX`가 있으면 그 글자로 시작하는 TASK만 (예행 연습 `REH_`). 수집 범위(`CVAT_PROJECT_ID`)와 따로 — Uld.gs의 중복 찾기는 조직 전체 수집을 기대하므로 수집은 비워 둘 수 있음 |
| 자동 요청 형식 | 심판이 읽는 형식: `tasks`(TASK 번호 문자열 목록) + 옛 `task_ids`. 파일 소유 계정이 G라서 심판은 `system:G`로 접수 (종류는 backup·export 등만, `AUTO_KINDS`). 이미 있던 검토 단계 TASK는 `backfillVfNow()` |
| ULD 기록 | Uld.gs와 같은 속성 `ULD_ROOT_FOLDER_ID`로 `CVAT_UpLoader`를 찾음 (G 계정의 내 드라이브에는 없음). 없으면 예전처럼 내 드라이브 최상위 |
| `Uld.gs` | 같은 프로젝트에 함께 넣음. 없으면 그 단계를 건너뜀 (`typeof uldAfterCollect_`) |
| 쓰는 곳 | `status/`와 `requests/`(자동 요청), 그리고 Uld.gs가 `CVAT_UpLoader/registry/sources.json`(ULD앱 원본 목록). CVAT에는 읽기(GET)만 |

시험: `tests/test_collector.js` 35개. 가짜 Drive·CVAT에서 `collect()`를 실제로 여러 번 돌립니다. 실제 `Uld.gs`도 함께 불러 돌립니다.

**`Uld.gs` (11/15 받음, `apps_script/G_collector/Uld.gs` — 고치지 않음):**
- 배정·깨우기 함수를 부르지 않습니다.
- 쓰는 수집기 함수가 `Collector.gs`에 모두 있습니다: `api_`, `readJson_`, `writeJson_`, `readCsv_`, `readRouting_`, `getSub_`, `parseName_`, `stateLabel_`, `countBy_`, `cfg_`, `statusDir_`, `CFG`.
- G 계정에서는 `GoPro_RAW`를 이름으로 찾지 못하므로 `ULD_SOURCE_FOLDER_ID`를 넣어야 합니다.
- 맨 위 주석의 'Code.gs의 함수'는 이제 'Collector.gs의 함수'입니다. 동작에는 영향이 없어 고치지 않았습니다.

## 2e: CTRL앱 `apps/ctrl/index.html` (A0에서 게시, claude.ai 아티팩트 '가지 CTRL')

Google Drive 커넥터(`search_files`·`download_file_content`·`create_file`)를 씁니다. 기존 '가지 시스템 프로세스 관찰 대시보드'와 같은 방식이고, 파일은 A0 계정으로 만들어집니다.

| 화면 | 내용 |
| --- | --- |
| 폴더 선택 | 운영(`eggplant_yolo`) / 시험(`eggplant_yolo_test`). 시험이면 위쪽에 시험 띠 |
| 보호 모드 띠 | `ARBITER.json`의 `protect`가 있으면 빨간 띠: 경로·이유·관리자 복구 절차 |
| 상태 판 | 판정 루프(회차 기록 나이·자격과 같은 세션인지), 마스터(생존 신호, GPU 상태 모름, 사람 목록 거절 이유, 작업 프로세스 재시작 그만둠), 실행기, 수집기, Keeper |
| 제어 | 보내는 사람(people.json). 마스터 깨우기(`wake`). 심판이 살아 있거나 보류가 있으면 막힘. 정지(`release`, 기한: 해제할 때까지 / 다음 08:00). 보류별 해제. 관리자의 '보류 해제하고 깨우기'(보류가 하나일 때, `release_stop`). 보호 모드 중에는 정지·해제를 막음 (처리되지 않으므로) |
| 보낸 신호 처리 결과 | 최근 7일 신호와 결과. 깨우기는 `jobs/wake_done/`, 그 밖은 `arb/signal_done/` (Keeper 확인 전 / 처리 중 / 거절·실패 사유 / 해제 게시됨) |
| 점검 | 읽지 못한 것, 확인 필요, 실행기 기다림, 옛 방식 요청, 깨우기 요약, 재시작 점검 |
| 관리 일·학습 | 실행 잠금 상태(확인 필요·멈춤 보고) |
| 알림 | 최근 하루 `arb/alerts/` |

시험: `tests/test_ctrl_app.js` 13개 (jsdom + 가짜 커넥터).
- 보호 모드 띠, 상태 판
- 깨우기·정지 막힘 조건
- 신호 파일 이름·내용(`wake__M1__…`·`release_stop`·`stop_id`·`until`)
- 처리 결과, 시험 폴더

**아직 하지 않은 것:**
- 관리 일 대기열과 '확인 필요' 선택 화면(`run_choice`·`confirm_choice`·`adopt_choice`): LC·AA앱과 함께 합니다.
- 실제 Drive에서의 확인: 예행 연습 때 합니다.

## b17 반영 (0k)

`docs/REVIEW_RESULT_v4.33.0j_b17.md`의 X1~X6과 '검토 질문별 보충'의 알림 두 가지를 고쳤습니다.

| 번호 | 고친 곳 | 고친 내용 | 시험 |
| --- | --- | --- | --- |
| X1 | `drive/scripts/arbiter.py` `View._check_plans` | 끝나지 않은 신호 계획을 신호와 맞춰 봄: `sid`·종류·대상, 효과 목록(신호에서 다시 계산한 것과 순서까지 같아야 함). 다르면 보호 모드. 끝난 계획(`signal_done` 있음)과 신호를 모르거나 형태가 틀린 경우는 보지 않음(어차피 진행되지 않음) | `test_arbiter_433` b17 회귀 9개 (일부 삭제·중복·바꿔치기·순서·sid·종류·대상, 정상 이어 하기, 새 배정 없음). `test_fuzz_433`: 효과는 구현을 빌리지 않은 독립 정답으로 판정, 목록 원소 빼기·중복·바꿔치기·뒤집기 변형 추가, 끝나지 않은 계획을 따로 골라 퍼징, '보류 없이 정지 완료' 뜻 검사, 고정 시험 |
| X2 | `apps/ctrl/index.html` | 읽기 세대(`S.gen`)와 다 읽은 환경(`S.loadedEnv`). 환경을 바꾸면 전송 대상·사람·대화상자를 버리고, 새 환경을 다 읽을 때까지 제어를 막음. 늦게 끝난 옛 읽기는 버림. 보낼 때 환경·폴더가 대화상자를 연 때와 같은지 다시 확인 | `test_ctrl_app` 7개 |
| X3 | `apps_script/G_collector/Collector.gs` | 보낼 목록 `status/auto_pending.json`. 사건은 스냅숏보다 먼저 목록에 넣고(못 넣으면 실행 실패, 스냅숏 그대로), 요청 ID를 정해 목록에 저장한 뒤 요청 파일 → 장부 → 목록에서 빼기. 중간에 멈추면 같은 요청 ID로 이어 하고, 요청 파일이 이미 있으면(상태가 바뀐 이름 포함) 다시 만들지 않음. `backfillVfNow`도 같은 길 | `test_collector` 9개 (만들기 실패, 장부 실패, 이름 바뀐 요청, 목록 저장 실패) |
| X4 | `apps_script/G_keeper/Keeper.gs` | 정상→보호 전환은 새 사건으로 알림. 끝날 때 그 구간의 진입 기록을 지움. 수집기 멈춤·깨우기 기록 모름·보류 모름 알림도 상태가 풀리면 이력에서 지워 다시 생기면 다시 알림 | `test_keeper` (keeper() 세 번: 진입·끝남·재진입) |
| X5 | `Collector.gs` `writeHeartbeat_`, `Keeper.gs` `kpCollectorAt_` | 수집기가 맨 위에 `time`·`ok`도 씀. Keeper는 맨 위 `time`, 없으면 `last.time`을 읽음 | `test_collector`가 남긴 실제 산출물을 `test_keeper`가 읽음 (수집기 시험을 먼저 돌릴 때), 둘 다 없으면 null |
| X6 | `apps/ctrl/index.html` | 보류 목록 읽기 실패·보류 파일 하나라도 못 읽음 → '읽지 못함'(없음과 구분), 깨우기·해제를 막고 못 읽은 파일을 오류 띠에 표시 | `test_ctrl_app` 4개 |
| 보충 | `Keeper.gs` `kpSendOutbox_` | 보내지 못한 메일·푸시를 `keeper.json`의 `outbox`에 남겨 다시 보냄(30번까지). 주제 이름·메일 주소는 남기지 않음. `keeper.json`을 못 읽으면 상태·심판 알림은 다시 보내지 않고 그 사실만 알림(보호 모드는 안전 쪽으로 한 번 더) | `test_keeper` 3개 |

판 번호: 심판 `4.33.0k`, 수집기 `4.33.0k`, Keeper `4.33.0k`.

## b18 반영 (0l)

`docs/REVIEW_RESULT_v4.33.0k_b18.md`의 Y1~Y6과 보충 두 가지(수집기가 계속 실패할 때의 멈춤 알림, CTRL앱의 같은 이름 폴더)를 고쳤습니다. Y3는 11/16 결정(같은 TASK 사건은 합쳐 최종 상태 export)대로입니다.

| 번호 | 고친 곳 | 고친 내용 | 시험 |
| --- | --- | --- | --- |
| Y1 | `arbiter.py` `process_signals`·`_check_plans` | 관리자 권한은 계획의 `admin`을 쓰지 않고 지금 신호 소유자의 권한으로 매번 정함. 계획의 요청자가 신호 소유자에서 다시 계산한 사람과 다르면 보호 모드 | `test_arbiter_433` 6개 (admin만 바뀜, 요청자 바뀜, admin 형태, 관리자에서 내려감, 정상 관리자). `test_fuzz_433`: 끝나지 않은 계획의 admin·requester를 바꿔도 보호 모드이거나 효과가 원래와 같은지 (구현과 따로 비교) |
| Y2 | `Collector.gs` `pendingProblem_`·`readPending_` | 보낼 목록의 형태 검사: 맨 위·`events`·`batches`가 객체 지도, 사건 칸과 키 일치, 묶음이 가리키는 사건. 틀리면 던짐 → 수집 실패, 스냅숏 그대로 | `test_collector` 10개 (배열·칸 없음·키 불일치·없는 사건, 고친 뒤 회복) |
| Y3 | `Collector.gs` `flushAutoRequests_`·`latestPerTask_` | 같은 TASK·같은 종류 사건은 최신 하나로 합쳐 요청에 한 번만. 아직 만들기를 시도하지 않은 묶음이 있으면 새 사건을 거기에 합침. 장부에 `merged` | `test_collector` 2개 |
| Y4 | `Collector.gs`, `arbiter.py` | 만들기 전 `attempt_at`, 만든 뒤 `file_id`를 보낼 목록에 저장. ID가 있으면 만든 것으로 봄. ID 없이 시도만 있으면 검색, 못 찾아도 10분 기다림. 심판은 같은 요청 ID 파일 여럿을 하나로 접수하고 `duplicate_request` 알림 | `test_collector` 4개 (검색 지연 모형), `test_arbiter_433` 1개 |
| Y5 | `apps/ctrl/index.html` `allowed` | 버튼·대화상자 열기·보내기를 한 판단 함수로. 새로 읽은 뒤 열린 대화상자의 동작이 더는 허용되지 않으면 닫음. 보내기 직전에 다시 계산. 읽기에 실패하면 다시 읽힐 때까지 제어를 막음 | `test_ctrl_app` 6개 |
| Y6 | `Keeper.gs` `kpSendOutbox_` | 상한 50, 보호 모드 알림은 상한·횟수와 상관없이 남김. 버린 일반 알림은 '보냄' 이력에서 지우고 요약 메일 | `test_keeper` 4개 |
| 보충 | `Keeper.gs` `kpCollectorAt_` | 수집기 멈춤 판단을 마지막 성공 시각(`last_ok`)으로 — 실행할 때마다 실패해도 20분 뒤 알림 | `test_keeper` 2개 |
| 보충 | `apps/ctrl/index.html` `findTop` | 최상위 폴더를 매번 찾음(저장한 ID를 쓰지 않음). 같은 이름 폴더가 여럿이면 읽기 실패로 보고 제어를 막음 | `test_ctrl_app` 2개 |

판 번호: 심판·수집기·Keeper `4.33.0l`.

남은 한계(검토에서 지적, 이번에 고치지 않음):
- Keeper가 메일·푸시를 보낸 직후 `keeper.json` 저장 전에 멈추면 같은 알림이 한 번 더 갈 수 있습니다. 전송과 기록을 한꺼번에 묶을 방법은 없습니다.
- 수집기는 요청 파일을 만드는 호출의 응답이 끊기면(파일은 생김) 파일 ID를 모릅니다. 이때는 검색과 10분 기다림에 기대고, 그래도 생긴 중복은 심판이 하나로 접수합니다.
