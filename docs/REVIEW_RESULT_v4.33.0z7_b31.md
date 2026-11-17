# v4.33.0z7 검토 결과 — b31

검토일: 2026-11-17. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0z7.md`, b29 결과와 `IMPL_STEP2C_v4.33.md`의 b29 반영 설명을 기준으로 검토했습니다.

**높음 3건, 보통 1건입니다.** b29의 기존 재현 조건들은 호환 재현에서 개선됐지만, 새 활성 가드 조회의 경합(X1)과 분석 부모 링크의 경계 이탈(X3)을 추가 실행으로 확인했습니다. 0z6 커널 전환(X2)은 구형 종료 계약 모형으로 재현했으며, 실제 구버전 전체 커널을 실행한 결과와 구분했습니다. X1~X3을 보완하기 전에는 2c-3 진행을 권하지 않습니다.

코드·노트북·시험·설계서는 수정하지 않았습니다. 지정 회귀 시험 9개는 모두 `RESULT True`이며 총 758개 확인 줄이 통과했습니다. 실제 CVAT·Google Drive·Kaggle에는 접속하지 않았습니다.

## 발견 사항

### X1 — 활성 세션을 읽은 뒤 앞 가드가 꺼지면 검사 없이 원래 쓰기·전송 함수로 내려감

| 칸 | 내용 |
| --- | --- |
| 심각도 | 높음 |
| 관련 항목 | b29 W1, 분석 쓰기·CVAT 변경 경계, 3장 약속 9 등의 보호 경계 |
| 위치 | `drive/scripts/cells_base.py:261` `_active_writes`, `cells_base.py:390` `_active_cvat`, `cells_base.py:731` `start` |
| 무엇이 문제인가 | 활성 세션/가드 조회와 그 가드의 `enabled` 판정이 분리돼 있습니다. 조회한 앞 가드가 그사이 꺼지면 `None`을 반환하고, 래퍼는 이미 새 활성 가드가 있는데도 검사 없이 원래 함수로 내려갑니다. 활성 세션 대입 한 번만으로 이 조회 순서까지 원자적으로 되지는 않습니다. |
| 일어나는 조건 | 쓰기 스레드가 `_active_writes`에서 앞 세션의 `w`를 얻음 → 재시작 스레드가 새 세션을 활성화하고 `prev.close()`로 앞 `w.enabled=False` 처리 → 쓰기 스레드가 `enabled`를 읽어 `None` 반환. `_active_cvat`도 같은 순서입니다. |
| 재현 결과 | Python 추적 함수로 가드 지역변수를 얻은 직후에만 스케줄을 멈췄습니다. 실제 가드 객체·enabled 값·install/uninstall은 바꾸지 않았습니다. 새 가드가 켜진 상태에서 `BASE/shared.json.write_text('changed')`가 성공했고, 가짜 전송 클래스의 `DELETE https://fake.cvat/api/tasks/1`도 원래 메서드까지 도달했습니다. 실제 네트워크 전송은 없습니다. |
| 확신 | 확인함 — `rLog/b31_race_probe.py`, `b31_race_probe.log`의 `active_lookup_write`, `active_lookup_transport` |
| 제안 | 가드 조회와 수명 변경을 함께 동기화하거나, 조회한 정책을 불변 스냅샷으로 사용하세요. 앞 객체가 비활성이라는 이유로 현재 가드가 존재하는 호출을 무검사 통과시키면 안 됩니다. `start()`끼리만 잠그는 것으로는 쓰기 스레드와의 경합을 막지 못합니다. |
| 2c-3으로 넘어가기 전 필수 여부 | **필수.** W1의 원래 테스트 시점은 고쳐졌지만 다른 정상 스레드 순서에서 보호가 풀립니다. |

### X2 — 구형 세션의 close가 새로 설치한 전역 래퍼를 다시 제거할 수 있음

| 칸 | 내용 |
| --- | --- |
| 심각도 | 높음 |
| 관련 항목 | b29 W1, 요청서의 0z6 커널 → 0z7 reload 전환 |
| 위치 | `drive/scripts/cells_base.py:728` `start`의 설치·활성화·`prev.close()` 순서; `_active_writes`·`_active_cvat`의 구형 객체 처리 |
| 무엇이 문제인가 | reload는 기존 세션 객체를 새 클래스의 인스턴스로 바꾸지 않습니다. 새 `start()`는 전역 래퍼를 설치하고 새 세션을 활성화한 뒤 앞 객체의 `close()`를 호출합니다. 0z6의 uninstall은 원래 전역 함수를 복구하는 방식이므로, 남아 있던 구형 객체가 새 래퍼를 제거할 수 있습니다. 현재 `prev.close()`가 전역을 건드리지 않는다는 주석은 새 버전 객체에만 맞습니다. |
| 일어나는 조건 | 0z6 분석 세션이 활성인 커널에서 모듈만 0z7로 다시 불러오고 `start()`가 앞 세션 종료까지 진행하는 경우. 또한 새 조회 함수는 구형 객체에 새 `enabled` 속성이 없으면 가드 없음으로 취급하므로, 전환 도중의 호환성도 필요합니다. |
| 재현 결과 | 구형 close의 전역 원래 함수 복구 계약을 앞 세션에 주입한 별도 모형에서, `start()` 반환 후 `active is 새 세션`, 새 `writes.enabled=True`인데도 공유 파일 생성이 성공했습니다. 이는 구형 수명주기의 호환성 재현이며, 0z6 모듈 전체를 재실행한 결과는 아닙니다. |
| 확신 | **추정 — 구형 close 계약 모형에서는 확인함.** 이번 작업에는 0z6 소스 전체 스냅샷이 없어 실제 구형 커널 전환은 실행하지 못했습니다. b29에서 확인한 전역 복구 동작과 현재의 호출 순서가 근거입니다. |
| 제안 | 구형 세션·래퍼를 식별하는 명시적인 전환 처리를 두거나, 구형 활성 세션이 있는 reload를 변경 전에 거절하고 커널 재시작을 안내하세요. 새 가드만 설치한 뒤 구형 close를 그대로 호출하는 방식은 피해야 합니다. 전환 중에도 보호가 유지되는지 별도 시험이 필요합니다. |
| 2c-3으로 넘어가기 전 필수 여부 | **필수.** 요청서가 지정한 구형 커널 전환을 지원하거나, 안전하게 차단하는 정책이 필요합니다. |

### X3 — boot 허용이 부모 링크를 따라 보호 공유 폴더에 분석 파일을 만듦

| 칸 | 내용 |
| --- | --- |
| 심각도 | 높음 |
| 관련 항목 | b29 W5, boot 허용 경계, **3장 약속 5: CVAT_UpLoader 읽기 전용** |
| 위치 | `drive/scripts/cells_base.py:135` `WriteGuard._booting`, `cells_base.py:159` `check_entry`, `cells_base.py:718` `start` |
| 무엇이 문제인가 | boot 허용이 링크를 해석하지 않은 `abspath`의 상하위 관계만 검사하고, `check_entry`는 그 결과가 참이면 실제 부모 경로 검사 전에 반환합니다. `analysis/<사람>`이 다른 공유 폴더를 가리키면 새 분석 폴더 생성이 그곳으로 새고, 이후 Saver도 링크로 이동한 출력 루트를 허용합니다. |
| 일어나는 조건 | 기존 `BASE/analysis/M2`가 `BASE/CVAT_UpLoader`를 가리키는 디렉터리 링크이고 M1 세션이 활성인 상태에서 M2로 재시작합니다. |
| 재현 결과 | `BASE/CVAT_UpLoader/<날짜_세션>/`과 그 안 `_session.json`이 실제 생성됐습니다. 링크는 시험 준비 단계에서 미리 만들었고, 재시작은 일반 `start()`를 호출했습니다. OS 원시 쓰기로 가드를 우회하지 않았습니다. 로컬 POSIX 링크 모형이며 실제 Drive FUSE의 링크 동작은 검증하지 않았습니다. |
| 확신 | 확인함 — `b31_race_probe.log`의 `boot_parent_symlink` |
| 제안 | 새 출력 루트와 기존 부모를 실제 경로로 해석해 의도한 분석 트리 안인지 검증한 뒤 boot 허용을 설정하세요. 분석 트리 밖으로 향하는 부모 링크는 거절하고, 만들어진 출력 루트도 다시 확인하세요. |
| 2c-3으로 넘어가기 전 필수 여부 | **필수.** 읽기 전용 보호 폴더에 쓰는 경로가 실제로 열립니다. |

### X4 — 지원 하한 Python 3.10에서는 Z 접미사 시각이 0으로 처리됨

| 칸 | 내용 |
| --- | --- |
| 심각도 | 보통 |
| 관련 항목 | b29 W2, 요청서의 Z 형식 점검, AGENTS의 Python 3.10 이상 |
| 위치 | `drive/notebooks/A0_colab/cells_v4.33/cell00.py:258` `_when` |
| 무엇이 문제인가 | `_when`은 `Z`를 숫자 UTC 오프셋으로 정규화하지 않고 `datetime.fromisoformat`에 넘깁니다. Python 3.10의 해당 API는 Z 형식을 지원하지 않으므로 ValueError가 0.0으로 바뀌고, 최신 Z 기록이 과거의 정상 파싱 기록보다 오래된 것으로 정렬됩니다. |
| 일어나는 조건 | Python 3.10에서 실행기 시각이 `2026-11-17T02:00:00Z`이고 옛 업로드가 `2026-11-16 23:00:00`인 경우. 전자는 실제 한국 시각 11월 17일 11시지만 파싱 실패로 0이 되어 뒤의 옛 기록이 선택됩니다. |
| 확신 | 확인함 — 코드 흐름과 공식 버전별 API 계약으로 확인. **Python 3.10 직접 실행은 미실시**이며, 현재 3.14.4에서는 같은 Z 값이 정상 파싱됩니다. |
| 제안 | 지원 버전에 맞게 끝의 Z를 `+00:00`으로 정규화하거나 지원 하한을 명시적으로 올리세요. 최소 지원 버전에서도 시각 비교 시험을 실행하세요. |
| 2c-3으로 넘어가기 전 필수 여부 | 비필수. 지원 하한 유지 여부를 확정하고 해당 환경 배포 전에는 보완해야 합니다. |

X4의 버전 차이는 [Python 3.10 공식 문서](https://docs.python.org/3.10/library/datetime.html#datetime.datetime.fromisoformat)의 지원 문법과 [Python 3.11 공식 문서](https://docs.python.org/3.11/library/datetime.html#datetime.datetime.fromisoformat)의 Z 예제·3.11 변경 설명을 대조했습니다. 참고 기록은 `rLog/b31_python_compat_sources.md`입니다.

## b29 반영 확인

| 항목 | 판정 및 근거 |
| --- | --- |
| W1 기존 close 직후 쓰기 재현 | 해당 조건은 개선됨. `b29_extra_probe.py` 원본에서 공유 쓰기가 차단됐고 새 가드가 활성인 상태로 앞 세션이 닫힙니다. 다만 X1의 가드 조회 경합이 남아 완전 해결로 판정하지 않습니다. |
| W2 같은 날 문자열 비교 | 개선됨. 호환 재현에서 10시 실행기 결과 대신 11시 옛 업로드를 선택했습니다. 현재 Python에서 초 없음·소수 초·Z·초 없는 Z·소수 초 Z도 정상 파싱했습니다. 최소 지원 버전의 차이는 X4입니다. |
| W3 실행기 이력만 있는 26번 셀 | 개선됨. 실제 `ctt.ACTIVITY_COLUMNS`를 사용한 모형에서 tasks/history 모두 예외 없이 1행을 만들었습니다. 기본 jobs 보기는 여전히 TASK 줄을 작업 목록으로 합성하지 않아 0개지만, 이번 수정 대상인 빈 열 예외와 구분했습니다. |
| W4 11번 셀 영상 이름 | 개선됨. 원문의 `os.path.basename(str(video))` 출력문을 문자열 경로로 실행해 `video.mp4` 출력을 확인했습니다. YOLO·영상 전체 실행은 하지 않았습니다. |
| W5 새 사람의 부모 폴더 | 일반 디렉터리에서는 개선됨. M2 분석 부모가 없는 상태에서 재시작 성공. 다른 스레드 및 분석 트리 밖 일반 경로의 boot 허용은 거절됩니다. 부모 링크 조건은 X3입니다. |

추가로 새 버전 세션에서 TransportGuard 설치 실패를 주입해 앞 활성 세션과 공유 쓰기 차단이 유지되는 것을 확인했습니다. 두 스레드의 `start()`를 boot 설정 직후에 겹치면, 전역 boot 값이 서로 덮이고 지워져 두 호출 모두 AnalysisRefused로 끝나는 순서도 재현됐습니다. 이때는 앞 세션과 보호가 유지됐으므로 무가드 상태로 판정하지 않았습니다. 동시 start의 성공까지 검증된 것은 아닙니다(`b31_boundary_probe.log`).

## 시험과 증거

실행 환경: `/tmp/b24_venv/bin/python` (Python 3.14.4), pandas·requests·IPython·cvat-sdk가 있는 시험용 가상환경. 모든 명령에 `PYTHONDONTWRITEBYTECODE=1`을 적용했습니다.

| 시험 | 결과 | 로그 |
| --- | --- | --- |
| `test_cells_433.py drive` | 79/79, RESULT True | `rLog/b31_cells.log` |
| `test_hosts_433.py drive` | 57/57, RESULT True | `rLog/b31_hosts.log` |
| `test_handlers_433.py drive` | 143/143, RESULT True | `rLog/b31_handlers.log` |
| `test_e2e_433.py drive` | 17/17, RESULT True | `rLog/b31_e2e.log` |
| `test_master_433.py drive` | 75/75, RESULT True | `rLog/b31_master.log` |
| `test_arbiter_433.py drive` | 247/247, RESULT True | `rLog/b31_arbiter.log` |
| `test_access_433.py drive` | 68/68, RESULT True | `rLog/b31_access.log` |
| `test_master_main_433.py drive` | 62/62, RESULT True | `rLog/b31_master_main.log` |
| `test_fuzz_433.py drive` | 10개 확인 줄, RESULT True | `rLog/b31_fuzz.log` |

요청된 b29 원본 재현도 수정 없이 실행했습니다.

- `b29_extra_probe.py`: 종료 1. W1 기존 조건 차단, W5 성공까지 확인한 뒤, 원본이 새 `_when`을 AST 추출 대상에 넣지 않아 NameError로 중단됐습니다. 제품 결함으로 세지 않았습니다. 로그: `b31_extra_original.log`.
- `b29_supervisor_compat.py`: 종료 0. 감독 준비 실패에서 `child_started:false`, 자식 표식 없음, RuntimeError를 확인했습니다. 로그: `b31_supervisor_original.log`.
- `b31_extra_compat.py`: 원본을 보존하고 `_when` 추출, 실제 ACTIVITY_COLUMNS 제공, 바뀐 11번 출력문 실행을 반영한 별도 재현입니다. b29의 나머지 조건과 추가 시각 형식을 확인했습니다. 로그: `b31_extra_compat.log`.

추가 재현 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b31_extra_compat.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b31_race_probe.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b31_boundary_probe.py
```

추가 스크립트는 관측 결과를 출력하는 진단용이므로 종료 0이 제품에 문제가 없다는 뜻은 아닙니다. 전송 재현은 실제 요청 대신 가짜 클래스의 원래 메서드에 도달했는지를 기록합니다.

검토 전후 소스·셀·시험·AGENTS 57개 파일의 SHA-256은 모두 동일했습니다. 셀 원문의 AST 문법 오류도 없었습니다. `rLog/b31_initial_hashes.json`, `b31_final_check.json`에 결과를 보관했습니다. 기존 작업 내용을 변경하지 않았습니다.

## 점검했지만 문제가 없던 항목

- 새 버전끼리의 순차 reload/start에서 래퍼가 원래 함수를 한 겹 감싸는 동작과 기본 공유 쓰기 차단.
- 잘못된 시작 설정 및 새 TransportGuard 설치 실패 시 앞 세션의 보호 유지.
- 기존 close 시점 재현과 연속 재시작 회귀 시험. 이 통과만으로 X1의 모든 스케줄을 보장하지는 않습니다.
- 새 분석 부모가 일반 디렉터리일 때 다른 사람 ID로 시작, 다른 스레드·다른 일반 경로로 boot 허용이 새지 않는 조건.
- 현재 Python에서 시간대 없는 한국 시각과 오프셋 시각 비교, 초 생략·소수 초·Z 변형의 파싱.
- 26번 셀의 필수 열 보충과 11번 셀의 문자열 파일명 출력.
- 분석 폴더·요청 ID의 KST 사용, BASE 기본값 비움 및 Drive 연결 전에 빈 BASE를 거절하는 순서.
- 지정된 심판·접근 통제·마스터·호스트·처리기·연결·퍼징 회귀 시험.

## 보지 못했거나 검증하지 않은 항목

- 실제 0z6 모듈 전체를 로드한 구형 커널 전환. X2는 구형 종료 계약 모형과 호출 순서 분석에 근거합니다.
- Python 3.10 인터프리터 직접 실행. X4는 공식 버전별 API 계약과 코드 흐름으로 확인했습니다.
- 실제 Colab·Drive FUSE·CVAT·Kaggle 및 실제 모델·영상·GPU 실행. 링크 시험은 로컬 POSIX 환경입니다.
- 모든 스레드 스케줄의 완전 탐색, 진행 중 HTTP 요청·열린 파일 핸들의 정책 변경까지 포함한 전체 수명 검증.
- 이번 범위 밖 쓰기 셀·제출본·작업자 셀·노트북 전체 조립 및 b30 검토, Apps Script·CTRL앱·v4.32 전체 회귀.
- 명시된 os.open·하위 프로세스·직접 전송 API 등의 우회 한계에 대한 보안 격리 검증.
