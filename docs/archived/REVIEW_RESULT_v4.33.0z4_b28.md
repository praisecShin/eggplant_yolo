# v4.33.0z4 검토 결과 — b28

검토일: 2026-11-17. `AGENTS.md`·이번 검토 요청·2c 구현 설명/계획·b26/b27 대응표·이전 결과와 관련 코드를 확인했다. **새 발견은 높음 4건(V1~V4), 보통 1건(V5)이다. 2c-2 전 필수는 V1~V4다.** 지정 일반 시험 709개와 기본 퍼징 10개 항목은 통과했다. 시험이 다루지 않는 가드 재설정·표준 API 인수·감독 초기화 실패 경계에서 반례가 나왔다.

코드·노트북·시험·설계서는 고치지 않았다. 보고서와 `rLog/b28_*`만 작성했다. 실제 CVAT·Google Drive·Kaggle·Colab·GPU 학습에는 접속하거나 실행하지 않았다. CVAT SDK 확인에 공식 공개 소스와 이전에 받은 공개 wheel을 사용했다. 0번 셀 자체는 실제 계정 접속을 수행하므로 실행하지 않고 원문과 모듈의 해당 순서를 검토·재현했다. 1~34번 셀 전환·노트북 조립은 요청에서 제외한 후속 범위로 구분했다.

## 시험·재현 자료

| 실행 | 결과 | 로그 |
| --- | --- | --- |
| test_cells_433 | 44개 성공 | `rLog/b28_cells.log` |
| test_hosts_433 | 54개 성공 | `rLog/b28_hosts.log` |
| test_handlers_433 | 142개 성공 | `rLog/b28_handlers.log` |
| test_e2e_433 | 17개 성공 | `rLog/b28_e2e.log` |
| test_master_433 | 75개 성공 | `rLog/b28_master.log` |
| test_arbiter_433 | 247개 성공 | `rLog/b28_arbiter.log` |
| test_access_433 | 68개 성공 | `rLog/b28_access.log` |
| test_master_main_433 | 62개 성공 | `rLog/b28_master_main.log` |
| test_fuzz_433 | 10개 항목 성공 | `rLog/b28_fuzz.log` |

모든 지정 시험의 최종 출력은 RESULT True다. 기존 `/tmp/b24_venv`의 Python 3.14.4를 사용했다. 셀 시험의 첫 시도는 pandas 미설치로 중단됐고, pandas·requests를 같은 `/tmp` 환경에 설치한 뒤 동일 명령을 다시 실행해 통과했다. 최초 로그는 `b28_cells_missing_dependency.log`에 보존했다. 저장소에 의존성을 설치하지 않았다. 실행 명령·환경은 `b28_run_tests.py`, 최초/재실행 상태는 `b28_test_status.json`에 있다.

이전 원본 재실행은 일반 시험 결과와 구분한다.

| 재현 | 결과·해석 |
| --- | --- |
| `rLog/b27_orphan_probe.py` 원본 | 종료 코드 0. 손자가 살아 있지 않았고 학습 실패 RuntimeError로 돌아옴. 새 감독 기본 유예 때문에 약 60초 걸림. `b28_b27_orphan_original.log` |
| `rLog/b26_process_boundaries.py` 원본 | 종료 코드 1. 옛 KILL_WAIT=0.1초가 새 감독 유예보다 짧아 AuthorityLost 대신 CleanupUnknown이 나면서, 원본의 옛 예외 가정에서 중단됨. 현재 코드의 회귀 실패로 세지 않음. `b28_b26_boundaries_original.log` |
| `b28_prior_boundaries_compat.py` | 새 구조에 맞춰 GRACE=0.2·KILL_WAIT=4초로 명시하고 상태 파일을 검사하는 호환본. 권한 상실·리더 먼저 실패·좀비 세 경우 모두 손자 생존 없음, clean=true. 원본 그대로 실행한 것으로 표시하지 않음. |

추가 재현은 다음과 같다. 실제 파일 변경은 임시 BASE에만, 프로세스는 시험이 만든 것만 대상으로 했다. 새 반례의 살아 있는 하위 프로세스는 재현의 finally에서 직접 종료했다.

| 스크립트·동명 로그 | 내용 |
| --- | --- |
| `b28_guard_probe.py` | reload/start, 실패한 start 뒤 가드, 키워드 replace, Path.touch·PIL·tempfile·sqlite3·심볼릭 링크 |
| `b28_import_probe.py` | bytecode 쓰기를 켠 상태에서 임시 BASE/scripts의 정상 import가 만드는 .pyc 확인 |
| `b28_supervisor_probe.py` | 감독의 prctl 설정 실패를 주입하고 실제 감독·RealTrainer의 결과 확인 |
| `b28_identity_probe.py` | 실제 셀 요청/신호 → 심판. 등록된 다른 사람의 취소와 미등록 계정의 취소 비교 |
| `b28_prior_boundaries_compat.py` | 앞서 설명한 이전 프로세스 경계의 감독 구조 호환본 |

저장소 루트에서 `PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/<스크립트>`로 실행한다. import 재현만 내부에서 bytecode 쓰기를 켰다가 복구한다. 시작/종료 코드·시험·셀 원문 해시는 일치했다(`b28_initial_hashes.json`, `b28_final_hash_check.json`).

## b26 U1~U5·b27 F1 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| b26 U1 DDP 새 세션 추적 | **부분 해결** | 새 세션·리더 먼저 종료·poll 사이 고아 생성은 감독의 소유 경계로 해결했다. 다만 subreaper 설정 실패에도 감독이 계속 실행해 clean=true를 남기는 V4가 있다. |
| b26 U2 확인 필요 인계 | 해결 — 기존 발견 범위 | CleanupUnknown → NeedsCheck → stop_run → needs_check 연결과 다음 학습 차단 회귀 통과. 감독 KILL/clean 부재도 같은 경로다. V4는 오류가 제대로 발생하지 않는 별도 반례다. |
| b26 U3 모델별 오류 격리 | 해결 — 기존 발견 범위 | clean_meta·legacy 경로 값 검사·모델별 웹 변환 경계가 있다. 0z2 이후 관련 회귀가 유지됨을 지정 시험에서 확인했다. |
| b26 U4 학습 쓰기 격리 | 해결 — 기존 발견 범위 | 실행별 설정·캐시·임시·홈 환경과 연동 변수 제거, 자식의 전용 설정 변경 경로를 유지한다. 전체 Ultralytics/GPU 실행의 모든 부수 파일은 예행 연습에서 확인해야 한다. |
| b26 U5 좀비 처리 | 해결 — 기존 발견 범위 | 감독은 좀비를 live에서 제외하고 자기 자식은 waitpid로 회수한다. 호환 재현의 좀비 경계에서 빠르게 종료하며 clean=true였다. |
| b27 F1 관측 전 입양 손자 누락 | 해결 — 기존 발견 범위 | 실행기와 분리된 감독이 학습만 소유하므로 중간 부모가 poll 사이에 사라져도 고아가 감독 아래로 온다. 원본 재현에서 손자 생존 없음. 감독 초기화 실패는 V4로 별도 보고한다. |

## 새 발견

### V1 — 0번 셀의 reload가 기존 세션을 잃어 재실행이 실패한다

| 칸 | 내용 |
| --- | --- |
| 번호 | V1 |
| 심각도 | 높음 |
| 관련 항목 | 2c-1 가드 설치, 검토 질문 B6 |
| 위치 | `drive/notebooks/A0_colab/cells_v4.33/cell00.py:87` importlib.reload(cb); `drive/scripts/cells_base.py:417` _ACTIVE 초기화, `:424` 이전 세션 닫기, `:445` 새 분석 폴더 생성 |
| 무엇이 문제인가 | reload는 _ACTIVE를 None으로 다시 만들지만 이미 바꿔 끼운 open/os/전송 함수는 이전 가드를 계속 참조한다. 새 start는 이전 가드를 찾지 못하고 새 분석 폴더를 만들다가 이전 세션의 출력 범위 검사에 걸린다. 정상적인 0번 셀 재실행이 실패하며 가드는 하나로 정리되지 않는다. |
| 일어나는 조건 | `b28_guard_probe.py`의 cell00_reload_start: start 성공 → 실제 0번 셀 순서대로 importlib.reload(cb) → start. 새 analysis/M1/<새 세션>의 mkdir에서 AnalysisRefused가 난다. 공식 재시작 시험은 reload 없이 cb.start만 다시 불러 이 조건을 빠뜨린다. |
| 확신 | 확인함 — 실제 모듈 reload·가드·start 연결. Colab 계정은 사용하지 않음. |
| 제안 | reload 전 기존 활성 세션을 안전하게 닫거나, 모듈 reload를 거쳐도 가드 소유 상태를 보존해 교체한다. 실제 cell00의 호출 순서를 회귀로 검사한다. 새 가드가 이전 가드를 원본 함수로 저장하지 않게 한다. |
| 2c-2로 넘어가기 전 필수 여부 | **필수.** 기반 셀을 다시 실행할 수 있어야 후속 셀을 안정적으로 옮길 수 있다. |

### V2 — 새 분석 세션의 설정 오류가 기존 가드를 해제한다

| 칸 | 내용 |
| --- | --- |
| 번호 | V2 |
| 심각도 | 높음 |
| 관련 항목 | 분석 모드의 공유 폴더 읽기 전용, 검토 질문 B6 |
| 위치 | `drive/scripts/cells_base.py:424`~435 start의 이전 세션 close와 설정 검증 순서 |
| 무엇이 문제인가 | start는 새 설정을 검증하기 전에 기존 세션의 쓰기·CVAT 가드를 제거한다. OPERATOR 누락·잘못된 모드·BASE 오류 등으로 새 시작이 실패하면 새 가드는 설치되지 않으며 커널은 미보호 상태가 된다. |
| 일어나는 조건 | `b28_guard_probe.py`의 failed_start/write_after_failed_start: 정상 start 뒤 OPERATOR=''로 start하면 예상대로 거절되지만, 바로 이어 BASE/shared에 write_text가 성공한다. 명시적으로 close를 호출하거나 우회 함수를 사용하지 않았다. |
| 확신 | 확인함 — 실제 start와 공유 경로 쓰기 재현. |
| 제안 | 교체할 세션의 검증·준비가 끝나기 전 기존 보호를 해제하지 않는다. 교체 도중 실패해도 기존 가드를 유지하거나 복구한다. 오류 뒤 BASE와 CVAT 전송이 계속 차단되는지 확인한다. |
| 2c-2로 넘어가기 전 필수 여부 | **필수.** 단순 설정 실수가 보호 해제로 이어진다. |

### V3 — 일반 키워드 인자로 호출한 os 쓰기는 경로 검사를 빠뜨린다

| 칸 | 내용 |
| --- | --- |
| 번호 | V3 |
| 심각도 | 높음 |
| 관련 항목 | 공유 파일 쓰기 통제, 검토 질문 B4 |
| 위치 | `drive/scripts/cells_base.py:121` wrap_os와 `:125` 위치 인자만 검사하는 반복문 |
| 무엇이 문제인가 | os.replace·rename·remove 등의 래퍼는 위치 인자 a만 검사하고 키워드 k의 경로는 검사하지 않은 채 원래 함수에 넘긴다. 같은 Python API를 키워드 형식으로 부르면 BASE의 보호 경로를 바꿀 수 있다. |
| 일어나는 조건 | `b28_guard_probe.py`의 os.replace_keywords: 로컬 임시 파일을 `os.replace(src=..., dst=BASE/shared/target)`로 옮겼고 거절 없이 공유 경로에 파일이 생겼다. 직접 os.open이나 하위 프로세스 같은 문서의 알려진 우회 경로를 사용한 것이 아니다. |
| 확신 | 확인함 — 실제 설치한 가드와 os.replace 실행. |
| 제안 | 각 함수 시그니처에 맞춰 위치/키워드 경로를 모두 검사한다. dir_fd 등 상대 경로 해석도 고려한다. 지우기·rename·replace의 일반 키워드 호출을 회귀에 추가한다. |
| 2c-2로 넘어가기 전 필수 여부 | **필수.** 감쌌다고 명시한 표준 API의 평범한 사용법에서 보호가 빠진다. |

### V4 — 감독은 subreaper 설정 실패를 무시하고 거짓 clean을 남길 수 있다

| 칸 | 내용 |
| --- | --- |
| 번호 | V4 |
| 심각도 | 높음 |
| 관련 항목 | b26 U1, b27 F1, 검토 질문 A2 |
| 위치 | `drive/scripts/train_supervisor.py:84` prctl 호출, `:93` 하위 목록 판단, `:111` clean 게시 |
| 무엇이 문제인가 | PR_SET_CHILD_SUBREAPER의 반환값을 확인하지 않는다. 설정이 실패하면 고아 손자가 감독 밖으로 넘어가는데 감독은 빈 자식 목록을 보고 clean=true를 기록한다. 실행기는 정리 확인 불가가 아니라 일반 학습 실패로 끝낼 수 있다. |
| 일어나는 조건 | `b28_supervisor_probe.py`: 감독의 prctl만 -1을 반환하도록 주입하고 실제 감독 본체·RealTrainer를 사용했다. 학습 자식이 새 세션 손자를 만든 뒤 종료 코드 3으로 끝나자 supervisor.json은 child_rc=3, clean=true, left=[]였지만 손자는 살아 있었다. 재현이 만든 손자 그룹은 직접 KILL로 정리했다. |
| 확신 | 확인함 — 초기화 실패만 주입한 실제 프로세스 재현. 실제 Kaggle에서 prctl이 실패함을 확인한 것은 아님. |
| 제안 | 하위 프로세스를 띄우기 전에 subreaper 설정 성공을 확인하고, 실패하면 감독을 시작하지 않으며 clean을 남기지 않는다. 필요한 /proc 관측을 할 수 없는 환경도 성공으로 판정하지 않게 한다. |
| 2c-2로 넘어가기 전 필수 여부 | **필수.** 감독이 소유 경계를 확보했다는 전제가 실패해도 실행을 계속한다. |

### V5 — 링크 대상만 검사해 BASE 안의 링크 자체를 지울 수 있다

| 칸 | 내용 |
| --- | --- |
| 번호 | V5 |
| 심각도 | 보통 |
| 관련 항목 | 경로 판정, 검토 질문 B5 |
| 위치 | `drive/scripts/cells_base.py:84` _under_base의 resolve, `:92` BASE 밖 조기 통과; os.unlink 래퍼 |
| 무엇이 문제인가 | 경로를 resolve한 링크 대상만 보고 BASE 밖이면 통과시킨다. 그러나 unlink/remove는 대상을 바꾸는 것이 아니라 BASE 안의 링크 항목 자체를 지우므로, 보호해야 할 경로의 실제 변경을 놓친다. |
| 일어나는 조건 | `b28_guard_probe.py`의 unlink_symlink_entry: 가드 설치 전 BASE/shared에 외부 파일을 가리키는 일반 심볼릭 링크를 두고, 분석 모드에서 Path.unlink로 링크를 지웠다. 외부 원본은 유지되지만 BASE의 링크 항목은 사라졌다. |
| 확신 | 확인함 — 일반 POSIX 링크 재현. 실제 Google Drive 바로가기의 동작을 재현한 것은 아님. |
| 제안 | 파일 내용 접근과 디렉터리 항목 삭제/이동을 구분해, lexical 경로·부모 경로와 해석된 대상 범위를 함께 검사한다. 링크를 통한 내용 쓰기와 링크 자체 삭제를 별도로 시험한다. |
| 2c-2로 넘어가기 전 필수 여부 | 필수 아님. **공유 원본·링크가 있는 입력 폴더를 이용한 예행 연습 전 보완 필요.** |

## 검토 질문별 판단

| 질문 | 확인 내용·판정 |
| --- | --- |
| A1 | 앞의 U1~U5·F1 판정 표 참조. 요청한 두 원본을 실제로 실행했고, b26 원본의 옛 유예/예외 가정에 따른 중단은 호환본과 구분했다. |
| A2 감독 KILL·잔존 | 감독이 KILL돼 상태 파일이 없거나 clean이 아니면 CleanupUnknown → 확인 필요로 간다. 공식 회귀 통과. 정상 지원 환경의 새 세션/입양 손자 정리는 원본·호환본에서 확인했다. 초기화 실패 경계는 V4다. |
| A2 waitpid·TERM 재진입 | 감독은 자식 Popen.poll을 별도로 호출하지 않고 reap의 waitpid(-1) 반환 PID가 학습 자식이면 rc와 child.returncode를 함께 보존한다. 이 코드 안에서 학습 종료 코드가 다른 wait에 먼저 소모되는 경로는 찾지 못했다. TERM 처리기는 최초 시각만 보존하고 본문에서 정리하므로 재진입마다 유예를 늘리거나 재귀 정리하지 않는다. 모든 타이밍을 전수 재현한 것은 아니다. |
| A3 자식 환경 | 실행별 설정/캐시/임시/홈 경로와 연동 차단을 유지한다. 감독도 그 환경을 상속한다. 기존 공용 설정 경로 반례는 해소됐고, 전체 GPU 라이브러리·자동 설치·연동의 실제 파일 추적은 예행 연습에 남는다. |
| B4 쓰기 경로 | open/io.open·Path.write_text·pandas·PIL.Image.save·ZipFile 쓰기·np.save는 일반 파일 열기 경로로 제한된다. 키워드 os 쓰기는 V3다. 추가 실행에서 Path.touch와 sqlite3는 통과했다. 일반 import도 bytecode가 켜져 있으면 BASE/scripts/__pycache__에 .pyc를 만들었다. 이들은 고의 우회가 아닌 상위 API가 낮은 경로를 사용하는 예다. 현재 모듈·노트북 검색에서 sqlite3/cv2.imwrite의 기존 사용은 찾지 못했고, 직접 os.open/하위 프로세스의 미보호는 이미 문서화된 한계라 별도 발견으로 중복하지 않았다. 이 기반이 모든 Python/C 저장을 차단한다고 설명해서는 안 된다. |
| B5 경로 | 일반 상대 경로·..·BASE를 가리키는 POSIX 심볼릭 링크는 resolve 후 같은 범위가 돼 기본 차단이 유지된다. 링크 자체 삭제는 V5다. Google Drive의 서로 다른 FUSE 경로는 POSIX resolve만으로 같은 Drive ID라고 인식하지 못할 수 있다. 실제 마운트·shortcut-targets 별칭·대소문자 동작은 로컬 폴더로 입증할 수 없어 미검증으로 남긴다. |
| B6 설치·스레드 | V1·V2 참조. _narrow는 thread-local이고 exec_scope는 contextvar이므로 다른 일반 스레드에 자동 전파되지 않는다. 하지만 가드 설치/해제는 전역 함수 교체여서 세션 교체를 다른 스레드의 처리와 함께 전수 검증한 것은 아니다. |
| C7 CVAT 허용 목록 | CVAT 2.79 wheel의 읽기·참조 export API와 현재 래퍼 인수를 대조했다. 로그인·로그아웃, /api/tasks 또는 jobs/<id>/dataset/export POST는 쿼리가 있어도 path로 판단하며 끝 슬래시도 허용한다. headers 인수를 바꾸지 않아 조직 헤더는 유지된다. requests.Session의 백업 준비 POST는 거절된다. GET으로 부수 서버 작업을 만드는 옛 API가 통과하는 것은 구현 설명의 알려진 한계다. |
| C8 다른 전송·CLI | SDK의 TUS POST/PATCH는 rest_client 경로를 사용하므로 해당 클래스 request 래퍼를 지난다. urllib3를 직접 부르거나 Session.send를 직접 부르는 경우에는 이 래퍼를 지나지 않는다. 검토한 기존 ctt/백업의 쓰기 경로는 SDK 또는 requests.Session을 사용한다. 직접 subprocess로 부른 cvat-cli는 프로세스 안에 가드가 없으며 Session.run 밖이면 검사되지 않는다. 이는 문서에 남겨 둔 하위 프로세스 한계다. 옛 0번 셀의 subprocess와 1~34번의 run 사용을 구분했고, 2c-2/3에서는 실행 경로를 Session.run 등으로 통일해야 한다. |
| C9 실행 범위 | run_loop는 ex.step을 exec_scope로 감싼다. 실제 쓰기 처리기는 그 스레드에서 수행한다. 진행 알림 스레드는 내부 progress만 바꾸며, frame prefetch는 읽기여서 CVAT 쓰기 차단 반례를 찾지 못했다. 생존 신호는 별도 스레드지만 Colab의 RcloneStore가 하위 rclone으로 원격에 쓰므로 BASE의 Python 파일 가드에 걸리는 경로와 다르다. 이 사실을 contextvar가 생존 스레드에 전파된다는 보장으로 해석하면 안 된다. 직접 환경/컨텍스트를 바꾸는 고의는 요청의 범위 밖이다. |
| D10 요청·신호 | tasks·params·name/model/dataset/server는 심판 접수와 처리기 계약에 맞는다. by_person/by_analysis_session은 스키마에 의해 거절되지 않지만 신원 판단에 사용되지도 않고 intake에 이어지지도 않는다. 신원은 Drive 소유 계정이다. request ID는 초·사람·세션 난수 4자·순번을 포함하고 기존 파일을 확인하므로 일반 순차 호출은 구분된다. 난수 충돌 확률이 0은 아니며 Drive의 확인-쓰기 비원자성은 알려진 한계다. |
| D10 다른 사람 취소 | **다른 등록 사용자라는 이유로 취소가 거절되지는 않는다.** 실제 심판 재현에서 요청 권한이 있는 M2 계정은 M1의 요청을 취소했고, 미등록 계정은 not_registered로 거절됐다(`b28_identity_probe.log`). 현재 Cancel.judge는 대상 존재·최종 상태만 확인한다. 제공된 설계에는 취소를 ‘본인 요청만’으로 제한하는 규칙이 없어 이를 새 ACL 결함으로 단정하지 않았다. 그 제한을 기대한다면 정책과 심판의 소유자/관리자 검사를 추가로 정해야 한다. 현재 A0 공유 신원 한계 역시 그대로다. |
| D11 latest | **옛 뜻과 다르다.** 옛 0번 셀은 TRAINING_DONE 파일의 수정 시각으로 가장 최근 학습 완료를 골랐고, 새 API는 채택 시각을 우선한다. 오래된 모델을 나중에 복원·재채택하면 새 latest가 될 수 있으며, 요청서가 정의한 새 뜻과 맞는다. 채택 시각이 없는 legacy는 train.json의 made_at으로 대체하고 그것도 없으면 0이다. 전부 0이면 이름순 목록의 첫 모델이 선택되므로 실제 최근 학습을 추정해 주는 것은 아니다. 이 선택을 오류로 올리지는 않았지만 UI에서 ‘최근 채택’과 ‘최근 학습 완료’를 혼용하면 안 된다. |

CVAT 2.79의 업로드 코드에서 시작 POST·청크 PATCH가 rest_client로 전달되는 것을 공개 소스로도 확인했다. 전체 SDK 경로 판단은 생성 코드가 포함된 2.79.0 wheel과 현재 설치된 2.83.0의 request 메서드를 함께 대조했다. 실제 서버에는 접속하지 않았다. [CVAT 2.79 업로드 구현](https://raw.githubusercontent.com/cvat-ai/cvat/v2.79.0/cvat-sdk/cvat_sdk/core/uploading.py)

## 점검했지만 문제가 없던 항목

- 지정 일반 시험 709개, 기본 퍼징 10개 항목 통과.
- 감독이 성공적으로 소유 경계를 만든 경우 새 세션·리더 먼저 실패·poll 사이 손자 생성·좀비 처리.
- clean 부재/감독 강제 종료의 CleanupUnknown과 원래 예외 원인 보존, 실행기·심판의 확인 필요 연결.
- 기본 쓰기 가드의 open/Path.write_text/pandas/PIL 저장·삭제·복사 거절, 좁은 API의 요청/신호 생성.
- 일반 POSIX 경로·링크 별칭을 통한 보호 파일 내용 쓰기 차단.
- 기본 CVAT SDK·requests 전송의 방식/경로 판정, 쿼리·끝 슬래시를 포함한 참조 export, 정상 로그인.
- 실행 범위를 벗어난 뒤 같은 스레드의 쓰기 재차단, 정상 모델·데이터셋의 채택 버전/다운로드 해시 검사.
- 미등록 소유 계정의 취소 신호 거절, 요청 params의 실제 심판 접수.
- 코드·시험·셀 원문의 시작/종료 해시 변경 없음.

## 시간이 모자라 보지 못한 항목·환경상 확인하지 못한 항목

- 실제 Colab·Drive 마운트·shortcut-targets/내 드라이브 별칭·대소문자·외부 폴더 링크의 동일 ID 판정.
- 실제 CVAT 2.79 서버·GPU 둘·Kaggle의 prctl 지원/실패 정책·PID 1 회수 정책. 감독 초기화 실패는 반환값만 주입했다.
- cv2.imwrite·matplotlib 모든 backend·모든 C 확장 저장 경로의 실행 검증. 설치하지 않은 라이브러리까지 차단됐다고 주장하지 않는다.
- 모든 전송 라이브러리·리다이렉트·직접 urllib3/CLI 호출의 조합. 보안 경계가 아닌 실수 방지 장치라는 설계 범위를 유지했다.
- 전체 Ultralytics/외부 연동의 부수 파일 쓰기 추적, 실제 데이터셋 캐시와 자동 설치.
- 0번 셀 전체의 실제 계정 실행, 1~34번 셀 전환·최종 ipynb 조립/일치·전 셀 분석 모드 시험. 요청에서 남겨 둔 2c-2 이후 범위다.
- v4.32 전체 회귀·이전 체크리스트 전수 재검토는 이번 범위 밖이다.
