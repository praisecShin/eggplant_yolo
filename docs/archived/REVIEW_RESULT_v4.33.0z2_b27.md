# v4.33.0z2 검토 결과 — b27 (요청서 확인 전 사전 검토)

검토일: 2026-11-17. **검토 미완료:** 지정된 `docs/REVIEW_REQUEST_v4.33.0z2.md`가 현재 작업 폴더에 없다. 저장소와 상위 `/mnt/c/Users/user/Project`에서 같은 이름을 검색했지만 찾지 못했고, 사용자에게 저장·동기화 또는 실제 경로 확인을 요청했다. 요청서에만 있는 검토 범위·질문·필수 시험·새 발견 번호 규칙은 확인하지 못했다.

그동안 `AGENTS.md`, `IMPL_STEP2B_v4.33.md`의 b26 반영(0z2), b26 결과 및 관련 코드를 기준으로 선행 점검했다. **이 범위에서 높음 1건을 확인했다.** 아래 F1은 AGENTS 기본 형식에 따른 임시 번호다. 요청서가 확인되면 추가 범위와 번호 규칙을 반영해 완성해야 한다.

코드·노트북·시험·설계서는 수정하지 않았다. 이 보고서와 `rLog/b27_*` 검토 자료만 작성했다. 실제 CVAT·Drive·Kaggle·Colab·GPU 모델에는 접속하거나 실행하지 않았다. 시작 시 코드·시험·AGENTS 해시를 기록하고 점검 후 대조했으며 변경은 없었다(`b27_initial_hashes.json`).

## 시험과 자료

0z1 요청에서 사용한 네 시험을 현재 0z2 코드에서 실행했다. 아직 없는 0z2 요청서의 시험 목록을 대신 확정한 것은 아니다.

| 실행 | 결과 | 로그 |
| --- | --- | --- |
| `python tests/test_hosts_433.py drive` | 52개 성공 | `rLog/b27_hosts.log` |
| `python tests/test_handlers_433.py drive` | 142개 성공 | `rLog/b27_handlers.log` |
| `python tests/test_e2e_433.py drive` | 17개 성공 | `rLog/b27_e2e.log` |
| `python tests/test_master_433.py drive` | 75개 성공 | `rLog/b27_master.log` |

**286개 모두 성공**, 종료 코드 모두 0, 마지막 출력 모두 RESULT True. 실행 명령·환경은 `b27_run_tests.py`, 종료 코드·시간은 `b27_test_status.json`에 있다. 기존 `/tmp/b24_venv`의 Python 3.14.4와 의존성을 사용하고 PYTHONDONTWRITEBYTECODE=1로 실행했다. 패키지는 새로 설치하지 않았다.

추가 재현:

| 자료 | 내용·결과 |
| --- | --- |
| `b27_orphan_probe.py`·동명 `.log` | 새 세션 손자를 만든 리더가 두 poll 사이에 종료하는 새 반례. RuntimeError로 돌아왔지만 실행기에 입양된 손자가 살아 있었음. |
| `b27_b26_model_boundaries.log` | 기존 `rLog/b26_model_boundaries.py` 원본 재실행. metrics/args가 목록이어도 정상 모델과 함께 행을 반환하고, 잘못된 legacy 경로는 해당 모델만 제외함. WebState._models도 정상 반환. |
| `b27_cleanup_flow_compat.py`·동명 `.log` | b26 정리 실패 재현에서 새 _kill(proc, tree, signal) 인수와 CleanupUnknown 타입만 맞춘 호환본. 실제 처리기·실행기·심판 연결에서 stop_run/cleanup_unknown → needs_check. |
| `b27_write_isolation_compat.py`·동명 `.log` | b26 쓰기 격리 재현의 가짜 ultralytics에 새 import 계약의 settings 객체만 추가한 호환본. 실제 부모·train_child와 라이브러리의 경로·JSON 저장 함수에서 두 실행의 설정 경로가 분리됨. |

실행 방법:

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b27_orphan_probe.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_model_boundaries.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b27_cleanup_flow_compat.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b27_write_isolation_compat.py
```

기존 b26 스크립트·로그는 수정하지 않았다. 호환본은 당시 원본 그대로 재실행한 것으로 표시하지 않았다. 쓰기 격리 호환본의 소스 입력은 이전에 내려받은 Ultralytics 8.4.215의 `/tmp/b24_sources/unpacked/ultralytics/utils/__init__.py`이며 소스 경로를 첫 인자로 바꿀 수 있다. 실제 모델 학습 대신 해당 라이브러리의 경로·JSON 저장 함수만 제한 실행한다.

## b26 수정분의 선행 판정

| b26 항목 | 현재 확인 범위의 판정 |
| --- | --- |
| U1 새 세션 DDP 작업자 추적 | **부분 해결.** 살아 있는 알려진 부모 사슬에 붙어 있는 새 세션 자식은 추적한다. 하지만 사슬을 관측하기 전에 부모가 종료해 subreaper에 입양된 자식은 놓친다(F1). |
| U2 정리 불확실성 보고 | 기존 발견 범위에서 해결. CleanupUnknown이 NeedsCheck를 통해 stop_run으로 보고되고 심판 잠금은 needs_check에 남는다. 공식 회귀와 호환 연결 재현 통과. PermissionError의 CleanupUnknown 변환·원인 보존도 공식 시험 통과. |
| U3 모델 메타데이터/legacy 격리 | 기존 발견 범위에서 해결. clean_meta가 중첩 형태를 걸러내고 legacy 경로 값을 검사한다. 기존 모델 재현에서 전체 예외가 사라졌고 잘못된 legacy만 제외했다. 모든 임의 입력을 전수 확인한 것은 아니다. |
| U4 쓰기 격리 | 기존 발견 범위에서 해결. 부모가 실행별 설정·캐시·임시 경로를 전달하고 외부 연동 변수를 제거한다. 자식은 실행 전용 설정에서 연동을 끈다. 두 실행의 같은 설정 파일 사용이라는 기존 경로 반례는 호환 재현에서 사라졌다. 실제 전체 라이브러리의 모든 파일 쓰기는 미검증이다. |
| U5 좀비 처리 | 기존 발견 범위에서 해결. ProcTree.alive가 Z 상태를 제외하고 자기 자식이 된 추적 좀비만 reap한다. 공식 회귀 통과. 추적 전에 입양된 프로세스 누락은 F1로 구분했다. |

## 새 발견

### F1 — poll 사이에 부모가 종료하면 subreaper에 입양된 손자를 추적하지 못한다

| 칸 | 내용 |
| --- | --- |
| 번호 | F1 (요청서 확인 전 임시 번호) |
| 심각도 | 높음 |
| 관련 항목 | b26 U1, 학습 하위 프로세스 전체 종료, 새 발견 |
| 위치 | `drive/scripts/h_run.py:190` ProcTree.scan, `:196` 추적 뿌리 계산, `:201` 부모 사슬 확장, `:207` alive; RealTrainer.train의 poll·scan·정리 연결 |
| 무엇이 문제인가 | scan은 이미 known에 있는 프로세스와 그 현재 자식만 확장한다. 손자를 아직 관측하지 못한 채 리더가 종료하면 손자의 부모는 subreaper인 실행기로 바뀌는데, 실행기는 추적 뿌리가 아니다. 따라서 입양된 손자가 실제로 보이더라도 known에 추가되지 않고, alive와 종료 대상에서도 빠진다. subreaper를 켠 것만으로 입양 프로세스를 자동 추적하지는 않는다. |
| 일어나는 조건 | `b27_orphan_probe.py`: 첫 poll에는 리더만 있고, 다음 poll 전 리더가 새 세션 손자를 만든 뒤 종료 코드 3으로 끝나게 했다. RealTrainer는 RuntimeError로 돌아왔으나 손자가 살아 있었다. 로그의 grandchild_ppid와 executor_pid가 같아 실제로 실행기에 입양됐음을 확인했다. 재현이 만든 손자는 finally에서 직접 KILL·waitpid로 정리했다. |
| 확신 | 확인함 — 실제 RealTrainer·Popen·새 세션·subreaper·/proc 관측으로 재현. 실제 GPU/DDP 실행은 아님. |
| 제안 | 실행별로 입양된 자식까지 식별·추적할 수 있는 소유 경계를 둔다. 예를 들어 학습만 소유하는 별도 supervisor/subreaper나 cgroup을 고려할 수 있다. 현재 실행기의 모든 자식을 무조건 포함하면 다른 subprocess까지 끝낼 수 있으므로, 단순히 실행기 PID 전체를 뿌리에 추가하는 수정은 피해야 한다. 사슬이 poll 사이에 사라지는 회귀를 추가한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 끝났다고 판단한 학습의 하위 프로세스가 계속 자원을 사용하며, 정리 확인 필요로도 보고되지 않을 수 있다. |

재현 출력:

```json
{"exception":"RuntimeError","grandchild_live":true,"adopted_by_executor":true}
```

스크립트는 production의 sleep 자체를 구현 변경하지 않고, 주입 가능한 sleep 함수로 poll 사이 순서를 재현했다. 실제 기본 poll 간격은 10초여서 자식 생성·부모 종료가 모두 한 간격 안에 일어나는 경우를 배제할 수 없다. 이 반례는 알려진 자식을 새 세션에서도 추적하는 정상 시험과 다르다. `_stat`·목록 읽기 자체의 실패를 주입한 사례는 아니다.

## 점검했지만 문제가 없던 항목

- 이전 좁은 범위 시험 네 명령, 총 286개 통과.
- 알려진 부모가 유지되는 동안 새 세션 작업자를 추적하고 TERM/KILL하는 공식 경로.
- CleanupUnknown → NeedsCheck → stop_run → needs_check 연결과 다음 학습 차단 회귀.
- 종료 신호 권한 오류의 확인 필요 변환·원래 예외 원인 보존 회귀.
- 기존 metrics/args 목록 반례와 legacy 경로 목록 반례의 모델별 격리.
- 기존 공용 설정 경로 반례의 해소, 실행별 환경 경로와 연동 변수 제거·자식의 경로 검사.
- 추적 중인 좀비를 실행 중으로 세지 않는 공식 회귀.
- 코드·시험·AGENTS의 시작/종료 해시 일치.

## 시간이 모자라 보지 못한 항목·확인할 수 없었던 항목

- **0z2 검토 요청서 자체와 그 문서에만 있는 검토 범위·질문·필수 시험·발견 번호 규칙.** 파일 확인 후 이 보고서를 완성해야 한다.
- 실제 GPU 둘의 torchrun·Kaggle/Colab subreaper·컨테이너 PID 정책, 배포 이미지 버전과 전체 파일 쓰기 추적.
- /proc 읽기 실패·PID 재사용·subreaper 설정 실패·다른 subprocess와 공존하는 모든 경합 조합.
- 실제 Ultralytics 자동 연동·외부 추적 서비스. 모델·서비스를 실행하지 않았다.
- 임의 모델 메타데이터·legacy 경로·Drive 실패의 전체 조합.
- 2c 셀·최종 노트북 일치, v4.32 전체 회귀는 선행 검토 범위 밖이다.
