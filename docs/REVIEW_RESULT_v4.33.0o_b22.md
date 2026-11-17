# v4.33.0o 검토 결과 — b22

검토일: 2026-11-16. `AGENTS.md`·이번 요청·b21 결과·2d의 b21 대응표·설계의 판정 보류/보호 모드/모름·변경 코드와 관련 시험을 검토했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle·메일·ntfy에는 접속하지 않았다.

**지정 일반 시험 675개와 기본·확장 퍼징 각 10개 항목은 모두 통과했다. P1~P4·Q1·Z4는 기존 발견 범위에서 해결됐다. 그러나 객체가 아닌 JSON을 실행기가 기다리지 않고 예외로 종료하는 높음 1건(R1)을 확인했다. arb/ 목록 실패 회차에 옛 요약으로 GPU를 기동하는 보통 1건(R2)도 있다. 2b 전 필수 수정은 R1이다.**

## 시험·재현 및 보관

| 실행 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 247개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 61개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 10개 성공. 입력 5,517개, 변형 46,239개 + 두 칸 조합 1,692개, 파일 숨기기 1,791회. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 10개 성공. 변형 102,586개 + 두 칸 조합 1,692개, 파일 숨기기 1,800회. 예외·뜻 위반 0건 |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 72개 성공, Keeper보다 먼저 실행 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 125개 성공 |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 34개 성공 |

Python은 `PYTHONDONTWRITEBYTECODE=1`, Node는 기존 `/tmp/node-v22.16.0-linux-x64/bin/node`, jsdom은 기존 `/tmp/b17_ctrl_deps/node_modules`를 NODE_PATH로 사용했다. npm 설치나 저장소 의존성 변경은 하지 않았다.

이전 `rLog/b20_*`·`b21_*`는 보존했다. 이번 결과는 다음 `rLog/b22_*`에 남겼다.

| 자료 | 내용 |
| --- | --- |
| `b22_run_tests.py`·`b22_test_status.json`·각 시험 `.log` | 지정 시험 9개 명령, 종료 코드 모두 0 |
| `b22_rerun_b21.py`·`b22_rerun_b21_status.json`·`b22_rerun_b21_{blocked,hold_monitor}.log` | b21_blocked_effect_probe.py·b21_hold_monitor_probe.js 원본 재실행, 종료 코드 모두 0 |
| `b22_rerun_older.py`·`b22_rerun_b20_status.json`·`b22_rerun_b20_{signals,night,collector,keeper}.log` | b21의 재실행기가 대상으로 삼았던 b20 재현 4개를 다시 실행, 종료 코드 모두 0 |
| `b22_non_object_probe.py`·동명 `.log` | 실제 snapshot·Executor.step·worker_cpu.run과 가짜 LocalStore에서 R1 재현 |
| `b22_master_shapes_probe.py`·동명 `.log` | 심판의 객체 아닌 외부 입력·판정 파일, 입력 모름별 쓰기 제한 확인 |
| `b22_state_gpu_probe.py`·동명 `.log` | 실제 MasterLoop·GpuLauncher와 가짜 Kaggle로 R2 재현 |

Python 재현은 저장소 최상위에서 `PYTHONDONTWRITEBYTECODE=1 python3 rLog/<파일>`로 실행한다. 지정 시험·옛 재현의 명령과 환경 설정은 실행 스크립트에 있다. b21_run_tests.py 자체는 과거 로그를 덮을 수 있으므로 b22 이름의 사본으로 실행했다.

## P1~P4·Q1·Z4 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| P1 차단된 배정·복구 요청의 후속 효과 | 해결 — 기존 발견 범위 | b21 재현에서 배정 파일 모름 회차의 TASK 잠금은 free로 유지된다. 복구 뒤 chunk=2의 실제 배정과 일치하는 E2 잠금이 생긴다. 복구 요청 모름 회차에도 접수·예약·배정은 생기지 않는다. 공식 회귀는 복구 후 요청 하나로 이어감을 확인한다. |
| P2 반환 보고의 잠금 모름 | 해결 — 기존 발견 범위 | 모름 회차에는 배정이 active이며 asks_handled도 비어 있다. 읽기 복구 뒤 기존 배정을 반환하고 새 decision·chunk의 정상 배정으로 이어진다. |
| P3 해제 대상 보류 모름 | 해결 — 기존 발견 범위 | b21 재현의 first_done은 null이고, 대상이 다시 읽히면 unhold=applied·active=false다. no_such_stop으로 영구 소비하던 경로가 재현되지 않는다. |
| P4 지속 모름 자동 알림 | 해결 — 기존 보류 파일 범위 | b21의 41회 연속 모름 재현에서 hold_on_long이 생성된다. 공식 Keeper 회귀는 메일·푸시·중복 억제를, CTRL 회귀는 판정 보류 띠의 진입·종료를 확인한다. 단, 아래의 state/grant 조기 반환 경계는 구별해야 한다. |
| Q1 모름 회차의 판정·후속 쓰기 | 해결 — 기존 발견 범위 | 입력 unknown(config 제외)이 있는 일반 보류 회차는 회차·알림 외 쓰기가 없다. 예전의 개별 경로 차단 후 후속 효과 진행은 그 앞에서 회차 전체를 멈춰 막는다. 새 경계인 R1·R2는 별도다. |
| Z4 동일 이름 파일 | 해결 — 기존 발견 범위 | snapshot의 file/dup 모름이 회차 단위 보류로 전달된다. 기존 hold/plan/done과 숨긴 옛 배정 재현에서 판정 쓰기를 하지 않고, 정상 관측 후 이어간다. 물리 중복 정리·rclone의 실제 동작은 T18 대상이다. |

b21의 순수 Keeper 재현은 alerts를 빈 목록으로 주므로 이번에도 mails/pushes가 없다. 0o는 심판이 만든 hold_on_long을 Keeper가 전달하는 구조이므로 이 옛 재현의 결과를 알림 수정 실패로 해석하지 않았다. 새 연결은 심판의 장기 보류 재현과 Keeper의 해당 알림 회귀를 나눠 확인했다.

## 새 발견

### R1 — 객체가 아닌 판정 JSON을 실행기가 ‘모름’으로 표시한 뒤 다시 직접 읽어 종료한다

| 칸 | 내용 |
| --- | --- |
| 번호 | R1 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | 객체 아닌 JSON의 실행기 기다림, 요청 미처리 |
| 위치 | `drive/scripts/executor.py:35` _non_object_unknown, `:178`~180 배정 순회, `:201`~210 _results_for/_lock, `drive/scripts/worker_cpu.py` run의 ex.step 호출 |
| 문제 | _non_object_unknown은 unknown 집합에 경로만 추가하고 files에는 원래 값을 남긴다. 이후 배정·결과·잠금 읽기의 여러 경로는 unknown을 확인하지 않고 원본에 .get을 호출한다. 따라서 ‘실행기는 모름으로 기다림’ 대신 AttributeError가 밖으로 전파되어 작업 프로세스를 종료시킨다. |
| 조건 | 실제 LocalStore에 정상 r1 배정·실행기 E1을 만든다. ① 별도 `arb/assign/aaa_bad.json` ② 별도 `arb/results/bad.json` ③ 자기 `arb/locks/task/1.json` 중 하나를 `[1]`로 저장한다. 각각 snapshot_unknown=[]이고 executor_unknown에는 해당 file: 경로가 생기지만 Executor.step은 `AttributeError: 'list' object has no attribute 'get'`로 실패한다. 실제 worker_cpu.run(max_steps=1)에 잘못된 배정 하나만 둔 경우도 같은 예외가 전파된다. 심판은 같은 파일을 정상적으로 보호 모드로 분류했다. |
| 확신 | 확인함 — `rLog/b22_non_object_probe.log`. CPU 재시작 상한의 후속 영향은 코드 추적 |
| 제안 | 실행기 전체의 파일 접근을 모름을 반영한 객체 읽기 함수로 통일하거나, 객체 아닌 파일을 소비자가 순회하는 사본에서 제거한다. 배정·결과·잠금·요청 최종화·실행형 잠금 탐색까지 대조한다. `[1]`·문자열·숫자 등 참으로 평가되는 비객체도 실제 step/run 회귀에 넣고, 복구 후 정상 작업 재개를 확인한다. |
| 2b 전 필수 여부 | **필수.** 작업 프로세스가 기다리지 않고 죽으며, 반복되면 WorkerSupervisor의 시간당 5회 기동 한도에 도달해 gave_up이 될 수 있다. 파일 복구 뒤에도 자동 처리기가 남지 않는 경로이므로 처리기 연결 전에 고쳐야 한다. |

### R2 — arb/ 목록 실패 회차에는 옛 깨우기 요약으로 GPU 기동을 계속할 수 있다

| 칸 | 내용 |
| --- | --- |
| 번호 | R2 |
| 심각도 | 보통 |
| 관점 | 스케줄링·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | 판정 보류 중 GPU 기동 없음, 실패 회차의 요약 재사용 |
| 위치 | `drive/scripts/arbiter.py:1939` 부근 state_unknown 조기 반환, `drive/scripts/arb_master.py:133` 부근 last_arbiter 유지, `drive/scripts/master_main.py:443`~448 GPU 기동 조건 |
| 문제 | arb/ 목록 실패는 일반 hold_on 분기보다 먼저 반환하므로 새 보류 요약을 쓰지 않는다. 그런데 acting은 true이고 last_arbiter는 이전 정상 회차의 요약으로 남는다. master_main은 acting만 확인하고 이 옛 wake를 GpuLauncher에 넘겨, 모름 회차에도 GPU 기동 요청을 낼 수 있다. |
| 조건 | GPU 없는 정상 회차에서 track 요청을 관측해 wake.gpu_needed=1을 만든다. 다음 실제 MasterLoop 회차에서 arb/ 목록만 실패시킨다. 결과는 acting=true·writes=0·unknown=[asks,state]·notes=[state_unknown]이며 last_arbiter는 같은 옛 객체다. master_main의 조건과 인수 전달을 그대로 적용한 실제 GpuLauncher는 가짜 status=complete 뒤 push를 호출하고 pushed를 반환했다. |
| 확신 | 확인함 — `rLog/b22_state_gpu_probe.log`. Kaggle은 가짜 함수이며 실제 기동하지 않음 |
| 제안 | GPU 기동은 이번 회차의 관측·쓰기 성공 및 보류 여부를 확인한 경우에만 허용한다. 회차 기록을 쓰지 않는 기존 안전 정책은 유지하더라도, 오래된 wake를 이번 판정의 근거로 재사용하지 않도록 한다. arb/ 목록 실패와 쓰기 실패 회차를 master_main 통합 회귀에 포함한다. |
| 2b 전 필수 여부 | 필수 아님. **2b 안에서 보완 가능하되 운영 배포 전에는 수정 권고.** 이번 재현에서 새 TASK 배정·CVAT 쓰기는 없고 불필요한 GPU 세션 기동이다. 다만 ‘모름 회차에는 GPU도 기동하지 않음’이라는 설명과는 어긋난다. |

## 검토 질문별 보충 판단

### 1·2. 회차 단위 보류와 internal_unknown

- **입력 모름의 쓰기 제한:** 기본·확장 퍼징의 파일 숨기기 1,791/1,800회가 모두 통과했다. 추가로 requests/workers/asks/signals/artifacts/grant/state 및 개별 file/dup 모름을 주었을 때도 회차·알림 외 쓰기가 없었다. View 생성은 사본 읽기·검사이고, 정상 판정 분기 앞에서 반환하므로 b21의 부분 효과 진행을 막는다.
- **우선순위·예외:** 보호 모드 사유가 함께 있으면 보호 분기가 먼저 반환한다. 자격이 없거나 믿을 수 없으면 not_arbiter로 반환한다. arb/ 목록 실패(state)는 기존 정책대로 회차 기록도 쓰지 않는다. 따라서 ‘입력 모름이면 회차·알림 외 쓰기 없음’은 맞지만, 모든 실패가 반드시 hold_on·hold_on_since에 기록되는 것은 아니다. R2는 이 조기 반환과 마스터 기동의 연결 문제다.
- **config:** config만 모름이면 전역 보류 대상이 아니다. 새 접수·신호·배정은 막고 기존 보고 마무리는 진행하는 기존 규칙을 유지한다. 사람 목록의 최초 읽기 실패·형태 오류는 MasterLoop 설정 검사에서 별도로 막는다.
- **안쪽 모름:** View가 산출물 `_files.json`의 형태 오류를 발견하면 unknown_files에 추가하고 사본을 None으로 바꾼다. 입력 unknown에는 없으므로 전역 hold_on이 되지 않는다. bad_input 알림과 res.internal_unknown에 경로가 남는다. 추가 재현에서 비객체 산출물 목록 하나 옆의 정상 track 요청은 접수·배정됐다. 이는 잘못된 바깥 파일 하나로 전체를 멈추지 않으려는 의도와 맞는다.
- **의존성:** 실행형 완료·채택의 _complete_deps, 데이터셋 목록이 모름일 때 학습 시작 보류, 시험 설정의 오염 대조 의존성은 유지된다. 이 범위에서 안쪽 모름을 부재로 소비해 b21의 배정/반환/해제 문제가 재발하는 반례는 찾지 못했다. 모든 관련 파일·부분 쓰기 조합을 전수 검증했다는 뜻은 아니다.
- **시험의 한계:** 현재 숨기기 불변 조건은 심판 쓰기를 검사한다. Executor.step/worker_cpu.run의 비객체 입력과 master_main의 옛 wake 사용은 그 범위 밖이어서 R1·R2를 잡지 못한다. 이번 수정의 객체 아닌 JSON 정책은 실행기 수준 회귀도 필요하다.

### 3. 객체가 아닌 JSON의 종류별 처리

추가 `b22_master_shapes_probe.py`는 `[1]`을 넣고 정상 요청을 함께 둔 실제 심판 회차를 실행했다.

| 종류 | 심판 결과 | 판단 |
| --- | --- | --- |
| 실행기 생존 신호 | bad_input으로 해당 파일 제외, 다른 정상 실행기/요청은 진행 | 형태 검사에 의한 격리 |
| 요청 | bad_input:not_object의 거절 접수 기록, 정상 요청 진행 | 맞음 |
| 신호 | bad_input:not_object로 rejected 완료, 정상 요청 진행 | 맞음 |
| 보고 | bad_input으로 보고 제외, 정상 요청 진행 | 맞음 |
| 산출물 목록 | bad_input·internal_unknown, 해당 산출물 의존 판단은 보류 | 전역 보류와 구분됨 |
| 자격 파일 | acting=false·not_arbiter, 판정 쓰기 없음 | 자격을 입증하지 못하므로 안전하게 정지. 자격이 없어 자기 거절 판정을 쓰지는 않음 |
| TASK 잠금 | not_object 사유의 보호 모드, 정상 요청도 배정하지 않음 | 맞음 |

snapshot이 비객체 JSON을 그대로 전달하는 변경 자체는 심판에서 동작한다. 그러나 실행기 쪽에서 같은 값을 모름으로 바꾸는 처리는 원본 객체를 제거하거나 모든 소비를 막지 못해 R1이다. 객체 아닌 자격은 실행기의 grant 모름으로 즉시 기다리지만, 배정·결과·잠금의 참으로 평가되는 리스트는 .get 예외가 났다. 빈 리스트·null처럼 거짓으로 평가되는 값만 시험해서는 이 차이를 잡지 못한다.

### 4. 판정 보류의 대가와 운영·복구 경계

- **이미 배정된 일:** 심판은 보류 중 보고 반영·승인·잠금 해제도 하지 않는다. 실행기는 심판의 hold_on을 직접 읽어 강제 종료하지 않으므로, 정상 자격·잠금으로 이미 승인받은 단계는 계속할 수 있고 보고를 남긴 뒤 기다린다. 확정 승인 전에는 confirm 보고가 처리될 때까지 기다린다. b21 재현의 end_under_unknown_hold는 이제 결과 기록이 생기지 않는 것이 정상이며, 공식 회귀도 새 정책에 맞게 변경됐다.
- **시간 제한:** 보류 중에는 expire도 실행되지 않아 심판이 시간 경과만으로 새 회수·재배정을 하지는 않는다. 다만 실행기의 호출 직전 권한 읽기까지 실패하면 Authority가 최대 10분 기다린 뒤 AuthorityLost로 멈춤 보고를 남길 수 있다. 회차 보류를 계속한다고 실행기 권한 대기 한도나 Kaggle 실행 한도가 늘어나지는 않는다. 복구 뒤 상태에 따라 정상 보고 또는 확인 필요로 이어가야 한다.
- **만료·해제:** 보류 만료와 release 처리도 다음 완전한 관측까지 미뤄진다. 예전처럼 다른 정상 보류를 같은 모름 회차에 먼저 해제하는 것은 이제 의도된 동작이 아니다. 확정된 만료/해제 시각이 지나도 보류 기간 동안 새 배정을 만들지 않으므로 안전 쪽으로 늦어진다.
- **밤 끝내기:** 입력 unknown이 남아 MasterLoop가 last_clean_at을 갱신하지 않는다. b20_night_probe 재실행에서 exit_reason=None이었다. 보류의 wake는 runnable/GPU=0, holds에 `(모름)`을 넣는다. 최대 11.2시간 종료는 별도 규칙이다. arb/ 목록 실패 시 옛 wake가 남는 R2는 별도로 보완해야 한다.
- **Keeper:** 최신의 같은 자격 회차가 있으면 보류 중에도 살아 있는 심판으로 계산해 새 마스터를 깨우지 않는다. hold_on_long은 메일·푸시로 보내며 같은 alert ID의 재알림은 mailed로 억제한다. 같은 이름 파일은 duplicate_path를 통해 알아보기 쉬운 제목의 메일도 만든다. 두 경로 모두 지정 Keeper 회귀를 통과했다.
- **관리자 정리:** 전체 시스템이 기다리는 비용을 선택한 만큼, 정상 회차에서 동작 가능한 경로의 중복이면 즉시 duplicate_path, 장기 지속이면 hold_on_long, CTRL 상단 보류 띠와 unknown 경로가 복구 안내를 제공한다. 실제 동일 이름 파일의 식별·내용 대조·한 개만 남기기·rclone 후속 읽기/쓰기는 T18에서 확인해야 한다.
- **관측 자체가 안 되는 경우:** 자격·arb/ 목록을 못 읽어 회차 기록을 갱신하지 못하는 경우에는 보류 시작 시각을 누적할 수 없다. 기존의 심판 회차 멈춤/깨우기 감시가 대신 보일 수 있으며, 모든 실패에서 정확히 30분 뒤 판정 보류 메일이 온다고 보장할 수는 없다. 이 경계는 운영 안내에서 구분하는 것이 좋다.
- **알림 한 번의 뜻:** 심판은 30분 초과 뒤 같은 since 기반 경로의 알림을 갱신한다. 파일 수가 구간마다 하나라는 뜻이며 매 회차 새 파일을 만들지는 않는다. Keeper의 동일 ID 억제가 실제 발송 중복을 막는다. 전송 직후 기록 전 중단의 기존 중복 가능성은 별도 한계다.

## 2b 전 최소 목록

1. **R1:** 실행기의 비객체 파일을 실제 기다림으로 소비하도록 고친다. 배정·결과·TASK 잠금뿐 아니라 실행형 잠금 탐색·요청 최종화도 함께 대조한다.
2. 실제 Executor.step·worker_cpu.run에서 비객체 입력→프로세스 생존/대기→파일 복구→정상 처리 재개의 회귀를 추가한다. 지정 시험·두 퍼징도 다시 통과시킨다.

**R2는 2b 안에서 수정 가능**하다. GPU 기동에 이번 회차의 관측·쓰기 성공을 연결하는 통합 회귀를 추가하고 운영 배포 전에는 옛 wake 재사용을 막는 것을 권한다. 실제 동일 이름 파일 정리·rclone 동작·계정 소유권·메일/ntfy 전달은 예행 연습에서 확인해도 된다.

## 점검했지만 문제가 없던 항목

- 일반 시험 675개, 기본·확장 퍼징 각각 10개 항목 통과.
- b21 P1의 배정/복구 요청 모름, P2의 반환 보고 모름, P3의 해제 대상 모름이 회차 보류로 차단되고 복구 후 이어감.
- b21 P4의 30분 초과 hold_on_long 생성, 보류 구간 시작 유지·종료·새 구간 처리.
- 입력 모름의 회차·알림 외 판정 쓰기 없음, config의 별도 처리.
- 심판의 비객체 외부 입력 격리·판정 파일 보호 모드와 산출물 목록 internal_unknown 전파.
- 일반 보류 회차의 wake가 GPU 필요 0·holds 모름으로 갱신되는 동작.
- Keeper의 보류 장기화 메일/푸시·중복 억제, CTRL의 판정 보류 띠와 정상 복구 시 제거.
- 변경하지 않은 수집기·접근 제어·배포/뿌리 코드의 지정 회귀.

## 시간이 모자라 보지 못한 항목·한계

- 실제 CVAT·Drive·Kaggle·Apps Script 권한·메일·ntfy·claude.ai 커넥터와 rclone 물리 중복 파일의 cat/moveto/rcat은 확인하지 않았다.
- 모든 internal_unknown 조합·모든 비객체 값·인계/채택/보고 순서·동시 장애와 복구를 전수 검증하지 않았다. R1은 실제 Executor와 worker_cpu.run의 예외, R2는 실제 MasterLoop·GpuLauncher에 가짜 목록 실패·Kaggle 함수를 연결한 재현이다.
- R1의 WorkerSupervisor가 실제 프로세스를 반복 기동해 gave_up까지 가는 전체 실행은 하지 않았다. worker_cpu.run의 예외 전파는 실행했고 기동 상한·gave_up 경로는 코드로 추적했다.
- v4.32 전체 회귀, 노트북 셀 전체 일치, Kaggle IPython 호환성, 아직 연결되지 않은 2b·LC·AA 처리기의 종단 백업/업로드/게시 경로는 이번 범위 밖이다.
