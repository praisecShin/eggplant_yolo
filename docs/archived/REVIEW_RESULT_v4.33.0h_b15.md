# v4.33.0h 검토 결과 — b15

검토일: 2026-11-15.`AGENTS.md`와 요청서에 따라 b14 U1~U7의 반영 범위만 검토했다. 대응표·수정 코드·관련 시험·설계의 알려진 한계를 읽었다. 코드·노트북·시험·설계서는 수정하지 않았으며 실제 서비스에 접속하지 않았다.

**판정: U1·U2·U4·U7 부분 해결, U3·U5·U6 해결. 지정 시험 467개는 모두 통과했다. 추가 재현에서 높음 4건·보통 1건을 확인했으므로 U1의 입력 격리와 U2·U4의 경계 보완 후 2b 연결을 진행하는 것을 권한다.**

## 시험

| 실행 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 192개 성공, `RESULT True` |
| `python3 tests/test_access_433.py drive` | 68개 성공, `RESULT True` |
| `python3 tests/test_master_433.py drive` | 56개 성공, `RESULT True` |
| `python3 tests/test_master_main_433.py drive` | 56개 성공, `RESULT True` — 로컬 실제 하위 프로세스 포함 |
| `/tmp/node-v22.16.0-linux-x64/bin/node tests/test_keeper.js apps_script/Keeper.gs` | Linux Node.js v22.16.0, 95개 성공, `RESULT True` |
| `/tmp/egg_b14_probes.py` 재실행 | 기존 current_change=1 격리, 정상 요청 접수, 조회 실패 unknown, 잘못된 CVAT 행 None, 요청 목록 실패 시 야간 종료 보류, GPU 조회 실패 시 push 없음 |
| 추가 `/tmp/egg_b15_probes.py` | 아래 V1~V5 재현 |

Python은 모두 `PYTHONDONTWRITEBYTECODE=1`로 실행했다. 로그는 `/tmp/b15_{arbiter,access,master,main,keeper,old,probes}.log`에 있다. 추가 재현 파일도 `/tmp`에만 작성했다.

## U1~U7 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| U1 복합 필드·입력 격리 | 부분 해결 | 기존 current_change=1과 train_keys 오류는 격리된다. 다만 중첩 type의 검사 자체가 예외를 내고, 산출물 task_keys 및 사람 필수 ID의 검사 누락이 남았다(V1·V2). |
| U2 import 경계 | 부분 해결 | lock_imports를 실제 부른 공식 시험에서 일반 작업 폴더의 동명·목록 밖 모듈 및 사전 로드 모듈을 차단한다. 그러나 폴더 이름만 site-packages인 임의 경로는 허용하며, 허용된 설치 경로의 배포 모듈 이름 충돌도 차단하지 않는다(V3). |
| U3 상태 문자열 | 해결 — 성공 응답 해석 기준 | 주소의 error/running을 무시하고 상태 값만 비교한다. 미지 값·복수 상태는 unknown이다. nonzero 응답의 absent 판정은 U7의 V5로 별도 평가했다. |
| U4 조회 실패·최신성 | 부분 해결 | 실패 시 unknown/None, 180초 초과 시 만료하는 공식 시험 통과. 그러나 긴 조회 묶음의 끝에서 오래된 관측에 새 시각을 붙인다(V4). |
| U5 CVAT 형태·페이지 | 해결 — 이번 요청 범위 | 모르는 행은 None, 다음 페이지를 조회하고 5쪽을 넘으면 None으로 둔다. 기존 잘못된 행 재현과 공식 페이지 시험 통과. 실제 응답 형식은 T10에서 확인해야 한다. |
| U6 밤 끝내기 | 해결 | last_run_at은 회차 시작에 갱신하고, 완전한 읽기·쓰기 성공 회차만 last_clean_at으로 인정한다. b14의 요청 목록 실패 반례에서 exit_reason은 None이다. 확인 필요 잠금을 busy에서 제외한 결정도 반영됐다. |
| U7 모르는 GPU 상태 | 부분 해결 | 일반 조회 오류·미지 상태는 status_unknown으로 push하지 않는다. 다만 일반 오류 문구의 not found도 노트북 부재로 오인한다(V5). |

b14 재현의 `unlisted_import`는 여전히 성공하지만, 옛 재현은 VerifiedFinder만 설치하고 새 lock_imports를 호출하지 않는다. 이 출력만으로 U2 미해결이라고 판단하지 않았다. V3은 **새 lock_imports까지 실제 호출한 별도 프로세스**의 결과다.

## 새 발견

### V1 — 입력 검사 자체의 예외와 사람 필수 ID 누락

| 칸 | 내용 |
| --- | --- |
| 번호·심각도 | V1 · 높음 |
| 관점·종류 | 복구·스케줄링 · 코드·시험 |
| 관련 항목 | U1, AGENTS.md 3장 7 |
| 위치 | `drive/scripts/arbiter.py:255` `_fits`의 _CC, `:232` person 형태 표, `:482` requester_ok; `drive/scripts/arb_master.py:69` 설정 검사 |
| 문제 | 중첩 type이 문자열인지 확인하기 전에 dict의 키 포함 검사를 하므로 list/dict 입력은 TypeError를 낸다. person 형태 표는 ID가 있는 경우의 타입만 검사하고 필수 여부는 검사하지 않아, account·권한은 있지만 id가 없는 사람도 설정에 채택되고 요청 접수에서 KeyError를 낸다. |
| 조건 | 인계 뒤 `{"type":"done_job","current_change":{"type":[]}}` 보고와 정상 요청을 넣었다. 연속 두 회차 `decide_error:TypeError`, writes=0, 정상 요청 intake 없음. 별도 World에서 사람을 `{"account":"a0@x","perms":["request"],"status":"active"}`로 주면 person 검사 결과는 빈 문자열인데 요청 회차는 `decide_error:KeyError`, writes=0이다. |
| 확신 | 확인함 — 실제 MasterLoop·LocalStore 재현 |
| 제안 | 검사 함수가 임의 JSON 입력에 예외 없이 오류 필드를 반환하게 한다. 중첩 type은 문자열 확인 뒤 집합/사전과 대조하고, 사람 id/account 등 실제 필수 필드는 설정 채택 전에 확인한다. 두 입력 옆 정상 요청의 진행 또는 안전한 설정 보류를 시험한다. |

### V2 — 산출물 목록의 task_keys가 형태 표에서 빠져 전체 회차를 막는다

| 칸 | 내용 |
| --- | --- |
| 번호·심각도 | V2 · 높음 |
| 관점·종류 | 복구·스케줄링 · 코드·시험 |
| 관련 항목 | U1, 고정 시험 TASK 오염 대조 |
| 위치 | `drive/scripts/arbiter.py:231` vfiles 형태 표, `:1303` train_start_compat, `:1574` 학습 배정의 데이터셋 목록 읽기 |
| 문제 | train_start_compat가 읽는 task_keys는 형태 표에 없다. 숫자는 검사에 통과한 뒤 set 변환에서 실패한다. 학습 배정은 목록을 v.f에서 직접 읽으며, vfiles를 unknown으로 분류한 경우에도 이 경로가 그 표시를 확인하지 않는 점을 함께 보완해야 한다. |
| 조건 | 정상 지문의 `datasets/ds/CURRENT.json`이 v1을 가리키고, `datasets/ds/v/v1/_files.json`은 `{"files":{},"task_keys":1}`이다. dataset=ds인 train 요청과 정상 track 요청을 넣었다. vfiles 검사 결과는 빈 문자열, 연속 두 회차는 `decide_error:TypeError`, writes=0, 정상 track intake 없음이다. GPU 실행기가 없어도 호환성 계산이 먼저 실행되어 발생한다. |
| 확신 | 확인함 — 실제 MasterLoop·LocalStore 재현 |
| 제안 | task_keys를 문자열 목록으로 검사하고, 호환성 계산 등 목록 직접 소비 경로도 unknown 표시를 따르게 한다. 누락·잘못된 타입·읽기 실패를 모름으로 처리하면서 다른 요청은 진행하는 시험을 둔다. |

### V3 — site-packages라는 이름만 가진 임의 경로도 import 허용된다

| 칸 | 내용 |
| --- | --- |
| 번호·심각도 | V3 · 높음 |
| 관점·종류 | 접근 · 코드·시험 |
| 관련 항목 | U2, 검증한 배포 코드만 실행 |
| 위치 | `drive/notebooks/master_boot_v4.33.py:191` `_allowed`, `:199` lock_imports, `:166` VerifiedFinder.find_spec |
| 문제 | 허용 루트 밖이어도 경로 구성 요소에 site-packages/dist-packages가 있으면 허용한다. 실제 설치 위치인지 확인하지 않는다. 또한 허용 경로에서 발견한 목록 밖 모듈은 배포 모듈과 외부 패키지의 이름을 구별하지 않고 실행한다. |
| 조건 | 새 `python -I` 프로세스에서 `/tmp/b15_import_…/site-packages`를 sys.path에 넣고, 그 안에 목록 밖 b15_unlisted.py를 둔 뒤 lock_imports를 호출했다. 검증된 b15_entry가 이를 import하여 `unverified fake package`를 반환했고 path_kept=true였다. 실제 설치 폴더에 목록에서 빠진 우리 모듈 이름의 파일이 있는 경우도 같은 fallback 구조다. |
| 확신 | 확인함 — 새 lock_imports를 호출한 실제 하위 프로세스 재현 |
| 제안 | 실제 설치 루트를 명시적으로 수집해 경로를 대조하고, 디렉터리 이름만으로 허용하지 않는다. 배포 모듈 이름 공간과 승인 외부 패키지를 구분해 목록에서 빠진 배포 모듈은 설치 경로에서도 거절한다. 작업 프로세스의 외부 의존성에도 같은 정책을 정한다. |

### V4 — 오래 걸린 조회가 오래된 결과를 최신으로 되살린다

| 칸 | 내용 |
| --- | --- |
| 번호·심각도 | V4 · 높음 |
| 관점·종류 | 복구·동시성 · 코드·시험 |
| 관련 항목 | U4, 확인 필요 선택의 종료 근거 |
| 위치 | `drive/scripts/master_main.py:143` ProbeCache.refresh, 특히 `:153`~160 시각 대입 |
| 문제 | kernels 조회를 마친 뒤 TASK 목록·CVAT 조회까지 모두 끝난 시각을 kernels_at과 imports_at에 함께 넣는다. 따라서 묶음 앞에서 얻은 값이 이미 180초를 넘겼어도 새 값으로 보인다. 실행기·TASK를 여러 개 순차 조회하는 실제 구조에서 발생할 수 있다. |
| 조건 | clock=1000에 _kernels가 g1=ended를 반환하고, 뒤의 _tasks에서 가짜 시각을 181초 진행시켰다. refresh 후 now=1181, kernels_at=1181이며 probes는 unknown이 아니라 ended다. imports도 여러 TASK의 앞쪽 관측이 전체 조회 종료 시각으로 기록되는 구조다. |
| 확신 | 확인함 — 실제 refresh와 주입 clock으로 재현 |
| 제안 | 대상별 실제 조회 시각을 기록하거나, 보수적으로 해당 조회 묶음의 시작 시각을 사용한다. 조회 도중 이미 만료한 값은 게시할 때도 unknown으로 둔다. 성공 뒤 기다리는 시험 외에 성공 응답을 모으는 도중 시간이 흐르는 시험을 추가한다. |

### V5 — 일반 not found 오류가 노트북 없음으로 바뀌어 GPU push가 허용된다

| 칸 | 내용 |
| --- | --- |
| 번호·심각도 | V5 · 보통 |
| 관점·종류 | 동시성·스케줄링 · 코드·시험 |
| 관련 항목 | U7 |
| 위치 | `drive/scripts/master_main.py:87`~89 parse_kernel_status, `:283` GpuLauncher의 ended/absent 분기 |
| 문제 | nonzero 종료의 오류 원문에 404 또는 not found가 들어가면 곧바로 대상 노트북 부재로 확정한다. 로컬 설정·실행 의존성·다른 URL의 부재는 대상 커널이 없다는 증거가 아니다. |
| 조건 | 가짜 status가 rc=1, stderr=`local configuration file not found`를 반환하고 push는 성공하게 했다. gpu_needed=1에서 호출은 status→push이고 결과는 pushed다. 실제 Kaggle 중복 실행 자체를 재현한 것은 아니다. |
| 확신 | 확인함 — 실제 GpuLauncher에 가짜 CLI 주입 |
| 제안 | 대상 커널 조회의 확정된 부재 응답만 absent로 인정하고, 일반 오류 문구는 unknown으로 둔다. T5·T6에서 실제 ‘최초 생성 대상 없음’과 인증·설정 오류 형식을 각각 확보한 뒤 좁은 판정을 시험한다. |

## 요청한 정책에 대한 의견

- **사람 목록 전체 보류:** 잘못된 새 설정을 부분 적용하면 같은 계정의 권한·역할을 다르게 해석할 수 있으므로 전체를 채택하지 않는 선택은 받아들일 만하다. 마지막 정상 설정을 쓰다가 20분 뒤 config 모름으로 보류하는 기존 정책도 일관된다. 다만 V1처럼 필수 칸 누락은 실제로 보류되지 않는다. 새 설정 거절 사유·마지막 정상 시각을 관리 화면에 보이는 것이 운영 복구에 도움이 된다. 기존 설계에 명시된 정지·취소 지연 한계는 새 결함으로 세지 않았다.
- **Kaggle 패키지 호환성:** 일반 site-packages/dist-packages에 설치된 cvat_sdk·kaggle·ultralytics는 현재 필터의 허용 대상이므로 그 경로 자체 때문에 막히지는 않는다. 반면 별도 소스 폴더를 가리키는 editable 설치, 데이터셋에 풀어 sys.path로 넣은 패키지는 차단될 수 있다. 실제 Kaggle 설치 레이아웃은 접속하지 않아 확인하지 않았다. 필요한 설치 경로를 실측해 허용하되 V3처럼 폴더 이름만으로 넓혀서는 안 된다.
- **모르는 GPU 상태:** 상태 형식을 계속 해석하지 못하면 매 회차 status_unknown이 되어 자동 GPU는 계속 뜨지 않는다. 마스터 재기동도 파서를 바꾸지 않으므로 해결되지 않는다. 이는 모름일 때 push하지 않는 요구에 맞는 안전한 보류이며, 임의 기동 fallback을 추가할 이유는 아니다. 다만 현재 main은 status_unknown을 로그로 알리지 않으므로 T5·T6를 운영 연결의 통과 조건으로 삼고 장기 보류를 운영자가 알아볼 수 있게 해야 한다. V5는 이 보류를 잘못 우회하는 별도 결함이다.
- **밤의 완전 관측 조건:** 파일 하나를 계속 못 읽으면 야간 유휴 종료가 막혀 최대 실행 시간까지 유지되는 선택은 받아들일 만하다. 부분 관측을 ‘일 없음’으로 확정하지 않는 비용이며 MAX_RUN_H의 상한이 있다. 읽기 회복 후에는 정상 유휴 종료가 가능하다. 파일 하나를 버려도 된다고 판단하려면 그 파일의 의미별 별도 정책이 필요하므로 이번 수정에서 조건을 완화할 필요는 없다.
- **밤의 확인 필요 제외:** _busy_count에서 needs_check를 빼는 결정과 알려진 한계 문서가 일치한다. 다만 다른 정상 대기 요청이 있으면 runnable/gpu_needed가 별도로 남을 수 있으므로 ‘확인 필요만 남음’이라는 조건에서 평가했다.

## 점검했지만 문제가 없던 항목

- 지정 467개 시험과 b14 기존 반례 중 U1의 단순 숫자 객체, U3~U7의 원래 실패 입력.
- 일반 작업 폴더의 import 차단·목록 안 동명 모듈 우선·일반 사전 로드 모듈 제거·표준 라이브러리 사용.
- 정확한 커널 상태 값 비교, cancelRequested를 실행 중으로 취급하는 선택.
- 조회 예외의 unknown/None 전환, 완료된 캐시의 180초 만료, 회복 뒤 정상값 복원.
- CVAT 미지 행·복수 페이지·페이지 상한의 모름 처리.
- 불완전한 직전 회차 뒤 야간 유휴 종료 보류와 needs_check 제외 결정.

## 시간이 모자라 보지 못한 항목·한계

- 짧은 검토 범위 밖의 v4.32 전체 회귀와 2b 실제 처리기·GPU 노트북은 검토하지 않았다.
- 실제 Kaggle 패키지 설치 위치·CLI 출력·커널 부재 응답, CVAT 스키마, Drive 지연은 서비스 접속 금지에 따라 실측하지 않았다.
- 모든 JSON 필드 조합을 전수 퍼징한 것은 아니다. 따라서 V1·V2를 수정해도 형태 표의 완전성을 이번 검토만으로 보증하지 않는다.
