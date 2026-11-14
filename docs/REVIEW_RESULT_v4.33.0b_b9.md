# v4.33.0b 검토 결과

검토일: 2026-11-14. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0b.md`, `IMPL_STEP1A_v4.33.md`, 설계 8판 보충의 ‘보고·결과·인계 계약’, arbiter/access와 두 시험을 읽고 이전 b8 결과에 대조했다.

**판정: 이전의 주요 권한·결과 유실 문제는 고쳐졌지만, 아직 1b 공용 프로토콜을 확정하기에는 이르다.** 중간 결과 뒤 다른 채택과 교차하는 재개, `run_choice` 완료, 개별 파일 ‘모름’의 복구를 1a에서 보완해야 한다. 새 발견은 N1~N5(높음 4건·보통 1건)이다. Drive 입출력 뼈대 작업은 병행할 수 있으나 아래 결함을 어댑터에서 우회하는 방식으로 넘기지 않는 편이 좋다.

코드·노트북·시험·설계서는 수정하지 않았다. 실제 Drive·CVAT·Kaggle에는 접속하지 않았다. 추가 재현과 로그는 `/tmp`에만 작성했다. 아래 ‘확인함’은 실제 현재 함수 호출 또는 코드 추적으로 확인했다는 뜻이다.

## 1. 실행한 시험·재현

| 항목 | 결과 |
|---|---|
| `python3 tests/test_arbiter_433.py drive` | `RESULT True`, 종료 0. 로그상 ✅ 111개(요청서/설명에는 107개로 기재됨) |
| `python3 tests/test_access_433.py drive` | ✅ 68개, `RESULT True`, 종료 0 |
| 기존 `/tmp/egg_b8_probes.py`, `/tmp/egg_b8_more.py` 그대로 실행 | 둘 다 이전 도우미의 `K` 변수가 새 시험에서 사라져 `KeyError: K`로 중단. 제품 코드의 실패로 세지 않음 |
| 이전 반례의 현재 API 비교본 `/tmp/egg_b9_m_compare.py` | held/quarantine 쓰기 거절, 일반 API/목록 원시 객체 변경 거절, 잘못된 end 거절, 실패 후 restore 거절, 누락 잠금 복원, 결과 보존, 입력 불변, grant 소유자 모름 거절, TASK 없는 생성·refresh 배정, until 후 재개 확인 |
| 추가 학습 채택 쓰기 경계 장면 | 완료 회차의 Write 5개에 대해 prefix 0~4, 같은/새 마스터 2종으로 총 10개를 실행. 정상 입력·신규 gen 재보고를 포함한 장면은 모두 통과 |
| 교차 장애·run_choice·개별 파일 모름·게시 범위·signature 재현 | N1~N5 반례 확인 |

비교본은 기존 재현의 의도를 유지하되 새 `Sim.confirm/end`와 보고 필수 항목·phase/job API에 맞췄다. 원래 재현 파일과 저장소 시험은 수정하지 않았다. 비교본 로그는 `/tmp/b9_m_compare.json`이다.

추가 장면/반례: `/tmp/egg_b9_probes_live.py` → `/tmp/b9_probes_live.json`, `/tmp/egg_b9_interleave.py` → `/tmp/b9_interleave.json`. 이들은 실제 arbiter 함수를 호출하며, 원격 동작을 추상적으로만 모사한 설계 그림이 아니다. 이번 좁은 요청에서는 기존 v4.32.0 전체 회귀 시험을 반복하지 않았다.

## 2. M1~M12 해결 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| M1 승인/격리 쓰기 허용 | 해결 | executor_may_follow의 phase·승인 상태·job 검사. held는 not_approved, quarantine은 quarantined로 거절함. |
| M2 읽기 proxy 우회 | 해결 | call_api/rest_client/GET 제거와 컨테이너 재귀 감싸기. 비교본의 두 변경 호출 모두 AccessError. 정상 읽기 호환성은 실제 SDK 연결 때 추가 시험 필요. |
| M3 보고 식별 | 부분 해결 | 종류별 필수 항목과 epoch/gen/chunk/job 검사를 추가해 이전 잘못된 end는 거절. publish_lock은 실제 배정 TASK 집합/줄을 검사하지 않음(N4). 재개 보고의 효과 범위는 N1과 별도 조정 필요. |
| M4 실패 후 캐시/로그 지연 | 해결 | 매 call 확인·finally 초기화·intent 뒤 틈 재확인. 실패 직후 권한 상실 restore는 호출되지 않음. |
| M5 assign만 남는 장애 | 해결(기존 반례) | reconcile이 누락 TASK 잠금을 같은 decision으로 채우고 실행형 잠금 누락 배정을 회수함. 비교본 및 공식 쓰기 경계 시험 통과. 개별 파일 모름 인계는 N3. |
| M6 종료 결과 유실 | 해결(기존 TASK 반례) | 결과 선기록과 end_resume으로 result만 저장한 뒤에도 결과 1개·lock free로 수렴. 실행 산출물의 채택 효과 재개는 새로운 N1. |
| M7 입력 변경 | 해결 | View가 deepcopy하고 View.put만 회차 사본을 갱신. 실제 입력 불변 확인. |
| M8 모름·인계 건너뜀 | 부분 해결 | grant 소유자 모름 거절, critical unknown 뒤 handover 재시도는 반영. 개별 파일 모름일 때 완료 인계/보고 처리 목록에 잘못 확정하는 N3이 남음. |
| M9 지문 검사 누락 | 해결(명시된 실수 방지 범위) | 결과/계획/완료/플래그/CURRENT가 trusted를 사용. 구 epoch 수용은 인계용이라는 기존 계약을 따름. 서명 부재 자체는 새 결함으로 세지 않음. |
| M10 작업 종류 수명 | 부분 해결 | create/aggregate/비산출물 관리 일 배정·done_job·run_choice를 추가. run_choice=done의 산출물 채택 및 create 결과 종류가 잘못됨(N2). |
| M11 until 영구 보류 | 해결 | expire_holds와 wake 후보에 until 추가. 비교본에서 기한 뒤 배정 재개. |
| M12 제출 프레임 대응 | 해결 | frame_range·frame_map_sha 필수화와 검증, 공식 신규 시험에 대응 변경 거절 포함. 실제 ULD 매핑 지문 생성은 1b/셀 연결 때 확인할 사항. |

## 3. 새 발견

### N1 — 저장된 첫 채택 판단을 재생하면서 그 뒤의 FORCE_NEW를 되돌림

| 칸 | 내용 |
|---|---|
| 번호 | N1 |
| 심각도 | 높음 |
| 관점 | 동시성·복구 |
| 종류 | 코드·설계(재개 시 채택 전제 계약 보완) |
| 위치 | `drive/scripts/arbiter.py:898`~902 `_resume`, 934~966 `adopt_report`, 특히 944~945행 |
| 문제 | 결과 선기록 뒤 재개하면 첫 reason을 그대로 사용하고 현재 채택 gen/시험 설정의 변경을 다시 검사하지 않는다. 그 사이 다른 정상 관리 일이 채택을 바꿔도 구 학습 결과가 최신 채택을 덮는다. 결과를 남기는 것과 가변 CURRENT 효과를 무조건 이어 쓰는 것은 다르다. |
| 조건 | 학습 done_run에서 result 쓰기까지만 저장하고 중단 → 그 보고 파일만 잠시 모름으로 두고 정상 force_new를 배정·done_job 처리 → CURRENT는 version=None, adopted_gen=4 → 옛 보고를 다시 읽으면 `_resume`이 이전 reason=None을 사용해 학습 버전을 CURRENT로 덮고 gen=5로 만듦. 채택 대기 flag도 없음. |
| 확신 | 확인함 — 직접 CURRENT를 조작한 모형 외에 **실제 force_new 요청·배정·done_job을 교차시킨** 함수 재현으로 같은 결과 확인 |
| 제안 | 결과 기록에 채택 전제/대상 효과 상태를 보존하고 재개 때 자기 효과가 이미 반영됐는지, 다른 채택이 선행했는지 구분한다. CURRENT가 다른 decision/gen으로 진행됐으면 옛 효과를 덮지 말고 채택 대기로 전환한다. 결과의 성공/판정 기록과 아직 미반영인 외부 상태 전이를 구별한다. 시험 설정 변경과의 교차도 동일하게 시험한다. |

### N2 — run_choice의 ‘끝난 것으로’가 산출물 채택을 빠뜨리고 생성 요청을 재실행시킴

| 칸 | 내용 |
|---|---|
| 번호 | N2 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 위치 | `drive/scripts/arbiter.py:598`~617 `RunChoice`, 1149~1153 `_completed`; 설계 ‘확인 필요’·작업 종류별 완료 계약 |
| 문제 | run_choice=done은 결과와 lock done만 쓰며 artifact가 있는 학습/관리 실행의 CURRENT나 채택 대기 판정을 수행하지 않는다. create도 결과의 task를 항상 run으로 써 `_completed`가 기대하는 create와 다르다. |
| 조건 | verified=True 목록이 있는 학습 needs_check에서 done 선택 → result=done_by_choice·lock=done인데 CURRENT는 VA 그대로. create needs_check에서 done 선택 → task=run 결과가 생기고 같은 요청이 C2에 chunk2·새 create run으로 바로 재배정됨. 정상 생성 완료 결과의 task_id도 사람 선택 경로에는 없다. |
| 확신 | 확인함 — 두 종류 실제 run_choice 재현 |
| 제안 | 종류별 정상 완료와 사람 완료가 공통의 멱등한 완료/채택 전이를 사용하게 한다. 학습/산출물은 현재 채택 전제·오염 검사를 거쳐 채택 또는 채택 대기, create는 확인된 새 TASK ID와 create 결과로 닫는다. 단순 상태 done을 성공 효과 전체의 증거로 쓰지 않는다. needs_check에서 선택까지의 대기/실행 종료 조건도 RunChoice.judge에는 없어 TASK와 같은 선택 조건 계약을 함께 연결해야 한다. |

### N3 — 개별 파일 모름을 완료 인계·처리된 보고로 굳혀 영구 대기를 만듦

| 칸 | 내용 |
|---|---|
| 번호 | N3 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 위치 | `drive/scripts/arbiter.py:1044`~1046 `reissue`, 1389~1394 인계 기록, 845~851 보고 처리, 1413~1417 처리 목록 |
| 문제 | 개별 잠금이 unknown이면 재발급에서 빠지지만 handover는 완료로 기록된다. 다른 한편 실행형 done_run의 잠금을 못 읽으면 stale로 끝내 asks_handled에 넣는다. 다음에 파일을 정상적으로 읽어도 인계/보고를 다시 하지 않는다. |
| 조건 | epoch2 첫 회에 `file:arb/locks/task/7.json`만 모름 → handover/2는 있으나 정상 회차 뒤에도 lock epoch1. 별도 장면에서 정상 학습 done_run 처리 시 `file:arb/locks/train/m.json`만 모름 → 이후에도 state=running, CURRENT=VA이고 보고 이름은 asks_handled에 남음. |
| 확신 | 확인함 — 두 경우 실제 결정/재실행 확인 |
| 제안 | 미완료 인계 자원 목록을 보존하거나 개별 파일 모름이 해소될 때 재조정에서 구 epoch를 다시 발급한다. 보고가 의존하는 lock/result/CURRENT/목록을 못 읽었으면 stale/handled가 아니라 defer로 둔다. 현재 처리 목록 가지치기 정책보다 먼저, 보고를 처리했다고 확정할 전제를 맞춘다. |

### N4 — publish_lock이 배정 밖 TASK와 다른 작업 줄에도 권한을 만들어 줌

| 칸 | 내용 |
|---|---|
| 번호 | N4 |
| 심각도 | 높음 |
| 관점 | 접근·동시성 |
| 종류 | 코드·시험 |
| 위치 | `drive/scripts/arbiter.py:830`~841 `publish_lock` 분기 |
| 문제 | rid·session·decision·chunk만 맞는 active assign을 찾고, 그 배정이 read 줄인지와 요청 TASK가 assign.tasks에 속하는지는 확인하지 않는다. 임의 TASK의 publish=True 잠금을 새로 줄 수 있다. |
| 조건 | TASK 7만 배정받은 backup C1이 같은 배정 식별자로 task=999 publish_lock을 보냄 → TASK 999에 held·publish=True 잠금이 생김. 이는 요청 처리기가 TASK 번호를 잘못 붙이는 정상 실수도 막지 못한다. |
| 확신 | 확인함 — 실제 잘못된 게시 잠금 생성 확인 |
| 제안 | read lane, 현재 assign epoch, 배정 TASK 집합 및 요청 소유를 모두 검사한다. 다른 TASK/다른 lane의 publish_lock은 거절하고 알린다. 일반 권한 도우미의 phase 검사를 강화한 만큼 권한을 발급하는 이 경계도 같은 자원 범위를 지켜야 한다. |

### N5 — signature가 CURRENT 버전·채택 플래그·실행형 잠금을 비교하지 않음

| 칸 | 내용 |
|---|---|
| 번호 | N5 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 시험 |
| 위치 | `tests/test_arbiter_433.py:652`~660 `signature`, 728행 이후 장면 반복 |
| 문제 | CURRENT는 실제 버전 대신 ‘version이 None이 아님’만 비교하고 flags와 관리/학습/create/aggregate 잠금은 빠져 있다. 복구 요청도 종류 이름만 비교한다. 따라서 잘못된 모델 채택이나 잘못 남은 채택 대기·실행 잠금이 정상 실행과 같은 signature로 통과할 수 있다. |
| 조건 | 정상 학습 상태에서 CURRENT.version을 WRONG, adopted_gen을 999로 바꾸고 adopt_wait flag를 추가해도 signature는 기존과 동일함. 단순 비교 모형이 아니라 실제 시험의 signature 함수를 호출해 확인했다. |
| 확신 | 확인함 — 실제 signature 동등 반환 |
| 제안 | 생성된 실행 ID·시각처럼 달라도 되는 값만 정규화하고, CURRENT가 어느 논리 작업의 어떤 파일 집합을 채택했는지, flag·모든 줄의 잠금 상태/실행 연결·복구 원요청/TASK를 비교한다. baseline끼리 일치만 보지 말고 잘못된 버전/잠금/flag를 인위적으로 넣었을 때 비교가 반드시 실패하는 음성 시험을 추가한다. |

## 4. 쓰기 경계 시험 평가·추가 장면

공식 4장면×같은/새 마스터의 8개 경계 시험은 실제 누락 잠금·결과 선기록 문제를 검출할 수 있고 개선이다. 각 회차의 Write prefix를 열거하는 방식도 타당하다. 다만 범위는 네 장면의 **외부 사건이 고정된 경로**이며, 다른 요청/신호·일시적 파일 실패가 끼어드는 경로까지 보장하지 않는다. N1은 prefix 뒤에 다른 정상 관리 일을 넣었을 때 나타난다.

추가한 학습 채택 장면은 정상 모델 VA·시험 T0·출처가 알려진 D0에서 시작했다. 학습 done_run 회차의 Write 5개에 대해 0~4개 저장 후 끊고, 동일/새 epoch에서 5회 더 진행했다. 실행기는 새 epoch/잠금 gen을 읽어 보고를 다시 냈다. 총 10개 경우 모두 최종 CURRENT=그 학습 실행 버전, 학습 잠금=done, 불필요한 flag 없음으로 통과했다. 이것은 현재 코드의 긍정적인 수렴 확인이며 N1의 교차 전제를 포함하지 않는다.

우선 추가할 장면:

- **학습/채택:** result 저장 뒤 CURRENT 변경·시험 설정 변경·다른 채택 신호를 교차. 성공 결과의 저장 시점과 실제 CURRENT 전이 시점의 의미를 정한다(N1).
- **adopt_choice:** current와 flag 두 효과 각각의 경계, 그 사이 다른 CURRENT 변경. 선택된 버전/flag까지 엄격 비교한다.
- **run_choice:** done(verified artifact·비산출물·create), redo, 결과만 저장 뒤 중단, 실행기 새 gen 재보고, create TASK ID 보존(N2).
- **publish_lock:** 자기/다른 TASK, read/일반 GPU lane, 잠금만 저장 뒤 중단, 결과와 release까지 마무리(N4).
- **stop/release:** hold와 GPU stop 효과 사이 중단, until 만료, 원정지 ID가 다른 해제, 같은 회차 둘 이상의 정지/해제.
- **모름/여러 보고:** 개별 실행 잠금/결과/CURRENT/버전 목록 모름, 같은 회차 여러 end·done_run, 보고가 잠시 목록에서 사라졌다 다시 등장함(N3).

결과 먼저 쓰기는 TASK 진행 유실을 해결한다. 그러나 결과 존재를 ‘모든 가변 효과의 최종 완료’와 동일시해서는 안 된다. `_resume`와 handover 역시 자원별 미완료 효과와 최신 상태의 관계를 보존해야 한다. 이 부분은 결과·인계 계약에 보충할 최소 내용이다.

## 5. 1b 시작 판단

### 1b 전에 고칠 것

1. **N1:** 채택 결과 재개 시 다른 CURRENT/시험 설정 변경을 덮지 않는 조건과 결과 상태를 정한다.
2. **N2:** run_choice의 정상 완료 효과를 작업 종류별 완료와 통합하고 create 결과/TASK ID·선택 조건을 맞춘다.
3. **N3:** 개별 파일 unknown은 인계 완료/보고 처리 완료로 확정하지 않도록 한다.
4. **N4:** publish_lock의 lane·TASK 집합 검사를 넣는다.
5. **N5:** 경계 시험의 의미상 최종 상태 비교를 강화하고 위 반례를 회귀 시험으로 둔다.

순수 판정 함수의 공용 동작을 고친 뒤 실제 I/O를 붙이는 편이 안전하다. 어댑터의 읽기·쓰기 인터페이스와 가짜 환경 확장은 병행할 수 있다.

### 1b와 함께 고쳐도 되는 것

- 실제 읽기 실패를 파일별 unknown/defer에 전달하고, 새 epoch 뒤 실행기가 새 gen으로 보고를 재발급하는 연결.
- 실행형 잠금에도 단계별 권한 확인을 적용하는 API. 현재 executor_may_follow는 TASK용이므로 관리/학습/취합/create가 이 함수를 그대로 호출할 수는 없다.
- 정기 점검의 단계 정체, CVAT 호출 timeout/서버 작업 상태, 단계 기록 번호의 재시작 보존. 명시된 1b 범위이므로 미구현 자체를 이번 새 결함으로 집계하지 않았다.
- 실제 SDK의 참조 export/조직/접속 확인 호출과 proxy 허용 범위를 통합 시험한다. broad raw API 차단을 풀어서 해결하지 않는다.

### 운영 결정이 필요한 것

세션 지문을 증명으로 보지 않는 결정, A0 토큰 공유, 야간 처리, CVAT 펜싱 잔여 위험은 재승인을 요청하지 않는다. N1에서 결과 기록을 채택의 논리적 순서로 간주하더라도, 그 뒤 다른 관리 선택을 구 효과가 덮지 않도록 하는 것은 코드/계약 문제다. 이를 운영 위험 수용으로 넘길 필요는 없다. 새로 필수인 운영 결정은 발견하지 못했다.

## 점검했지만 문제가 없던 항목

- 이전의 승인 전/격리 쓰기, generic API와 목록 raw 객체 우회, 불완전 TASK 보고, 실패 후 복원 권한 캐시는 비교본에서 차단됐다.
- 입력 사본·결과 선기록·TASK 결과 재개·누락 TASK 잠금 재조정은 기존 대표 반례에서 동작한다.
- grant 소유자 모름은 판정하지 않고, 전체 목록 unknown 뒤에는 handover를 다음 정상 회차에 수행한다.
- 산출물 없는 관리 완료와 TASK 없는 create/refresh 배정, until 자동 해제, 프레임 범위/매핑 검증이 추가됐다.
- 공식 두 시험과 추가한 단독 학습 채택 10개 prefix 장면은 모두 통과했다.

## 시간이 모자라 보지 못한 항목 및 검증 한계

- 요청된 M1~M12 판정·경계 시험 품질·추가 장면·새 계약·1b 판단은 모두 다뤘다. 모든 신호/보고 교차의 완전 탐색은 아니다. 위 추가 장면 전체를 새 시험 파일로 구현하지는 않았다.
- 기존 b8 스크립트의 그대로 실행은 도우미 이름 변경으로 중단됐고, 새 API 비교본으로 의도를 옮겨 검증했다. 저장소 시험 코드는 바꾸지 않았다.
- 실제 Drive·Apps Script·Kaggle·CVAT 접속과 실측, 1b/2단계의 어댑터·셀 전환 자체, 설계 다른 절의 전면 재검토는 범위 밖이다.
- 기존 v4.32.0 회귀 시험은 이번 좁은 수정 검토에서 재실행하지 않았다. 공식 신규 두 시험과 현재 코드의 추가 재현을 중심으로 검증했다.
- F7·F8과 저장소 밖 앱은 검토하지 않았다.
