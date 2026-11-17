# v4.33.0k 검토 결과 — b18

검토일: 2026-11-16. `AGENTS.md`와 `REVIEW_REQUEST_v4.33.0k.md`, b17 결과, 2d 구현 대응표, 설계의 보호 모드·알림·CTRL 제어 규칙과 수정 코드·시험을 확인했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle에는 접속하지 않았다.

**지정 시험은 모두 통과했다. X1·X3·X6은 부분 해결, X2·X4·X5는 해결로 판단한다. 기존 b17 반례의 수정은 확인했지만, 추가 경계에서 높음 3건·보통 3건(Y1~Y6)을 발견했다. 2b 연결 전에 Y1~Y3을 먼저 보완해야 한다.**

## 로그 보관·시험 결과

요청대로 `/tmp/b17_*`의 실행 가능한 추가 재현 스크립트 네 개를 다시 실행해 해당 `.log`를 갱신하고, `/tmp/b17_*.log` 13개를 `rLog/`에 복사했다. 기존 일반 시험 로그는 b17 때의 결과이며, 네 추가 재현 로그만 현재 0k 코드의 재실행 결과다.

| b17 재현 | 현재 결과 |
| --- | --- |
| `b17_arb_probe.py` | plan_effects_mismatch로 보호 모드. 정지 완료 기록·새 배정 없음 — 기존 X1 반례 차단 |
| `b17_ctrl_probe.js` | 시험 폴더 없음 → 정지 버튼 비활성, 운영 폴더로 전송 없음 — X2 반례 차단 |
| `b17_ctrl_unknown.js` | 보류 ‘읽지 못함’, 깨우기 비활성, 오류 띠 표시 — 기존 X6 반례 차단 |
| `b17_collector_probe.js` | 옛 가짜 Drive에 새 의존 함수 searchFiles가 없어 `reqDir.searchFiles is not a function`. 사건은 pending=1로 유지되지만 이 실행만으로 X3 해결을 판정할 수 없음 |

수집기는 현재 공식 시험의 가짜 Drive(searchFiles 포함)로 같은 실패를 다시 주입했다. 생성 실패 후 다음 회차에 같은 ID로 요청을 만드는 것을 확인했다. 아래 추가 경계 재현도 이 가짜 환경을 사용했다.

| 지정 시험 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 211개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 65개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 61개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 8개 성공. 변형 46,229개 + 두 칸 조합 1,692개. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 8개 성공. 변형 102,385개 + 두 칸 조합 1,692개. 예외·뜻 위반 0건 |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 44개 성공, RESULT True. Keeper 시험보다 먼저 실행 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 112개 성공, RESULT True |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 24개 성공, RESULT True |

일반 시험 합계 585개, 퍼징 기본·확장 각각 8개 항목이다. Python에는 `PYTHONDONTWRITEBYTECODE=1`을 설정했다. Linux Node.js v22.16.0과 기존 `/tmp/b17-js-approved/node_modules`의 jsdom을 사용했다. 새 시험 로그는 `rLog/b18_{arbiter,access,master,master_main,fuzz,fuzz7,collector,keeper,ctrl}.log`에 있다.

추가 재현 코드는 `/tmp/b18_plan_probe.py`, `/tmp/b18_collector_probe.js`, `/tmp/b18_ctrl_probe.js`에 작성했고 결과는 `rLog/b18_{plan,collector,ctrl}_probe.log`에 남겼다. Keeper outbox 직접 호출 결과는 `rLog/b18_keeper_probe.log`이다. 이 파일들은 실패를 의도적으로 재현하는 탐침이므로 종료 코드 0이 결함 없음이라는 뜻은 아니다.

## X1~X6 반영 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| X1 계획 대조 | 부분 해결 | 효과 일부 삭제·중복·치환·순서, sid·kind·target 대조는 반영됐고 기존 반례는 차단된다. 그러나 계획의 admin은 그대로 실행 권한이 되어 값 손상으로 일반 사용자 강제 해제가 가능하다(Y1). |
| X2 환경 전환 | 해결 — 기존 발견 범위 | 환경 전환 때 dirs·people·act를 비우고 늦은 이전 읽기를 버린다. 전송도 대화상자 환경·폴더를 확인한다. 기존 운영 폴더 오전송 반례 및 공식 시험 통과. 같은 환경 안의 대화상자 상태 재확인은 Y5다. |
| X3 자동 사건 재시도 | 부분 해결 | 목록 선행 저장과 요청 ID 보존으로 정상 형태 파일의 생성·장부 실패는 재시도한다. 그러나 목록 형태 손상으로 신규 사건 누락(Y2), 두 사건의 중복 TASK 묶음(Y3), 검색 지연 때 물리 파일 중복(Y4)이 남는다. |
| X4 보호 모드 재진입 알림 | 해결 — 기존 발견 범위 | 정상→보호 재진입을 새 사건으로 알리고 종료 때 이전 보호 키를 잊는다. 실제 Keeper 세 번 실행 회귀 시험 통과. 전달 실패 보관은 추가됐으나 outbox 용량 초과 유실은 Y6이다. |
| X5 생존 기록 | 해결 | 수집기의 최상위 time·ok와 last.time·last.ok가 같은 실행 결과다. Keeper는 time 및 옛 last.time을 지원한다. 실제 수집기 산출물을 읽는 연결 시험 통과. |
| X6 보류 모름 표시 | 부분 해결 | 파일·목록 읽기 실패를 모름으로 표시하고 새 버튼은 막는다. 이미 연 대화상자는 새 읽기로 모름이 확인돼도 전송할 수 있다(Y5). |

## 새 발견

### Y1 — 계획의 admin 손상으로 일반 사용자의 강제 해제가 허용된다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y1 |
| 심각도 | 높음 |
| 관점 | 접근·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | X1 계획 신뢰, 관리자 강제 해제 |
| 위치 | `drive/scripts/arbiter.py:434` View._check_plans, `:796` ConfirmChoice.judge, `:1012` process_signals |
| 무엇이 문제인가 | 계획의 admin이 신호 소유자의 실제 권한과 대조되지 않고 `_admin`으로 직접 전달된다. 형태상 올바른 false→true 손상이면 보호 모드를 우회해, 아직 선택할 수 없는 격리 TASK를 일반 사용자가 강제로 풀 수 있다. |
| 일어나는 조건 | approved_sim의 E1 종료 확인 없이 heartbeat만 만료시켜 TASK 7을 quarantine으로 만든다. 일반 사용자 M2의 `confirm_choice(choice='ok',force=true)` 계획을 쓴 직후 중단한다. 정상 재개에서는 `invalid:choice_not_open`이며 quarantine 유지다. 저장된 계획의 admin만 true로 바꾸면 `protect=[]`, 효과 lock=applied, TASK state=free가 된다. 계획 저장 직후 중단 상태에서 비교했으며 완료 파일 삭제는 사용하지 않았다. `rLog/b18_plan_probe.log`. |
| 확신 | 확인함 — 실제 decide_round와 Sim 여러 회차 실행 |
| 제안 | 관리자 권한을 쓸 때 원 신호의 소유 계정·현재 관리자 권한을 다시 확인한다. 계획 메타데이터가 대조 결과와 다르면 보호 모드로 다룬다. admin·requester 변형에 대한 독립 권한 불변 조건을 시험에 추가한다. |

### Y2 — 보낼 목록의 events가 배열이면 사건이 저장되지 않고 사라진다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y2 |
| 심각도 | 높음 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | X3, 손상된 auto_pending.json |
| 위치 | `apps_script/G_collector/Collector.gs:451`~455 readPending_, `:466`~479 queueHits_, `:244`~245 스냅숏 확정 |
| 무엇이 문제인가 | JSON 해석 성공만 검사하고 events·batches가 객체 지도인지는 확인하지 않는다. events=[]도 통과하여 문자열 사건 키를 배열 속성으로 추가하지만 JSON.stringify는 그 속성을 저장하지 않는다. 신규 사건은 queued로 집계된 뒤 실제 파일에는 남지 않고 스냅숏만 앞으로 진행한다. |
| 일어나는 조건 | 첫 정상 수집 뒤 `auto_pending.json`을 `{"events":[],"batches":{}}`로 둔다. 다음 수집에서 _uld→_vf 전환을 관측하면 `queued=1`, `export=0`, `pending=0`, requests=0, 저장 목록은 여전히 events=[]다. 바뀐 이름은 스냅숏에 저장되어 다음 회차에는 재감지하지 않는다. `rLog/b18_collector_probe.log`의 array_corruption. 누락된 지도도 `{}`로 조용히 바꾸는 경로가 있다. |
| 확신 | 확인함 — 실제 collect·가짜 Drive 파일 손상 주입 |
| 제안 | 읽을 때 최상위 객체, 필수 지도, 사건·batch 내용과 상호 참조까지 검증한다. 손상은 예외로 올리고 스냅숏·목록을 덮지 않는다. 문법 오류 외에 유효한 JSON의 배열·필수 칸 누락을 시험한다. |

### Y3 — 같은 TASK의 서로 다른 사건을 한 요청으로 묶어 한 작업으로 축약한다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y3 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | X3, 검토 단계가 바뀔 때마다 export |
| 위치 | `apps_script/G_collector/Collector.gs:507`~511 묶기, `:529` TASK 목록, `:539`~545 사건 처리 완료; `drive/scripts/executor.py:264`~300 _step_read |
| 무엇이 문제인가 | 사건 키에는 updated가 있지만 batch는 같은 종류의 모든 loose 사건을 합친다. 같은 TASK가 두 번 등장하면 tasks=['11','11']인 하나의 요청이 된다. 실행기는 `(assign, task)` 기억과 TASK별 결과로 처리하므로 두 사건이 독립된 작업으로 유지되지 않는다. 수집기는 두 사건 모두 요청을 만들었다고 장부에 남기고 목록에서 제거한다. |
| 일어나는 조건 | _uld→_vf를 관측해 사건 저장은 성공시킨 뒤 cvat_tasks.json 쓰기만 한 번 실패시킨다. 다음 수집 전에 같은 TASK를 _vfdf로 바꾼다. 기존 _vf 사건과 새 _vfdf 사건이 함께 쌓여 `export=2`, 요청 1개, payload tasks=['11','11'], pending=0이 된다. `rLog/b18_collector_probe.log`의 snapshot_failure·two_events_real·two_events_payload. _step_read의 mem 및 결과 키가 TASK 하나로 합쳐지는 것은 코드로 확인했다. |
| 확신 | 확인함 — 실제 collect의 중단·다음 회차 재현과 실행기 코드 추적 |
| 제안 | 한 batch에 같은 TASK의 다른 사건을 넣지 말고 사건 시각 순으로 별도 요청을 만든다. 사건을 의도적으로 최신 하나로 합칠 정책이라면 ‘바뀔 때마다’ 계약·집계·이력을 그 정책에 맞춰 명시해야 한다. |

### Y4 — 요청 생성 뒤 장부 실패와 검색 지연이 겹치면 같은 이름 파일이 중복된다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y4 |
| 심각도 | 보통 |
| 관점 | 복구·동시성 |
| 종류 | 코드·시험 |
| 관련 항목 | X3, Drive searchFiles 반영 지연 |
| 위치 | `apps_script/G_collector/Collector.gs:523`~534 존재 확인·생성, `:551`~554 requestExists_ |
| 무엇이 문제인가 | 요청 ID는 보존하지만 기존 파일 존재 여부는 검색 결과만으로 판단한다. 이미 만든 파일을 검색이 일시적으로 보여주지 않으면 createFile을 다시 호출해 같은 RID·같은 이름의 물리 파일이 여러 개 생긴다. |
| 일어나는 조건 | 정상 요청 생성 직후 auto_requests.json 쓰기를 실패시킨다. 다음 회차의 requests.searchFiles만 빈 목록을 돌려주도록 지연을 모형화하면 같은 이름 `REQ_<동일ID>__export__pending.json` 두 개가 남는다. `rLog/b18_collector_probe.log`의 ledger_fail·index_lag_retry·physical_duplicate_names. 실제 Drive의 지연 발생 빈도는 측정하지 않았다. |
| 확신 | 확인함 — 가짜 검색 지연에서 중복 생성. 실제 외부 작업의 이중 실행까지는 확인하지 않음 |
| 제안 | 검색의 ‘없음’을 즉시 재생성 근거로 삼지 않는 재확인·보류 정책과 중복 파일 처리 절차를 둔다. 생성 뒤 파일 ID를 보관하는 경로도 추가하되, 생성 응답 자체가 끊긴 구간은 별도로 다룬다. 동일 RID가 중복 열거될 때 저장소·실행기가 어떻게 수렴하는지도 시험한다. |

### Y5 — 새로고침으로 보류 모름이 확인돼도 열린 해제 대화상자는 전송한다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y5 |
| 심각도 | 보통 |
| 관점 | 접근·동시성 |
| 종류 | 코드·시험 |
| 관련 항목 | X6, CTRL앱 새로고침·대화상자 겹침 |
| 위치 | `apps/ctrl/index.html:336` openDlg, `:366`~376 send, `:241` ready |
| 무엇이 문제인가 | 전송 직전에는 환경·폴더만 확인하고 현재 보류 모름·보호 모드·권한·생존 판정을 다시 확인하지 않는다. 같은 환경의 새 읽기가 성공하면 대화상자는 유지되어, 새 화면이 해제를 막았다고 알린 뒤에도 이전 대화상자의 확인 버튼이 신호를 만든다. |
| 일어나는 조건 | 정상 hold에서 해제 대화상자를 연다. 그 hold의 다운로드를 실패시키고 새로고침한다(자동 갱신도 같은 loadAll 경로). 화면은 ‘읽지 못함 — 깨우기·해제를 막았습니다’로 바뀌지만 대화상자는 열려 있다. 확인을 누르면 release 신호가 생성된다. `rLog/b18_ctrl_probe.log`. 이 재현은 화면 제어 우회이며 심판의 별도 안전 확인까지 우회했다고 주장하는 것은 아니다. |
| 확신 | 확인함 — jsdom에서 실제 클릭·읽기 실패·create_file 확인 |
| 제안 | 대화상자에 읽기 세대를 저장하고 새 관측이 반영되면 닫거나 재확인을 요구한다. send에서 동작별 현재 허용 조건을 다시 계산한다. |

### Y6 — 전송 실패 알림이 50개를 넘으면 앞 알림을 첫 실패 직후 버린다

| 칸 | 내용 |
| --- | --- |
| 번호 | Y6 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | Keeper outbox 재시도 |
| 위치 | `apps_script/G_keeper/Keeper.gs:400`~403 mailed·outbox 구성, `:439`~453 kpSendOutbox_ |
| 무엇이 문제인가 | kpSendOutbox_는 재시도가 남아도 마지막 50개만 반환한다. keeper는 목록에 넣은 알림 키를 이미 mailed에 기록하므로 잘린 알림은 재생성도 억제된다. 30번 재시도 전에 중요한 보호 모드 알림이 조용히 사라질 수 있다. |
| 일어나는 조건 | 보호 알림을 첫 항목으로 하고 총 51개 메일 모두 한 번 실패시켰다. 반환은 50개, tries=1, 보호 알림은 없음이다(`rLog/b18_keeper_probe.log`). 기존 실패 50개에 새 알림이 들어오는 경우도 같은 경로다. |
| 확신 | 확인함 — 실제 kpSendOutbox_와 전송 실패 모형 |
| 제안 | 용량 초과를 명시적으로 기록하고 중요 알림을 보존한다. 일반 알림을 묶거나 요약하되 탈락한 알림을 영구히 ‘보냄’으로 확정하지 않는다. 넘침·회복을 회귀 시험에 넣는다. |

## 검토 질문별 보충

- **효과 재계산 가정:** 현재 7종 SignalKind.effects는 모두 신호의 kind·choice·type만 사용한다. 현재 상태·세션·시각에 따라 목록이 바뀌는 구현은 없다. 독립 expected_effects도 같은 규칙을 별도로 기술한다. 대상 식별자와 목록 순서 대조는 기존 X1에 유효하다.
- **대조 제외 세 경우:** 읽을 수 있는 완료 파일이 있으면 process_signals도 sid를 건너뛴다. 원 신호가 없거나 unknown이면 signals 순회에 들어가지 않는다. 형태가 틀린 신호는 완료를 rejected로 기록하고 계획 효과를 실행하지 않는다. 이 세 경우 자체에서 손상 계획의 효과가 실행되는 반례는 찾지 못했다. 단, sid·kind 불일치는 신호를 못 읽어도 먼저 보호 모드로 보낼 수 있다.
- **admin·requester·seq:** admin의 의미 손상은 Y1이다. requester는 원 소유자와 대조되지 않아 정지 기록의 by 같은 행위자 표기가 잘못될 수 있다. seq는 intlike 형태만 확인하고 전체 최대값+1에 사용한다. 숫자 변형이 회차 사이 실제 신호 처리 순서를 정한다는 경로는 찾지 못했다. 신호 순회는 파일 생성 시각·이름 순이다.
- **퍼징 정답:** expected_effects·plan_mismatch는 SignalKind.effects를 호출하지 않아 효과 목록에 대해서는 독립성이 생겼다. 구조·필수 칸 판정은 여전히 input_problem을 빌리며, admin의 ‘이 사람이 관리자여야 한다’는 불변 조건은 없다. 따라서 Y1을 현재 통과 결과로 배제할 수 없다. 수집기·CTRL·Keeper 상태 기계는 이 Python 퍼징의 범위 밖이다.
- **CTRL 환경:** 운영·시험 폴더가 둘 다 존재해도 각기 다른 NAMES와 환경별 캐시 키를 사용한다. 세대 확인으로 늦은 옛 읽기는 버린다. 다만 같은 이름의 루트 폴더가 여러 개면 findTop은 첫 검색 결과를 저장하며, 중복 후보·기존 캐시의 실제 폴더를 재검증하지 않는다. 실제 Drive의 중복 이름 구성은 확인하지 않았다. 같은 환경에서 열린 대화상자는 Y5다. 심판 생존 표시는 신선한 회차·동일 자격을 기준으로 하며 Keeper의 ‘방금 자격을 받아 부팅 중’ 조건까지 표시하지는 않는다.
- **목록 순서:** 사건→스냅숏→batch ID→요청 파일→장부→목록 제거의 기본 복구 순서는 맞는다. 공식 시험과 호환 재현에서 요청 생성·장부 실패 후 재시도, 상태 이름이 바뀐 요청 발견은 통과했다. 의미상 손상된 목록·사건 축약·검색 지연은 Y2~Y4다. backfill은 쓰기를 잠금 안에서 하지만 hits를 위한 스냅숏·장부 읽기는 잠금 전에 수행한다. queueHits_가 잠금 안에서 최신 장부·목록을 다시 읽어 같은 updated 사건의 단순 중복은 거른다. 모든 경합 조합을 전수 실행하지는 않았다.
- **Keeper 알림:** 구간 종료 때 protect 키를 지우고 새 진입을 알리는 경로, 상태 회복 후 collector_stale·wake_done_unknown·hold_unknown 이력 해제, 메일·ntfy 실패 보관·성공 후 제거는 공식 시험으로 확인했다. 주제 이름과 수신 주소는 outbox에 저장하지 않고 현재 Script Properties에서 전송에만 사용한다. outbox는 50개·시도 30회로 제한되므로 항목 수가 무한히 누적되지는 않으나 제한 적용은 Y6처럼 유실을 만든다. mailed는 이전 것 200개에 새 키를 붙여 저장하므로 한 회차의 신규 알림 수까지 200개로 제한되는 것은 아니다.
- **keeper.json 모름:** 해당 회차에 상태·심판 알림을 억제하고 기록 읽기 실패를 알리는 처리는 있다. 이 억제용 임시 mailed 값은 그대로 저장되는 구조가 아니어서, 다음 회차의 이력은 새로 시작한다. 손상으로 이미 잃은 outbox·과거 통지 성공 여부를 복원하는 기능은 없다. 외부 전송 성공 직후 keeper.json 저장 전에 중단되면 중복 전송할 수 있는 한계도 남는다. 실제 전송과 Drive 기록을 원자적으로 묶는 보장은 이번 구현에 없다.
- **생존 계약:** 최상위 time은 실행 완료 시각, ok는 전체 수집 실행 결과다. 자동 발행 실패는 기존처럼 last.auto.error 등에 남고 전체 ok=true일 수 있어 ‘생존’과 ‘자동 발행 성공’은 다르다. Keeper 멈춤 감시는 시각, CTRL 상태는 last.time·last.ok를 사용하므로 새 형식에서 기본 생존 의미는 일치한다.

## 2b 시작 전 최소 목록

1. Y1: 계획의 메타데이터만으로 관리자 강제 권한을 부여하지 않도록 재확인한다.
2. Y2·Y3: pending 파일의 의미 형태를 검증하고, 같은 TASK의 다른 사건을 별도 요청으로 보존한다.
3. Y4: Drive 검색 지연·동일 이름 중복 파일에 대한 재시도·수렴 정책을 정하고 시험한다.
4. Y5·Y6: 대화상자 전송 시 현재 상태를 재확인하고 알림 목록 넘침에서 중요 알림을 보존한다.
5. 이후 2b에서는 가짜 CVAT로 실제 처리기의 백업 선행·사람 라벨 보호·단일 소유·정지/확정 경계를 연결 시험한다. 이번 심판·수집기 시험 통과가 그 종단 보증을 대신하지는 않는다.

## 점검했지만 문제가 없던 항목

- 일반 시험 585개 및 기본·확장 퍼징 각 8개 항목 통과.
- b17 효과 누락·환경 오전송·보류 읽기 실패의 기존 반례 차단.
- 현재 SignalKind.effects의 신호만으로 재계산 가능성, 독립 효과 정답 추가.
- 완료·원 신호 없음/모름·형태 오류인 신호의 계획 효과 비실행 경로.
- 정상 형태 pending의 선행 저장, 생성 실패·장부 실패·상태 이름 변경 후 재개.
- 보호 구간 재진입 알림, 수집기 생산→Keeper 소비의 실제 생존 기록 연결.
- ntfy 주제·메일 수신 주소를 outbox에 기록하지 않는 전송 경로.

## 시간이 모자라 보지 못한 항목·한계

- 실제 서비스 접속·실제 Drive 검색 지연·중복 파일 응답·메일/ntfy 전달은 지침에 따라 시험하지 않았다. Y4는 검색 지연을 주입한 코드 경로 확인이다.
- 동일 RID 중복 물리 파일이 실제 rclone·Drive에서 일으키는 후속 효과와 모든 장애·경합 조합을 전수 검사하지 않았다.
- v4.32 전체 회귀, 모든 노트북 셀·버전 문자열 일치, 실제 Kaggle IPython, 2b 실제 처리기·LC·AA앱 종단 동작은 이번 검토 범위 밖이다.
