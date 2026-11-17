# v4.33.0s 검토 결과 — b23

검토일: 2026-11-17. `AGENTS.md`·이번 요청·b22 결과·2d의 b22 대응표·2b 구현 설명·작업 계획·관련 구현과 시험을 확인했다. 코드·노트북·시험·설계서는 수정하지 않았다. 실제 CVAT·Drive·Kaggle·메일·ntfy에는 접속하지 않았다.

**지정 일반 시험 743개와 기본·확장 퍼징 각 10개 항목은 모두 통과했다. 0p의 R1·R2는 기존 발견 범위에서 해결됐다. 새 처리기에서 높음 6건(S1~S6)·보통 1건(S7)을 확인했다. 2b-4 전 필수 수정은 사람 라벨 보호·가져오기 모름·되돌리기 권한·재게시 검증·가져오기 형식의 S1~S4·S6다. 실제 track 계산 연결의 S5와 범위 감싸기의 S7은 2b-6 연결 전까지 처리할 수 있다.**

## 시험·재현 및 보관

| 실행 | 결과 |
| --- | --- |
| `python3 tests/test_arbiter_433.py drive` | 247개 성공, RESULT True |
| `python3 tests/test_access_433.py drive` | 68개 성공, RESULT True |
| `python3 tests/test_master_433.py drive` | 75개 성공, RESULT True |
| `python3 tests/test_master_main_433.py drive` | 62개 성공, RESULT True |
| `python3 tests/test_handlers_433.py drive` | 60개 성공, RESULT True |
| `python3 tests/test_fuzz_433.py drive` | 10개 성공. 입력 5,561개,변형 46,785개 + 두 칸 조합 1,704개,파일 숨기기 1,788회. 예외·뜻 위반 0건 |
| `FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive` | 10개 성공. 변형 103,923개 + 두 칸 조합 1,704개,파일 숨기기 1,800회. 예외·뜻 위반 0건 |
| `node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs` | 72개 성공, Keeper보다 먼저 실행 |
| `node tests/test_keeper.js apps_script/G_keeper/Keeper.gs` | 125개 성공 |
| `node tests/test_ctrl_app.js apps/ctrl/index.html` | 34개 성공 |

Python은 `PYTHONDONTWRITEBYTECODE=1`, Node는 기존 `/tmp/node-v22.16.0-linux-x64/bin/node`, jsdom은 기존 `/tmp/b17_ctrl_deps/node_modules`를 NODE_PATH로 사용했다. npm 설치나 저장소 의존성 변경은 하지 않았다.

이전 자료는 덮어쓰지 않았다. 이번 자료는 `rLog/b23_*`에 보관했다.

| 자료 | 내용 |
| --- | --- |
| `b23_run_tests.py`·`b23_test_status.json`·각 시험 `.log` | 지정 시험 10개 명령, 종료 코드 모두 0 |
| `b23_rerun_b22.py`·`b23_rerun_status.json`·`b23_rerun_b22_{non_object,master_shapes,state_gpu}.log` | b22의 새 재현 세 개 원본 재실행, 종료 코드 모두 0 |
| `b23_state_gpu_compat.py`·동명 `.log` | b22 GPU 재현의 호출 조건만 현재 master_main의 last_arbiter_fresh 사용으로 맞춘 호환본 |
| `b23_handler_probe.py`·동명 `.log` | S1~S7 추가 재현. 공식 가짜 CVAT·LocalStore·처리기·실행기·심판을 사용. track CLI는 모델을 불러오기 전 인수 검사에서 종료 |

저장소 최상위에서 Python 재현은 `PYTHONDONTWRITEBYTECODE=1 python3 rLog/<파일>`로 실행한다. 전체 지정 시험 명령·환경은 b23_run_tests.py에 있다. 이번 추가 재현은 실제 모델·영상·CVAT 토큰을 사용하지 않는다.

## 0p의 R1·R2 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| R1 비객체 JSON으로 실행기 종료 | 해결 — 기존 발견 범위 | b22의 잘못된 배정·결과·TASK 잠금 재현에서 step=wait·error=null이며 worker_cpu.run도 정상 반환한다. 원본을 소비 목록에서 제거하고 판정 파일/자격 모름은 차례 전체 대기로 처리한다. 공식 7개 회귀는 파일 복구 후 재개와 잘못된 요청 옆 정상 요청 처리도 확인한다. |
| R2 오래된 wake로 GPU 기동 | 해결 — 기존 발견 범위 | 새 master_main은 last_arbiter_fresh일 때만 wake를 넘긴다. 현재 조건의 호환 재현에서 no_summary·fake_calls=[]이며 공식 통합 회귀도 통과했다. |

**b22 GPU 원본 재현의 해석:** 원본 스크립트는 당시 문제가 있던 `if r.acting`과 옛 wake 직접 전달을 스크립트 안에 복제해 두었다. 따라서 그대로 다시 실행하면 여전히 가짜 push가 나온다. 이는 현재 master_main의 회귀가 아니다. 원본은 보존하고, 현재 조건만 반영한 호환본 및 실제 master_main 회귀로 해결 여부를 확인했다.

실행기의 전체 모름 대기는 다른 사람의 요청 파일 읽기 실패에도 자기 단계 진행·결과 보고·최종화를 미룬다. 생존 신호는 별도 스레드라 계속될 수 있다. 이는 선택한 전체 보류 정책의 대가이며 이번에 별도 결함으로 올리지 않았다. 이미 처리기 호출 안에 들어간 실행은 호출 전체가 자동 중단되는 것이 아니라 다음 권한 확인·다음 step에서 영향을 받는다.

## 새 발견

### S1 — 이름의 구분자와 tags를 확인하지 않아 사람 라벨 보호를 우회한다

| 칸 | 내용 |
| --- | --- |
| 번호 | S1 |
| 심각도 | 높음 |
| 관점 | 접근·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | AGENTS 3장 3, 검토 질문 8 |
| 위치 | `drive/scripts/h_task.py:56`~59 is_target, `:72` 부근 count_labels, `:180`~190 보호·교체 판정 |
| 문제 | is_target은 `_uld`·`_AA` 상태 꼬리가 아니라 단순히 `uld`·`AA`라는 문자로 끝나는지만 확인한다. count_labels도 tags를 제외한다. 따라서 예외 이름이 아닌 TASK나 사람 tag만 있는 TASK에서 명시적 allow_replace 없이 업로드한다. |
| 조건 | ① 이름 humanAA·기존 사람 shape 1개인 TASK에 allow_replace 없는 track 요청을 실행했다. remove→import가 실행되어 사람 shape는 없어지고 모델 track 3개로 교체됐으며 결과는 done이다. ② 이름 human_vf·기존 사람 tag 1개인 TASK에도 held가 아니라 import·done이 됐다. 태그 사례의 가짜 CVAT는 append 방식이라 tag 자체는 남았으며, 실제 SDK 가져오기의 tag 교체까지 실행한 것은 아니다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 protection_humanAA·protection_human_vf |
| 제안 | 허용 상태는 구분자가 포함된 정확한 `_uld`·`_AA`·`_AA_rN` 꼬리로 확인한다. 기존 라벨 존재 판단은 shapes·tracks·tags를 모두 포함한다. `_AA` 앞 구분자가 없는 이름·유사 문자열·tags-only·allow_replace의 정확한 True를 회귀로 검사한다. 기존 함수와 같다는 이유로 AGENTS의 보호 약속을 넓히면 안 된다. |
| 2b-4 전 필수 여부 | **필수.** 새 TASK 쓰기 처리기의 사람 라벨 보호 약속 위반이다. 백업이 남는다고 무동의 교체가 허용되는 것은 아니다. |

### S2 — 가져오기 호출의 응답을 잃으면 진행 중인 작업 위에 백업을 되돌린다

| 칸 | 내용 |
| --- | --- |
| 번호 | S2 |
| 심각도 | 높음 |
| 관점 | 동시성·복구 |
| 종류 | 코드·시험 |
| 관련 항목 | AGENTS 3장 7, 검토 질문 7의 가져오기 모름 |
| 위치 | `drive/scripts/h_task.py:190` import 호출, `:202`~212 예외·되돌림; `drive/scripts/cvat_ops.py` RealCvat.import_annotations의 SDK 동기 호출 |
| 문제 | import_status가 unknown인 경우는 ImportUnknown으로 막지만, 가져오기 요청/대기 호출 자체의 TimeoutError·접속 단절 등은 일반 실패로 받아 즉시 되돌린다. RealCvat은 SDK 호출이 성공 반환해야만 sync 작업 번호를 주므로, 서버 접수 뒤 응답을 잃은 경우의 ‘진행 중일 수 있음’이 구분되지 않는다. |
| 조건 | 가짜 import가 서버 작업을 만든 뒤 응답만 TimeoutError로 잃게 했다. 첫 작업의 상태는 계속 started로 유지했다. 처리기는 두 번째 remove·백업 import를 실행하고 `failed:TimeoutError(restored)`를 기록했으며 심판은 잠금을 free로 풀었다. 첫 가져오기는 여전히 started다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 timeout_restore |
| 제안 | 서버 접수 여부/종료를 입증하지 못한 쓰기 예외는 ImportUnknown으로 전달하여 되돌리지 않고 확인 필요로 보낸다. 되돌림은 첫 가져오기가 실패 종료했음을 확인한 경우에만 한다. 요청 접수 뒤 응답 유실·상태 조회 실패·SDK 대기 시간 초과를 실제 어댑터 계약에 포함한다. |
| 2b-4 전 필수 여부 | **필수.** 끝나지 않은 가져오기와 되돌리기가 경합하고, 그 상태를 복구 완료로 기록해 다른 쓰기를 허용할 수 있다. |

### S3 — 되돌리기 내부의 두 CVAT 쓰기 사이에는 권한을 재확인하지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | S3 |
| 심각도 | 높음 |
| 관점 | 동시성·접근 |
| 종류 | 코드·시험 |
| 관련 항목 | 검토 질문 7, 호출 직전 권한 확인·권한 상실 뒤 쓰기 중단 |
| 위치 | `drive/scripts/h_task.py:205`~211 restore와 단일 w.call |
| 문제 | 정상 쓰기는 remove·import 각각 Authority.call로 감싸지만, 되돌리기는 remove와 import를 하나의 콜백에 묶는다. 권한 확인은 콜백 시작에만 하므로 삭제 뒤 권한을 잃어도 백업 import가 실행된다. |
| 조건 | 첫 가져오기를 실패 종료로 만들고 되돌리게 했다. 두 번째 remove(되돌림 삭제) 직후 TASK 잠금을 quarantine으로 바꿨다. 그 뒤에도 백업 import가 호출됐으며 import 당시 잠금 상태 기록은 첫 호출 confirm_approved, 두 번째 호출 quarantine이었다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 restore_authority |
| 제안 | 되돌리기의 remove와 import를 각각 권한 확인으로 감싸고, 되돌리기 작업의 상태 확인도 명시적으로 처리한다. RealCvat의 shapes 500개씩 update_annotations 반복처럼 한 공개 함수 안에서 여러 서버 쓰기를 하는 부분도 같은 기준으로 대조한다. |
| 2b-4 전 필수 여부 | **필수.** 확인 필요/다른 소유자로 바뀐 뒤 옛 실행기가 CVAT에 쓰는 경로다. |

### S4 — 같은 버전 재게시가 실패해도 옛 verified 목록이 남는다

| 칸 | 내용 |
| --- | --- |
| 번호 | S4 |
| 심각도 | 높음 |
| 관점 | 복구·접근 |
| 종류 | 코드·시험 |
| 관련 항목 | 필수 산출물 최종 검증, 검토 질문 3 |
| 위치 | `drive/scripts/handlers.py:214`~234 publish_version |
| 문제 | 기존 `_files.json`이 있는 버전 경로에 파일을 먼저 덮고, 기존 검증 표시를 무효화하지 않는다. 재게시 중 일부만 바뀌거나 검증에 실패하면 새 목록은 안 쓰지만 옛 verified=true는 그대로 남아, 실제 파일과 맞지 않는 버전을 검증 완료로 보이게 한다. |
| 조건 | v1/a.bin=old를 정상 게시해 verified=true 목록을 만든다. 같은 v1에 new를 다시 게시하되 업로드 결과를 corrupt로 바꿨다. publish_version은 VerifyError를 냈지만 파일은 corrupt, 목록은 old의 해시·verified=true다. verify_version을 다시 부르면 false지만, 심판의 목록 소비는 그 재다운로드를 자동 실행하는 구조가 아니다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 republish |
| 제안 | 완료된 버전은 불변으로 거절하거나, 같은 버전 재시도는 기존 목록과 완전히 같은 파일임을 확인한 경우에만 허용한다. 수정 가능한 재게시를 허용하려면 변경 전에 검증 상태를 내려야 하며, 실패·중단 때도 stale verified가 남지 않게 해야 한다. |
| 2b-4 전 필수 여부 | **필수.** 공통 게시 기반의 필수 검증 보장이 깨져 이후 취합·관리/학습 처리기의 완료 판정을 잘못 유도한다. |

### S5 — RealEngine의 기본 track 인수가 실제 CLI와 맞지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | S5 |
| 심각도 | 높음 |
| 관점 | 스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | 검토 질문 9, 실제 track 계산 연결 |
| 위치 | `drive/scripts/h_task.py:240` 부근 RealEngine 설정, `:248`~252 명령 생성; `drive/scripts/yolo_track_to_cvat.py:345`·350 인수 선언 |
| 문제 | 기본 near=0.5·box_source='track'을 넘기지만 실제 CLI는 near 정수, box-source는 detection/tracker만 받는다. 기본 RealEngine의 track은 모델을 읽기도 전에 종료된다. settings로 이 키를 덮으려 해도 dict의 중복 키워드 구성 때문에 TypeError가 난다. |
| 조건 | 실제 RealEngine.make_track을 존재하지 않는 모델·영상 경로로 호출했다. 모델 로드 전 argparse가 `--near: invalid int value: '0.5'`로 종료하고 처리기는 track 생성 실패를 낸다. near만 1로 고친 별도 파서 실행도 box-source='track'을 거절한다. settings={'near':1,'box_source':'tracker'} 생성은 중복 키워드 TypeError다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 engine_cli. 실제 추론·미디어 접근은 실행되지 않음 |
| 제안 | CLI의 기존 선택값·자료형과 설정 병합을 맞춘다. 가짜 Engine만 쓰는 통합 시험 외에 실제 명령 생성과 실제 파서의 계약 시험을 추가한다. |
| 2b-4 전 필수 여부 | 필수 아님. **2b-6의 실행 호스트 연결 전 필수.** 요청서가 실제 모델/영상 연결을 2b-6으로 남겼으므로 취합 일 개발까지 막지는 않지만, 현재 RealEngine을 정상 track 구현으로 배포할 수는 없다. |

### S6 — 내보내기 형식을 가져오기와 되돌리기에 그대로 넘긴다

| 칸 | 내용 |
| --- | --- |
| 번호 | S6 |
| 심각도 | 높음 |
| 관점 | 복구·스케줄링 |
| 종류 | 코드·시험 |
| 관련 항목 | 검토 질문 6·7, 기존 CVAT 함수와의 계약 |
| 위치 | `drive/scripts/h_task.py:34` BACKUP_FMT, `:120` 부근 track fmt 기본값, `:208` 되돌리기; `drive/scripts/cvat_ops.py` import_annotations의 직접 전달; `drive/scripts/cvat_task_tools.py:27`~28·428~432 기존 형식 분리 |
| 문제 | 기존 코드의 EXPORT_FORMAT은 CVAT for video 1.1, IMPORT_FORMAT은 CVAT 1.1인데 새 처리기는 두 용도에 BACKUP_FMT 하나를 쓴다. RealCvat도 형식 이름을 바꾸지 않고 SDK에 전달한다. 따라서 기존 가져오기 계약과 맞지 않으며 정상 업로드뿐 아니라 백업 되돌리기도 같은 잘못된 이름을 사용한다. |
| 조건 | 실제 소스에서 기존 IMPORT_FORMAT을 읽고 이 형식만 받는 가짜 가져오기 함수로 track 교체를 돌렸다. 두 번 전달된 형식은 모두 CVAT for video 1.1이었다. 첫 삭제 뒤 업로드와 되돌리기 가져오기가 모두 실패하여 라벨은 비어 있고 잠금은 quarantine이었다. |
| 확신 | 확인함 — 코드의 형식 계약 불일치와 `b23_handler_probe.log`의 import_format 모형 실행. 실제 CVAT 서버의 형식 거절 응답은 접속 금지에 따라 미확인 |
| 제안 | export와 import의 형식 상수를 구분하고, track·제출본 기본값·복구 zip 가져오기에는 기존 IMPORT_FORMAT 계약을 적용한다. 실제 어댑터 모형도 모든 format을 받아들이지 말고 기존 함수의 계약을 검사한다. T15에서 서버 형식 목록과 정상 업로드·되돌리기를 확인한다. |
| 2b-4 전 필수 여부 | **필수.** 원본 라벨 삭제 뒤 새 가져오기와 되돌리기가 함께 실패하는 공통 계약 오류다. |

### S7 — ScopedCvat의 공개 client 경로가 쓰기 범위를 우회한다

| 칸 | 내용 |
| --- | --- |
| 번호 | S7 |
| 심각도 | 보통 |
| 관점 | 접근 |
| 종류 | 코드·시험 |
| 관련 항목 | 검토 질문 4, 시험/운영 범위의 실수 방지 |
| 위치 | `drive/scripts/handlers.py` ScopedCvat.ops·__getattr__, `drive/scripts/cvat_ops.py` RealCvat.client, `drive/scripts/h_task.py:266` 실제 client 사용 |
| 문제 | __getattr__는 정해진 네 쓰기 이름 이외를 원본으로 전달하므로 client()가 쓰기 가능한 SDK 객체를 그대로 내준다. 감싼 remove_annotations는 막아도 client().tasks.retrieve(...).remove_annotations()는 범위 검사 없이 호출할 수 있다. ops 원본도 공개되어 있다. |
| 조건 | 시험 범위는 프로젝트 7·REH_인데 운영 TASK 61은 프로젝트 9에 둔다. sc.remove_annotations(61)은 차단됐지만, sc.client().tasks.retrieve(61).remove_annotations()는 가짜 CVAT 쓰기 기록을 남겼다. |
| 확신 | 확인함 — `b23_handler_probe.log`의 scope_client. 실제 현재 RealEngine 경로에서는 collect_only이므로 이 우회로 CVAT에 쓰는 실행까지 확인한 것은 아님 |
| 제안 | 처리기에 공개하는 client는 읽기 전용으로 제한하거나, raw client를 환경의 명시적 내부 경로로 분리한다. 새 쓰기 메서드를 추가할 때도 기본 통과되지 않게 한다. 일반 개발자가 공개 API를 사용하다 범위를 빠뜨리는 경우를 회귀로 검사한다. |
| 2b-4 전 필수 여부 | 필수 아님. **2b-6 범위 강제 연결 전에 보완 권고.** 등록 사용자의 고의를 막는 보안 경계로 해석한 발견은 아니며, 제공된 쓰기 래퍼를 벗어나는 실수 방지의 빈틈이다. |

## 검토 질문별 보충 판단

### A. 0p와 전체 대기

비객체 판정 파일은 목록에서 제거된 뒤 unknown으로 전달되고, 실행기는 그 차례 전체를 wait로 끝낸다. 비객체 외부 요청은 제거만 하므로 정상 요청을 막지 않는다. 실제 읽기 실패·중복은 어느 요청이든 wait 사유다. 다른 사람 요청의 지속 실패가 자기 실행기를 오래 기다리게 할 수 있으나, 심판도 같은 관측 실패에 판정 보류를 선택한 정책이다. 객체가 아닌 정상 JSON과 실제 읽기 실패는 구분된다. R1·R2 수정의 해당 범위에서 새 정체 반례는 확인하지 못했다.

### B. 진행·멈춤·검증·시험 범위

- **busy의 판단:** 처리 단계 시작 때 since/progress_at을 기록하고 ctx.progress가 progress_at을 갱신한다. 심판은 lane별 STALL_SEC 초과를 stalled로 계산해 alive를 거짓으로 보며 hb_lost_at을 진행 시각+한도로 잡는다. TASK 확정 중은 quarantine, 관리/학습/만들기 실행 중은 needs_check, 준비 단계와 read 배정은 기존 만료·회수 경로를 따른다. 회차 단위 보류 중에는 이 판정도 미뤄진다.
- **스레드 경합:** busy의 설정·갱신·해제와 heartbeat의 사본 생성은 같은 _busy_lock으로 보호된다. 잠금을 잡은 채 네트워크 쓰기는 하지 않는다. 스냅숏을 복사한 직후 처리기가 progress를 갱신하면 한 heartbeat 동안 옛 진행 시각을 보낼 수는 있다. 이것만으로 데이터가 잘못 쓰이는 재현은 하지 않았다.
- **진행이 없는 긴 구간:** 큰 단일 download·put_file·get_file 안에서는 중간 progress가 없고, RealCvat의 SDK 동기 가져오기나 shape 500개 묶음 내부에도 ctx.progress가 없다. rclone 파일 전송 허용 한도는 1시간인데 read/TASK 진행 한도는 30분이다. 따라서 정상이나 오래 걸리는 호출을 멈춤으로 판단할 수 있다. 다음 권한 확인은 이를 막는 방향이지만, 모든 내부 쓰기 사이에 확인하는 것은 아니므로 S3의 묶음 경계를 함께 보완해야 한다. 실제 대용량 전송은 실행하지 않았고, 전송 진행 콜백 또는 장기 단계별 한도 정합성은 2b-6 연결 전에 확인해야 한다.
- **publish_version:** 처음 게시하는 정상 경로는 업로드→재다운로드 해시/크기 확인→auth→verified 목록 순서다. 새 경로의 부분 실패에서 목록을 쓰지 않는 공식 시험도 통과한다. 동일 버전 재게시의 지속적인 stale verified는 S4다. 마지막 확인과 목록 쓰기 사이의 일반적인 Drive 비교-쓰기 틈 자체는 AGENTS 지침대로 별도 발견으로 올리지 않았다. 완료 버전을 불변으로 유지해야 이 틈을 불필요한 재게시로 넓히지 않는다.
- **범위:** 제공된 네 쓰기 래퍼는 호출 때마다 현재 TASK 정보를 다시 읽어 시험 프로젝트·REH_를 검사한다. 정보를 못 읽으면 차단하고, 준비 단계의 조기 검사 뒤 이름이 바뀌어도 쓰기 직전 래퍼에서 다시 확인한다. 다만 raw client 경로는 S7이다. create_task는 CvatOps 기본 선언과 ScopedCvat 검사가 있으며 실제 RealCvat 생성 구현은 아직 없다(2b-5 범위). 생성 자체가 완성됐다고 판정하지 않았다.

### C. 받는 중 일과 실제 어댑터

- job 번호가 pending 기록에 저장된 뒤 실행기가 바뀌는 정상 경로는 같은 job의 상태를 조회한다. ready/받음도 새 준비 요청을 만들지는 않는다. 실패 상태를 fetch가 다시 보게 되면 새 준비를 요청할 수 있지만, 이미 TASK 결과를 failed로 마친 요청을 자동 재시도하는 정책까지 제공하는 것은 아니다.
- 서버 요청과 pending 기록 저장은 하나의 원자적 동작이 아니다. 서버 접수 후 작업 번호를 기록하기 전에 프로세스가 끊기면 다음 실행기가 다시 요청할 수 있다. 현재 기록에는 시도 의도·고정 서버 작업 식별자·이전 소유자 확인이 없어 그 공백의 정확히 한 번 접수까지 보장하지 않는다. 새 외부 백업/export 준비 작업의 중복 가능성이고, CVAT 라벨 중복 쓰기를 실행해 확인한 것은 아니다.
- 같은 pending 파일에는 assign을 적지만 쓰기 직전에 현재 배정 소유를 다시 확인하는 코드는 없다. 이전 실행기의 늦은 fetch가 새 실행기의 기록을 덮는 모든 조합을 시험하지 못했다. 배정 하나만 동작하고 기록에 job이 이미 남은 공식 교체 시험과, 모든 중단·두 세션 쓰기의 안전성을 구분해야 한다. 단순 Drive 재읽기-쓰기의 몇 초 틈 자체는 새 발견으로 반복하지 않았다.
- 취소는 준비 단계에서 더 이상 publish_lock을 신청하지 않고 배정을 반환하게 한다. 게시 잠금을 이미 받은 단계는 마무리할 수 있다. h_read.publish의 download는 Executor가 게시 잠금이 자기 것임을 확인한 뒤 시작하고, Drive 파일 올리기·다시 받기 확인은 ctx.auth('publish') 안에서 한다. 최종 pending 갱신은 그 호출 뒤 별도 쓰기다. 긴 단계 중 권한 변경·늦은 기록은 후속 호스트 통합 시험이 필요하다.
- **RealCvat 읽기 어댑터:** request_backup/check_backup/fetch_backup과 request_export/export_status/download_result의 인수·반환형 연결은 기존 함수와 맞는다. bk:/ex: 접두사 구분도 맞고 지정 모형 시험이 통과한다. 새 쓰기 형식은 S6이다.
- **비밀 값:** 토큰은 RealCvat 내부·cvat_backup 접속 설정에만 전달하며 pending·결과 계획에는 넣지 않는다. 실행기의 실패 보고는 주로 예외 종류만 기록하고 Authority 단계 기록도 error=종류이므로 이번 정상/실패 재현에서 토큰 노출은 없었다. 다만 실제 SDK·서버 오류 메시지 전체의 비밀 값 포함 여부를 전수 검증하지 않았다. RealCvat.download는 서버 message 일부를 예외에 넣으므로 호스트가 이를 그대로 로그로 출력하는 연결은 별도 확인해야 한다.

### D. TASK 준비·확정·복구

- **백업 선행:** 확정은 현재 라벨 export를 받아 복구 경로에 게시하고 재다운로드 해시·크기를 확인한 뒤 쓰기로 간다. 백업 요청·다운로드·게시 검증 실패는 CVAT 쓰기에 도달하지 않는다. 준비 때 받은 reference를 확정 백업 대신 쓰지 않는 점도 맞다.
- **실패 분류:** import_status의 failed는 되돌림, unknown·진행 시간 초과는 ImportUnknown으로 격리하는 기본 시험이 통과한다. 호출 자체의 응답 유실은 S2다. 권한을 잃으면 정상 remove→import의 다음 쓰기를 막는 시험도 통과하지만, 되돌림 내부는 S3다.
- **되돌리기 실패:** restore 자체의 예외는 밖으로 전파되어 실행기가 commit_error로 멈춤 보고를 하고 quarantine/확인 필요에 남는다. 되돌림이 finished가 아니어도 ImportUnknown을 낸다. 이때 실패 완료로 자동 잠금을 풀지는 않는다. 다만 S6처럼 같은 잘못된 가져오기 형식을 쓰면 실제 복구 능력이 없어질 수 있다.
- **삭제와 가져오기 사이 중단:** 백업·steps 의도와 result_plan은 남고 confirm_approved가 끝나지 않으면 quarantine으로 간다. 문서가 말하는 확인 필요 선택 경로 자체는 있다. 하지만 새 recovery TASK 처리기도 원본 job의 백업을 선택해 복원하는 구현은 아직 아니다. h_task.prepare는 recovery 종류를 구현하지 않았고 등록부에도 recovery 처리기가 없다. 그 요청의 실제 백업 복원 완료까지 이번 범위에서 검증된 것으로 보아서는 안 된다. 이 연결은 남은 복구/관리 일 구현 및 T15에서 확인해야 한다.
- **사람 보호:** allow_replace가 정확히 True인지 확인하고 확정 때 현재 이름·라벨을 읽는 기본 흐름은 맞다. 예외 이름과 tags 존재는 S1이다. AGENTS의 명시적 금지는 기존 사람 라벨의 무동의 덮어쓰기다. 기존 라벨을 보존하는 것이 검증된 append까지 일괄 held로 처리하는 현재 선택은 그보다 보수적이며, 허용 여부를 별도로 정할 수 있다. 다만 현재 RealCvat은 요청 mode를 받지 않으므로 FakeCvat의 덧붙이기 구현만으로 SDK 가져오기가 기존 라벨을 보존한다고 보증할 수 없다. append를 보호 예외로 열기 전에 이 계약부터 확인해야 한다.
- **준비 분리:** track은 reference 읽기·로컬 계산, shape/auto는 collect_only=True로 탐지 결과만 모으고, 제출본은 로컬로 받아 해시·TASK/서버/프레임 범위/프레임맵을 검사한다. collect_only 분기의 flush는 서버 update 대신 collected에 저장한다. 현재 준비 경로에서 명시적인 CVAT 라벨 쓰기는 찾지 못했다. raw client의 쓰기 가능성 자체는 S7이다.
- **TASK 변경 검사:** commit은 size·labels 이름 목록만 다시 대조한다. RealCvat.get_task는 labels의 이름만 남기므로 라벨 ID·타입·속성이나 같은 장수의 프레임 대응 변경까지 검사하지는 않는다. 제출본의 frame_map 검증도 준비 시점이다. 동일 TASK의 미디어/정의 변경을 지원할 호스트에서는 이 전제가 충분한지 2b-6에서 확인해야 한다.
- **결과 검사:** shapes+tracks 개수의 하한 검사이므로 같은 개수의 잘못된 프레임·라벨·좌표나 예상보다 많은 중복을 확인하지 못한다. 이는 내용 동등성 검증이 아니며, counts-only와 FakeCvat 통과를 실제 업로드 내용 검증으로 해석해서는 안 된다. tags 누락이 보호 판정까지 영향을 주는 것은 S1이다.
- **이름·최종 상태:** 일반 경로에서 이름 변경은 업로드 확인 뒤 _uld에 _AA를 붙이는 한 가지다. held:human_labels가 있어도 요청을 done으로 마치고 TASK별 보류를 보인다는 것은 이번 구현 설명의 명시적 정책이므로 새 거짓 완료 발견으로 올리지 않았다. failed:…(restored)는 요청 failed로, commit 예외·ImportUnknown은 확인 필요로 남는 기본 경로가 시험됐다.

## 2b-4로 넘어가기 전 최소 목록

1. **S1:** 상태 꼬리의 구분자와 tags를 포함해 사람 라벨 보호를 바로잡는다.
2. **S2·S3:** 가져오기 호출의 불명확한 종료를 되돌림으로 소비하지 않고, 되돌림의 각 서버 쓰기에 권한을 재확인한다.
3. **S4:** 같은 버전 재게시/실패가 검증 완료 상태를 잘못 남기지 않도록 게시 정책을 정한다.
4. **S6:** 내보내기와 가져오기 형식을 분리하고 백업 복원에도 올바른 가져오기 형식을 적용한다.
5. 위 사례를 독립 회귀에 포함한 뒤 지정 시험·두 퍼징을 다시 통과시킨다. FakeCvat의 무조건적인 format 수용·append 동작·명확한 서버 응답만으로 실제 어댑터 계약을 대신하지 않는다.

S5는 2b-6 연결 전 필수 수정이고, S7의 raw client 범위 제한도 그때까지 보완할 수 있다. 큰 파일 진행·요청/기록 사이 중단·pending 소유권·복구 요청의 실제 복원·SDK append 및 결과 내용은 호스트 통합과 T15에서 확인할 항목이다. 실제 계정 접속이 필요한 검증과 로컬에서 이미 확인한 S1~S4·S6를 구분해야 한다.

## 점검했지만 문제가 없던 항목

- 일반 시험 743개, 기본·확장 퍼징 각 10개 항목 통과.
- 0p의 비객체 실행기 대기와 복구 후 재개, last_arbiter_fresh에 따른 GPU 기동 차단.
- 처리기 등록·미등록 종류의 NoHandler, params의 접수 기록 전달.
- busy 사본의 잠금 보호와 진행 갱신, 기본 stalled→격리/확인 필요·권한 차단 시험.
- 새 버전 최초 게시의 업로드·재다운로드 검증·목록 직전 auth 순서.
- 기존 job이 기록된 받는 중 일의 실행기 교체·취소·서버 준비 실패·게시 검증 실패.
- 업로드 직전 백업과 복구 자료 게시, 정확한 True 설정, 준비와 확정의 기본 분리.
- 기본 가져오기 상태 unknown/시간 초과와 권한 상실 시 되돌리지 않는 시험, 정상 이름 변경.

## 시간이 모자라 보지 못한 항목·한계

- 실제 CVAT/SDK·Drive·Kaggle·GPU 모델·실제 영상·실행 호스트 연결·Apps Script 계정·메일·ntfy·claude.ai 커넥터는 확인하지 않았다.
- S1~S4는 가짜 CVAT/LocalStore와 실제 처리기·실행기·심판의 추가 실행이다. S5는 실제 CLI 파서까지 실행했으나 모델 로드는 하지 않았다. S6는 기존 소스의 형식 계약을 적용한 모형이며 서버 응답은 미확인이다. S7은 공개 client 경로의 가짜 쓰기다.
- 모든 전송 지연·프로세스 중단·두 실행기 공유 기록·복구 실패 순서를 전수 시험하지 않았다. 실제 병렬 재시도·대용량 전송·각 SDK 내부 HTTP 호출의 종료 상태는 T15와 호스트 통합 범위에 남는다.
- 취합 일(2b-4)·관리/학습/만들기(2b-5)·호스트/모델/영상 연결(2b-6)은 아직 완료되지 않은 범위로 구분했다.
- v4.32 전체 회귀·노트북 셀 전체 일치·Kaggle IPython 호환성은 이번 지정 범위 밖이다.
