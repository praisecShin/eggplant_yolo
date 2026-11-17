# v4.33.0z6 검토 결과 — b29

검토일: 2026-11-17. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0z6.md`, b28 결과와 `IMPL_STEP2C_v4.33.md`의 2c-2·b28 반영 설명을 기준으로 검토했습니다.

**높음 2건, 보통 3건을 확인했습니다. W1·W2는 2c-3 진행 전 보완이 필요합니다.** 기존 b28 재현 조건의 수정은 확인했지만, 동시 실행 중 세션 교체와 기록 시각 비교에 빈틈이 남아 있습니다. 코드는 수정하지 않았습니다.

## 발견 사항

### W1 — 세션 교체 중 앞 가드를 제거하고 새 가드를 설치하기 전 공유 쓰기가 통과함

| 칸 | 내용 |
| --- | --- |
| 심각도 | 높음 |
| 관련 항목 | b28 V1·V2, 분석 모드 쓰기 경계, 3장 약속 9에 대한 보호 경계 |
| 위치 | `drive/scripts/cells_base.py:669` `start`, `cells_base.py:583` `Session.close` |
| 무엇이 문제인가 | `prev.close()`가 전역 파일·CVAT 래퍼를 원래 함수로 복구한 뒤 새 `S.writes.install()`·`S.cvat.install()`을 부릅니다. 이 사이 다른 스레드는 분석 세션의 제한 없이 공유 파일을 쓸 수 있습니다. 마지막 상태가 한 겹 가드라는 사실만으로 교체 중의 보호가 유지되지는 않습니다. |
| 일어나는 조건 | 0번 셀 재시작 스레드가 앞 세션의 `close()`를 끝낸 직후 다른 스레드가 실행되는 순서. 재현은 원래 `close()`를 실행한 뒤 이벤트로 새 설치 직전 스케줄을 고정했고, 다른 스레드의 `BASE/shared/during_restart.write_text('changed')`가 실제 성공했습니다. 원래 보호 함수를 우회한 쓰기가 아닙니다. |
| 확신 | 확인함 — `rLog/b29_extra_probe.py`, `b29_extra_probe.log`의 `restart_thread_gap` |
| 제안 | 전역 래퍼는 유지한 채 활성 정책을 교체하거나, 모든 가드 호출이 함께 따르는 교체 동기화로 무가드 구간을 없애세요. `start()`끼리만 잠그는 것으로는 다른 쓰기 스레드를 막지 못합니다. |
| 2c-3으로 넘어가기 전 필수 여부 | **필수.** 쓰기 셀을 더 연결하기 전에 세션 전환 중에도 기본 거절 경계가 유지돼야 합니다. |

### W2 — 같은 날의 옛 기록과 실행기 결과를 비교하면 실제 최신 업로드를 잘못 고름

| 칸 | 내용 |
| --- | --- |
| 심각도 | 높음 |
| 관련 항목 | 2c-2 `last_upload`, 옛 기록·v4.33 결과 합치기 순서 |
| 위치 | `drive/notebooks/A0_colab/cells_v4.33/cell00.py:277` `last_upload` |
| 무엇이 문제인가 | 옛 `run_time`은 `YYYY-MM-DD HH:MM:SS`, 실행기 `time`은 `YYYY-MM-DDTHH:MM:SS+09:00`인데 문자열 그대로 `max`를 적용합니다. 같은 날짜에서는 시간보다 앞선 `T`와 공백 차이 때문에 실행기 결과가 무조건 이깁니다. 이를 쓰는 검수·모델 비교 셀이 오래된 자동 라벨을 기준으로 삼습니다. |
| 일어나는 조건 | 같은 TASK에 실행기 결과 `2026-11-17T10:00:00+09:00`와 옛 업로드 완료 `2026-11-17 11:00:00`이 있으면, 나중의 `old.xml` 대신 10시의 `new.xml`을 반환합니다. `include_track=True`일 때 같은 날 더 늦게 만든 옛 형식 track 기록도 같은 영향을 받습니다. |
| 확신 | 확인함 — 0번 셀 원문 함수를 AST로 추출해 실행한 `b29_extra_probe.log`의 `same_day_last_upload` |
| 제안 | 양쪽 시각을 같은 시간대의 datetime 또는 epoch로 정규화해 비교하고, 같은 날짜·다른 구분자·시간대가 포함된 회귀 사례를 추가하세요. |
| 2c-3으로 넘어가기 전 필수 여부 | **필수.** 뒤 단계가 재사용할 결과 선택 도우미의 기준이 틀립니다. |

### W3 — 옛 activity.csv가 없는 새 환경에서 26번 셀의 TASK·이력 보기가 예외로 끝남

| 칸 | 내용 |
| --- | --- |
| 심각도 | 보통 |
| 관련 항목 | 새 발견, 2c-2 작업 기록 조회 |
| 위치 | `drive/notebooks/A0_colab/cells_v4.33/cell26.py:19`, `cell26.py:27`, `cell26.py:67`, `cell26.py:77` |
| 무엇이 문제인가 | 실행기 결과로 추가한 줄에는 `boxes_before`, `boxes`, `by_label`, `frames`, `task_updated`가 없고, DataFrame을 만든 뒤 공통 열을 보충하지 않습니다. 옛 기록이 없는 환경에서는 TASK 보기의 열 선택과 history의 값 접근이 `KeyError`를 냅니다. 옛 CSV 행이 있으면 pandas가 그 열을 만들어 주므로 기존 시험에서는 가려집니다. |
| 일어나는 조건 | `ctt.read_sharded(activity.csv)`는 빈 목록이고 실행기 성공 결과는 1건 존재하는 환경. `AC_VIEW='tasks'`는 누락 열 목록의 `KeyError`, `AC_VIEW='history'`와 TASK 지정은 `KeyError('boxes')`로 재현됐습니다. |
| 확신 | 확인함 — 26번 셀 원문을 가짜 이력으로 실행한 `b29_extra_probe.log`의 `cell26_tasks`, `cell26_history` |
| 제안 | 입력 종류와 관계없이 활동 기록의 공통 스키마를 먼저 채우고, 수량 정보가 없는 실행기 결과는 빈 값으로 표시하세요. 옛 기록 0건인 시험을 추가하세요. |
| 2c-3으로 넘어가기 전 필수 여부 | 비필수. 다만 2c-2 완료 판정 및 2c-6 전 셀 검증 전에는 수정해야 합니다. |

### W4 — 11번 진단 셀이 문자열 영상 경로의 `.name`에 접근함

| 칸 | 내용 |
| --- | --- |
| 심각도 | 보통 |
| 관련 항목 | 새 발견, 2c-2 영상 도우미 연결 |
| 위치 | `drive/notebooks/A0_colab/cells_v4.33/cell11.py:18`; 반환 계약 `drive/scripts/cells_base.py:572` `Session.video` |
| 무엇이 문제인가 | `S.video()`는 영상 발견·백업 복원 양쪽 모두 문자열 경로를 반환합니다. 11번 셀은 이를 `cv2.VideoCapture(str(video))`에 전달한 뒤 `video.name`을 출력하므로 정상 영상이 있어도 `AttributeError`로 진단이 중단됩니다. |
| 일어나는 조건 | 업로드 전 백업과 영상이 존재하고 모델·영상 열기가 성공한 정상 진단 경로. 해당 출력문을 문자열 경로로 실행하면 `'str' object has no attribute 'name'`이 발생합니다. |
| 확신 | 확인함 — 반환 분기 코드 추적 및 원문 출력문 실행, `b29_extra_probe.log`의 `cell11_video_string`. 실제 YOLO·영상 처리는 실행하지 않았습니다. |
| 제안 | 도우미의 반환 계약에 맞춰 파일명 추출을 통일하세요. 모델 없이도 검사할 수 있는 경로 타입 연결 사례를 추가하세요. |
| 2c-3으로 넘어가기 전 필수 여부 | 비필수. 11번 셀 사용 및 2c-6 전 셀 검증 전에는 수정해야 합니다. |

### W5 — 재시작 시 새 OPERATOR의 분석 부모 폴더 생성이 앞 가드에 막힘

| 칸 | 내용 |
| --- | --- |
| 심각도 | 보통 |
| 관련 항목 | b28 V1 재시작, 새 분석 폴더 생성 허용 범위 |
| 위치 | `drive/scripts/cells_base.py:660` `start`, `WriteGuard._booting` |
| 무엇이 문제인가 | boot 허용은 새 세션의 최종 출력 폴더와 그 아래만 인정합니다. `analysis/<새 사람>/`이 없으면 `out.mkdir(parents=True)`가 그 부모를 만들려는 순간 앞 세션 가드가 거절합니다. 같은 사람의 재실행만으로는 드러나지 않습니다. |
| 일어나는 조건 | 같은 BASE에서 M1 세션이 활성인 상태로, 아직 분석 폴더가 없는 M2로 `start()`를 호출합니다. 재현 결과 `os.mkdir: not_permitted:analysis/M2`로 실패했습니다. 앞 가드는 유지되므로 보호 해제나 데이터 손실은 확인되지 않았습니다. |
| 확신 | 확인함 — `b29_extra_probe.log`의 `switch_person` |
| 제안 | 검증된 새 출력 경로를 만드는 데 필요한 부모 항목만 현재 스레드에 제한적으로 허용하세요. 부모 허용을 일반적인 공유 쓰기 허용으로 넓히지는 마세요. |
| 2c-3으로 넘어가기 전 필수 여부 | 비필수. 사람 ID를 바꾸는 재초기화를 지원하려면 보완해야 합니다. |

## 시험 및 b28 재점검

실제 CVAT·Drive·Kaggle에는 접속하지 않았습니다. Python 시험은 `/tmp/b24_venv/bin/python`, `PYTHONDONTWRITEBYTECODE=1`로 실행했습니다.

| 시험 | 결과 | 로그 |
| --- | --- | --- |
| `test_cells_433.py drive` | 69/69, RESULT True | `rLog/b29_cells_with_ipython.log` |
| `test_hosts_433.py drive` | 57/57, RESULT True | `rLog/b29_hosts.log` |
| `test_handlers_433.py drive` | 143/143, RESULT True | `rLog/b29_handlers.log` |
| `test_e2e_433.py drive` | 17/17, RESULT True | `rLog/b29_e2e.log` |
| `test_master_433.py drive` | 75/75, RESULT True | `rLog/b29_master.log` |
| `test_arbiter_433.py drive` | 247/247, RESULT True | `rLog/b29_arbiter.log` |
| `test_access_433.py drive` | 68/68, RESULT True | `rLog/b29_access.log` |
| `test_master_main_433.py drive` | 62/62, RESULT True | `rLog/b29_master_main.log` |
| `test_fuzz_433.py drive` | 10개 확인 줄, RESULT True | `rLog/b29_fuzz.log` |

최종 지정 시험은 합계 748개 확인 줄이 모두 통과했습니다. 최초 셀 시험은 IPython 미설치로 6개 항목이 실패했습니다(`b29_cells.log`). 시험용 가상환경에 IPython을 설치하고 재실행해 통과했으므로 제품 결함으로 세지 않았습니다. `b29_test_status.json`은 최초 실행 기록이며 최종 셀 결과는 위 재실행 로그가 기준입니다.

| b28 원본 재현 | 결과와 해석 |
| --- | --- |
| `b28_guard_probe.py` | 종료 0. reload 후 시작 성공, 잘못된 설정의 시작 실패 후 공유 쓰기 차단, 키워드 replace 및 공유 링크 삭제 차단을 확인했습니다. `b29_guard_original.log` 참고. V1·V2는 해당 단일 스레드 재현은 수정됐지만 W1의 교체 구간은 남습니다. |
| `b28_supervisor_probe.py` | 종료 1. 예전 재현은 학습 자식이 만든 `grand.pid`를 무조건 읽는데, 수정 후 자식을 띄우지 않아 FileNotFoundError로 끝났습니다. 이것을 V4 재발로 판정하지 않았습니다. `b29_supervisor_original.log` 참고. |
| 감독 보완 재현 | 원본을 수정하지 않고 `b29_supervisor_compat.py`에 새 실패 계약을 검사하도록 별도 사본을 만들었습니다. prctl 실패 주입 시 `setup_failed`, `child_started:false`, 자식 표식 없음, RealTrainer의 RuntimeError를 확인했습니다. `b29_supervisor_compat.log` 참고. 감독 준비 검사가 Popen보다 앞서 있어 일반 실패 처리가 타당합니다. |
| `b28_import_probe.py` | 종료 0, 공유 bytecode 생성은 여전히 관측됩니다. 이 원본은 bytecode를 명시적으로 켠 직접 import 시험입니다. 수정은 가드 자체가 아니라 0번 셀의 import 전 `sys.dont_write_bytecode=True`이므로 서로 다른 조건입니다. 실제 0번 셀의 설정 순서는 원문으로 확인했습니다. `b29_import_original.log` 참고. |

원본 가드 재현의 `Path.touch`·sqlite 쓰기 통과와 직접 import 시험의 bytecode 생성은 이미 설명된 저수준 쓰기 한계와 위 초기화 조건에 해당하여 새 발견으로 중복 보고하지 않았습니다. V3의 키워드·dir_fd, V5의 항목/내용 구분은 지정 시험 범위에서 통과했습니다.

추가 재현 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b29_extra_probe.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b29_supervisor_compat.py
```

추가 재현은 제품 결함을 출력하는 진단 스크립트이며, 종료 0이 제품에 문제가 없다는 뜻은 아닙니다. 모델·영상이 필요한 셀은 원문과 국소 표현식/도우미만 검사했습니다. 0번 셀 전체는 실행하지 않았습니다.

검토 전후 AGENTS·Python 소스·셀 원문·시험 57개 파일의 SHA-256이 모두 동일했습니다. 증거는 `rLog/b29_initial_hashes.json`, `b29_final_hash_check.json`에 있습니다. 셀 원문의 AST 문법 검사에서도 오류가 없었습니다. 코드·노트북·시험·설계서는 수정하지 않았습니다.

## 점검했지만 문제가 없던 항목

- sys 기반 활성 세션 보존, reload 뒤 같은 사람으로 재시작, 원래 함수 표시에 따른 가드 중첩 방지.
- OPERATOR 누락·BASE 오류·잘못된 모드로 시작 실패할 때 앞 가드 유지.
- 키워드 경로 인자, 시험된 dir_fd 경로 해석, 공유 폴더 링크 항목 삭제 차단과 내 분석 폴더 링크 삭제 허용.
- 감독의 subreaper 설정·재확인 실패 시 학습 자식 미생성. 이 조건에서 일반 실패 처리.
- `last_adopted`의 채택 시각 선택, `latest` 거절, 채택 시각이 전혀 없을 때 임의 모델 선택 금지. 등록자가 다른 사람 요청을 취소할 수 있는 정책은 확정 결정으로 취급했습니다.
- 실행기 업로드 뒤 revert 성공만 있는 기본 이력에서 `last_upload`가 그 업로드를 반환하지 않는 동작, 실패한 실행기 결과 제외.
- 가짜 환경에서 7·8·19·25·26번 셀 실행, 옛 기록 읽기와 현재 세션 records 합치기, 캐시·보고서의 분석 폴더 저장. 시험 전후 공유 파일 변경 없음.
- h_task의 업로드 결과 파일·해시·모델 게시와 관련 처리기 회귀 시험.

## 보지 못했거나 검증하지 않은 항목

- 실제 Colab·Drive FUSE·CVAT·Kaggle, 실제 GPU·YOLO 모델·영상·CVAT 프레임을 이용한 전체 실행.
- 요청서에서 후속 단계로 남긴 2c-3 쓰기 셀, 2c-4 제출본, 2c-5 작업자 셀, 2c-6 노트북 조립과 전 셀 실행.
- 이번 요청 범위 밖 v4.32 전체 회귀 및 Apps Script·CTRL앱 시험.
- 모든 OS 함수·제3자 라이브러리·스레드 스케줄 조합의 완전 탐색. 기존에 명시된 os.open·하위 프로세스·직접 전송 API의 우회 한계를 보안 격리 수준으로 검증하지 않았습니다.
