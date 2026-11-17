# v4.33.0y 검토 결과 — b24

검토일: 2026-11-17. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0y.md`, b23 결과, `IMPL_STEP2B_v4.33.md`, 관련 설계·구현·시험을 확인했다. **높음 5건(T1~T5), 보통 2건(T6~T7)을 확인했다. 지정 일반 시험 861개와 기본·확장 퍼징 각 10개 항목은 모두 통과했다.** 시험 통과와 별개로 실제 어댑터와 소비자 사이의 경계가 빠져 있다.

코드·노트북·시험·설계서는 수정하지 않았다. 보고서와 `rLog/b24_*` 검토 자료만 작성했다. 실제 CVAT·Google Drive·Kaggle·Colab에는 접속하지 않았다. 시험 도구와 공개 패키지만 내려받아 `/tmp`에 설치했다. 작업 시작 때부터 있던 저장소 변경은 그대로 두었다.

## 시험과 재현 자료

| 실행 | 결과 | 로그 |
| --- | --- | --- |
| `python tests/test_arbiter_433.py drive` | 247개 성공 | `rLog/b24_arbiter.log` |
| `python tests/test_access_433.py drive` | 68개 성공 | `rLog/b24_access.log` |
| `python tests/test_master_433.py drive` | 75개 성공 | `rLog/b24_master.log` |
| `python tests/test_master_main_433.py drive` | 62개 성공 | `rLog/b24_master_main.log` |
| `python tests/test_handlers_433.py drive` | 126개 성공 | `rLog/b24_handlers.log` |
| `python tests/test_hosts_433.py drive` | 35개 성공 | `rLog/b24_hosts.log` |
| `python tests/test_e2e_433.py drive` | 17개 성공 | `rLog/b24_e2e.log` |
| `python tests/test_fuzz_433.py drive` | 10개 항목 성공 | `rLog/b24_fuzz.log` |
| `FUZZ_SEED=7 FUZZ_N=5 python tests/test_fuzz_433.py drive` | 10개 항목 성공 | `rLog/b24_fuzz7.log` |
| Collector 지정 Node 명령 | 72개 성공 | `rLog/b24_collector.log` |
| Keeper 지정 Node 명령 | 125개 성공, Collector 뒤 실행 | `rLog/b24_keeper.log` |
| CTRL 지정 Node 명령 | 34개 성공 | `rLog/b24_ctrl.log` |

모든 지정 명령의 종료 코드는 0이며 마지막 출력은 `RESULT True`다. 실행기·명령·시간은 `rLog/b24_run_tests.py`, `b24_test_status.json`에 있다. Python 3.14.4의 `/tmp/b24_venv`(NumPy·Pillow·pyflakes·cvat-sdk·cloudpickle), Node 22.16.0, `/tmp/b24_js`의 jsdom을 사용했다. `PYTHONDONTWRITEBYTECODE=1`로 실행했다. 저장소에서 npm 설치는 하지 않았다. 새 처리기·호스트 7개 파일의 pyflakes 결과는 미사용 import 7건뿐이며, 스타일 항목이므로 발견으로 올리지 않았다(`b24_pyflakes.log`).

추가 재현:

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b24_probe.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b24_integration_probe.py
```

각 출력은 동명의 `.log`에 보관했다. 두 번째 스크립트는 공식 처리기 시험의 `World` 정의부만 읽어 실제 심판·실행기·처리기를 연결한다. GPU·모델·실제 영상 없이 실행한다. SDK/DDP 확인에 사용한 공개 패키지 버전·SHA256·관련 소스 발췌는 `b24_sdk_ddp_sources.log`에 있다. CVAT SDK 2.79.0과 설치된 2.83.0의 관련 예외 계약을 대조했고, DDP는 내려받은 Ultralytics 8.4.215 소스를 확인했다. 이 버전 확인을 실제 배포 이미지의 실행 검증으로 간주하지 않는다.

**b23 원본 재현 파일 부재:** 현재 작업 폴더에는 `rLog/b23_*`가 하나도 없다(`b24_b23_inventory.log`). 따라서 원본 재현을 그대로 다시 실행할 수 없었다. 이전 보고서의 조건을 확인하고 공식 S1~S7 회귀 시험, b24의 SDK·추가 경계 재현으로 대신했다. 원본 재실행을 완료했다고 주장하지 않는다.

## b23 원본 부재에 대한 재점검 보충

사용자 후속 요청에 따라 `REVIEW_RESULT_v4.33.0s_b23.md`의 S1~S7 조건을 독립 스크립트로 재구성했다. **원본 파일은 여전히 없지만, 보고된 현상을 현재 코드에서 다시 점검하는 데에는 원본이 필수는 아니다.** 아래 자료는 당시 원본을 복원한 것이 아니라 보고서에서 재구성한 새 재현이다. 과거 0s 코드에서 같은 결함이 발생했는지를 다시 실행한 것은 아니다.

- 스크립트: `rLog/b24_reconstructed_b23.py`
- 실행 로그: `rLog/b24_reconstructed_b23.log`
- 개별 검사·근거 JSON: `rLog/b24_reconstructed_b23_status.json`
- 실행: `PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b24_reconstructed_b23.py`

| 항목 | 보고서 조건의 재구성 결과 |
| --- | --- |
| S1 | humanAA+사람 shape, human_vf+사람 tag 모두 held:human_labels. CVAT 쓰기 0회, 기존 라벨 유지. |
| S2 | 서버 작업을 started로 남기고 TimeoutError를 발생시켰다. 최초 remove/import 각 1회 이후 복원 호출 없음, 잠금 quarantine. 원래 TimeoutError 사례는 해결됐다. 다만 상태 조회 4xx의 T1이 남아 S2 전체 판정은 부분 해결로 유지한다. |
| S3 | 실패한 최초 import 뒤 복원 remove 직후 권한을 quarantine으로 바꿨다. 추가 백업 import가 없고 확인 필요 상태를 유지했다. |
| S4 | old 정상 게시 뒤 new를 corrupt로 쓰는 재게시를 시도했다. 파일 변경 전에 VerifyError로 거절하고 old 파일·원래 목록·검증 결과가 유지됐다. |
| S5 | 실제 CLI에 현재 RealEngine 인수를 전달했다. 가짜 ultralytics 모듈이 모델 생성 직전에 중단하도록 해 파서를 통과했음을 확인했다. 옛 잘못된 near=0.5와 box-source=track은 각각 종료 코드 2로 거절되는 음성 대조도 수행했다. 모델·영상 로드는 하지 않았다. |
| S6 | 최초 import는 failed, 백업 import는 성공시키고 기존 ctt 상수와 대조했다. 두 import 모두 CVAT 1.1, 참고/업로드 전 export 모두 CVAT for video 1.1이며 원래 라벨이 복원되고 failed:import(restored)로 끝났다. |
| S7 | 범위 밖 TASK의 감싼 삭제와 client().tasks.retrieve(...).remove_annotations(), session·ops 접근을 모두 차단했다. CVAT 쓰기 0회. |

**13개 검사 모두 통과, RESULT True. S1·S3~S7 해결 / S2 부분 해결이라는 기존 판정은 유지한다.** 실서비스 접속 없이 실제 처리기·실행기·심판과 공식 FakeCvat·LocalStore를 연결했다. 이 보충으로 ‘독립 재현 파일이 없어 공식 회귀에만 의존’하던 제한은 해소했으며, ‘당시 원본 바이트의 동일성 확인·원본 그대로 재실행’은 여전히 불가능하다.

b23에서 다룬 이전 R1·R2도 `test_master_433.py`와 `test_master_main_433.py`의 실제 경로 회귀로 재실행했다. 각각 75개·62개 검사가 모두 통과했고 마지막 출력은 RESULT True다. 로그는 `rLog/b24_recheck_b23_master.log`, `rLog/b24_recheck_b23_master_main.log`에 있다. 이들은 b23/b22의 잃어버린 스크립트를 가장한 파일이 아니다.

## 0t의 S1~S7 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| S1 사람 라벨 보호 | 해결 — 기존 발견 범위 | `_uld`·`_AA`·`_AA_rN`의 밑줄을 포함해 판정하며 tags도 센다. `humanAA`의 shape·`human_vf`의 tag를 무동의로 교체하지 않는 회귀와 연결 시험 통과. |
| S2 가져오기 모름/거절 | **부분 해결** | 접수 뒤 TimeoutError는 복원하지 않고 quarantine으로 간다. 그러나 SDK 전체 호출에서 나온 4xx를 단계 구분 없이 거절로 바꾸므로 상태 조회 401에도 복원한다(T1). 서버 작업의 명확한 `failed`는 SDK의 `BackgroundRequestException`이 되는데 이 예외는 terminal 실패로 인식하지 못한다. |
| S3 복원 중 권한 재확인 | 해결 — 기존 발견 범위 | 되돌리기 remove/import를 따로 `w.call`로 감싸고 shape 묶음에도 `before_each`를 전달한다. 복원 삭제 직후 권한을 잃으면 다음 import가 없고, 함수 안 권한 상실 회귀도 통과. |
| S4 버전 재게시 | 해결 | `_files.json`이 있으면 파일을 쓰기 전에 거절한다. 같은 버전 재게시 후 기존 파일과 해시가 유지되는 회귀 통과. ‘확인한 버전 불변’ 결정과 맞는다. |
| S5 track 인수 | 해결 — 기존 발견 범위 | near는 정수 1, box-source는 detection이며 settings 병합이 가능하다. 실제 CLI 파서 통과·프레임맵 인수 회귀 통과. 실제 추론 성공을 확인한 것은 아니다. |
| S6 export/import 형식 | 해결 — 코드 계약 | export `CVAT for video 1.1`, import/복원 `CVAT 1.1`로 분리했다. 시험 CVAT도 잘못된 import 형식을 거절한다. 서버의 실제 형식 목록은 예행 연습에서 확인할 사항이다. |
| S7 원래 연결 노출 | 해결 — 기존 발견 범위 | 허용 목록 밖의 `client`·`session`·`ops` 접근을 거절한다. 호스트가 별도로 보관하는 원래 연결은 shape의 collect_only 계산·웹 상태 읽기에 사용된다. 다만 새 `_made` 예외에는 별도의 범위 우회가 있다(T3). |

## 새 발견

### T1 — 접수 뒤 상태 조회의 4xx를 가져오기 거절로 오인해 복원한다

| 칸 | 내용 |
| --- | --- |
| 번호 | T1 |
| 심각도 | 높음 |
| 관련 항목 | AGENTS 3장 7, S2, 검토 질문 A2·E14 |
| 위치 | `drive/scripts/cvat_ops.py:22` `_rejected`, `:119` 예외 변환, `:141` SDK 동기 호출; `drive/scripts/h_task.py:239` 실패 복원 분기 |
| 무엇이 문제인가 | `task.import_annotations`는 업로드 접수와 완료 상태 조회를 모두 포함한다. 이를 감싼 예외에서 상태 코드만 보므로, 이미 접수된 작업의 GET 상태 조회가 401·403·404 등으로 실패해도 ‘서버가 가져오기를 거절’한 것으로 바꿔 기존 라벨을 다시 지우고 백업을 가져온다. 첫 작업의 종료를 확인하지 않은 채 복원과 경합할 수 있다. |
| 일어나는 조건 | `b24_probe.py`의 T1: 서버 작업을 started로 남긴 뒤 실제 SDK `Client.wait_for_completion`의 상태 조회가 `ApiException(status=401)`을 내게 했다. 실제 RealCvat 예외 변환을 거친 commit은 remove를 두 번 실행하고 백업 import를 호출해 `failed:import(restored)`를 반환했다. 첫 서버 작업은 계속 started인 모형이다. 네트워크 응답 유실 그 자체는 현재 안전하게 모름으로 분류되지만, 접수 뒤의 다른 HTTP 오류는 안전하지 않다. |
| 확신 | 확인함 — 실제 SDK 대기 함수·실제 어댑터·commit 연결 재현. 실제 서버에 접속하지는 않음. |
| 제안 | 접수·상태 조회 단계를 구분하고 접수 작업 번호를 보존한다. 접수 뒤 조회 오류는 모름으로 처리하며, 복원은 최초 제출의 명확한 거절 또는 해당 작업의 failed 종료를 확인했을 때만 허용한다. SDK `BackgroundRequestException`도 별도로 해석한다. 현재 SDK의 명확한 failed는 이 예외이며 status 속성이 없어 지금은 오히려 ImportUnknown이 된다. 4xx 코드 목록만 수정해서는 두 경우를 해결할 수 없다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 진행 중인 쓰기가 없다는 근거 없이 복원하고 잠금을 풀 수 있는 경로다. |

### T2 — 23번 복원 모델의 가중치 경로가 소비 계약과 다르다

| 칸 | 내용 |
| --- | --- |
| 번호 | T2 |
| 심각도 | 높음 |
| 관련 항목 | 새 발견, 검토 질문 C·D13, 버전 소비 계약 |
| 위치 | `drive/scripts/h_run.py:372`·`:384`·`:391` run_restore23; `drive/scripts/exec_host.py:137` Media.model; `drive/scripts/h_run.py:212` 이어 학습 |
| 무엇이 문제인가 | 복원은 `weights/best.pt`를 그대로 버전 파일 목록에 싣지만 일반 학습·추론 소비자는 `best.pt`를 찾는다. 복원 요청은 done과 채택 변경을 보고하나 채택한 모델을 추론이나 이어 학습에서 사용할 수 없다. legacy 경로 예외도 이 새 복원 버전에는 적용되지 않는다. |
| 일어나는 조건 | `b24_probe.py`의 T2: 가짜 revision에서 weights/best.pt를 복원하면 done_job과 m_A 채택 변경이 나온다. 그 버전을 CURRENT로 지정하고 실제 Media.model을 부르면 `MgmtFailed: model_unverified`가 난다. 공식 시험은 복원 목록이 weights/best.pt라는 것까지만 확인해 이 불일치를 통과시킨다. |
| 확신 | 확인함 — 실제 게시 함수와 실제 소비 함수 연결. |
| 제안 | 복원 게시 시 가중치 파일 이름을 새 모델 버전 계약으로 맞추거나 모든 소비자에게 공통 경로 해석을 제공한다. ‘복원 → 채택 → 모델 받기/이어 학습’ 회귀를 추가한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 23번 셀을 연결하기 전에 완료된 복원 결과를 사용할 수 있어야 한다. |

### T3 — 새로 만든 TASK의 범위 예외가 세션 내 모든 후속 쓰기에 남는다

| 칸 | 내용 |
| --- | --- |
| 번호 | T3 |
| 심각도 | 높음 |
| 관련 항목 | 시험 범위 강제, 검토 질문 D10, 새 발견 |
| 위치 | `drive/scripts/handlers.py:206` `_made`, `:214` `_check`, `:246` create_task, `:252` create_from_backup |
| 무엇이 문제인가 | `_made`에 있는 TASK는 이름·프로젝트 조회를 모두 생략한다. 이 집합은 ‘복원 직후 이름·프로젝트 맞춤’ 동안만 쓰이는 것이 아니라 호스트의 ScopedCvat 수명 내내 남고, remove/import/다음 요청의 prepare까지 우회한다. |
| 일어나는 조건 | `b24_probe.py`의 T3: 시험 ScopedCvat로 REH_ TASK를 만든 뒤 그 TASK의 이름을 production_vf, 프로젝트를 99로 바꾸었다. 같은 시험 객체의 remove_annotations가 거절 없이 실행됐다. 복원 직후 프로젝트 맞춤이 실패해 범위 밖에 남는 경우에도 이 번호가 집합에 남는다. 운영 객체에서도 자신이 만든 TASK가 나중에 REH_가 되면 같은 검사 생략이 적용된다. |
| 확신 | 확인함 — 가짜 CVAT와 실제 ScopedCvat로 재현. |
| 제안 | 예외는 해당 create16 작업의 새 TASK에 대한 초기 rename/move에만 한정하고, 범위를 맞추거나 작업이 끝나면 회수한다. 라벨 삭제·업로드와 후속 요청은 언제나 현재 이름·프로젝트를 확인한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 사람용 셀·예행 연습이 의존하는 강제 범위 보장이다. |

### T4 — DDP에 넘기는 학습 콜백이 실행기의 스레드 잠금을 캡처한다

| 칸 | 내용 |
| --- | --- |
| 번호 | T4 |
| 심각도 | 높음 |
| 관련 항목 | 검토 질문 C8, 학습 호스트 연결 |
| 위치 | `drive/scripts/h_run.py:153` RealTrainer 콜백, `:219` run_train.on_epoch; `drive/scripts/executor.py:112` `_busy_lock`·`:138` `_progress` |
| 무엇이 문제인가 | on_epoch가 ctx를, ctx.progress가 실행기 객체를 참조하며 실행기에는 직렬화할 수 없는 threading.Lock이 있다. 확인한 Ultralytics 8.4.215의 DDP는 trainer callbacks를 cloudpickle로 자식 프로세스용 파일에 저장하므로 이 콜백을 넘길 수 없다. |
| 일어나는 조건 | `b24_integration_probe.py`의 T4는 실제 run_train이 만든 on_epoch와 실제 Executor._progress를 사용한다. DDP와 같은 cloudpickle 직렬화에서 `TypeError: cannot pickle '_thread.lock' object`로 실패한다. 단일 GPU의 가짜 Trainer처럼 같은 프로세스에서 콜백을 부르는 시험은 이 문제를 잡지 못한다. |
| 확신 | 확인함 — 해당 공개 버전의 DDP 소스와 실제 콜백 직렬화 실패. 실제 GPU 학습·자식 프로세스 기동은 미실행. |
| 제안 | 배포할 Ultralytics 버전을 고정하고 자식 프로세스에 전달 가능한 콜백/설정과 부모의 권한 감시를 분리한다. 부모는 권한 상실 시 전체 DDP 프로세스 묶음을 종료할 수 있어야 한다. 임시로 단일 GPU만 허용한다면 입력에서 다중 device를 명시적으로 막는다. 콜백을 전달하지 않는 다른 Ultralytics 버전도 권한 확인이 빠질 수 있으므로 버전별 계약을 검증한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 다중 GPU를 지원하는 연결로 셀을 내기 전 해결하거나 해당 입력을 막아야 한다. 단일 GPU의 콜백 예외 전파 자체는 소스상 학습을 중단시킨다. |

### T5 — 새 웹 상태는 공유 폴더의 모델을 발견하지 못한다

| 칸 | 내용 |
| --- | --- |
| 번호 | T5 |
| 심각도 | 높음 |
| 관련 항목 | 검토 질문 D13, 새 발견, 모델 선택·버전 목록 |
| 위치 | `drive/scripts/exec_host.py:228` WebState.PULLS, `:261` build_state 호출; `drive/scripts/web_bridge.py:698` 모델 발견; `drive/scripts/h_agg.py:247` 이전 models 계승 |
| 무엇이 문제인가 | WebState는 runs 읽기 사본도, runs 원격 목록을 담은 files 인수도 제공하지 않는다. 옛 build_state는 이 두 입력으로만 모델을 찾으므로 새 세션의 web/state.json은 모델이 있어도 models=[]가 된다. 별도의 relabel/state.json도 models를 계산하지 않고 이전 값만 이어받아 신규 학습·복원·채택 변경을 반영하지 못한다. ‘이전 상태 계승’은 새 버전을 발견하는 경로를 대신하지 못한다. |
| 일어나는 조건 | `b24_probe.py`의 T5: 공유 저장소에 복원 버전과 정상 best.pt 경로의 학습 모델 버전·각 CURRENT가 있는 상태에서 실제 WebState.build와 실제 wb.build_state를 연결했다(CVAT 읽기·통계만 가짜). 결과는 `모델 0개`, models=[]다. 원래의 web/state.json 자체도 읽어 계승하지 않는다. 따라서 기존 상태가 공유 폴더에 있더라도 이 웹 목록은 빈 목록으로 게시될 수 있다. |
| 확신 | 확인함 — 실제 웹 계산 호출 연결·입력 경로 추적. 실제 LC·AA 앱 화면은 저장소에 없어 미실행. |
| 제안 | CURRENT가 가리키는 모델 버전 목록을 공통으로 계산해 웹·relabel 양쪽에 공급한다. 버전 경로와 legacy를 해석하고 채택된 가중치만 모델 선택에 노출한다. 기존 파일 위치를 기대하는 옛 build_state에 단순히 버전 폴더만 내려주는 것으로 끝내지 않는다. ‘학습/복원 → 새로 고침 → 새 모델 선택 가능’을 시험한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 새 모델을 화면·셀의 선택 목록으로 전달하는 계약을 먼저 확정해야 한다. |

### T6 — 새 TASK 쓰기의 결과가 취합 이력에 들어가지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | T6 |
| 심각도 | 보통 |
| 관련 항목 | 검토 질문 B3·D13·E14, 2b-3 이력 대체 설명 |
| 위치 | `drive/scripts/h_agg.py:198` task_summary, `:238` 읽는 기록 경로; `drive/scripts/h_task.py:203` result_plan 게시 |
| 무엇이 문제인가 | 새 처리기는 복구 자료·심판 결과로 이력을 대신하지만 취합기는 여전히 relabel/tasks/<id>.json의 옛 history만 읽는다. 새 result_plan·arb/results를 요약하지 않아 이번 작업의 last/runs/worked가 갱신되지 않는다. 구현 설명의 ‘취합 일이 복구 자료와 결과 기록을 요약’한다는 연결이 없다. |
| 일어나는 조건 | `b24_integration_probe.py`의 T6: 실제 심판·실행기·h_task로 track을 완료한 뒤 h_agg refresh까지 완료했다. CVAT 이름은 …_uld_AA이고 심판 결과는 done이나, 게시된 행은 `last=None, runs=0, worked=None`이다. 옛 history가 있으면 그 과거 이력만 계속 나온다. |
| 확신 | 확인함 — track 완료부터 상태 게시까지 연결 재현. |
| 제안 | 심판이 확정한 결과를 기준으로 새 쓰기 이력을 읽기 전용으로 합산하고, 복구/재실행이 같은 건을 중복 계산하지 않게 식별한다. 성공 업로드·보류·실패·되돌림을 구분한다. |
| 2c로 넘어가기 전 필수 여부 | 필수 아님. 셀 요청 연결은 진행할 수 있으나 **AA 화면 연결·예행 연습 전 필수**다. 현재는 완료한 대상도 미작업처럼 보인다. |

### T7 — 시험 범위 필터가 목록 잘림 정보를 없애 거짓 ‘사라짐’을 만든다

| 칸 | 내용 |
| --- | --- |
| 번호 | T7 |
| 심각도 | 보통 |
| 관련 항목 | 검토 질문 B4·D10, 목록 한도 경계 |
| 위치 | `drive/scripts/handlers.py:197` ScopedCvat.list_tasks; `drive/scripts/h_agg.py:226`·`:227` complete 계산 |
| 무엇이 문제인가 | 원래 CVAT 목록은 먼저 limit까지 잘린다. 그 뒤 시험 프로젝트/REH_로 필터링한 개수를 complete 판단에 쓰므로 원래 목록이 5000개여도 필터 결과가 작으면 ‘끝까지 읽음’으로 바뀐다. 보이지 않은 시험 TASK를 사라짐으로 표시한다. |
| 일어나는 조건 | `b24_integration_probe.py`의 T7: 같은 로직의 작은 경계(limit=1)에 운영 TASK 1개 뒤 시험 TASK 1개를 둔다. 시험 TASK는 실제로 존재하지만 refresh 후 `list_complete=True`, `in_cvat=False`, `gone_at` 생성, `progressed=True`가 된다. 운영 5000개 뒤 시험 TASK가 있는 입력과 동형이다. |
| 확신 | 확인함 — 실제 ScopedCvat·취합·심판 연결 재현. |
| 제안 | 목록과 함께 원래 조회의 complete/truncated 정보를 반환하거나, 서버에서 시험 범위로 먼저 조회한 뒤 한도를 적용한다. 필터 후 행 수로 원래 조회 완전성을 추론하지 않는다. |
| 2c로 넘어가기 전 필수 여부 | 필수 아님. **시험 프로젝트를 이용한 예행 연습 전 필수**다. 실제 TASK 삭제나 운영 파일 쓰기는 발생하지 않지만 시험 판정을 왜곡한다. |

## 검토 질문별 추가 판정

| 질문 | 판정·의견 |
| --- | --- |
| A1·A2 | S 표와 T1 참조. SDK의 failed는 BackgroundRequestException, 조회 HTTP 실패는 ApiException이다. 원본 b23 파일 부재와 별개로 공식 회귀는 모두 실행했다. |
| B3 | 취합 잠금 발급마다 gen이 증가한다. 각 게시에서 현재 권한과 기존 _pub를 검사하고 tracked 작성 경로도 취합 하나다. 이미 알려진 Drive의 읽기/쓰기 사이 틈을 제외하면 새 경합 결함은 확인하지 못했다. |
| B4 | 일반 목록은 한도 도달 시 list_complete=false를 게시해 앱이 판단 불완전성을 알 수 있다. 단, 시험 필터에서는 T7이 있다. 실제 앱이 이 값을 표시하는지는 앱 부재로 확인하지 못했다. |
| C5 | 받은 export 중 published_at이 최신인 것을 고르고 내려받은 파일 해시를 비교한다. 시험 TASK ID·동일 그루/날짜 키 제외와 출처 미상 시 task_keys 미기록은 회귀 통과. 실제 RealBuilder의 영상 디코딩·산출 데이터의 품질은 별도 미검증이다. |
| C6 | 버전 목록 → 내용, 신호 계획 → 완료 기록, 복구 result_plan → 내용의 삭제 순서가 있다. 선행 삭제 실패 때 다음 삭제를 멈추는 경로도 확인했다. 채택·진행 중 pin·adopt_wait·legacy 보호 시험 통과. marks의 작성자는 DESIGN 파일 쓰기 표에서 관리 실행으로 명시돼 있어 현재 신뢰 모델과 맞는다. 끝난 실행 확인과 생성 시각 하한을 사용한다. 등록 사용자와 검증 코드가 신뢰된다는 설계 밖의 악의적 변조 방어로 해석하지 않았다. |
| C7 | 원래 사람 라벨 교체 동의를 redo에 이어받는 것은 같은 원작업 재수행이라는 계약과 맞는다. revert는 사람이 고른 복구 동작 자체로 원본 복원을 허용한다. before_sha256 없는 과거 자료의 revert를 거절하는 것은 안전한 실패다. 해시가 없는 자료를 임의로 승인하지 않아야 한다. 해시 변조·정확한 개수 검사·권한 상실 회귀 통과. |
| C8 | 고정된 데이터셋·시작 모델 버전과 파일 해시를 사용한다. 단일 프로세스의 epoch 콜백 예외는 전파되고 AuthorityLost는 stop_run이 된다. DDP 계약은 T4 때문에 미완성이다. 실제 프로세스 묶음 종료는 검증하지 못했다. |
| C9 | 생성 전 intent, 빈 TASK 번호 선기록, 응답 모름 후 같은 rid의 확인 없는 재시작 차단을 확인했다. 모름일 때 자동 재생성하지 않고 후보 확인을 사람에게 맡기는 방식은 허용 가능하다. 2c에서 intent·알려진 TASK 번호·이름·시각을 보여주고 재시도 동의를 명시적으로 받아야 한다. 후보 자동 검색의 부재 자체는 새 결함으로 올리지 않았다. |
| D10 | 시험 프로젝트 필수·연결 이름 일치·일반 TASK 쓰기 범위를 확인했다. shape의 원래 연결은 collect_only이고 웹 계산도 CVAT 읽기다. 새 TASK 초기 이름/프로젝트 맞춤 예외는 필요하지만 T3처럼 수명이 넓으면 안 된다. |
| D11 | 기본 빌더가 만든 master manifest → GPU notebook → worker_manifest → scripts의 해시 사슬과 시험 연결 치환은 시험 통과. main_gpu가 검증 바이트를 쓰며, 맡은 배정이 있거나 목록을 못 읽으면 idle_exit로 끝내지 않는다. 실제 Kaggle 업로드·시크릿 연결은 미검증. |
| D12 | Colab 로그인 접근 토큰을 세션 전용 0700 디렉터리의 처음부터 0600인 파일에 쓰고 refresh token은 설정에 싣지 않는 방식은 요청서가 정한 예외와 맞는다. 저장소 읽기 실패는 대기/권한 재확인으로, 확정 중 게시 실패는 멈춤 경로로 간다. 쓰기 실패가 루프 밖으로 전파돼 실행기가 종료할 수 있으므로 ‘항상 기다린다’고 보장할 수는 없지만, 실패를 성공으로 바꾸는 새 경로는 확인하지 못했다. 실제 1시간 이상 토큰 갱신·동시 rclone 읽기는 미검증. |
| D13 | T5·T6 참조. relabel 모델·출처의 과거 값 계승을 최신 계산 완료로 보아서는 안 된다. 옛 legacy CSV·루트 기록 일부도 PULLS에 없어 신선한 사본에서 빠질 수 있다. 샤드 CSV는 기존 read_sharded를 통해 읽으므로 샤드를 물리적으로 합치지 않는 것 자체는 문제가 아니다. |
| E14 | 요청한 ①~⑥의 기본 경로는 연결 시험 17개가 확인한다. 실제 SDK의 ‘접수 후 조회 실패’, 복원 산출물의 소비, DDP 직렬화, create 예외의 수명, 작업 후 refresh, 필터 뒤 한도 경계는 덮지 못한다. T1~T7 재현이 이를 보완한다. |
| E15 | 묶음 전체가 승인된 뒤 취소해도 최대 5개를 마치는 현 동작은 승인된 TASK를 마친다는 확정 경계와 맞으므로 결함으로 올리지 않았다. **확정 신청을 TASK별로 순차 발행하는 방식을 권한다.** 준비 계산은 묶음으로 유지하되 직전 TASK의 결과 처리 뒤 다음 TASK를 신청하면 취소 후 쓰기 범위를 현재 확정 중 TASK로 줄일 수 있다. 정책을 유지한다면 앱은 ‘이미 확정된 최대 5건은 마침’을 표시해야 한다. 이는 설계 결정 사항이며 이번 검토에서 코드를 바꾸지 않았다. |

## 점검했지만 문제가 없던 항목

- 지정 시험 전체, S1·S3~S7의 기존 발견 범위, 응답 유실 TimeoutError의 확인 필요 처리.
- 업로드 전 export·복구 파일 해시 확인, 사람 라벨 교체 동의의 정확한 true 판정, 보류 시 CVAT 쓰기 없음.
- 되돌리기 각 쓰기 전 권한 확인, 원본 백업 해시 불일치 시 거절, 복원 라벨 개수의 정확한 대조.
- TASK별 순서·두 실행기의 작업 분담·요청별 복구 폴더 구분, 승인 전 취소·정지·해제, 승인 뒤 마무리.
- 취합 epoch/gen 비교, 읽을 수 없는 기존 게시물 덮어쓰기 거절, hide/unhide 요청 최종화.
- 시험 TASK 제외·export 해시 비교·출처 미상 호환 정보 처리, 청소의 채택/참조/legacy 보호와 선행 파일 삭제 순서.
- 기본 GPU 배포 해시 사슬·시험 연결, 활성 배정 중 idle_exit 방지, Kaggle 보안 비밀 우선 읽기와 세션 비밀 파일 0600.
- 검토 범위에서 TASK 삭제·CVAT_UpLoader 쓰기·원본 clip 삭제·추가 웹앱 doGet/doPost 경로는 발견하지 못했다.

## 시간이 모자라 보지 못한 항목·환경상 확인하지 못한 항목

- 존재하지 않는 `rLog/b23_*` 원본 재실행. 공식 회귀와 조건 재구성으로 대체했다.
- 실제 CVAT 서버의 가져오기 실패 상태·형식 목록·영상 업로드·백업 복원·이름/프로젝트 변경 결과. 접속 금지 지침을 지켰다.
- 실제 Ultralytics 추론·단일/다중 GPU 학습, 자식 프로세스 전체 종료, 패키지 설치가 끝난 Kaggle 이미지에서의 동작. 공개 소스·콜백 직렬화까지만 확인했다.
- RealBuilder/HostBuilder의 실제 영상·ULD 이미지 데이터셋 품질과 디코딩. ULD 프레임맵 track은 요청서가 남겨 둔 2c 범위다.
- Colab OAuth 1시간 이상 갱신·토큰 만료 중 대용량 전송·rclone 동시 설정 읽기. 파일 권한과 예외 경로만 확인했다.
- 실제 Google Drive의 중복 파일·삭제 권한·네트워크 중단·파일 생성 시각, 대규모 목록에서의 실행 시간.
- 저장소에 없는 LC·AA 앱의 실제 렌더링·모델 선택·list_complete 표시, 2c에서 넣을 최종 노트북 셀과의 일치.
- 이번 변경과 무관한 v4.32 전체 회귀 시험과 과거 체크리스트 전 항목의 재검토.
