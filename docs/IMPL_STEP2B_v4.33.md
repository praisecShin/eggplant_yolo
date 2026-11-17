# v4.33 구현 2b — 처리기 옮기기

계획과 순서는 `docs/IMPL_CHECKLIST_v4.33.md`의 '2b 작업 계획'에 있습니다. 단계마다 이 문서에 무엇을 바꿨는지 적습니다.

## 2b-1 기반 (v4.33.0q)

| 고친 곳 | 내용 | 시험 (`tests/test_handlers_433.py`) |
| --- | --- | --- |
| `drive/scripts/handlers.py` (새로) | 처리기 등록부 `register`·`Dispatch`·`NoHandler`. CPU 작업 프로세스·GPU 작업자·Colab 30번 셀이 함께 씀. 옛 요청 종류 대응표 `LEGACY_KIND`(2f용) | 등록부 5개 |
| `handlers.CvatOps`·`ScopedCvat` | 처리기가 쓰는 CVAT 동작 묶음(실제 구현은 2b-2·2b-3에서 `cvat_task_tools`·`cvat_backup`을 감쌈). 시험 실행은 지정 프로젝트의 `REH_` TASK에만, 운영 실행은 `REH_`에 쓰지 않음, TASK 정보를 못 읽으면 쓰지 않음 | 시험 범위 7개 |
| `handlers.publish_version`·`verify_version`·`check_files` | **필수:** 산출물을 올린 뒤 다시 받아 해시·크기 확인 → 모두 맞을 때만 `_files.json`(`verified`). 목록 쓰기 바로 앞에서 권한 재확인. 버전 밖 경로 거절 | 게시·검증 6개 |
| `arb_io.py` `put_file`·`get_file` | 큰 파일 올리기·받기 (폴더 저장소, rclone `copyto` — 시간 한도 1시간) | 게시 시험 |
| `executor.py` `busy`·`_working`·`_progress`, `Ctx.progress` | **필수:** 처리기가 일하는 동안 생존 신호에 단계·요청·TASK·진행 시각·메모 | 진행 2개 |
| `arbiter.py` `STALL_SEC`·`View.stalled`, 형태 표 `busy` | **필수:** 진행 시각이 한도를 넘게 멈추면 끊긴 것으로(`alive` 거짓, `hb_lost_at` = 진행 시각 + 한도) → 기존 격리·확인 필요 경로. `worker_stalled` 알림 | 멈춤 4개 (확정 중 TASK → 격리·쓰기 막힘·권한 잃음 보고, 진행을 알리면 멈춤 아님, 관리 일 → 확인 필요) |
| `worker_cpu.py` | 등록부를 `handlers`로 옮김 (옛 이름 `HANDLERS`·`register`·`Dispatch`·`NoHandler` 유지) | 기존 시험 |
| `tests/fake_cvat.py` (새로) | 가짜 CVAT: TASK·라벨, 백업/export 준비 작업(여러 번 물어야 끝남), 가져오기 작업 번호·실패·멈춤, 호출 기록 | — |

판 번호: 심판 `4.33.0q`.

## 2b-2 받는 중 일 — 백업·export (v4.33.0r)

v4.32의 `run_cpu_backup_and_export`·`run_cpu_export`·`poll_waiting_backups`(CPU 마스터)와 30번 셀 `_rl_backup`·`_rl_bk_poll`을 '준비 요청·상태 확인'(`fetch`)과 '받기·게시'(`publish`)로 나눴습니다.

| 고친 곳 | 내용 | 시험 (`tests/test_handlers_433.py`) |
| --- | --- | --- |
| `drive/scripts/h_read.py` (새로) | **fetch:** TASK 정보 읽기 → 서버 준비 요청 → 받는 중 기록 `backups|exports/pending/<요청>__<TASK>.json`(요청 시각의 CVAT 라벨 버전 `task_updated`, J1·G9). 다음 차례부터는 같은 작업 번호의 상태만 물음. 실행기가 바뀌어도 다시 요청하지 않음<br>**publish:** 게시 잠금 아래 받기 → `backups|exports/<요청>/<TASK 이름>__<TASK>.zip`에 올림 → 다시 받아 해시·크기 확인 → 기록을 '받음'으로(해시·크기). 다르면 실패 | 백업 5개, export 3개, 실행기 바뀜 1개, 서버 준비 실패·TASK 없음·올린 파일 다름·취소 4개 |
| `drive/scripts/cvat_ops.py` (새로) `RealCvat` | 실제 CVAT 어댑터. 백업은 `cvat_backup`(request·check·fetch), export는 `cvat_task_tools`(request_export·export_status·download_result)를 그대로 부름. 작업 번호 앞에 `bk:`·`ex:`. 처음 쓸 때 접속, 토큰은 넘겨받기만 함 | 가짜 모듈로 바꿔 끼운 어댑터 시험 3개 |
| `handlers.py` `Env`·`load_all`·`HANDLER_MODULES` | 처리기 환경(저장소·범위가 걸린 CVAT·세션 임시 폴더 0700·시계). `Dispatch(env=…)`가 `ctx.env`로 넘김 | — |
| `arbiter.py` 형태 표·`make_intake` | 요청의 `params`(객체)를 접수 기록에 실어 처리기까지 (Codex b17 보충: 앱·수집기 설정값 전달) | export 형식 전달 2개 |
| `arb_io` | 2b-1의 `put_file`·`get_file` 사용 | — |

v4.32에서 바뀐 점:
- 백업 뒤 검토 TASK의 export를 이어 붙이던 동작은 없앴습니다. 수집기가 검토 단계로 바뀔 때 export 요청을 따로 만듭니다(11/12 결정).
- 백업 현황판(`backup_status.csv`)과 export 목록 요약은 취합 일(2b-4)이 받는 중 기록에서 만듭니다.
- 이미 받은 최신 export를 복사해 다시 쓰던 최적화(`best_export`)는 아직 옮기지 않았습니다. 언제나 서버에 준비를 요청합니다. 필요하면 2b-4 뒤에 넣습니다.

판 번호: 심판 `4.33.0r`.

## 2b-3 TASK 쓰기 — track·shape·auto·제출본 (v4.33.0s)

v4.32의 30번 셀 `_rl_track_one`·`_rl_shape_one`·`_rl_upload_one`과 5·6·10번 셀을 실행기의 두 단계로 나눴습니다. **11/17 결정: track 요청은 한 단계입니다.** 만들고 바로 올리며, 확인 대기 화면은 없습니다. auto는 shape와 같은 처리기입니다.

**준비(`prepare`)** — 로컬에서 끝까지 하고, CVAT에 쓰지 않습니다.
- TASK 정보를 읽고 시험 범위를 미리 확인합니다. 범위 밖이면 무거운 계산 전에 멈춥니다.
- track은 참고 라벨을 받아 track을 만듭니다.
- shape·auto는 프레임 탐지만 합니다(`auto_annotate_frames`에 `collect_only=True` 추가).
- 제출본은 받아서 해시와 TASK 일치를 검사합니다(`access.verify_submission`).

**확정(`commit`)** — 심판의 확정 승인 뒤:
1. TASK의 프레임 수·라벨 정의가 준비 때와 같은지 봅니다. 다르면 `TaskChanged`로 멈추고 '확인 필요'가 됩니다.
2. **업로드 전 백업:** 지금 라벨을 받아 복구 자료(`recovery/<TASK>/<작업번호>/before_upload.zip`, 다시 받아 해시 확인)와 `result_plan.json`으로 게시합니다. 받지 못하면 쓰지 않습니다.
3. **사람 라벨 보호:** 기존 라벨이 있고 이름이 uld·AA가 아니면, 요청의 `params.allow_replace`가 정확히 `true`일 때만 씁니다. 아니면 결과는 `held:human_labels`(보류)이고 아무것도 쓰지 않습니다.
4. **쓰기:** 쓸 때마다 권한을 확인합니다. 교체면 지운 뒤 가져오고, 가져오기 작업이 끝날 때까지 진행을 알리며 기다립니다.
   - 실패하면 백업으로 되돌리고, 결과는 `failed:…(restored)`입니다.
   - 권한을 잃었거나 가져오기가 끝났는지 모르면(시간 초과) 되돌리지 않고 멈춤 보고를 합니다. 심판은 '확인 필요'로 처리합니다.
5. **결과 확인:** 올린 뒤 라벨 수가 기대보다 적으면 `ResultMismatch`로 '확인 필요'가 됩니다.
6. **이름:** `…_uld` → `…_uld_AA`만 바꿉니다(권한 확인 뒤).
7. **AA TASK를 교체했을 때:** 이전 라벨을 `exports/_aa_replaced/<이름>__<TASK>__<요청>.zip`에 보관합니다.

| 고친 곳 | 내용 |
| --- | --- |
| `drive/scripts/h_task.py` (새로) | 위 처리기, 그리고 실제 계산 `RealEngine`(track은 `yolo_track_to_cvat.py`를 v4.32와 같은 인자로 실행하고 줄마다 진행을 알림, shape는 `auto_annotate_frames(collect_only)`). 모델·영상 찾기는 실행 호스트가 넘겨줌(2b-6) |
| `cvat_ops.RealCvat` | 쓰기 추가: 가져오기(`task.import_annotations` — 끝나면 `sync:` 작업 번호), shape 목록 올리기(500개씩), 지우기, 이름 바꾸기 |
| `cvat_task_tools.auto_annotate_frames` | `collect_only=True`: 쓰지 않고 탐지 결과만 돌려줌 (기존 호출은 그대로) |
| `handlers.ScopedCvat.check_write` | 준비 단계에서 쓰기 범위를 미리 확인 |

시험(`tests/test_handlers_433.py`, 2b-3 18개):
- track: 바로 올림·이름 규칙, 백업 선행, 복구 자료 게시, 계산은 준비 단계
- 교체
- 사람 라벨 보호: 보류, 명시 동의일 때만, 문자열 'yes'는 동의 아님
- 가져오기 실패 → 되돌림
- 가져오기 끝났는지 모름 → 되돌리지 않고 확인 필요
- 쓰는 도중 권한 잃음 → 다음 쓰기·되돌리기 없음
- 시험 범위
- TASK 바뀜
- 업로드 전 백업 실패
- shape·auto(AA 교체 보관)
- 제출본: 정상, 프레임 수 다름

사람 라벨 보호와 백업 선행은 그 줄을 일부러 빼고 돌려 보아 시험이 실제로 잡는 것을 확인했습니다.

v4.32에서 바뀐 점:
- track 확인 대기(`track_pending`·폰 미리보기 그림)는 없어졌습니다(11/17 결정).
- AA 교체 때 원본 영상이 없으면 백업 요청을 만들던 동작은 옮기지 않았습니다. 수집기가 `_uld`로 올라올 때 백업을 요청합니다(11/12 결정).
- TASK 이력·대장(`task_registry.csv`·`rb.add_history`)은 복구 자료의 `result_plan.json`과 결과 기록으로 대신합니다. 요약은 취합 일(2b-4)이 만듭니다.
- 요청의 최종 상태: 보류(`held:human_labels`)인 TASK가 있어도 요청은 '완료'입니다. 앱은 TASK별 결과로 보류를 보입니다(2e).

판 번호: 심판 `4.33.0s`.

### b23 반영 (v4.33.0t)

| 지적 | 고친 곳 |
| --- | --- |
| S1 | 대상 이름은 밑줄까지 맞는 꼬리만(`_uld`·`_AA`·`_AA_rN`) — `humanAA`·`xuld`는 사람 라벨. 태그만 있는 TASK도 라벨이 있는 것으로 셈 |
| S2 | 가져오기 오류는 둘로 나눔: 서버가 분명히 거절(`ImportRejected`, 4xx·형식) → 되돌림, 응답을 잃음·시간 초과·모르는 상태 → 되돌리지 않고 멈춤 보고('확인 필요') |
| S3 | 쓰기마다 권한 확인: 지우기·가져오기·되돌리기 지우기·되돌리기 가져오기 각각 `w.call`, 가져오기 함수 안의 묶음 쓰기도 `before_each`로 매번 확인 |
| S4 | 확인을 마친 버전(`_files.json` 있음)에는 다시 게시하지 않음 — 새 실행 번호로 (11/17 결정 '바꾸지 않음') |
| S5 | `RealEngine.track_args`가 `yolo_track_to_cvat.py` 인자 해석을 통과(`--near` 정수, `--box-source detection`), 설정으로 기본값 덮기 |
| S6 | 받기 형식 `CVAT for video 1.1`, 가져오기 형식 `CVAT 1.1`(v4.32 `IMPORT_FORMAT`)로 나눔. 어댑터·시험 CVAT 모두 다른 형식은 거절 |
| S7 | `ScopedCvat`는 읽기 허용 목록만 넘김 — `client`·`session` 등 원래 연결은 내주지 않음 |
| 보충 | 큰 전송(받기·올리기·가져오기) 동안 `ticking`으로 60초마다 진행 알림 → 멈춤 한도(30분)에 걸리지 않음 |

시험: test_handlers_433 73개(0s 60개 + 13개). 새 시험은 0s 코드에서 실패함을 확인.

## 2b-4 취합 일 — hide·unhide·refresh (v4.33.0u)

`h_agg.py` — 한 단계(`run`). 취합 잠금 하나를 받은 실행이 읽기 사본으로 계산하고 자기 상태 파일만 게시합니다.

| 일 | 하는 것 |
| --- | --- |
| hide · unhide | 최신 `relabel/tracked.json`을 받아 숨김 표시를 고쳐 게시. 대상이 아닌 TASK만 적은 요청은 '실패' |
| refresh | CVAT 목록(보이는 모든 조직) → tracked 갱신(옛 `update_tracked` 규칙을 순수 함수로, 대상 판정은 h_task의 밑줄 규칙) → `relabel/state.json`(TASK 이력 요약·열린 요청) → `web/pending_status.json`(요청·TASK별 받는 중 기록 요약, J1) |

규칙:
- 게시 파일마다 `_pub = {epoch, gen, run, rid, at}`. 이미 더 높은 (epoch, gen)이 있으면 쓰지 않고 멈춤 보고. 쓰기마다 권한 확인(`auth('publish').call`), 잃으면 게시 없이 멈춤 보고
- 지금 파일을 읽지 못하면(객체 아님) 덮어쓰지 않고 실패
- CVAT 목록이 한도(5000)에 닿으면 보이지 않은 TASK를 '사라짐'으로 보지 않음. '사라짐'은 tracked에 표시만 — TASK 이력은 그 TASK 권한 경로가 씀
- 받는 중 기록 파일·TASK 기록 파일은 읽기만
- 시험 실행은 `test/` 아래에만 게시, 목록도 정해진 프로젝트의 `REH_` TASK만 (`ScopedCvat.list_tasks`)
- 요청 최종 상태: 실행기 `_finalize`가 TASK를 적은 취합 요청(숨김)도 실행 결과로 끝냄 (`TASKLESS_KINDS`)
- 옛 읽는 쪽 `relabel_bridge.load_tracked`는 `_`로 시작하는 키를 TASK로 보지 않음

남은 것 (2b-6에서 실행 호스트와 함께): `web/state.json`·`label_stats`·`corrections`·`snapshots`(옛 `wb.build_state` 전체 — 로그 샤드·영상·백업 목록이 필요), relabel 상태의 모델 목록·영상/ULD 출처 계산(지금은 이전 상태에서 이어 받음), TASK 기록을 하나씩 읽는 대신 한 번에 받기.

시험: test_handlers_433 87개(+14). 돌연변이 확인 — 마무리의 TASKLESS 조건과 (epoch, gen) 비교를 빼면 해당 시험이 실패.

## 2b-5a 관리 일 — 데이터셋·시험 TASK·초기화·정리·청소 (v4.33.0v)

`h_mgmt.py` — 한 단계(`run`). 관리 잠금 하나를 받은 실행. 쓰기마다 권한 확인, 잃으면 멈춤 보고.

| 종류 | 하는 것 | 보고 |
| --- | --- | --- |
| dataset | 요청 TASK마다 가장 나중에 받은 export(J1 기록, `params.export_rid`로 고정 가능) → 받은 파일 해시를 기록과 대조 → 채택된 시험 TASK와 같은 TASK·같은 그루·촬영일은 뺌 → 만들기 엔진(`env.builder`) → `datasets/<이름>/v/<실행ID>/`에 `dataset.zip`·`dataset.json`(출처·뺀 것·설정) → `_files.json`(`task_keys`·`tasks`) | `done_run` → 심판 채택 |
| test_tasks33 | TASK 이름을 CVAT에서 읽어 그루·촬영일 키 → `sets/test_tasks/v/<실행ID>/`(`ids`·`keys`) | `done_run` → 채택, 모델 오염 대조 |
| force_new | 확인된 버전(또는 빈 시작)으로 채택 바꾸기만 | `done_job` + `current_change` |
| cleanup29 | 채택 안 된 버전에 '정리 대상' 표시만 → `arb/mgmt/<실행ID>/marks.json`. 채택됨·진행 중 참조·채택 대기·`legacy`는 건너뜀 | `done_job` |
| cleanup34 | 미리 보기(`plan.json`) 늘. `params.apply = true`일 때만 지움 | `done_job` |

청소가 지우는 것: 끝난 정리 실행이 표시한 지 30일 지난 채택 안 된 버전(목록 먼저, 그다음 파일) · 끝난 요청 30일(복구가 참조하는 원요청 제외) · 완료 기록이 있는 신호 7일 · 완료 기록과 계획은 신호가 없어진 뒤 30일(계획 먼저) · 확정 신청·생존 신호 7일. 판단 재료(채택 표시·잠금·표시 파일)를 하나라도 못 읽으면 계획을 만들지 않음. 못 지운 것은 계정별로 `report.json`.

저장소: `delete(path)` 추가 (rclone `deletefile` — Drive 휴지통). 청소 관리 일만 씀.

실패는 `failed:<이유>`로 보고 (export 없음·export 바뀜·시험 설정 확인 안 됨·모두 빠짐·확인 안 되는 버전·TASK 이름 못 읽음 등) — 거짓 완료 없음.

데이터셋 출처 키를 모르는 TASK(이름 규칙 밖)가 하나라도 있으면 `task_keys`를 적지 않음 → 학습 시작 때 '호환 확인 불가'(b7).

남은 것: 23번 복원·끝난 확정의 `recovery/` 30일 청소·복구 일(2b-5b), 실제 만들기 엔진(`RealBuilder`)의 영상·원본 이미지 준비와 ULD 사진 TASK(2b-6 실행 호스트), 옛 15번의 검토 규칙(REVIEWED_RULE)·검색어 고르기는 요청을 만드는 쪽(LC앱·셀)에서 TASK 목록으로 넘김.

시험: test_handlers_433 105개(+18). 돌연변이 확인 — 같은 그루·촬영일 빼기, 30일 기간, 채택 보호, export 해시 대조를 빼면 각각 실패.

## 2b-5b 복구 일·학습·새 TASK 만들기·23번 복원 (v4.33.0w)

`h_run.py`.

| 종류 | 줄 | 하는 것 |
| --- | --- | --- |
| recovery | TASK (prepare·commit) | '확인 필요'에서 ② 되돌리기(`revert`)·③ 다시 하기(`redo`). 원래 확정의 `recovery/<TASK>/<origin_job>/`를 씀. revert: 업로드 전 백업을 기록된 해시와 대조 → 같은 확정 절차(업로드 전 백업·복구 자료·쓰기마다 권한 확인·분명한 실패만 되돌림)로 교체 → 라벨 수가 원래와 정확히 같아야 끝 → 원래 이름. redo: 복구 자료의 원요청 종류·설정으로 다시 계산 → 같은 확정 절차. 원래 사람 라벨 교체 동의는 이어받음 |
| train | 학습 (run) | 학습 잠금의 고정값만: 시작 데이터셋 버전(목록 해시 대조해 받음), `train_from='current'`면 시작 때 채택된 모델 best.pt(해시 대조), 아니면 기본 모델. 에폭마다 진행 알림·권한 확인(잃으면 멈춤, 게시 없음). `runs/<모델>/v/<실행ID>/` best.pt·results.csv·args.yaml·train.json, `_files.json`에 `train_keys`(데이터셋 출처 키) → `done_run` → 심판 채택/채택 대기. 학습 설정은 정해 둔 항목만 |
| create17 | 만들기 (run) | 의도 기록(`recovery/create/<요청>/<실행>/intent.json`: 이름·원본 해시·프로젝트·decision) → 빈 TASK 먼저 → 번호 기록 → 영상 올리기 |
| create16 | 만들기 (run) | 의도 기록 → 백업 복원(한 번 호출) → 번호 기록 → 이름·프로젝트 맞춤 |
| restore23 | 관리 일 (run, Colab) | Drive 버전 기록(`env.revisions`)에서 고른 사용자(이메일 또는 A·B…)의 마지막 파일 → `runs/<이름>_<A|B>/v/<실행ID>/` + `RESTORED_FROM.json` → 채택 바꾸기 보고. 원본 이름은 그대로 |

만들기 규칙: 응답을 잃으면 다시 만들지 않고 의도에 '모름'을 남기고 멈춤 보고('확인 필요'). 같은 요청의 앞선 의도가 끝나지 않았으면 새 실행이어도 시작하지 않음 — 사람이 CVAT를 보고 `params.retry_confirmed = true`로. 원본은 `videos/`·`backups/` 안만. 시험 실행은 `REH_` 이름·정해진 프로젝트로만(만든 TASK는 그 묶음 안에서 이름·프로젝트 맞춤 허용).

함께 고친 것:
- **작업 번호 겹침 (중요):** TASK 작업 번호가 `<실행기>-<TASK>-<묶음>`이라 같은 실행기가 같은 TASK의 다른 요청을 받으면 번호가 같아져 앞 확정의 복구 자료(`recovery/<TASK>/<작업번호>/`)를 덮어썼음. 배정 키의 해시를 붙여 요청마다 다르게 함. 복구 일 시험에서 발견.
- 복구 자료 `result_plan.json`에 업로드 전 백업의 해시·크기와 원요청 설정을 기록 (되돌리기·다시 하기가 씀).
- 복구 요청 intake에 `origin_job`을 실음 (심판 스키마에 추가).
- CVAT 동작에 `create_task`(빈 TASK)·`upload_video`·`create_from_backup`·`move_task` (실제·시험 어댑터, 범위 묶음).

남은 것 (2b-6 실행 호스트): A0 Kaggle 학습 노트북과 GPU 작업자에 `RealTrainer` 연결(GPU 여럿 `device`), Colab 30번 셀에 `RealRevisions`, 끝난 확정의 `recovery/` 30일 청소(복구 자료를 참조하는 '확인 필요'·복구 일 판단 포함).

시험: test_handlers_433 125개(+20). 돌연변이 확인 — 되돌리기 해시 대조, 앞선 만들기 '모름' 확인, 에폭마다 권한 확인을 빼면 각각 실패.

## 2b-6 실행 호스트 (v4.33.0x)

`exec_host.py` — CPU 작업 프로세스·Kaggle GPU 작업자·Colab 30번 셀이 실행기를 띄우는 공용 코드.

| 호스트 | 띄우는 곳 | 능력 | 하는 것 |
| --- | --- | --- | --- |
| CPU 작업 프로세스 | 마스터(`WorkerSupervisor`) → `worker_cpu.main` | cpu, agg | 백업·export·취합·관리 일. 마스터가 `--test`·`--exec-config`(관리자 `config/exec.json` 사본, 비밀 아님)를 넘김 |
| GPU 작업자 | 마스터가 Kaggle에 올리는 **GPU 뿌리 노트북** (ROLE='gpu') → `exec_host.main_gpu` | gpu | track·shape·학습·복구 일. 맡은 일 없이 15분(설정 `idle_exit_min`)이면 끝냄. 생존 신호에 Kaggle 주소(`kernel`) |
| Colab 30번 셀 | `drive/notebooks/A0_colab/cell30_v4.33.py` (노트북에는 2c에서 넣음) → `exec_host.main_colab` | gpu, colab_oauth | GPU 일·23번 복원 |

- **시험 범위 강제:** 모든 호스트의 CVAT는 `ScopedCvat`. 시험 실행인데 `config/exec.json`에 `test_project_id`(eggplant_AA 번호)가 없으면 마스터·GPU 작업자·Colab 모두 시작하지 않음. 시험·운영과 rclone 연결 이름이 맞지 않아도 멈춤.
- **GPU 뿌리 노트북 사슬:** 마스터 노트북 → `manifest.json` → (GPU 노트북 → `worker_manifest.json` → scripts). GPU 노트북은 같은 뿌리 템플릿(`master_boot_v4.33.py`)에서 ROLE·목록 이름·Kaggle 주소만 바꿔 `build_deploy.py`가 만듦. 패키지: 서버와 같은 X.Y의 cvat-cli/sdk, av, (GPU) ultralytics·lap.
- **영상·모델 받기 (`Media`):** 영상은 `videos/`에서 TASK 기본 이름과 같은 것만, 없으면 `backups/<기본 이름>/`의 가장 최근 백업에서 꺼냄. 모델은 채택(`CURRENT.json`)된 버전의 best.pt를 목록 해시와 대조해 받음 (`v/legacy` 등록은 옛 위치를 가리킬 수 있음).
- **데이터셋 만들기:** 쓸 export zip의 TASK 영상을 먼저 받고 `cvat_to_yolo` (`HostBuilder`).
- **웹 상태 (2b-4에서 미룬 것):** 취합(agg)에 `WebState` — 기록(logs/shards·relabel/tasks·exports csv/zip·status·캐시)을 읽기 사본으로 받아 옛 `wb.build_state`·통계·검토 수정량을 계산하고, 취합 처리기가 `web/state.json`·`label_stats`·`corrections`를 epoch·회차와 함께 게시 (정해 둔 파일만). 샤드 합치기·요청 완료·사라진 TASK 이력은 하지 않음.
- **Colab 저장소:** Colab 보안 비밀에는 RCLONE_CONF가 없으므로 Colab 로그인의 접근 토큰으로 세션 전용 rclone 설정(0600, 갱신 토큰 없음)을 만들고 30분마다 다시 씀.
- **청소에 복구 자료 추가:** 끝난 확정의 `recovery/<TASK>/<작업번호>/` 30일. 끝나지 않은 TASK 잠금(확정 중·'확인 필요'·복구 예약)이 가리키는 것, 끝나지 않은 복구 요청의 원래 작업, 결과를 모르는 만들기 의도는 남김. 결과 계획을 먼저 지움.
- 실행기 생존 신호에 `kernel`(Kaggle 주소) — 마스터의 커널 종료 확인이 GPU 작업자에도 닿음.
- 저장소: `list_any`(JSON 아닌 파일 목록), `pull`(읽기 사본) 추가.
- 처리기 모듈 등록은 호스트 시작 때(`load_all`) — 무거운 모듈(h_task·h_mgmt·h_run)은 쓸 때 불러옴.

예행 연습에서 볼 것 (T 항목 추가 후보): GPU 뿌리 노트북 첫 수동 올리기와 보안 비밀 연결, Kaggle GPU 이미지의 패키지 설치 시간, Colab 접근 토큰으로 rclone이 1시간 넘게 도는지, 웹 상태 계산 시간과 옛 화면과의 차이, ULD 사진 TASK(프레임맵)는 아직 track 안 됨(2c).

시험: test_hosts_433 35개(새로), test_handlers_433 126개. 돌연변이 확인 — 시험 프로젝트 번호 강제, 복구 자료 남김 규칙, 쉬는 시간 끝내기, 생존 신호의 Kaggle 주소를 빼면 각각 실패.

## 2b-7 연결 시험 (v4.33.0y)

`tests/test_e2e_433.py` — 실제 심판(`MasterLoop`)·실행기(`Executor`) 여럿·처리기(h_*)·가짜 CVAT 하나. 실행기마다 같은 CVAT를 보는 창(`Tagged`)이 쓰기마다 누가 했는지 남김.

| 요청 항목 | 시나리오 | 확인 |
| --- | --- | --- |
| ⑥ params 전달 | LC(`requests/`, 관리자)·AA(`relabel/requests/`, 동료)·수집기(G) 요청 | 처리기 계산이 받은 params가 요청과 같음 · 세 요청 '완료' · 접수에 요청자 · G의 관리 일 요청은 거절 |
| ① 백업 선행 | 7개 TASK(두 사람 요청)·같은 TASK에 두 번째 요청 | 쓰기 묶음마다 앞에 업로드 전 export, 모든 TASK에 복구 자료 |
| ③ 한 실행기만 | 실행기 둘 | TASK마다 쓴 실행기는 하나 · 두 실행기가 나눠 맡음 · 같은 TASK 두 요청은 차례대로, 복구 자료 폴더도 따로 |
| ② 사람 라벨 보호 | `_vf`(박스), `humanAA`(태그만), 동의 true / 'yes' | 동의 없으면 쓰기 없음·'보류' · 정확히 true일 때만 교체 |
| ④ 취소·정지 경계 | 준비 중 취소 · 확정 중 취소 · 준비 중 정지 → 해제 | 승인 전 TASK는 쓰지 않음, 승인된 TASK는 마침 · 정지 동안 새 일 시작 없음, 해제 뒤 이어서 |
| ⑤ 권한 바뀐 뒤 복원하지 않음 | 가져오기 실패 직후 실행기가 끊긴 것으로 처리됨(심판 4분) | 되돌리기 지우기·가져오기 없음 · '확인 필요' · 사람이 '되돌리기'를 고르면 복구 일이 원래 라벨로 |

돌연변이 확인: 동의 값 느슨하게(`bool`), 되돌리기 지우기의 권한 확인 빼기, 준비 단계 취소 무시, 복구 자료 게시 빼기 → 각각 실패.

시험을 만들며 확인한 동작: 한 실행기는 묶음의 TASK를 한 차례에 모두 준비하고 확정 신청을 함께 냄 → 심판이 함께 승인하므로, 확정 승인 뒤의 취소에서는 그 묶음 전체가 끝까지 감(설계의 '확정 신청 뒤면 그 TASK를 마침'과 같음). 묶음 크기(5)만큼이 취소 뒤에도 쓰일 수 있음 — 검토 질문에 넣음.

## b24 반영 (v4.33.0z)

| 지적 | 고친 곳 |
| --- | --- |
| T1 | `RealCvat.import_annotations`는 **접수만** 하고 작업 번호(`rq:<id>`)를 돌려줌. 접수 자체의 4xx만 `ImportRejected`, 접수 응답 유실은 예외 그대로('모름'). 끝났는지는 `import_status`(서버 요청 상태 조회 — failed는 상태로, `BackgroundRequestException`을 거치지 않음). 조회 오류는 4xx라도 '모름'. `h_task.wait_import`가 첫 가져오기·되돌리기 가져오기 모두 같은 규칙. shape 묶음은 첫 묶음의 4xx만 거절, 그 뒤는 '모름' |
| T2 | 23번 복원은 `weights/best.pt`·`weights/last.pt`를 버전 바로 아래 `best.pt`·`last.pt`로 (모델 버전 계약). 복원 → 채택 → 모델 받기·이어 학습 시작 가중치 회귀 |
| T3 | `ScopedCvat`의 새 TASK 예외는 백업에서 만든 직후의 `rename_task`·`move_task`에만, 만들기 처리기가 끝나면 `release_new`로 거둠. 빈 TASK(17번)는 처음부터 범위 안이라 예외 없음 |
| T4 (11/17 결정) | 학습은 `train_child.py`를 **새 프로세스 묶음**으로 띄우고 부모(실행기)가 지켜봄: 자식 폴더의 results.csv로 에폭, 출력 증가로 진행, poll마다 권한 확인. 권한을 잃거나 예외면 묶음 전체(DDP 자식 포함) TERM→KILL, 게시 없음. 자식에게 콜백·잠금을 넘기지 않음. **자식은 자기 작업 폴더에만 씀** — 공유 폴더·다른 실행의 기록·옛 공용 CSV에 쓰지 않고, 게시는 부모가 확인 뒤 실행마다 다른 버전 경로로 (사람 작업자·앱 작업이 동시에 여럿이어도 기록을 덮지 않음) |
| T5 | `h_agg.adopted_models`: `CURRENT.json`이 가리키는 확인된 모델 버전(legacy 포함). relabel 상태의 `models`는 매번 이것으로 계산(이전 값 이어받기 없앰). 웹 상태는 읽기 사본에 채택 버전을 옛 모양(`runs/<이름>/results.csv`·`args.yaml`·`TRAINING_DONE`)으로 펼치고 가중치는 크기·시각만 `files`로 → 옛 `build_state`가 모델을 찾음. 채택 안 된 버전은 목록에 없음. 학습 `train.json`에 학습 클래스 |
| T6 | `h_agg.result_history`: 심판의 TASK 결과(`arb/results`) + 접수 기록(종류·모델·요청자)을 읽기만 해서 TASK 이력에 합침. (요청, TASK, 작업 번호)마다 한 번. '작업함'은 완료된 쓰기만(보류·실패·되돌리기 제외) |
| T7 | `ScopedCvat.list_tasks_full` → (행, **거르기 전** 원래 목록이 한도에 닿지 않았는가). 취합은 이 값으로 '끝까지 읽음'을 판단 |
| E15 (11/17 결정) | 확정 신청을 TASK 하나씩: 같은 배정의 앞 TASK가 확정 신청 중·확정 중이면 다음 TASK는 신청하지 않음(준비 계산은 묶음 그대로). 멈춤 보고한 TASK는 다음을 막지 않음 → 취소·정지 뒤에 쓰이는 것은 지금 확정 중인 TASK 하나 |

시험: test_handlers_433 140개(+14), test_hosts_433 42개(+7, 실제 자식 프로세스·손자 프로세스 종료 확인, 실제 `build_state`의 모델 목록), test_e2e_433 17개(확정 승인 뒤 취소가 TASK 하나만 마치는지로 강화). 돌연변이 확인 — 상태 조회 오류를 실패로, 새 TASK 예외를 모든 쓰기에, 묶음 대신 자식만 끝내기, TASK 하나씩 신청 빼기, 거른 뒤 개수로 완전성 판단 → 각각 실패.

남은 것: 실제 SDK의 `AnnotationUploader.upload_file`·요청 상태 API가 배포 이미지의 cvat-sdk 버전에서 같은지(예행 연습 T15), 실제 GPU 둘에서 DDP 자식 종료.

## b25 반영 (v4.33.0z1)

b25는 요청서 없이 0z를 사전 검토한 결과입니다(요청서는 2c 첫 단계 뒤에 낼 예정이었음). 임시 번호 F1·F2를 반영했습니다.

| 지적 | 고친 곳 |
| --- | --- |
| F1 | `RealTrainer._kill`: 리더 프로세스가 끝났는지가 아니라 **프로세스 묶음에 남은 것이 있는지**(`killpg(묶음, 0)`)로 판단. TERM → 묶음이 빌 때까지 기다림 → 남으면 KILL → 다시 확인, 그래도 남으면 실패(수동 확인). 정상 끝·리더의 먼저 실패·권한 상실·어떤 예외든 `finally`에서 같은 정리. 원래 예외(권한 상실)는 그대로 전달 |
| F2 | `adopted_models`: `_files.json`이 객체가 아니거나, `verified`가 정확히 true가 아니거나, 파일 항목(해시 64자·크기 양수)이 틀리면 **그 모델만** 빼고 이유를 `skipped`에. relabel 상태에 `models_skipped` |

시험: test_hosts_433 44개(+2: TERM을 무시하는 손자를 세 경로에서 정리, 깨진 목록 네 가지가 정상 모델을 막지 않음). 돌연변이 확인 — 리더 종료로 묶음 종료를 판단, 객체 확인 빼기 → 각각 실패. 시험 뒤 남은 프로세스 없음.

## b26 반영 (v4.33.0z2, 11/17 결정 포함)

| 지적 | 고친 곳 |
| --- | --- |
| U1 (결정: 끝까지 추적) | `ProcTree`: 학습 리더와 그 아래 모든 프로세스를 (pid, 시작 시각)으로 poll마다 기억 — 부모 사슬로 잡으므로 새 세션으로 나간 DDP 작업자(`torch.distributed.run`)도 포함. 학습 동안 실행기 프로세스를 고아 프로세스의 새 부모(`PR_SET_CHILD_SUBREAPER`)로 → 리더·중간 프로세스가 먼저 죽어도 아래 프로세스가 이쪽으로 넘어와 보임. 끝낼 때: 살아 있는 추적 프로세스와 그 묶음에 TERM → **60초**(PyTorch 자체 정리 30초보다 길게) → KILL → 확인. /proc가 없으면(Linux 아님) GPU 여럿 학습을 거절 |
| U2 | `access.NeedsCheck` → 실행기는 `stop_run`(이유 표식) → 심판은 실행 잠금을 '확인 필요'로 두고 같은 학습을 다시 시작하지 않음. `h_run.CleanupUnknown`(정리 확인 불가)·종료 신호 권한 오류 모두 이 길로. 원래 예외(권한 상실 등)는 원인(`__cause__`)으로 남김 |
| U3 | `clean_meta`: train.json에서 쓰는 칸(성적·설정·클래스·시각)만 자료형이 맞을 때 — 틀리면 그 칸만 비움. legacy `paths` 값이 문자열 경로가 아니면 그 모델만 뺌(`legacy_paths_invalid`). 모델 목록 변환·웹 상태 펼치기도 모델마다 따로 실패 처리 |
| U4 (11/17 결정) | 학습 자식 환경: `YOLO_CONFIG_DIR`·`XDG_CONFIG_HOME`·`XDG_CACHE_HOME`·`TMPDIR`·`HOME`·`TORCH_HOME`·`MPLCONFIGDIR`를 실행별 작업 폴더 안으로(DDP 임시 코드도 여기), 외부 기록 연동 환경 변수(MLflow·W&B·Comet·ClearML 등)는 넘기지 않음, `YOLO_OFFLINE=1`. 자식은 설정 폴더가 작업 폴더 밖이면 시작하지 않고, 실행 전용 설정 파일에서만 연동을 끔 — 사람 작업자의 설정은 그대로 |
| U5 | 좀비는 '살아 있음'에서 뺌, 이쪽 자식이 된 추적 좀비는 회수(다른 subprocess의 자식은 건드리지 않음) |

시험: test_hosts_433 52개(+8: 새 세션 작업자를 권한 상실·리더 먼저 죽음에서 끝냄, 좀비, 신호 권한 오류의 원인 보존, 자식 환경 폴더·연동 변수, 설정 폴더 밖이면 시작 안 함, 메타데이터·legacy 경로), test_handlers_433 142개(+2: 정리 확인 불가 → 확인 필요·다음 학습 막음). 돌연변이 확인 — 추적 끄기, 좀비를 살아 있음으로, NeedsCheck 처리 빼기, 실행별 설정 폴더 빼기 → 각각 실패. 시험 뒤 남은 프로세스 없음.

남은 것: 실제 Kaggle GPU 둘에서 torchrun 중단·subreaper 동작(예행 연습), 배포 이미지의 Ultralytics·PyTorch 버전 고정.

## b27 반영 (v4.33.0z3)

b27은 요청서 없이 0z2를 사전 검토한 결과입니다(사용자 질문 착오 — 원래 b27은 2c-1 뒤였음). U2~U5는 해결, U1은 부분 해결로 F1이 나왔습니다.

| 지적 | 고친 곳 |
| --- | --- |
| F1 | **학습만 소유하는 감독 프로세스** `train_supervisor.py`. 실행기 → 감독 → 학습 자식. 감독이 고아 프로세스의 새 부모(`PR_SET_CHILD_SUBREAPER`)이므로, 학습 자식·DDP launcher가 poll 사이에 먼저 끝나도 그 아래(새 세션 작업자 포함)는 감독 아래로 넘어옴 — 실행기의 다른 subprocess와 섞이지 않음. 감독은 아래에 살아 있는 것이 하나도 없을 때까지 끝나지 않음: 학습 자식이 끝난 뒤 남은 것·TERM을 받은 경우 모두 TERM → 60초 → KILL, 좀비는 거둠. 끝날 때 `supervisor.json`에 `child_rc`·`clean`. 실행기는 감독에게만 TERM을 보내고 90초 기다림 → 감독이 안 끝나거나, `clean`이 없거나 거짓이거나, 추적한 것이 남으면 KILL 뒤 `CleanupUnknown`('확인 필요'). 실행기 자신은 더 이상 고아의 새 부모가 되지 않음 |

감독은 우리 모듈을 불러오지 않습니다(표준 라이브러리만, 경로로 실행). 배포 묶음의 scripts에 들어가므로 해시 사슬 안에 있습니다.

시험: test_hosts_433 54개(+2: poll 사이 리더 종료·새 세션 손자를 감독이 정리, 감독이 강제로 끝나면 '정리 확인 불가'·원인 보존). 돌연변이 확인 — 감독의 subreaper 빼기, 아래가 남아도 끝내기 → 각각 실패. 시험 뒤 남은 프로세스 없음.
