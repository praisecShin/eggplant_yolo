# v4.33.0n 검토 결과 — b21

검토일: 2026-11-16. `AGENTS.md`·이번 요청·b20 결과·2d의 b20 대응표·설계의 보호 모드/모름/수집기 자동 요청·관련 구현과 시험을 검토했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle·메일·ntfy에는 접속하지 않았다.

**지정 일반 시험 660개와 기본·확장 퍼징 각 10개 항목은 모두 통과했다. Q2·Q3·Q4와 Z1·Z3은 기존 발견 범위에서 해결, Q1·Z4는 부분 해결이다. 새 발견은 높음 3건(P1·P2·P3), 보통 1건(P4)이다. P1·P2·P3는 읽기 복구 후에도 요청 정체나 해제 미적용을 남기므로 2b 전에 고쳐야 한다.**

## 시험·재현 및 보관

| 실행 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 236개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 61개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 10개 성공. 입력 5,458개, 변형 46,195개 + 두 칸 조합 1,692개, 파일 숨기기 1,797회. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 10개 성공. 변형 102,532개 + 두 칸 조합 1,692개, 파일 숨기기 1,800회. 예외·뜻 위반 0건 |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 72개 성공, Keeper보다 먼저 실행 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 123개 성공, 실제 수집기 생존 기록 연결 포함 |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 32개 성공 |

Python은 `PYTHONDONTWRITEBYTECODE=1`, Node는 기존 `/tmp/node-v22.16.0-linux-x64/bin/node`, jsdom은 기존 `/tmp/b17_ctrl_deps/node_modules`를 NODE_PATH로 사용했다. npm 설치나 저장소 의존성 변경은 하지 않았다.

b20 자료는 덮어쓰지 않고 보존했다. 지정 시험과 b20 재현을 다시 실행한 결과는 모두 `rLog/b21_*`에 남겼다.

| 파일 | 내용 |
| --- | --- |
| `b21_run_tests.py`·`b21_test_status.json`·각 시험 `.log` | 지정 시험 9개 명령과 종료 코드(모두 0) |
| `b21_rerun_b20.py`·`b21_rerun_status.json` | b20_signal_duplicate_probe.py·b20_night_probe.py·b20_collector_probe.js·b20_keeper_probe.js 원본 재실행(모두 종료 코드 0) |
| `b21_rerun_b20_{signals,night,collector,keeper}.log` | 옛 재현의 이번 실행 결과. b20의 원 로그와 비교 가능 |
| `b21_blocked_effect_probe.py`·동명 `.log` | 차단된 배정/복구 요청의 후속 효과, 반환 보고의 잠금 모름, 해제 대상 모름, 보류 모름 중 완료·만료·해제, 장기 모름 알림 |
| `b21_hold_monitor_probe.js`·동명 `.log` | 살아 있는 심판 아래 보류 읽기 실패에 대한 Keeper 판정 |

저장소 최상위에서 Python 재현은 `PYTHONDONTWRITEBYTECODE=1 python3 rLog/<파일>`로 실행한다. 추가 Keeper 재현은 위 Node 실행 파일로 `rLog/b21_hold_monitor_probe.js`를 실행한다. 전체 재실행 명령은 b21_run_tests.py·b21_rerun_b20.py에 보관했다.

## Q1~Q4·Z1·Z3·Z4 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| Q1 모름 경로의 쓰기와 의존성 | 부분 해결 | 모르는 판정 경로의 직접 쓰기 차단, hold 모름의 배정/GPU 차단, plan/done 모름의 신호 보류, 인계 모름의 재인계 방지는 반영됐다. 그러나 put 차단을 호출자가 성공처럼 소비하는 P1과, 관련 TASK 잠금 모름을 놓친 반환 보고 P2가 남는다. |
| Q2 G 해제의 원 신호 모름 | 해결 — 기존 발견 범위 | b20의 origin_read_failed·origin_duplicate 모두 완료를 쓰지 않고 기다리며, 원 파일이 복구되면 해제한다. 새 계획 전에도 같은 보류가 적용된다. 확정 부재는 거절한다. |
| Q3 실제 시각 비교 | 해결 — 기존 발견 범위 | 소수초 없는 UTC와 .500Z를 넣은 b20 재현에서 최신 .500Z가 장부와 latestPerTask_에 보존된다. 숫자 시각 비교·동일 시각의 표기 차이 중복 억제가 반영됐다. |
| Q4 skipped 장부 최신 보존 | 해결 — 기존 발견 범위 | b20의 최신 skipped=original_exists 이후 옛 시도 묶음 완료에서도 최신 updated=02:00이 유지되고 옛 요청은 history에만 추가된다. 원본 있음 기록을 쓰는 쪽에도 같은 비교가 있다. |
| Z1 신원 모름·철회·허용 | 해결 — 기존 발견 범위 | owner_unknown·origin_owner_unknown·origin_read_unknown은 보류하고, 확인된 권한 없음·중지·미등록은 미적용 효과를 거절한다. 원 소유자를 못 읽었다가 복구하는 b20 재현과 공식 회귀 통과. |
| Z3 최신 장부 보존 | 해결 — 기존 발견 범위 | Q3의 시각 표기 문제와 Q4의 skipped 예외가 함께 해소됐다. 원 시나리오의 늦은 발행은 history만 더한다. |
| Z4 같은 이름 파일 처리 | 부분 해결 | b20의 중복 hold 아래 새 배정, 중복 plan/done 재쓰기 반례는 해소됐다. 다만 숨겨진 옛 배정 때문에 새 배정 쓰기가 차단되어도 TASK 잠금은 생기는 P1이 있으므로 ‘관리자 정리 전 해당 작업 전체가 보류됨’까지는 완성되지 않았다. |

b20 재현의 duplicate_round는 여전히 ARBITER.json을 쓴다. 이번 설계가 회차 기록·알림을 쓰기 차단의 명시적 예외로 두므로 이 결과 자체를 새 결함으로 보고하지 않는다.

## 새 발견

### P1 — 배정 쓰기가 차단돼도 TASK 잠금을 만들고, 복구 요청 쓰기가 차단돼도 접수·배정을 진행한다

| 칸 | 내용 |
| --- | --- |
| 번호 | P1 |
| 심각도 | 높음 |
| 관점 | 동시성·스케줄링·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | Q1, Z4, AGENTS 3장 7의 요청 미처리·배정 준수 |
| 위치 | `drive/scripts/arbiter.py:593` View.put, `:1737`~1745 _assign, `:1856`~1862 TASK 잠금 생성, `:827`~829 ConfirmChoice.apply |
| 문제 | View.put은 차단 시 반환값으로 실패를 알리지 않는다. _assign은 쓰기가 빠졌어도 성공 배정 객체를 돌려주고, schedule은 이를 근거로 TASK 잠금을 만든다. ConfirmChoice도 복구 요청 쓰기 차단 뒤 v.requests를 직접 채우고 접수·예약을 계속해 같은 회차에 배정까지 만든다. 신호 완료를 한 회차 미루는 것만으로 관련 효과의 불일치를 막지 못한다. |
| 조건 | ① TASK 7의 r1 배정을 E1이 정상 반환하게 하되 현재 GPU 능력이 없게 둬 재배정하지 않은 상태를 만든다. 다음 회차에 반환된 `arb/assign/r1__1.json`만 읽기 모름으로 숨기고 새 GPU E2를 켠다. 기존 배정이 목록에서 빠져 chunk=1을 다시 고른다. assign 쓰기는 write_blocked_unknown으로 빠지지만 TASK 7은 새 decision·E2의 held가 된다. 실제 저장된 배정은 E1의 returned뿐이다. 읽기를 복구하고 세 회차 더 돌려도 E2 held와 반환 배정만 남는다. ② redo 복구에서 계획·요청 저장 후 끊고 다음 회차에 요청만 모름으로 두면 요청 쓰기는 막히지만 recovery intake·active 배정·held가 생긴다. 그다음에도 요청이 모름인데 신호는 recovery_request=reflected로 완료된다. |
| 확신 | 확인함 — `rLog/b21_blocked_effect_probe.log`의 assignment_blocked·recovery_request_unknown·recovery_second_hidden. 실제 CVAT 실행은 하지 않음 |
| 제안 | put의 수용 여부를 명시적으로 반환하고, 선행 쓰기가 차단되면 그 작업의 후속 사본 갱신·잠금·접수·배정을 중단한다. 배정은 배정 기록이 정상적으로 쓰기 목록에 들어간 경우에만 잠금을 만들고, 복구 요청은 요청·접수의 존재/쓰기 가능성을 함께 확인한다. 복구 뒤 종속 기록이 자동으로 정상 상태에 수렴하는 여러 회차 시험을 추가한다. |
| 2b 전 필수 여부 | **필수.** 실행기가 받지 못하는 배정의 잠금이 남아 요청이 정체된다. 공통 판정 계층의 문제이므로 실제 처리기 연결 전에 해결해야 한다. |

### P2 — 반환 보고가 읽지 못한 TASK 잠금을 건너뛰고 처리됨으로 끝난다

| 칸 | 내용 |
| --- | --- |
| 번호 | P2 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | Q1의 보고·잠금 의존성, AGENTS 3장 7 요청 미처리 |
| 위치 | `drive/scripts/arbiter.py:1171`~1184 apply_reports의 deps, `:1222`~1233 release 보고, `:1269` 부근 handled 추가 |
| 문제 | release 보고는 배정 파일만 의존성에 넣고 그 배정의 TASK 잠금들은 넣지 않는다. 잠금이 모름이면 l2={}로 보고 해제를 건너뛰지만, 배정은 returned로 바꾸고 보고를 asks_handled에 넣는다. 읽기 복구 후에도 보고를 재적용하지 않아 살아 있는 실행기의 held 잠금이 남는다. |
| 조건 | E1이 TASK 7을 held인 r1 배정을 반환한다. 반환 보고를 읽는 회차에 `arb/locks/task/7.json`만 모름으로 숨긴다. 배정은 returned, 보고 키는 asks_handled에 들어간다. 잠금을 다시 읽고 E1 생존을 유지하며 세 회차 더 진행해도 TASK 7은 E1의 held이고 active 배정은 없다. 만료는 E1이 살아 있으므로 풀지 않고, reconcile은 returned 배정을 대상으로 하지 않는다. |
| 확신 | 확인함 — `rLog/b21_blocked_effect_probe.log`의 release_lock_unknown |
| 제안 | 배정 반환이 확인·해제하는 모든 TASK 잠금을 의존성으로 포함한다. 하나라도 모르면 반환 완료와 handled 처리를 미룬다. 일부 TASK만 반환할 정책이라면 재개할 대상을 영속 기록으로 남겨야 한다. 반환 보고→TASK 잠금 읽기 실패→복구→잠금 해제·재배정 순서의 회귀를 추가한다. |
| 2b 전 필수 여부 | **필수.** 정상적인 일시 읽기 실패가 읽기 복구 후에도 남는 요청 정체로 바뀐다. |

### P3 — 해제 대상 보류를 못 읽으면 정상 해제 신호를 무효 완료한다

| 칸 | 내용 |
| --- | --- |
| 번호 | P3 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | Q1의 모름·부재 구분, 검토 질문 3의 해제 신호 |
| 위치 | `drive/scripts/arbiter.py:764`~771 Release.judge, `:1058`~1071 process_signals의 invalid·완료 기록 |
| 문제 | Release.judge는 대상 hold가 View에 없으면 no_such_stop으로 판단한다. file: 모름 때문에 제외된 보류도 없는 보류와 같게 처리된다. 쓰기를 시도하지 않고 invalid로 끝내므로 blocked_writes 비교가 이 잘못된 완료를 막지 못한다. |
| 조건 | 정상 stop으로 active 보류를 만든 뒤 그 stop_id에 release를 보낸다. 다음 회차에 대상 hold만 읽기 모름으로 숨기면 해제 신호가 `result=done, effects={unhold: invalid:no_such_stop}`으로 끝난다. 파일을 복구하고 재실행해도 같은 done 때문에 해제를 하지 않고 원 보류는 active=true다. |
| 확신 | 확인함 — `rLog/b21_blocked_effect_probe.log`의 release_target_unknown |
| 제안 | 대상 hold 경로가 unknown_files에 있으면 Release.judge가 defer하도록 한다. 효과 쓰기 차단뿐 아니라 효과를 판단할 입력의 모름도 완료 전에 확인해야 한다. 해제 대상 모름→done 없음→복구 후 해제의 회귀를 추가한다. |
| 2b 전 필수 여부 | **필수.** 정상 해제 신호가 일시적인 읽기 실패로 영구 소비되어 정지가 풀리지 않는다. |

### P4 — 살아 있는 심판 아래 보류 읽기 실패가 오래 지속돼도 자동 알림이 없다

| 칸 | 내용 |
| --- | --- |
| 번호 | P4 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | 검토 질문 3, 설계 판정 루프 3의 같은 대상 모름 30분 초과 알림 |
| 위치 | `drive/scripts/arbiter.py:388` holds_unknown·`periodic_check` 1866행 부근, `apps_script/G_keeper/Keeper.gs:263` holdUnknown 알림 조건 |
| 문제 | 읽기 실패의 file: 경로는 회차 기록·CTRL에 보이지만 지속 시간을 추적해 알리는 경로가 없다. 중복이면 duplicate_path, 실제 쓰기를 막으면 write_blocked_unknown이 생기지만, 단순 보류 읽기 실패로 새 배정만 멈춘 경우에는 둘 다 없을 수 있다. Keeper도 심판이 살아 있으면 hold_unknown 메일을 만들지 않는다. |
| 조건 | 정상 stop 뒤 같은 보류 파일을 매 회차 읽기 모름으로 두고 60초씩 41회 진행했다. wake.holds_unknown=true·unknown 경로는 유지되지만 alerts=[]다. 최신 심판 회차·생존 신호와 holds=null을 Keeper 판정에 넣으면 alive=true, mails=[], pushes=[]다. |
| 확신 | 확인함 — `b21_blocked_effect_probe.log`의 long_hold_read_failure, `b21_hold_monitor_probe.log` |
| 제안 | 경로별 최초 모름 시각과 복구를 기록하고, 30분 초과 시 중복 억제 알림을 만든다. 보호 모드와 구별해 ‘정지 여부 모름으로 새 일을 기다림’을 표시한다. 단순 읽기 실패·중복·복구·재발을 각각 시험한다. |
| 2b 전 필수 여부 | 필수 아님. **2b 안에서 감시 보완 또는 알려진 한계로 명시 가능.** 현재 새 배정 차단과 CTRL의 모름 표시는 동작하므로, 자동 알림 누락만으로 착수를 막지는 않는다. |

## 질문별 보충 판단

### 1·2. 쓰기 차단의 범위와 후속 판단

- **이번 차단의 효과:** View.put은 모름 경로를 쓰기 목록·View 사본 모두에서 갱신하지 않는다. 알림·회차 기록은 설계상의 예외다. 신호 처리의 blocked_writes 비교는 같은 회차에 효과 쓰기가 차단됐으면 완료 기록을 미루므로, b20의 단순 stop 효과 차단 회귀는 통과한다.
- **접수:** 일반 접수는 intake 경로가 모름이면 미리 건너뛴다. 반면 ConfirmChoice의 복구 접수는 직접 v.requests를 채우는 별도 경로이므로 P1처럼 성공한 요청으로 보일 수 있다. put 한곳의 차단만으로 모든 호출자의 의미가 일치하지 않는다.
- **배정·잠금:** 대부분의 실행형 잠금과 TASK 잠금의 모름은 schedule의 선행 검사로 걸러진다. 그러나 배정 파일 자체가 모름인 경우 _assign이 성공 객체를 돌려주는 P1이 남는다. 직접 쓰기 없음보다 ‘잠금에 대응하는 배정이 있음’이라는 조건이 필요하다.
- **결과·승인:** TASK end/result는 결과 경로·잠금 의존성을 확인하고, 실행형 완료는 _complete_deps를 통해 결과·잠금·CURRENT·플래그·산출물 목록을 확인한다. 승인 보고도 해당 TASK 잠금이 모름이면 apply_reports에서 보류한다. 이번 검토에서 이 기본 경로에 추가 반례는 확인하지 못했다. 반환 보고는 배정 아래 TASK 잠금 전체를 대조하지 않아 P2다.
- **인계:** 이 epoch의 handover 파일을 모르면 재발급·인계 기록을 반복하지 않고 기다리는 공식 회귀가 통과했다. 잠금·배정 모름은 pending으로 남기는 기존 인계 규칙도 유지된다. 다만 모든 종류의 복수 파일 모름·부분 인계를 전수 확인한 것은 아니다.
- **채택:** 정상 보고와 사람 선택의 CURRENT·결과·플래그·버전 목록 의존성 검사는 유지된다. 최신 시험 설정 채택의 오염 대조는 _contam_deps로 관련 모름을 포함한다. 이번 변경에서 채택 쓰기 차단 뒤 별도 거짓 완료가 되는 재현은 찾지 못했다.

### 퍼징에 빠진 불변 조건

현재 파일 숨기기 시험은 실제로 약 1,800회 수행됐고, 숨긴 경로에 직접 쓰지 않는 조건과 hold 모름 아래 새 배정 없음 조건을 검사한다. 다음 조건은 추가로 필요하다.

1. **새 잠금에는 대응 배정이 있어야 함:** 잠금의 rid/session/decision/chunk와 일치하는 active 배정이 기존 관측 또는 이번 쓰기 목록에 있어야 한다. 배정 쓰기가 차단되면 그 배정의 잠금도 만들면 안 된다(P1).
2. **복구 접수에는 확인된 요청이 있어야 함:** 모름인 요청 경로를 사본에 직접 주입해 접수·배정을 만들지 않는다. 선행 효과 차단 뒤 후속 효과·증거가 진행하지 않아야 한다(P1).
3. **반환 완료 뒤 잠금이 고아가 되면 안 됨:** 배정을 returned로 닫고 보고를 handled로 만들 때, 그 배정의 미완료 held 잠금을 모두 해제했거나 재개할 상태가 남아야 한다(P2).
4. **숨김→복구의 여러 회차 수렴:** 숨긴 경로에 쓰지 않는 한 회차 통과만으로는 충분하지 않다. 모름을 유지하고 다른 효과를 부분 적용한 뒤 읽기를 복구했을 때, 정상 배정·잠금·접수·완료 상태로 수렴하는지 검사한다.

기존 숨김 시험의 통과는 위 조건을 보증하지 않는다. P1·P2는 모두 숨긴 경로에 직접 쓰지 않으므로 현재 성공 조건을 지킨 채 발생한다.

### 3. 보류 모름 중 허용되는 일과 관리자 감지

- **이미 배정된 일의 마무리:** schedule만 hold_unknown으로 막고 보고 반영은 별도로 진행한다. 추가 재현에서 이미 confirm_approved인 TASK 7의 end를 처리해 정상 결과를 기록하고 free로 해제했다. 새로운 배정은 만들지 않았다.
- **보류 만료:** 읽힌 정상 보류의 기한이 지나면 expire_holds가 해제한다. 다른 hold 하나가 모름이어도 정상 보류의 만료를 막지 않는다. 모르는 보류 자체는 내용을 모르므로 만료로 간주하지 않는다.
- **해제 신호:** 다른 모름 보류가 있어도 읽힌 대상 보류에 대한 release는 정상 적용된다. 추가 재현에서 기한 만료 보류와 명시 해제 보류가 모두 inactive가 됐지만, 별도의 모름 보류가 남아 wake.holds에는 `(모름)`·holds_unknown=true가 유지됐다. 해제 대상인 그 보류가 모름이면 no_such_stop으로 무효 완료되어 복구 뒤에도 적용되지 않는 P3이 있다. 이 경우는 보류 모름을 정상 대기로 다루는 동작이 아니다.
- **밤 끝내기·GPU:** b20_night_probe 재실행에서 wake의 runnable=0·gpu_needed=0·holds=[(모름)]이고, unknown 회차는 clean을 갱신하지 않아 exit_reason=None이었다. 기존 GpuLauncher도 holds가 비어 있지 않으면 기동하지 않는다. 최대 실행 시간 종료는 별도 규칙이다.
- **화면:** ARBITER.json의 unknown 목록이 CTRL ‘읽지 못한 것’에 표시된다. CTRL 자신의 hold 조회가 실패하면 정지 보류의 모름을 표시하고 깨우기·해제를 막는다. 관련 32개 앱 회귀가 통과했다. 마스터와 앱이 서로 다른 시각에 읽기 때문에 마스터만 못 읽는 경우에는 앱의 hold 조회가 정상일 수 있으며, 이때 마스터의 unknown 표를 함께 봐야 한다.
- **알림:** 중복은 duplicate_path, 차단된 쓰기는 write_blocked_unknown을 남겨 Keeper의 일반 알림 경로로 전달된다. 순수 읽기 실패가 오래가는 경우는 P4이므로 자동 알림까지 충분하다고 보기는 어렵다.

### 4. 신원 모름 세 종류와 거절 분류

- owner_unknown은 현재 신호의 소유 계정을 모를 때, origin_owner_unknown은 G 해제 원본의 소유 계정을 모를 때, origin_read_unknown은 원본 경로가 file: 모름일 때다. 세 경우를 신규 계획과 재개 경로 모두에서 미루는 분류가 타당하다.
- 원본 경로가 모름이 아니며 관측 목록에도 없으면 origin_missing으로 거절한다. 새 신호에서는 rejected, 기존 계획의 미적용 효과는 invalid:revoked:origin_missing으로 끝내는 현재 정책과 맞다. 이미 적용한 효과는 되돌리지 않는다.
- 사람의 미등록·사용 중지·동작 권한 없음은 확인된 거절이다. G가 일반 신호를 낸 경우에는 g_not_allowed, 원 소유자가 system이면 origin_not_person 등으로 거절한다. G의 소유권만으로 사람의 관리 권한을 얻지 않는다.
- 사람 목록 읽기 실패·형태 오류는 MasterLoop의 전체 설정 검사·캐시 유예·오래된 설정 보류를 따른다. 현재 보고 범위에서 이 문제를 새 신호의 허용 권한으로 바꿔 주는 경로는 확인하지 못했다.
- 원래 신호 파일 내용 자체가 잘못됐지만 소유자 정보는 읽히는 경우까지 이번 세 사유가 모두 표현하는 것은 아니다. 현재 Q2는 원 파일/소유자의 읽기 모름에 대한 수정이며, 모든 종류의 원 신호 손상 인증을 보증하는 것으로 해석하지 않았다.

## 2b 전 최소 수정 목록

1. **P1:** 선행 쓰기 차단 시 해당 전이의 후속 효과를 중단한다. 배정 쓰기 차단→TASK 잠금 없음, 복구 요청 쓰기 차단→접수·예약·배정 없음, 복구 후 정상 재개의 회귀를 추가한다.
2. **P2:** 반환 보고가 배정의 TASK 잠금 전체를 확인하게 한다. 하나라도 모르면 보고를 handled로 소비하지 않고, 복구 뒤 해제·재배정하도록 한다.
3. **P3:** Release의 대상 보류 모름을 부재와 구분하고, 정상 해제를 완료로 소비하지 않고 기다리게 한다.
4. 세 수정 후 지정 시험과 두 퍼징을 다시 통과시키고, 위의 구조적 불변 조건과 여러 회차 복구도 확인한다.

P4의 지속 모름 알림은 2b 안에서 보완하거나 알려진 한계로 명시해도 된다. 실제 Drive/rclone 동일 이름 파일 처리·CTRL 관측·메일/ntfy 전달은 예행 연습 T18 및 알림 시험에 남겨도 된다. 이번에 확인한 P1·P2·P3를 실환경 예행 연습까지 미룰 필요는 없다.

## 점검했지만 문제가 없던 항목

- 일반 시험 660개, 기본·확장 퍼징 각각 10개 항목 통과.
- b20의 원 신호 owner 모름·읽기 실패·중복→복구 후 해제, ISO 표기 차이, 최신 skipped 장부 퇴행 재현 해소.
- 중복 hold의 새 배정·GPU 차단, 중복 plan/done의 해당 신호 보류, 모름 handover의 반복 인계 방지.
- 모름 경로의 직접 쓰기 차단과 write_blocked_unknown 알림 생성.
- 다른 보류가 모름인 동안 이미 승인된 TASK의 결과 기록·잠금 해제, 읽힌 정상 보류의 만료·명시 해제 진행.
- 밤의 unknown 회차를 clean으로 세지 않는 동작과 wake 요약의 모름 표시.
- 일반 결과·승인과 실행형 완료·채택의 기본 의존성 검사.
- 변경하지 않은 Keeper·CTRL·배포/뿌리 코드의 지정 회귀 통과.

## 시간이 모자라 보지 못한 항목·한계

- 실제 CVAT·Drive·Kaggle·Apps Script 권한·메일·ntfy·claude.ai 커넥터와 rclone 동일 이름 파일의 실제 cat/moveto/rcat은 확인하지 않았다.
- 모든 put 호출의 다중 차단 조합·모든 인계/채택 부분 쓰기·모든 보고 순서를 전수 검증하지 않았다. 확인된 P1·P2는 가짜 파일 저장소 입력과 실제 판정 코드의 연속 회차 재현이다.
- v4.32 전체 회귀, 노트북 셀 전체 일치, Kaggle IPython 호환성, 아직 연결 전인 2b·LC·AA 처리기의 종단 백업/업로드/게시 경로는 이번 범위 밖이다.
- 실제 실행기의 장시간 생존과 실제 CVAT 쓰기를 실행하지 않았다. P1·P2의 ‘계속 잠김’은 생존을 유지한 모형에서 읽기 복구 후에도 반복 확인한 결과이며, 실행기가 종료되면 기존 만료 규칙으로 잠금이 풀릴 수 있다.
