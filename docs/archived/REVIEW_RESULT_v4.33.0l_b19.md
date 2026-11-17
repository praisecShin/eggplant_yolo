# v4.33.0l 검토 결과 — b19

검토일: 2026-11-16. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0l.md`, b18 결과, 2d의 b18 대응표, 설계의 보호 모드·수집기 자동 요청·알림 및 관련 구현·시험을 확인했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle에는 접속하지 않았다.

**지정 시험은 모두 통과했다. Y1~Y4는 부분 해결, Y5·Y6은 기존 발견 범위에서 해결이다. 새 발견은 높음 1건·보통 4건(Z1~Z5)이다. 2b 연결 전에는 특히 Z1의 권한 모름·권한 철회 구분을 보완해야 한다.**

## 시험·재현 및 보관

| 시험 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 218개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 65개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 61개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 9개 성공. 변형 46,229개 + 두 칸 조합 1,692개. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 9개 성공. 변형 102,510개 + 두 칸 조합 1,692개. 예외·뜻 위반 0건 |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 61개 성공, RESULT True. Keeper보다 먼저 실행 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 118개 성공, RESULT True |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 32개 성공, RESULT True |

일반 시험 합계 623개, 기본·확장 퍼징 각 9개 항목이다. Python은 `PYTHONDONTWRITEBYTECODE=1`, Node.js는 기존 Linux v22.16.0, jsdom은 `/tmp/b17-js-approved/node_modules`를 사용했다. 실행 로그는 `rLog/b19_{arbiter,access,master,master_main,fuzz,fuzz7,collector,keeper,ctrl}.log`에 있다.

남아 있던 b18 스크립트도 다시 실행했다.

- `b18_plan_probe.py`: 계획 admin=true 변조에도 quarantine 유지, 강제 해제 차단.
- `b18_ctrl_probe.js`: 보류 모름을 다시 읽으면 대화상자가 닫히고 release 전송 없음.
- `b18_collector_probe.js`: 현재 공식 가짜 Drive(getId·searchFiles 포함)로 앞부분만 교체한 `b19_b18_collector_compat.js`를 실행했다. 중복 TASK 사건은 최신 하나로 합쳐지고, 잘못된 배열 목록을 넣는 부분에서는 이제 예외로 멈춘다. 따라서 전체 스크립트 종료 코드 1은 이 손상 사례의 차단 결과이며, 정상 시험 실패로 집계하지 않았다.
- b18 Keeper 직접 호출은 스크립트가 남아 있지 않았다. 같은 51개 실패 입력을 중요 표시 포함으로 다시 구성해 보호 알림 보존을 확인했다(`b19_keeper_probe.js`).

옛 스크립트 사본·호환본·재실행 로그와 새 재현 스크립트를 모두 `rLog/`에 보관했다. 새 재현은 `b19_signal_probe.py`, `b19_collector_probe.js`, `b19_duplicate_probe.py`, `b19_keeper_probe.js`이며 각각 같은 이름의 `.log`가 있다. JavaScript 실행 인수는 수집기 재현에 `apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs`, Keeper 재현에 `apps_script/G_keeper/Keeper.gs`이다. Python 재현은 저장소 최상위에서 실행한다.

## Y1~Y6 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| Y1 관리자 권한 | 부분 해결 | 계획 admin을 현재 권한 대신 사용하는 우회는 닫혔다. requester 대조와 독립 변형 비교도 추가됐다. 그러나 현재 신원 재계산이 실패했을 때 효과 순회를 막지 않는 Z1이 있다. |
| Y2 목록 형태 | 부분 해결 | top·지도·사건 키·종류·묶음 참조 검사는 추가됐고 기존 배열 손상 반례를 차단한다. 시각 문자열의 실제 유효성·일부 필수 칸은 검사하지 않아 Z2가 남는다. |
| Y3 같은 TASK 합치기 | 부분 해결 | 새 결정대로 미시도 사건을 최신 하나로 합치고 merged를 기록한다. 시도한 묶음 뒤 사건은 새 요청으로 분리된다. 그러나 옛 묶음이 늦게 끝나면 장부가 과거 상태로 돌아간다(Z3). |
| Y4 중복 방지 | 부분 해결 | attempt_at 선행 기록, file_id 보존, 10분 대기, 서로 다른 경로의 같은 RID 접수는 반영됐다. 실제 같은 이름 파일은 snapshot에서 하나로 합쳐져 duplicate_request 검사에 도달하지 않는다(Z4). |
| Y5 CTRL 제어 | 해결 — 기존 발견 범위 | allowed가 열기·전송에서 현재 조건을 다시 확인한다. 재관측 뒤 불허 동작은 대화상자를 닫고 읽기 전체 실패도 제어를 막는다. b18 재현과 공식 회귀 통과. |
| Y6 outbox 중요 알림 | 해결 — 기존 발견 범위 | 보호 모드 진입·종료 알림을 important로 표시하여 상한·시도 횟수에서 제외한다. 버린 일반 알림 키를 mailed에서 빼고 요약을 만든다. 중요 알림이 빠졌던 51개 입력 재현은 이제 중요 알림을 보존한다. 장기간 전달 불능 때의 크기 한계는 아래에 별도 설명한다. |

## 새 발견

### Z1 — 계획 재개 때 신원 확인 실패를 ‘보류’나 ‘거절’로 분리하지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | Z1 |
| 심각도 | 높음 |
| 관점 | 접근·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | Y1 현재 권한 확인, 모름은 막는 쪽으로 |
| 위치 | `drive/scripts/arbiter.py:470` 부근 _check_plans의 requester 대조, `:1021`~1025 process_signals, `:746` Release |
| 무엇이 문제인가 | 지금 신호 소유자의 권한을 재계산해도 now_who=None이면 효과 처리를 중단하지 않는다. admin만 false로 내려서 강제 선택은 무효 완료하고, admin을 사용하지 않는 해제 효과는 현재 권한이 사라져도 실행한다. |
| 일어나는 조건 | ① 관리자 강제 confirm_choice 계획 저장 직후 중단하고 다음 회차에 원 신호 owner만 빈 값으로 준다. protect=[]이고 `invalid:choice_not_open`으로 done을 쓴다. owner를 복구해도 done 때문에 다시 처리하지 않고 quarantine에 남는다. ② 정상 stop으로 hold를 만든 뒤, 관리자 원 신호를 연결한 G의 release 계획 저장 직후 중단한다. 원 관리자의 release 권한을 철회하고 재개해도 protect=[], unhold=applied, active=false다. `rLog/b19_signal_probe.log`. |
| 확신 | 확인함 — 실제 Sim·decide_round 여러 회차 실행 |
| 제안 | 현재 신원·권한의 ‘모름’과 확인된 권한 철회를 구분한다. 소유자 모름은 계획을 유지하고 defer한다. 현재 권한이 없으면 아직 적용하지 않은 효과를 실행하지 않고 정책에 맞게 명시적으로 거절한다. G 원 신호 연결도 같은 규칙을 사용한다. |

### Z2 — 잘못된 시도 시각이 형태 검사를 통과하여 10분 대기를 우회한다

| 칸 | 내용 |
| --- | --- |
| 번호 | Z2 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | Y2 목록 검사, Y4 검색 재확인 대기 |
| 위치 | `apps_script/G_collector/Collector.gs:458`~473 pendingProblem_, `:560` 부근 attempt_at 대기, `:573` created |
| 무엇이 문제인가 | attempt_at은 문자열인지만 확인한다. 날짜가 아닌 문자열은 Date.parse 결과가 NaN이 되어 대기 조건이 false가 되고 곧바로 생성 경로로 들어간다. batch.at 누락도 통과해 created 없는 요청을 만든다. |
| 일어나는 조건 | 정상 형태의 사건·묶음에 attempt_at='broken'을 넣고, 앞선 생성으로 같은 ID 요청 파일은 존재하되 검색에서 잠시 안 보이게 한다. pendingProblem_은 빈 문자열을 반환하고 waiting 없이 같은 이름 파일을 하나 더 만든다(physical_files=2). 별도 batch.at 삭제 사례도 검사 통과 후 created 없는 요청을 생성했다. `rLog/b19_collector_probe.log`의 invalid_attempt_problem·invalid_attempt_flush·missing_at_body. |
| 확신 | 확인함 — 실제 flushAutoRequests_·가짜 검색 지연 |
| 제안 | 사건·묶음의 필수 시각과 optional attempt_at을 실제로 해석 가능한 날짜인지 검사한다. 해석할 수 없는 ‘시도함’은 안전한 재생성 근거가 아니므로 관리자가 복구할 때까지 보류한다. |

### Z3 — 대기하던 옛 묶음의 재시도가 최신 장부를 과거로 덮는다

| 칸 | 내용 |
| --- | --- |
| 번호 | Z3 |
| 심각도 | 보통 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | Y3 합치기 경계·최신 사건 기록 |
| 위치 | `apps_script/G_collector/Collector.gs:556`~563 대기·continue, `:585` 부근 log.items 갱신 |
| 무엇이 문제인가 | 같은 TASK의 옛 시도 묶음이 검색 대기하는 동안 새 묶음은 먼저 발행할 수 있다. 옛 묶음이 나중에 성공하면 log.items를 조건 없이 덮어 최신 updated·이름·요청 연결이 과거 사건으로 돌아간다. |
| 일어나는 조건 | TASK 11 _vf 사건의 첫 createFile을 실패시켜 attempt_at만 남긴다. 1분 뒤 _vfdf 사건을 넣고 flush하면 옛 묶음은 waiting=1, 새 묶음은 성공하고 장부는 updated=02:00·_vfdf다. 10분 더 지나 flush하면 옛 묶음이 발행되면서 장부가 updated=01:00·_vf로 바뀐다. `rLog/b19_collector_probe.log`의 ledger_before·ledger_after. |
| 확신 | 확인함 — 실제 보낼 목록·두 묶음·시간 이동 재현 |
| 제안 | 최신 장부 갱신을 사건 updated·동률 시 입력 시각으로 비교하고, 이미 기록한 더 최신 사건을 오래된 묶음의 완료가 덮지 않게 한다. 늦은 발행 자체의 이력은 요청별로 보존한다. |

### Z4 — 같은 이름의 중복 파일은 심판 입력 전에 합쳐져 중복 알림이 없다

| 칸 | 내용 |
| --- | --- |
| 번호 | Z4 |
| 심각도 | 보통 |
| 관점 | 복구·동시성 |
| 종류 | 코드·시험 |
| 관련 항목 | Y4 같은 이름 파일 둘·duplicate_request |
| 위치 | `drive/scripts/arb_io.py:280`~286 snapshot의 seen[e.path], `:306` files[path]; `drive/scripts/arbiter.py:529` 중복 검사; `tests/test_arbiter_433.py:1230` 부근 중복 회귀 |
| 무엇이 문제인가 | snapshot은 파일 경로를 사전 키로 사용하므로 같은 폴더·같은 이름의 물리 파일 둘은 한 Entry로 덮인다. 그 뒤의 심판 중복 검사는 서로 다른 경로에 같은 RID가 있을 때만 동작한다. 파일 ID도 보존하지 않아 같은 이름 파일의 최신본 선택을 이 코드로 보장할 수 없다. |
| 일어나는 조건 | 가짜 Store.list가 requests/의 같은 경로를 서로 다른 수정 시각으로 두 번 반환하게 했다. snapshot_copies=1, unknown=set(), duplicate_alerts=[]다(`rLog/b19_duplicate_probe.log`). 공식 회귀는 requests/와 relabel/requests/라는 서로 다른 경로를 사용하므로 이 경우를 시험하지 않는다. 실제 rclone의 중복 경로 cat·rcat 동작까지 실행한 것은 아니다. |
| 확신 | 확인함 — 실제 snapshot·decide_round에 중복 목록 주입. 외부 rclone의 후속 영향은 미확인 |
| 제안 | 경로를 사전으로 합치기 전에 중복을 감지해 알림·모름을 전달한다. 물리 파일 ID로 최신본을 고르거나 관리자가 정리할 때까지 보류하는 정책을 정한다. T17에서 Apps Script 검색뿐 아니라 실제 마스터 읽기·실행기 완료 쓰기까지 확인한다. |

### Z5 — 한 번도 성공하지 못한 수집기는 계속 실패해도 멈춤 알림이 없다

| 칸 | 내용 |
| --- | --- |
| 번호 | Z5 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | Y2 관리자 감지 경로, last_ok 감시 보충 |
| 위치 | `apps_script/G_keeper/Keeper.gs:315`~321 kpCollectorAt_, `:248` 멈춤 판정; `apps_script/G_collector/Collector.gs:378` last_ok 기록 |
| 무엇이 문제인가 | last_ok가 null이면 매번 갱신되는 실패 실행의 time으로 대체한다. 최초 설치부터 계속 실패하거나 성공 이력이 없는 상태에서 목록 복구가 필요한 경우에는 마지막 성공 부재가 계속 ‘방금 관측’으로 바뀌어 감시 임계값을 넘지 못한다. |
| 일어나는 조건 | last_ok=null, ok=false, time=현재 시각인 실제 생존 기록 형태를 2시간 간격으로 넣었다. kpCollectorAt_의 age는 두 번 모두 0초이고 collector_stale 메일은 false다. `rLog/b19_keeper_probe.log`의 never_success. 성공 이력이 한 번이라도 있는 일반 실패 회귀는 통과한다. |
| 확신 | 확인함 — 실제 시각 해석·keeperDecide_ 호출 |
| 제안 | ‘옛 형식이라 last_ok 칸이 없음’과 ‘현재 형식이고 성공한 적 없음’을 구별한다. 최초 관측/최초 실패 시각을 보관해 성공 부재가 20분 지속되면 알린다. |

## 질문별 보충 판단

- **현재 관리자·G·사람 목록:** 계획 admin·requester 변형 불변 조건은 기존 Y1 변조를 잡는 데 유효하다. 그러나 소유자 정보 유실·현재 권한 철회는 그 변형 조건 밖이며 Z1을 놓친다. unknown에 config가 들어온 회차는 decide_round가 신호 처리 자체를 건너뛰므로 임의 관리자 권한을 주지 않는다. 반면 개별 신호 owner의 빈 값은 config 모름과 같은 차단을 받지 않는다. G 신호도 원 사람의 현재 권한을 재계산하지만, 실패 결과를 실제 효과 순회 중단에 연결해야 한다.
- **목록 손상 때 중단:** 잘못된 지도를 빈 목록으로 덮어 사건을 잃는 것보다 수집 실패로 유지하는 선택이 맞다. 배열·키 불일치·없는 사건 참조 등 기존 손상은 막는다. CTRL은 last.ok=false·last.error를 표시해 관리자가 볼 수 있다. 기존 성공 기록이 있으면 Keeper가 마지막 성공 시각으로 멈춤을 알리지만 최초 성공 부재는 Z5이며, 시각 검사의 빈틈은 Z2다.
- **합치기 결정:** 11/16의 최신 상태 하나로 합치는 정책을 이번 검토 기준으로 사용했다. 미시도 batch에 loose 사건을 추가하고 latestPerTask_로 updated·동률 at 순으로 고르는 기본 동작은 맞는다. 시도한 묶음은 새 사건을 받지 않으며 별도 요청이 된다. 두 요청의 발행 완료 순서가 바뀔 때 최신 장부가 퇴행하는 Z3이 남는다.
- **ID와 대기:** 자신이 만든 file_id가 기록돼 있으면 검색에 기대지 않고 이미 만든 것으로 처리하는 기본 경로는 확인했다. 이는 관리자가 해당 파일을 지우거나 ID를 손상시키지 않았다는 전제다. ID 없는 응답 중단은 검색·10분 대기로 수렴시키며 10분 이후 중복 가능성은 구현 설명에 명시된 한계이므로 그 틈 자체를 새 발견으로 반복하지 않았다. 다만 생긴 같은 이름 중복의 실제 관측은 Z4다.
- **CTRL:** 운영/시험 변경의 dirs·people·act 초기화, 늦은 읽기 버리기, 현재 allowed 재검사, 권한·보류·보호 모드 변화 시 대화상자 닫기를 확인했다. 정상 폴더 둘이 있는 경우와 이름 중복의 차단 시험도 통과한다. 전체 읽기 실패는 ready를 무효화한다. 이미 시작한 create_file 호출 이후 환경 변경까지 외부 쓰기를 취소하는 보장은 없으며, 이번 검토에서 새 환경을 읽지 못해 옛 폴더로 전송하는 기존 반례는 재현되지 않았다.
- **outbox:** 보호 모드 진입·종료 항목은 실제 important 표시가 붙고 상한·30회 제한에서 제외된다. 51개 실패 직접 호출에서 중요 알림은 보존되고 일반 항목 하나만 dropped로 돌아온다. dropped 키의 mailed 제거·요약 생성은 공식 시험으로 확인했다. 일반 알림을 다시 만들도록 한 정책 때문에 상태가 지속되면 넘침·재생성이 되풀이될 수 있다. 중요 채널 전송이 영구 실패하고 보호 상태가 반복 전환되면 중요 항목은 상한 없이 누적될 수 있다. 이는 현재 설계가 ‘상한·횟수와 상관없이 남김’을 택한 결과이며, 크기 상한이 있다고 해석하면 안 된다. 장기 운영에서는 중요 상태 알림의 구간별 요약·최신 상태 보존 방침을 별도로 정하는 것이 좋다. 이미 명시된 전송 직후 기록 전 중단의 중복 가능성은 재보고하지 않는다.

## 2b 시작 전 최소 목록

1. Z1: 현재 권한의 모름·거절·허용을 재개 경로의 효과 적용과 연결하고, 소유자 모름은 완료로 소비하지 않는다.
2. Z2·Z3: 보낼 목록의 시각 검증과 장부의 최신 사건 보존을 보완한다.
3. Z4: 같은 이름의 물리 파일 중복을 저장소 단계에서 감지하고, T17에 실제 rclone·완료 쓰기 경로를 포함한다.
4. Z5: 성공 이력이 없는 실패 수집기도 시간 경과로 감지한다.
5. 이 보완 후 2b 처리기의 실제 핸들러를 연결할 때 백업 선행·사람 라벨 보호·단일 소유·권한 변경·정지/확정 경계를 가짜 CVAT로 시험한다.

## 점검했지만 문제가 없던 항목

- 일반 시험 623개, 기본·확장 퍼징 각각 9개 항목 통과.
- b18 계획 admin 변조의 강제 해제 우회 차단, requester 불일치 보호 모드.
- 잘못된 events 배열을 조용히 저장하던 반례 차단.
- 새 정책에 따른 미시도 같은 TASK 사건의 최신 하나 합치기·merged 기록.
- file_id 보존 및 정상 attempt_at의 검색 대기 경로.
- CTRL 대화상자의 보류 모름 이후 전송 차단, 전체 읽기 실패·중복 루트 이름 차단.
- 보호 모드 중요 알림 보존, 수집기의 기존 성공 이후 연속 실패 감시.

## 시간이 모자라 보지 못한 항목·한계

- 실제 서비스·계정·권한·메일/ntfy·Drive 검색 지연은 지침에 따라 접속하지 않았다. rclone의 동일 이름 파일 cat·rcat 결과는 T17에서 확인해야 한다.
- 모든 파일 형태·다중 손상·장기 알림 누적·모든 쓰기 중단 조합을 전수 검증하지 않았다.
- v4.32 전체 회귀, 노트북 전체 셀 일치, 실제 Kaggle IPython과 아직 연결 전인 2b·LC·AA앱의 종단 처리는 이번 검토 범위 밖이다.
