# v4.33.0c 검토 결과

검토일: 2026-11-14. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0c.md`, `IMPL_STEP1A_v4.33.md`의 b9 반영표, 설계 8판 보충의 보고·결과·인계 계약과 지정한 코드·시험 네 파일을 읽었다. 검토 범위는 N1~N5 수정과 새 완료/재개 경로에 집중했다.

**판정: 이전 반례들은 상당 부분 닫혔지만, 공용 완료 프로토콜을 확정해 1b를 연결하기 전 세 가지를 보완해야 한다.** 시험 설정 채택의 후속 효과 복구, 완료 경로 전체의 파일별 모름 전파, 사람의 채택 선택을 옛 완료 재개가 되돌리지 않는 조건이다. 새 발견은 P1~P3, 모두 높음이다. Drive 어댑터·가짜 작업자의 뼈대 작업은 병행할 수 있다.

코드·노트북·시험·설계서는 수정하지 않았다. 실제 Drive·CVAT·Kaggle에 접속하지 않았다. 추가 재현·로그는 `/tmp`에만 만들었다. 아래 확인함은 현재 함수를 실행하거나 해당 경로를 추적한 결과이며 실제 원격 피해를 관찰했다는 뜻이 아니다.

## 1. 시험과 이전 재현 재실행

| 항목 | 결과 |
|---|---|
| `python3 tests/test_arbiter_433.py drive` | ✅ 136개, `RESULT True`, 종료 0 |
| `python3 tests/test_access_433.py drive` | ✅ 68개, `RESULT True`, 종료 0 |
| `/tmp/egg_b9_probes_live.py` | 실행 완료. 이전 FORCE_NEW 덮어쓰기는 superseded로 막힘. 단독 학습 완료 10개 쓰기 경계도 통과 |
| `/tmp/egg_b9_interleave.py` | 실행 완료. 정상 FORCE_NEW 뒤 옛 학습 완료를 재개해도 CURRENT는 version=None·gen=4를 유지하고 superseded flag가 생김 |
| `/tmp/egg_b9_m_compare.py` | 실행 완료. 승인 전/격리 쓰기·proxy 변경·잘못된 end·실패 뒤 restore는 거절. 누락 잠금·결과 보존·입력 불변·grant 모름 거절·TASK 없는 작업·until 재개도 이전 비교 결과 유지 |
| 추가 `run_choice=done` 모든 쓰기 경계 장면 | Write 6개의 prefix 0~5 × 같은/새 마스터, 총 12개 모두 강화된 signature로 정상 실행과 일치 |
| 추가 교차/시험 설정/모름 장면 | P1~P3 반례 확인 |

이전 스크립트는 그대로 실행했다. 다만 b9의 ‘만들기 done’ 예는 TASK 번호 없이 15분 전에 선택하므로 이제 정상 거절되어 결과가 없다. 이것을 새 실패로 세지 않았고, 현재 시험의 충분한 대기+task_id=777 성공 사례를 함께 확인했다. 마찬가지로 b9 스크립트의 CURRENT/flag를 고의 변경한 음성 비교는 이제 signature가 차이를 잡는다.

이번 새 재현: `/tmp/egg_b10_probes.py` → `/tmp/b10_probes.json`, `/tmp/egg_b10_adopt_interleave.py` → `/tmp/b10_adopt_interleave.json`. 시험의 Sim·train_sim 등을 읽어 재사용하고 **실제 현재 arbiter 함수**를 호출했다. 이전 설계 검토의 추상 모형과 구별한다.

## 2. N1~N5 반영 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| N1 옛 결과가 최신 CURRENT를 덮음 | 부분 해결 | 결과 기록의 premise와 `_settle_artifact`/`_settle_change`가 실제 FORCE_NEW 교차를 막는다. 그러나 CURRENT가 자기 효과라는 이유로 후속 오염 효과를 건너뛰는 P1, 사람이 채택한 결과를 옛 판정 flag로 되돌리는 P3이 남는다. |
| N2 run_choice 완료 누락·생성 재실행 | 해결(기존 반례) | 정상 보고와 complete_run을 공유하고, artifact 채택·create tag/task_id·선택 가능 조건을 연결했다. 검증된 학습 done의 12개 중단 경계도 통과했다. 선택 경로의 모름 의존성은 별도 P2. |
| N3 개별 파일 모름 확정 | 부분 해결 | handover.pending과 only 재발급, 잠금/결과/자기 CURRENT/목록을 기대는 보고 defer가 이전 반례를 고쳤다. 학습의 시험 CURRENT 의존성과 RunChoice의 동일 의존성 검사에는 누락이 있다(P2). |
| N4 publish_lock 범위 | 해결 | read lane·assign epoch·TASK 집합을 확인한다. 이전 배정 밖 TASK 999 잠금은 생성되지 않는다. |
| N5 signature 느슨함 | 해결(지적한 비교 항목) | CURRENT의 논리 버전·flags·실행형 잠금·결과 이유·보류·복구 연결을 비교한다. 틀린 버전/flag/잠금 음성 시험이 있다. 버전 내용과 시험 keys까지의 검증은 아래 추가 시험으로 보완할 수 있다. |

### M3·M8·M10 마무리 판정

- **M3: 해결(기존 보고 식별·게시 범위 반례).** 필수 항목·잠금 식별·승인 gen과 read 배정 TASK 범위 검사가 있다. 결과가 이미 저장된 보고를 재개하는 예외는 의도된 계약이므로 gen만 다시 맞추는 것을 요구하지 않는다. 대신 사람의 후속 선택과의 순서는 P3에서 다룬다.
- **M8: 부분 해결.** 자격 모름·전체 목록 모름·개별 인계 잠금 모름은 개선됐다. 완료 함수가 실제로 읽는 모든 의존 파일로 모름을 전파하는 일은 P2 때문에 아직 닫히지 않았다.
- **M10: 기존 작업 종류 배정/완료와 run_choice 누락 반례는 해결.** 생성/취합/비산출물 관리 완료와 create 결과 중복 재배정 방지는 구현됐다. 다만 완료/선택의 모든 장애 경로까지 닫혔다고 볼 수는 없으며 P1~P3은 별도 남은 조건이다.

## 3. 새 발견

### P1 — 시험 설정 CURRENT가 이미 반영됐으면 오염 표시를 복구하지 않음

| 칸 | 내용 |
|---|---|
| 번호 | P1 |
| 심각도 | 높음 |
| 관점 | 복구·동시성 |
| 종류 | 코드·시험 |
| 위치 | `drive/scripts/arbiter.py:970`~971 `_settle_artifact` 조기 반환, 985~989행 시험 설정·오염 효과; 555~566행 `AdoptChoice.apply` |
| 문제 | test_tasks 채택은 CURRENT와 모델별 오염 flag 여러 개를 쓴다. CURRENT만 저장하고 끊기면 재개는 ‘이미 반영’으로 반환해 빠진 flag를 만들지 않는다. 시험 설정을 사람의 adopt_choice로 채택하는 경로도 CURRENT에 keys를 복사하거나 오염 대조를 수행하지 않는다. |
| 조건 | train_keys=[t1]인 V0 모델이 있는 상태에서 keys=[t1]인 새 시험 설정을 완료한다. 결과·CURRENT 두 쓰기만 저장하고 중단 → 재개 뒤 mgmt lock=done, CURRENT는 새 설정이지만 V0의 오염 flag는 없음. 정상 실행에는 adopted_contaminated flag가 있으며 강화 signature도 둘의 차이를 잡음. 별도로 시험 설정 WAIT의 adopt_wait flag에서 adopt_choice를 보내면 CURRENT.version=WAIT이나 keys가 사라짐. |
| 확신 | 확인함 — 실제 prefix 중단/재개 및 사람 채택 함수 재현 |
| 제안 | CURRENT 자체의 완료와 후속 오염 효과의 완료를 구별한다. 같은 시험 버전이 이미 CURRENT여도 누락된 오염 효과는 멱등하게 끝낸다. 사람 채택도 keys 보존·동일 오염 전이를 거치는 공통 경로를 사용한다. CURRENT 뒤·각 모델 flag 사이의 모든 중단과 test_tasks adopt_choice를 시험한다. |

### P2 — 완료 함수가 읽는 시험 CURRENT와 사람 선택의 파일 의존성이 모름 검사에서 빠짐

| 칸 | 내용 |
|---|---|
| 번호 | P2 |
| 심각도 | 높음 |
| 관점 | 복구·접근·동시성 |
| 종류 | 코드·시험 |
| 위치 | `drive/scripts/arbiter.py:1039`~1053 `_deps_run`, 935~951 premise/판정, 596~631 `RunChoice`, 964~987 채택 |
| 문제 | 학습 완료는 시험 설정 CURRENT를 읽지만 `_deps_run`은 대상 모델 CURRENT와 버전 목록만 의존성에 넣는다. RunChoice는 정상 보고의 의존성 검사를 거치지 않는다. trusted가 반환한 None을 `or {}`로 빈 상태처럼 처리해 미확인 전제 위에서 채택하거나 모르는 CURRENT를 덮는다. |
| 조건 | T1에 t1이 있고 학습 출처도 t1인데 `file:sets/test_tasks/CURRENT.json`을 모름으로 두고 done_run → 오염 flag 없이 모델이 채택되고 train lock=done. 별도 dataset run_choice=done에서 `file:datasets/ds/CURRENT.json`이 모름이면 기존 OLD/gen9를 새 버전/gen1로 쓰고 신호를 done 처리함. |
| 확신 | 확인함 — 두 경로 실제 함수 재현, unknown 대상으로 Write가 생성되는 것도 확인 |
| 제안 | complete_run이 필요로 하는 잠금·결과·대상 CURRENT·시험 CURRENT·목록·관련 flag의 의존성을 공통으로 계산해 정상 보고/RunChoice 모두 defer한다. 존재하지 않음과 읽지 못함을 빈 사전 하나로 합치지 않는다. 모름이 해소되기 전에는 result 판정·CURRENT·완료 잠금을 확정하지 않는다. |

### P3 — 사용자 채택 선택 뒤 옛 완료를 재개하면 flag가 다시 채택 대기가 됨

| 칸 | 내용 |
|---|---|
| 번호 | P3 |
| 심각도 | 높음 |
| 관점 | 복구·동시성 |
| 종류 | 코드·설계(후속 선택과 완료 재개의 순서) |
| 위치 | `drive/scripts/arbiter.py:956`~973 `_flag`·`_settle_artifact`, 555~566행 `AdoptChoice.apply` |
| 문제 | result의 최초 판정이 adopt_wait면 재개할 때 그 flag를 다시 만든다. 사람이 그 버전을 채택해 flag를 adopted로 바꾼 사실은 재개의 완료 증거로 인정하지 않는다. AdoptChoice의 CURRENT에는 원실행 decision이 없어 ‘이미 반영’ 조건도 통과하지 않는다. |
| 조건 | 모델 채택 gen 변경 때문에 학습 완료가 adopt_wait가 된 회차에서 result·flag까지만 저장하고 중단한다. 옛 done_run 파일만 잠시 모름으로 두고 사람이 adopt_choice=adopt를 처리하면 flag=adopted, CURRENT=그 학습 버전이 된다. 옛 완료 파일을 다시 읽으면 flag가 adopt_wait/current_changed로 돌아가며 by_signal도 없어짐. 사용자 신호 완료 기록은 계속 done이다. |
| 확신 | 확인함 — 현재 Sim으로 두 회차를 교차해 실제 adopted→adopt_wait 전이 확인 |
| 제안 | 원완료 판정과 그 판정을 해소한 사람 선택을 연결해 후속 선택이 우선하도록 한다. 재개는 남은 잠금/배정을 닫되 이미 adopted/discarded로 해소된 flag를 되살리지 않는다. 사람의 채택/버림 각각에 대해 완료 result→flag 중단과 선택→옛 완료 재개를 시험한다. |

## 4. 새 완료 계약과 끊김 시험 평가

결과(판정+전제)→가변 효과→잠금·배정 닫기의 순서는 코드에 반영됐다. 기존 TASK 결과 선기록, handover.pending, 실행형 공통 완료로의 통합도 개선이다. N1에서 우려한 ‘결과 존재를 모든 효과의 완료로 간주’하는 문제는 CURRENT 전제 비교에서는 고쳐졌지만, **CURRENT 뒤 부수 효과**(P1)와 **사용자가 해소한 판정의 재생**(P3)에서는 아직 구분이 필요하다.

공식 7장면의 모든 쓰기 경계 시험은 통과했다. 강화한 signature는 이번 P1의 정상/중단 상태 차이를 실제로 검출했다. 따라서 비교 함수가 언제나 참인 것은 아니다. 문제는 공식 장면에 **오염될 기존 모델이 있는 test_tasks 채택**이나 완료/선택의 교차가 없다는 점이다. 정상 경로의 prefix 열거만으로 다른 사건이 끼어든 모든 전이를 증명하지는 못한다.

추가 장면은 verified 학습 needs_check에서 run_choice=done이었다. 한 회차 Write 6개에 대해 0~5개만 저장한 뒤 동일 마스터/새 epoch의 마스터가 4회 더 처리하도록 했다. 정상 실행의 강화 signature와 비교한 **12개 모두 통과**했다. 선택 가능 시간은 1200초 경과로 만족시켰고, 조건이 안 된 입력을 오류로 세지 않았다.

추가로 필요한 시험:

- P1: 결과→시험 CURRENT→각 모델 오염 flag→실행 잠금 사이 전 경계. 출처가 여러 모델에 걸친 경우와 같은 회차 모델 done_run도 포함.
- P2: 시험 CURRENT·대상 CURRENT·목록·flag 각각의 unknown을 정상 done_run과 run_choice에 대칭 적용. 읽힘 회차에 한 번만 마무리되는지 확인.
- P3: 완료가 잠금 닫기 전에 멈춘 동안 adopt_choice adopt/discard, 시험 설정 변경, 다른 모델 채택을 각각 교차.
- 반대 방향: 전제가 바뀌지 않은 정상 완료는 superseded로 막히지 않음. 같은 회차 여러 서로 다른 모델의 완료는 각 모델 CURRENT에 독립 채택됨. 모델 전제 A→B→A는 gen이 바뀌므로 대기가 맞다.
- signature는 현재 CURRENT의 논리 버전·flag state/reason을 비교하지만 CURRENT.keys, flag의 contaminated_for, create 결과 task_id와 파일 내용 지문은 직접 비교하지 않는다. 해당 작업 장면의 최종 단언이나 음성 시험에 이 값도 포함한다. 생성 실행 ID를 논리 요청으로 정규화하는 취지는 유지할 수 있다.

시험 설정 정상 채택과 모델 완료를 같은 회차에 받은 기존 시험은 시험 설정을 먼저 반영해 오염 대기로 가는 결과를 확인한다. 이번 반례는 그 정상 순서를 부정하는 것이 아니라, 그 사이 한 효과만 원격에 남았을 때의 재개와 별도 선택 경로를 보완하는 것이다.

## 5. 1b 시작 판단

### 1b 전에 고칠 것

1. **P1:** 시험 설정 채택을 CURRENT+오염 대조의 멱등한 전이로 만들고 정상/재개/사람 채택 모두 같은 효과를 보존한다.
2. **P2:** complete_run 전제 읽기의 공통 의존성·모름 검사를 보고와 선택 양쪽에 적용한다.
3. **P3:** 완료 판정을 사용자가 해소한 뒤에는 옛 완료가 해당 flag를 복구하지 않도록 선택의 완료 증거와 순서를 연결한다.
4. 위 반례를 경계·교차 회귀 시험에 넣는다. 현재 결과/전제/인계 구조 전체를 다시 버릴 필요는 없고, 누락된 전이와 의존성에 집중하면 된다.

이 조건을 정한 뒤 1b 실행기·마스터 어댑터를 붙이는 것이 적절하다. 순수 I/O 인터페이스와 가짜 환경 기반 작업은 병행 가능하다.

### 1b와 함께 고쳐도 되는 것

- 실제 Drive 읽기 결과를 없음/모름으로 구분해 전달하고, 기대 파일 의존성을 빠뜨리지 않는 어댑터 연결.
- 실제 실행기의 새 epoch/gen 재보고, 실행형 단계별 권한 확인, CVAT timeout·서버 작업 대조.
- 정기 점검의 단계 정체, 단계 기록 번호 보존, 실제 SDK 참조 읽기 경로 통합. 명시된 1b 항목은 이번에 미구현 결함으로 세지 않았다.
- 작업별 최종 단언에 시험 keys·시험 버전별 오염·create TASK ID·버전 파일 지문을 포함하는 보완.

### 운영 결정이 필요한 것

새로 필수인 운영 결정은 발견하지 못했다. 기존 A0 토큰 공유·실수 방지 세션 지문·밤 요청 지연·펜싱 한계의 결정을 다시 묻지 않는다. P1~P3은 기존의 고정 시험 보호·선택 결과 유지·모름 시 보류 계약을 구현하는 문제이며 운영상 위험 수용으로 대신할 필요는 없다.

## 점검했지만 문제가 없던 항목

- 공식 136/68개와 추가 run_choice 완료 12개 경계, 이전 단독 학습 완료 10개 경계는 통과했다.
- 기존 FORCE_NEW가 옛 학습 완료 재개에 덮이던 N1 재현은 superseded로 차단됐다.
- 정상 run_choice의 학습 산출물 채택·선택 가능 조건·생성 task_id 요구와 create 결과 종료는 이전 반례를 다룬다.
- 개별 TASK 인계 pending과 학습 잠금 unknown 보고 defer, read 게시 TASK 범위가 구현됐다.
- 입력 사본·결과 선기록·기본 보고 식별·access의 승인/격리 차단·실패 후 권한 캐시 폐기는 이전 재현에서 유지됐다. access.py는 이번 수정 대상의 동작 변경이 없다.

## 시간이 모자라 보지 못한 항목 및 검증 한계

- 요청된 N1~N5·M3/M8/M10 판정·완료 전제·추가 경계 장면·1b 판단은 모두 다뤘다. 모든 보고/선택/모름 조합을 완전 탐색하지는 않았다.
- `/tmp/egg_b10_probes.py`, `/tmp/egg_b10_adopt_interleave.py`의 재현은 실제 현재 함수 기반이며 입력 모형·원격 I/O는 가짜다. 네트워크나 실제 서비스 동작을 검증한 것은 아니다.
- 실제 Drive·Apps Script·Kaggle·CVAT 접속, 1b/2단계 전환 자체, 설계의 변경 없는 다른 절 전면 검토는 범위 밖이다.
- 기존 v4.32.0 전체 시험은 이번 좁은 수정 검토에서 반복하지 않았다. 지정한 두 시험과 이전/추가 반례를 실행했다.
- F7·F8과 저장소 밖 앱 코드는 보지 않았다.
