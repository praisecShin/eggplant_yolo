# v4.33.0z1 검토 결과 — b26

검토일: 2026-11-17. `AGENTS.md`, `REVIEW_REQUEST_v4.33.0z1.md`, b25 결과, 구현 설명의 b25 반영 절과 관련 구현·시험을 확인했다. 요청한 좁은 범위인 **학습 프로세스 정리·모델별 오류 격리·학습 자식의 쓰기 격리**만 검토했다.

**b25 F1·F2는 모두 부분 해결이다.** 원래 두 재현과 지정 시험은 통과하지만, 추가 경계에서 **높음 2건(U1·U2)·보통 3건(U3~U5)**을 확인했다. 2c 전 필수는 DDP 종료 범위 U1, 종료 불확실성 보고 U2, 11/17 결정에 따른 쓰기 격리 U4다.

코드·노트북·시험·설계서는 수정하지 않았다. 이 보고서와 `rLog/b26_*`만 작성했다. 실제 CVAT·Google Drive·Kaggle·Colab·GPU 학습·외부 자동 연동에는 접속하지 않았다. 공개 소스 확인을 위해 공식 GitHub 소스만 열었으며, 로컬 재현은 임시 파일·직접 만든 시험 프로세스만 사용했다.

## 시험과 자료

| 실행 | 결과 | 로그 |
| --- | --- | --- |
| `python tests/test_hosts_433.py drive` | 44개 성공 | `rLog/b26_hosts.log` |
| `python tests/test_handlers_433.py drive` | 140개 성공 | `rLog/b26_handlers.log` |
| `python tests/test_e2e_433.py drive` | 17개 성공 | `rLog/b26_e2e.log` |
| `python tests/test_master_433.py drive` | 75개 성공 | `rLog/b26_master.log` |
| `python rLog/b25_process_probe.py` | 원본 그대로 재실행, 종료 코드 0. 권한 상실·리더 먼저 실패 모두 살아 있는 손자 없음 | `rLog/b26_process_probe.log` |
| `python rLog/b25_model_probe.py` | 원본 그대로 재실행, 종료 코드 0. []·null·빈 best 항목 모두 제외하고 good 모델 반환 | `rLog/b26_model_probe.log` |

지정 시험 **276개 모두 성공**, 네 시험의 마지막 출력은 `RESULT True`다. 실행 명령·환경은 `b26_run_tests.py`, 종료 코드·시간은 `b26_test_status.json`에 있다. Python 3.14.4 및 기존 `/tmp/b24_venv`를 사용하고 `PYTHONDONTWRITEBYTECODE=1`로 실행했다. 새 패키지는 설치하지 않았다.

추가 재현은 저장소 루트에서 다음과 같이 실행한다. 동일 이름의 `.log`에 결과를 보관했다.

```bash
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_process_boundaries.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_cleanup_flow.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_permission_override.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_model_boundaries.py
PYTHONDONTWRITEBYTECODE=1 /tmp/b24_venv/bin/python rLog/b26_write_isolation.py
```

- `process_boundaries`: 새 세션으로 나간 손자, 좀비만 남은 그룹, 신호 권한 오류. 좀비 사례는 시험 프로세스를 일시적으로 subreaper로 삼고 회수 시점을 제어했다. 생성한 살아 있는 하위 프로세스는 직접 종료하고 회수 가능한 자식은 회수했다.
- `cleanup_flow`: 실제 `RealTrainer → h_run → Executor → MasterLoop`를 연결한다. 학습 자식은 가짜이며 종료 확인 실패를 주입해 보고·잠금 상태를 확인한다.
- `permission_override`: 실제 RealTrainer에서 원래 AuthorityLost가 정리의 PermissionError로 대체되는지 확인한다. 권한 오류만 모형으로 주입하고 시험 자식은 직접 정리했다.
- `model_boundaries`: 실제 adopted_models·model_rows·WebState._models에 잘못된 메타데이터/legacy 경로를 넣는다.
- `write_isolation`: 실제 RealTrainer·train_child를 실행하되 YOLO는 가짜다. 이전 검토에서 내려받은 Ultralytics 8.4.215의 **실제 경로 결정 함수와 JSON 저장 클래스**만 AST로 추출해 실행한다. 전체 라이브러리나 모델을 실행한 시험은 아니다. 기본 소스 위치는 `/tmp/b24_sources/unpacked/ultralytics/utils/__init__.py`이며, 다른 위치는 스크립트 첫 인자로 줄 수 있다.

공개 소스 URL·확인 버전·로컬 소스 SHA256은 `b26_source_refs.json`에 있다. 시작 시 기록한 코드·시험·AGENTS 해시는 `b26_initial_hashes.json`에 있으며 종료 전 대조에서 변경은 0개였다. 추가 재현 결과 묶음은 `b26_additional_summary.json`에 있다. 추가 재현은 결함 조건을 출력하는 진단 도구이므로 종료 코드 0을 ‘결함 없음’으로 해석하면 안 된다.

## F1·F2 판정

| 항목 | 판정 | 근거 |
| --- | --- | --- |
| F1 학습 묶음 정리 | **부분 해결** | finally에서 항상 정리하며 같은 PGID 안에 있는 TERM 무시 손자를 정상 끝·먼저 실패·권한 상실 모두 정리한다. 원래 b25 재현도 해결됐다. 그러나 DDP 작업자가 별도 세션인 경우 관측 범위 밖이다(U1). 정리 불확실성도 심판의 확인 필요로 연결되지 않는다(U2). 좀비만 남아도 수동 확인 실패가 난다(U5). |
| F2 모델 목록 오류 격리 | **부분 해결** | 원래 []·null·빈 가중치·확인 안 된 목록을 모델 단위로 제외하고 skipped에 이유를 남긴다. relabel의 models_skipped 연결도 있다. 하지만 train.json의 중첩 값과 legacy paths의 값은 검증하지 않아 전체 계산이 실패할 수 있다(U3). |

## 새 발견

### U1 — DDP 작업자가 새 세션으로 나가면 원래 PGID 정리로 종료를 확인할 수 없다

| 칸 | 내용 |
| --- | --- |
| 번호 | U1 |
| 심각도 | 높음 |
| 관련 항목 | F1, 검토 질문 2, 11/17 DDP 포함 전체 종료 결정 |
| 위치 | `drive/scripts/h_run.py:172` Popen, `:209` _group_alive, `:221` 정리 대상 PGID; `drive/scripts/train_child.py:22` Ultralytics 학습 호출 |
| 무엇이 문제인가 | 종료·잔존 확인이 최초 train_child의 PGID 하나에 한정돼 있다. 하위 프로세스가 새 세션을 만들면 원래 그룹이 비어도 작업자가 살아 있을 수 있다. 이는 임의의 외부 프로그램만의 문제가 아니라 공개 PyTorch DDP 실행 경로에도 있는 동작이다. |
| 일어나는 조건 | `b26_process_boundaries.log`의 setsid 사례에서 손자를 start_new_session=True로 만들고 권한을 잃게 했다. RealTrainer는 AuthorityLost로 돌아왔고 원래 leader_group_alive=false였으나 detached_live=true였다. 시험은 남은 새 그룹을 직접 KILL로 정리했다. |
| 확신 | 확인함 — 실제 세션·프로세스 그룹·RealTrainer를 사용한 로컬 재현 및 공개 소스 추적. 실제 GPU에서 특정 DDP 중단 순서를 실행한 것은 아님. |
| 제안 | 처음부터 새 세션까지 포함하는 실행 단위(cgroup 등)로 관리하거나, DDP 작업자의 PID/PGID를 따로 추적하고 종료 확인에 포함한다. torchrun의 정상 종료 전파에 기대는 경로와 부모가 강제 종료하는 경로를 구분한다. 지원 환경에서 이를 보장하기 어렵다면 다중 GPU를 명시적으로 제한한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** DDP 자식까지 모두 끝냈다는 보장이 성립하지 않는다. |

공개 Ultralytics는 `torch.distributed.run`을 사용한다. PyTorch 2.5.1·2.9.0의 POSIX `SubprocessHandler`는 작업자를 새 세션으로 띄운다. 따라서 작업자가 최초 그룹에 남는다는 전제는 틀리다. [Ultralytics DDP 실행 코드](https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/utils/dist.py), [PyTorch 2.5.1 작업자 실행](https://raw.githubusercontent.com/pytorch/pytorch/v2.5.1/torch/distributed/elastic/multiprocessing/subprocess_handler/subprocess_handler.py), [PyTorch 2.9.0 작업자 실행](https://raw.githubusercontent.com/pytorch/pytorch/v2.9.0/torch/distributed/elastic/multiprocessing/subprocess_handler/subprocess_handler.py)

torchrun 자체는 신호를 받아 작업자 그룹을 정리하고 유예 뒤 KILL하는 절차가 있다. **따라서 모든 DDP 취소가 반드시 손자를 남긴다고 주장하지 않는다.** 다만 해당 launcher가 먼저 죽거나 강제 종료되면 부모는 별도 작업자의 종료를 확인하지 못한다. 부모의 기본 KILL_WAIT도 30초이고 PyTorch의 작업자 종료 유예 기본값도 30초여서, launcher의 정리가 끝나기 전 강제 종료되는 경계를 배제할 수 없다. 후자는 소스에서 도출한 위험이며 실제 GPU 시간 경합 재현은 하지 않았다. [PyTorch 종료·강제 종료 절차](https://raw.githubusercontent.com/pytorch/pytorch/v2.9.0/torch/distributed/elastic/multiprocessing/api.py)

### U2 — ‘수동 확인 필요’ 정리 실패가 일반 실패로 확정돼 잠금이 끝난다

| 칸 | 내용 |
| --- | --- |
| 번호 | U2 |
| 심각도 | 높음 |
| 관련 항목 | F1, 검토 질문 2의 결과 보고·확인 필요 연결 |
| 위치 | `drive/scripts/h_run.py:196`·`:247` 정리 실패; `drive/scripts/executor.py:410` 일반 예외의 done_job 변환; `drive/scripts/arbiter.py:1456` 실행 잠금 마무리 |
| 무엇이 문제인가 | _kill의 ‘끝내지 못함 — 수동 확인 필요’는 일반 RuntimeError다. 실행기는 메시지를 보존하지 않고 done_job/failed:RuntimeError로 보고하며 심판은 잠금을 done으로 끝낸다. 하위 프로세스가 계속 있을 수 있다는 상태가 needs_check로 남지 않아 이후 학습을 막지 못한다. |
| 일어나는 조건 | `b26_cleanup_flow.py`는 실제 RealTrainer의 정리 단계에서 해당 RuntimeError를 주입하고 실제 처리기·실행기·심판으로 진행했다. 결과는 failed:RuntimeError, 학습 잠금 state=done, 요청 파일은 __failed.json이었다. stop_run이나 확인 필요 기록은 없었다. 모델이 채택되거나 성공 완료된 것은 아니지만 종료 불확실성을 일반 실패로 확정했다. |
| 확신 | 확인함 — 실제 제어 경로 연결 재현. 정리 실패 자체는 주입한 조건이다. |
| 제안 | 종료 확인 실패를 구분할 타입/결과를 두고 stop_run → needs_check로 보낸다. 원래 예외를 보존하더라도 정리 불확실성은 별도 상태로 보존해 사람이 확인할 때까지 같은 학습의 재시작을 막는다. ‘메시지에 수동 확인 필요’라고 쓰는 것만으로는 제어 상태가 바뀌지 않는다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 실패한 종료 확인을 안전하게 인계하는 경로가 필요하다. |

PermissionError 경계도 같은 문제에 닿는다. `_group_alive`의 신호 0 PermissionError는 true로 처리하므로 없는 그룹으로 오인하지는 않는다. 그러나 TERM/KILL의 PermissionError는 변환되지 않고 그대로 나온다. `b26_permission_override.log`는 원래 AuthorityLost 대신 PermissionError가 전달되고 context에만 AuthorityLost가 남는 것을 확인했다. finally가 RuntimeError만 잡으므로 ‘원래 예외 그대로 전달’ 약속도 이 경계에서는 지키지 못한다. 이 경우 실행기는 일반 실패 경로로 간다. 실제 소유권을 바꾼 시험은 아니며 신호 권한 오류만 모형으로 주입했다.

### U3 — train.json 하위 값과 legacy 경로 값의 오류가 정상 모델까지 막는다

| 칸 | 내용 |
| --- | --- |
| 번호 | U3 |
| 심각도 | 보통 |
| 관련 항목 | F2, 검토 질문 3 |
| 위치 | `drive/scripts/h_agg.py:228` paths 해석, `:238` meta 처리, `:246` model_rows; `drive/scripts/exec_host.py:288`~294 WebState._models |
| 무엇이 문제인가 | manifest의 파일 항목은 검사하지만, train.json을 최상위 dict로만 확인하고 metrics·args의 형태는 확인하지 않는다. legacy paths도 사전인지까지만 확인한다. 이 하위 값이 잘못되면 모델별 제외 대신 목록 전체가 예외로 끝난다. |
| 일어나는 조건 | `b26_model_boundaries.py`: 정상 good과 함께 train.json이 {metrics:[1]} 또는 {args:[1]}인 모델을 게시했다. model_rows가 AttributeError로 끝나 정상 good 행도 반환하지 못했고 skipped는 빈 목록이었다. 별도 legacy 사례에서 paths.results.csv를 목록 값으로 넣으면 adopted_models는 이를 통과시키고 WebState._models의 파일 받기가 TypeError로 끝났다. |
| 확신 | 확인함 — 실제 목록 함수·WebState._models와 임시 LocalStore 실행. |
| 제안 | 사용되는 메타데이터 하위 필드와 legacy 경로 값의 자료형을 모델 단위로 검사한다. 부가 메타데이터만 깨졌다면 그 필드를 비우고 경고할 수 있고, 경로가 잘못됐으면 해당 모델을 제외해야 한다. 각 모델의 읽기·변환 실패가 다음 정상 모델을 막지 않게 한다. |
| 2c로 넘어가기 전 필수 여부 | 필수 아님. **모델 선택·취합 예행 연습 전 보완 필요.** 원래 F2의 기본 반례는 해결됐지만 오류 격리 전체는 미완성이다. |

train.json이 []인 경우는 현재 빈 메타데이터로 바뀌므로 전체 실패가 나지 않았다. JSON 구문 오류/읽기 실패도 StoreError로 잡힌다. 모든 깨진 train.json이 문제인 것이 아니라 **객체 안에서 소비하는 하위 값이 잘못된 경우**가 반례다. 웹도 동일 adopted_models를 사용하지만 이후 파일 받기·시각 변환은 모델별 방어가 없어 격리가 자동으로 보장되지는 않는다.

### U4 — 학습 자식의 Ultralytics 설정·부수 쓰기가 실행별로 격리되지 않는다

| 칸 | 내용 |
| --- | --- |
| 번호 | U4 |
| 심각도 | 보통 |
| 관련 항목 | 검토 질문 4, 11/17 ‘학습 프로세스는 자기 작업 폴더에만 씀’ 결정 |
| 위치 | `drive/scripts/h_run.py:172` Popen의 환경 상속·cwd 지정; `drive/scripts/train_child.py:20` import와 `:22` 학습 호출 |
| 무엇이 문제인가 | cwd와 학습 산출물 project만 실행별로 지정하고 Ultralytics 설정·캐시·자동 연동 환경은 분리하지 않는다. 같은 호스트의 사람 작업자와 앱 자식은 동일 사용자 설정 파일을 사용할 수 있다. DDP 임시 코드도 라이브러리 설정 폴더를 사용하므로 ‘자기 작업 폴더에만 쓴다’는 설명이 성립하지 않는다. |
| 일어나는 조건 | `b26_write_isolation.py`는 실제 부모·train_child와 공개 라이브러리의 경로/JSON 저장 함수를 연결했다. 서로 다른 A/B 작업 폴더가 같은 settings.json 경로를 사용했고 두 작업 폴더 밖에 기록했다. 두 번째 저장 뒤 공유 설정 값은 B로 바뀌었다. 이 시험은 실제 모델 학습의 설정 변경을 재현한 것이 아니라, 현재 환경 상속으로 공용 파일 접근과 덮어쓰기가 가능한지를 제한된 라이브러리 함수로 확인한 것이다. |
| 확신 | 확인함 — 환경 격리 부재·공개 소스·경로/저장 함수 실행. 실제 모든 자동 연동의 부수 쓰기는 미실행. |
| 제안 | Ultralytics를 import하기 전에 자식 전용 설정·캐시 경로와 허용할 연동 정책을 정한다. 실행별 환경을 전달하고 자동 연동은 명시적으로 비활성화하거나 실행별 저장소로 제한한다. 사람 작업자의 설정을 공통 파일에서 바꾸는 방식으로 끄지 않는다. 라이브러리 버전을 고정하고 부수 쓰기 위치도 확인한다. |
| 2c로 넘어가기 전 필수 여부 | **필수.** 심각도와 별개로 이번에 명시한 11/17 쓰기 격리 결정의 미구현 부분이다. |

공개 소스는 `YOLO_CONFIG_DIR`, 없으면 Linux의 XDG/사용자 설정 경로를 선택하며 settings.json을 그 아래에 둔다. DDP 생성 파일은 USER_CONFIG_DIR/DDP를 사용한다. 이는 cwd만 바꿔서는 달라지지 않는다. [Ultralytics 설정 경로](https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/utils/__init__.py), [DDP 임시 파일 위치](https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/utils/dist.py)

검토한 8.4.215 소스에는 설정값에 따라 ClearML·Comet·DVC·MLflow 등 연동을 붙이는 경로도 있다. 설치된 연동 및 상속된 설정/추적 환경에 따라 작업 폴더 밖 기록이 생길 수 있다는 **소스 기반 추론**이며, 외부 서비스를 실제로 호출하지 않았다. 반면 이 저장소가 생성한 데이터셋은 실행별 폴더에 풀고 train/val 상대 경로를 사용하므로, 그 정상 경로의 labels.cache는 같은 실행의 데이터셋 폴더에 생긴다. 데이터셋 캐시 자체가 항상 공용 위치에 생긴다고 보지는 않았다.

### U5 — 좀비만 남은 그룹도 실행 중으로 판단해 정리 실패를 낸다

| 칸 | 내용 |
| --- | --- |
| 번호 | U5 |
| 심각도 | 보통 |
| 관련 항목 | F1, 검토 질문 2의 좀비 경계 |
| 위치 | `drive/scripts/h_run.py:209` _group_alive, `:239` 종료 재확인, `:246` 수동 확인 실패 |
| 무엇이 문제인가 | killpg(pgid, 0)은 그룹 존재를 확인하며 실행 가능한 프로세스인지 구분하지 않는다. 리더를 poll/wait로 회수해도 다른 부모에게 속한 손자 좀비까지 회수하지 못한다. 실제 살아 있는 작업자가 없는데도 유예 후 KILL과 수동 확인 실패로 갈 수 있다. |
| 일어나는 조건 | `b26_process_boundaries.py`의 zombie_only: 시험 reaper가 손자를 회수하기 전, 리더는 이미 wait로 회수했고 그룹에는 Z 상태 손자만 남겼다. _group_alive=true이고 _kill은 약 10.2초 뒤 RuntimeError를 냈다(KILL_WAIT만 0.1초로 단축). 시험이 waitpid로 좀비를 회수한 뒤 종료했다. 기본 설정에서는 추가 대기가 더 길다. |
| 확신 | 확인함 — 실제 POSIX 프로세스·좀비·그룹 신호로 재현. |
| 제안 | ‘살아 있는 작업’과 ‘종료 후 회수 대기’를 구분한다. 지원 Linux 환경의 하위 프로세스 회수/관측 방법을 정하고, 자기 자식이 아닌 좀비가 정리 성공 판정을 영구적으로 막지 않게 한다. |
| 2c로 넘어가기 전 필수 여부 | 필수 아님. **컨테이너·Kaggle 실행 호스트 예행 연습 전 보완 필요.** 정상 완료를 실패로 바꿀 수 있는 경계다. |

## 검토 질문별 답

1. **F1·F2:** 모두 부분 해결. b25 원본 두 개를 수정 없이 다시 실행했고 원래 반례는 해결됐다. 추가 반례는 위 U1~U5에 구분했다.
2. **묶음 관측:** 좀비는 존재로 보지만 실행 중 여부를 구분하지 못한다(U5). 새 세션 작업자는 원래 그룹에서 보이지 않으며 실제 PyTorch 실행 경로가 해당한다(U1). 신호 0의 PermissionError는 보수적으로 존재로 보지만 종료 신호의 권한 오류 처리와 원래 예외 보존은 부족하다(U2). 수동 확인 정리 실패도 needs_check로 연결되지 않는다(U2).
3. **모델 오류 격리:** manifest 기본 형태와 파일 항목은 보완됐다. train.json의 읽기 실패·최상위 비객체는 빈 메타데이터로 넘긴다. 중첩 metrics/args·legacy 경로 값은 정상 모델에 영향을 줄 수 있고 웹도 그 영향을 받는다(U3). models_skipped는 기본 manifest 제외에는 연결되지만, 이후 변환에서 예외가 나면 새 상태를 게시하지 못한다.
4. **자식 쓰기 격리:** 산출물과 정상 데이터셋 캐시는 실행별 경로에 있지만 설정·DDP 임시 자료·자동 연동의 쓰기 경로는 보장되지 않는다(U4). 같은 호스트에서의 사람 작업자/앱 프로세스 공존을 확인해야 한다. 서로 다른 Kaggle 머신끼리 로컬 설정 파일을 공유한다고 주장하는 것은 아니다.

## 점검했지만 문제가 없던 항목

- 지정 시험 276개와 b25 원본 재현 두 개 모두 통과.
- 원래 F1의 같은 PGID 내 TERM 무시 손자를 정상·실패·권한 상실의 세 경로에서 종료한다.
- finally에서 정상·실패·기존 예외 모두 정리를 호출하며, 정리 함수가 RuntimeError를 낼 때 기존 예외를 유지하려는 경로가 있다. PermissionError 예외는 U2로 구분했다.
- 원래 F2의 []·null·빈 가중치·verified 문자열 입력은 해당 모델만 제외하고 정상 모델을 유지한다.
- 기본 제외 사유를 skipped와 relabel models_skipped에 전달하는 연결.
- 메타데이터 최상위 비객체/읽기 실패의 빈 객체 대체, 정상 모델 버전의 기본 목록 계산.
- 이번 범위에서 CVAT 라벨 쓰기·TASK 삭제·원본 영상 삭제 경로를 새로 추가한 것은 없다.

## 시간이 모자라 보지 못한 항목·환경상 확인하지 못한 항목

- 실제 Kaggle GPU 둘의 학습·torchrun 장애·프로세스 트리·PID 1 회수 정책. 공개 PyTorch 2.5.1/2.9.0과 Ultralytics 소스를 확인했으나 배포 이미지의 실제 버전은 고정돼 있지 않다.
- 실제 권한이 다른 프로세스/컨테이너에 대한 종료. PermissionError는 신호 함수에만 주입했다.
- 실제 Ultralytics 전체 import/학습의 파일 쓰기 추적과 모든 자동 연동. 경로/JSON 저장 함수만 제한 실행했고 캐시·연동은 소스로 추적했다.
- 모델 경로·메타데이터의 모든 임의 입력, 실시간 Drive 변경·중복 파일·네트워크 실패의 전 조합.
- 실제 CVAT·Drive·Colab·외부 추적 서비스. 접속 금지와 메시지 전송 제한을 지켰다.
- 2c 사람용 셀·최종 노트북 일치, 기타 0z 변경 및 v4.32 전체 회귀는 이번 좁은 요청 범위 밖이다.
