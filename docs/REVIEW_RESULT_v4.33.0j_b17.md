# v4.33.0j 검토 결과 — b17

검토일: 2026-11-16. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0j.md`, b16 보고서, 설계의 보호 모드·차례·CTRL앱 절, 2a·2d 구현 설명과 관련 코드·시험을 확인했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle에는 접속하지 않았다. 시험 도구 Node.js·jsdom만 `/tmp`에 준비했다.

**판정: W1 부분 해결, W2 해결(기존 재현 범위), W3 해결(기존 import 우회 범위). 지정 시험은 모두 통과했지만 새 발견 6건(높음 3건, 보통 3건)이 있다. X1~X3을 먼저 보완하고, 감시·제어 연결 전에 X4~X6도 반영하는 것을 권한다.**

## 시험 결과

| 실행 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 202개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 65개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 61개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 6개 성공. 입력 5,338개, 변형 44,890개 + 두 칸 조합 1,680개. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 6개 성공. 변형 99,095개 + 두 칸 조합 1,680개. 예외·뜻 위반 0건 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 101개 성공, RESULT True |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 35개 성공, RESULT True |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 13개 성공, RESULT True |

Node.js는 Linux v22.16.0을 사용했다. jsdom은 저장소 대신 `/tmp/b17-js-approved`에 설치하고 NODE_PATH로 연결했다. 로그는 `/tmp/b17_{arbiter,access,master,master_main,fuzz,fuzz7,keeper,collector,ctrl}.log`이다. `/tmp/egg_b16_probes.py`는 남아 있지 않아 재실행하지 못했다.

추가 재현은 `/tmp/b17_arb_probe.py`, `/tmp/b17_collector_probe.js`, `/tmp/b17_ctrl_probe.js`, `/tmp/b17_ctrl_unknown.js`에 작성했고 같은 이름의 `.log`로 결과를 남겼다. Python 재현은 공식 시험의 Sim 정의를, JavaScript 재현은 공식 시험의 가짜 Drive·CVAT·커넥터를 재사용했다. Keeper 재진입은 실제 `keeperDecide_`를 Node vm에서 세 번 연속 호출해 확인했다.

## W1~W3 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| W1 | 부분 해결 | seq·effects 전체 누락, 배정 지문 누락은 보호 모드로 들어간다. seed=7도 통과한다. 그러나 effects가 비어 있지 않다는 것만 검사하므로 필요한 효과 일부가 빠진 계획은 통과한다. 정지 효과 없이 done을 쓰는 X1이 남는다. |
| W2 | 해결 — 기존 발견 범위 | active가 잘못된 hold는 보호 모드로 들어가 접수·배정을 하지 않는다. 보호 모드·internal_unknown 회차는 last_clean_at을 갱신하지 않아 밤의 night_idle 종료를 막는다. 공식 회귀·퍼징 통과. 다만 정지 계획 자체의 의미 손상은 X1이다. |
| W3 | 해결 — 기존 우회 범위 | lock_imports가 검증 목록과 예약 이름 전체를 합쳐 최상위 이름·하위 모듈을 sys.modules에서 제거한다. 목록 밖 예약 이름은 Finder도 차단한다. 기존 사전 로드 우회가 닫혔고 master_main 시험도 통과했다. 실제 Kaggle IPython 환경의 모든 기존 참조까지 검증한 것은 아니다. |

## 새 발견

### X1 — 효과 일부가 빠진 정지 계획을 정상 완료하고 새 일을 배정한다

| 칸 | 내용 |
| --- | --- |
| 번호 | X1 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | W1, 보호 모드, 정지 효과·완료의 정합성 |
| 위치 | `drive/scripts/arbiter.py:345` 계획 effects 검사, `:676` Stop, `:975`~994 계획 재개·완료; `tests/test_fuzz_433.py:129` untrusted_judgement |
| 문제 | 계획의 effects는 비어 있지 않은 문자열 목록이면 통과한다. 신호가 요구하는 효과와 대조하지 않아 `stop` 계획이 `['gpu']`만 가지고 있어도 보호 모드에 들어가지 않고, hold 없이 완료된다. |
| 조건 | 정상 인계를 마친 Sim에서 stop 계획 쓰기 직후 중단한다. 저장된 effects를 `['hold','gpu']`에서 `['gpu']`로 바꾸고 재개한다. `protect=[]`, signal_done은 `result=done, effects={'gpu':'reflected'}`, hold는 없음이다. 뒤이어 GPU와 TASK 99 track 요청을 넣으면 active 배정이 생긴다. `/tmp/b17_arb_probe.log`에서 확인했다. |
| 확신 | 확인함 — 실제 decide_round 여러 회차 실행 |
| 제안 | 신호 종류별 필수 효과 집합과 계획의 kind·sid·대상을 대조하고, 불완전한 계획은 보호 모드로 보낸다. 효과 목록 전체 누락뿐 아니라 일부 삭제·중복·다른 효과 치환을 고정 회귀 시험에 넣는다. 퍼징의 신뢰 판정이 구현의 input_problem을 그대로 재사용하므로 이 검사 누락까지 정답으로 받아들이는 점도 보완한다. |

### X2 — 시험 환경 전환 실패 후 운영 폴더에 제어 신호를 쓴다

| 칸 | 내용 |
| --- | --- |
| 번호 | X2 |
| 심각도 | 높음 |
| 관점 | 접근·동시성 |
| 종류 | 코드·시험 |
| 관련 항목 | CTRL앱 운영·시험 분리 |
| 위치 | `apps/ctrl/index.html:189`~196 폴더 읽기, `:354`~362 send, `:371` setEnv |
| 문제 | setEnv는 화면 데이터만 비우고 이전 환경의 S.dirs·S.people·S.at을 남긴다. 새 환경 폴더 조회가 실패하면 이전 전송 대상이 유지되어 시험 띠 아래의 버튼으로 운영 신호를 보낼 수 있다. |
| 조건 | 공식 CTRL 시험의 가짜 운영 폴더를 읽은 뒤, 존재하지 않는 시험 폴더로 전환한다. 오류 표시 이후에도 정지 버튼은 활성 상태다. 버튼을 눌러 전송하면 parentId가 운영 signals 폴더인 `stop__M1__….json`이 생성된다. `/tmp/b17_ctrl_probe.log`: `test folder missing; stop disabled=false`, `created on prod signals=true`. |
| 확신 | 확인함 — jsdom에서 실제 화면 클릭·create_file 인수 확인 |
| 제안 | 환경 전환 즉시 폴더·사람·전송 대화상자·읽기 완료 상태를 무효화하고 새 환경 읽기가 완료될 때까지 제어를 막는다. 전송 시 환경과 읽기 세대가 같은지도 확인한다. 이전 환경의 비동기 읽기가 늦게 끝나 새 화면을 덮는 경우도 함께 막는다. |

### X3 — 자동 요청 생성 실패를 다음 수집에서 재시도하지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | X3 |
| 심각도 | 높음 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | 2d 자동 backup·export 요청 누락 |
| 위치 | `apps_script/G_collector/Collector.gs:242` 스냅숏 저장, `:250`~254 자동 요청, `:467` 요청 생성 |
| 문제 | 변화 감지 기준인 cvat_tasks.json을 자동 요청보다 먼저 확정한다. 이후 Drive 오류 등으로 요청을 못 만들면 이미 변화를 소비했기 때문에 다음 회차에는 같은 TASK가 changes에 들어오지 않는다. 오류를 auto.error로 잡고 전체 ok=true로 기록하므로 자동 복구도 없다. |
| 조건 | 첫 수집에서 TASK 11의 _uld를 기록한다. 다음 수집에서 _vf로 변경하고 requests 폴더 createFile에 한 번만 오류를 주입했다. 첫 결과는 `auto={error:'fake Drive failure'}`. 같은 최신 TASK로 다음 수집을 돌리면 `auto={found:0}`, requests=0이다. `/tmp/b17_collector_probe.log`. 기존에 export 이력이 있는 TASK라면 backfillVfNow도 그 TASK를 고르지 않는다. |
| 확신 | 확인함 — 실제 collect 두 회차와 가짜 Drive 쓰기 실패 |
| 제안 | 관측 스냅숏과 별도로 아직 발행하지 못한 자동 이벤트를 내구성 있게 보관하고 성공 확인까지 재시도한다. 요청 생성 성공 후 장부 저장 실패의 반대 순서에서도 같은 이벤트를 중복 생성하지 않도록 이벤트 식별자를 고정한다. |

### X4 — 같은 손상이 다시 생기면 보호 모드 진입 알림이 빠진다

| 칸 | 내용 |
| --- | --- |
| 번호 | X4 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | 보호 모드 진입·종료 알림 |
| 위치 | `apps_script/G_keeper/Keeper.gs:213`~226, `:365`~374 mailed 누적 |
| 문제 | 진입 알림 키가 경로·이유로만 만들어지고 과거 mailed에 있으면 무조건 억제된다. 한 번 복구되어 종료 알림을 보낸 뒤 같은 경로·이유로 다시 보호 모드에 들어가도 메일·푸시를 보내지 않는다. |
| 조건 | keeperDecide_에 hold active 손상 → 정상 → 같은 hold active 손상을 차례대로 넣고 mailed·prevProtectKey를 넘겼다. 진입 푸시 1, 종료 푸시 1, 재진입 푸시 0·메일 0이었다. |
| 확신 | 확인함 — 실제 판정 함수 연속 호출 |
| 제안 | 현재 보호 모드 구간과 과거 통지 이력을 구분하고, 정상→보호 전환은 같은 손상이어도 새 사건으로 알린다. 구간 안의 동일 알림만 중복 억제한다. |

### X5 — 수집기 생존 시각 필드가 달라 Keeper의 멈춤 알림이 작동하지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | X5 |
| 심각도 | 보통 |
| 관점 | 복구 |
| 종류 | 코드·시험 |
| 관련 항목 | 2d 수집기·Keeper 감시 연결 |
| 위치 | `apps_script/G_collector/Collector.gs:367`~374 writeHeartbeat_, `apps_script/G_keeper/Keeper.gs:340` collectorAt, `:232` 멈춤 알림 |
| 문제 | 수집기는 최상위 time 없이 last.time·last_ok를 쓰는데 Keeper는 최상위 o.time만 읽는다. 이 수집기의 collector.json에서는 collectorAt이 항상 null이라 20분 멈춤 알림 조건이 성립하지 않는다. |
| 조건 | 새 수집기가 생존 기록을 한 번 쓴 뒤 멈춘다. 아무리 오래되어도 Keeper가 collectorAt=null을 만들고 `st.collectorAt && …`에서 감시를 건너뛴다. CTRL앱은 last.time을 읽으므로 화면과 자동 감시가 서로 다르게 동작한다. |
| 확신 | 확인함 — 생산·소비 코드의 파일 형태 추적 |
| 제안 | 생존 기록의 필드 계약을 맞추고 실제 writeHeartbeat_ 산출물을 Keeper 입력으로 쓰는 연결 시험을 추가한다. |

### X6 — 정지 보류 읽기 실패가 화면에서 ‘없음’으로 바뀐다

| 칸 | 내용 |
| --- | --- |
| 번호 | X6 |
| 심각도 | 보통 |
| 관점 | 접근·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | CTRL앱 보류 표시·깨우기 1차 확인 |
| 위치 | `apps/ctrl/index.html:173` readFile, `:202`~206 목록 읽기, `:244` holdsActive, `:293`~303 깨우기 제어 |
| 문제 | 보류 파일 읽기 오류는 __bad 객체로 바뀐 뒤 active 필터에서 빠진다. 보류 목록 읽기 실패도 null을 빈 목록으로 바꾼다. 화면은 보류 없음으로 표시하고 일반 깨우기를 허용한다. 개별 파일 실패는 오류 띠에도 남지 않는다. |
| 조건 | 실제 active hold를 둔 공식 가짜 Drive에서 해당 파일의 download_file_content만 실패시켰다. 심판 기록은 오래된 상태로 둔다. 결과는 `hold display=없음`, `wake disabled=false`, `note=`였다(`/tmp/b17_ctrl_unknown.log`). Keeper의 별도 확인이 깨우기를 거절하므로 이 재현이 실제 보류 해제까지 이르지는 않는다. |
| 확신 | 확인함 — jsdom·실제 읽기 실패 주입 |
| 제안 | 없음·읽지 못함을 구분하고 보류 전체를 확인하지 못하면 깨우기와 보류 해제를 막는다. 폴더·목록·개별 파일 실패를 모두 표시한다. |

## 검토 질문별 보충

- **보호 모드 조건:** 옛 epoch의 정상 지문은 허용하고 현재 epoch의 다른 세션·미래 epoch은 막는다. 인계 전 옛 정상 파일만으로 보호 모드에 들어가는 경로는 발견하지 못했다. 공식 arbiter 시나리오에서 생성한 모든 판정 쓰기를 input_problem에 다시 넣었을 때 형태 오류는 0건이었다. 과거 모든 배포판 파일과의 호환성을 보증하는 검사는 아니다. 너무 좁은 검사로는 X1을 확인했다.
- **보호 모드 중 실행:** 심판은 회차 기록·알림만 쓰고 GPU 필요량도 0으로 기록한다. 실행기는 기존 배정·잠금의 권한 확인을 계속 사용하며 이미 승인된 단계는 진행할 수 있다. 새 확정 신청·반납·완료 보고의 심판 반영은 복구까지 기다린다. 이것을 실행 프로세스 전체의 즉시 정지로 해석해서는 안 된다. Keeper는 신선한 회차·자격이 같으면 보호 모드 심판도 살아 있다고 판단한다. 마스터는 보호 회차를 정상 관측으로 세지 않아 night_idle로 끝나지 않는다. 최대 실행 시간·자격 상실 종료는 별도다.
- **퍼징의 보류 해제 제외:** 같은 회차에 실제 inactive로 쓴 보류를 빼는 것은 정상 해제·만료 이후 배정을 허용하는 동작과 맞는다. 다만 must_protect가 구현의 검사 함수를 재사용하고, 단일 필드의 목록 원소 일부 삭제까지 독립적으로 생성·검증하지 않아 X1을 놓친다. 통과 결과는 이 범위 안의 결과다.
- **알림 경계:** 손상 경로·이유가 바뀌면 새 키로 알리고, 심판 기록이 오래되어 protect가 비어 있으면 이전 보호 상태를 유지하는 처리는 확인했다. X4 외에도 keeper.json을 읽지 못하면 이전 키·mailed를 빈 값으로 시작해 같은 진입 알림을 다시 보낼 수 있다. 메일·ntfy 실패도 재시도 상태를 저장하지 않으므로 전달 성공까지 보장하지 않는다. ntfy 주제는 요청 JSON의 topic에만 사용하고 응답·예외를 기록하지 않아 Drive·메일로 새는 경로는 발견하지 못했다.
- **W3·IPython:** 예약 이름은 현재 scripts와 명시한 과거 이름을 대상으로 하며 IPython 이름 자체를 지우지 않는다. 이미 다른 객체가 가진 이전 모듈 참조까지 제거하지는 않지만, 그것만으로 검증된 진입 모듈이 그 참조를 실행한다는 경로는 찾지 못했다. 실제 Kaggle 커널에서의 영향은 접속 금지 범위라 확인하지 않았다.
- **수집기 경계·ULD:** 배정·깨우기 함수 제거, CVAT GET 전용, 수집기의 status/·requests/ 쓰기를 확인했다. 실제 Uld.gs와 함께 돌린 시험도 통과했다. optional 함수는 typeof로 확인하고 Uld.gs의 수집기 함수 의존성도 맞는다. sources.json은 요청서가 지정한 ULD앱 산출물 예외로 판단했다.
- **자동 요청 형태·범위:** tasks는 문자열 목록, params는 객체, task_names는 이름 목록이며 검사에 거절되지 않는다. G 소유 요청은 system:G이고 backup·export는 AUTO_KINDS에 있다. AUTO_PROJECT_ID가 없으면 끄고 AUTO_NAME_PREFIX를 함께 적용한다. 기존 진행 요청을 수집기에서 지우거나 완료로 바꾸지는 않는다. 새 이벤트는 별도 RID로 접수되며 차례·읽기 받는 중 예외는 심판이 처리한다. 2b가 아직 없어 params가 실제 처리기까지 올바르게 전달되는지는 후속 연결 시험이 필요하다.
- **자동 규칙·관측 한계:** _uld 진입 backup, videos/·ULD 기록·장부가 있을 때 제외, 검토 상태 간 전환마다 export, _AA 자동 요청 중단은 확인했다. 전체 맞추기에서 처음 관측한 이름 변화도 changes를 거쳐 처리한다. 첫 수집은 자동 요청을 건너뛰며 기존 검토 TASK는 backfill 대상이다. 두 수집 사이에 상태가 바뀌었다 원래대로 돌아오는 사건은 현재 CVAT 목록 스냅숏만으로 복원할 수 없다. 이 관측 한계와 달리, 관측한 사건도 잃는 X3은 수정 대상이다.
- **CTRL 신호:** wake·stop·release 파일 이름과 release_stop·stop_id·until은 심판·Keeper의 기대와 맞고 공식 시험도 통과했다. 보호 모드의 정지·해제 차단, 살아 있는 심판의 깨우기 차단, 관리자 단일 보류 해제하고 깨우기는 정상 입력에서 맞았다. 환경 전환·읽기 실패는 X2·X6이다.

## 2b·LC·AA앱 시작 전 최소 목록

1. X1: 신호 계획의 필수 효과·식별 관계를 검사하고 일부 효과 누락 회귀 시험을 추가한다.
2. X2·X6: CTRL 전송 대상을 환경별로 확정하고, 환경 읽기 실패·보류 모름 상태에서 제어를 막는다.
3. X3: 자동 이벤트의 미발행 상태와 재시도를 보존한다. 생성 전 실패·생성 뒤 장부 실패를 각각 확인한다.
4. X4·X5: 보호 모드 재진입 알림과 수집기 생존 기록 계약을 맞춘다.
5. 2b 연결 시 실제 처리기 대신 가짜 CVAT로 backup 선행·사람 라벨 보호·TASK 이름/삭제 금지·중복 실행 방지를 확인하고, LC·AA 요청 params와 자동 요청이 끝까지 전달되는지 시험한다.

## 점검했지만 문제가 없던 항목

- 지정한 일반 시험 545개와 기본·확장 퍼징 각각 6개 항목.
- b16 seq·effects 전체 누락과 배정 지문 누락의 보호 모드 전환, hold 형태 손상 시 새 판정 중단.
- 보호 회차의 밤 종료 억제와 GPU 기동 억제, Keeper의 신선한 보호 회차 생존 판단.
- 예약 이름 전체·하위 모듈의 sys.modules 제거와 목록 밖 import 차단.
- 수집기의 배정·깨우기 제거, CVAT 읽기 전용, 자동 요청 범위·기본 형식, 실제 Uld.gs 함수 연결.
- 정상 입력의 CTRL 신호 이름·내용·권한 및 보호 모드 버튼 차단.
- ntfy 주제 값을 Drive·메일·오류 로그로 내보내지 않는 현재 구현.

## 시간이 모자라 보지 못한 항목·한계

- 실제 Drive 커넥터 응답·계정 소유권, Apps Script 트리거·메일·ntfy 실제 전달, Kaggle IPython 실행은 접속 금지에 따라 확인하지 않았다.
- v4.32 전체 회귀·모든 노트북 셀 일치·운영 전환 도구는 이번 요청의 새 범위 중심 검토에서 제외했다.
- 모든 과거 판정 파일 형태, 다중 파일 동시 손상, 장기간 알림 키 누적·모든 쓰기 중단 조합을 전수 검사하지 않았다.
- 2b 실제 처리기 및 LC·AA앱은 아직 연결 전이므로 실제 라벨 쓰기의 종단 보증은 하지 않는다.
