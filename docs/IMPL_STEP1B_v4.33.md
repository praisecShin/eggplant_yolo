# v4.33 구현 1b — 저장소 어댑터·마스터 판정 루프·실행기 뼈대·Keeper (v4.33.0d)

1a의 판정 함수(`arbiter.py`)·실행 권한(`access.py`)에 **실제 입출력을 붙이는 층**입니다. 새 파일만 더했고, 기존 v4.32.0 파일(노트북·마스터·`Code.gs`)은 고치지 않았습니다. 그래서 **아직 운영에 연결되지 않았습니다** — 노트북·셀·앱에 연결하는 일은 2단계입니다.

| 파일 | 내용 |
| --- | --- |
| `drive/scripts/arb_io.py` | 저장소 어댑터. `LocalStore`(폴더), `RcloneStore`(rclone 원격, 명령마다 timeout), `snapshot()`(읽기: 못 읽은 것은 '모름'으로), `apply_writes()`(차례대로 쓰고 실패하면 멈춤) |
| `drive/scripts/arb_master.py` | 마스터 판정 루프 `MasterLoop`: 읽기 → `arbiter.decide_round` → 쓰기. 자격 신청, 생존 신호(`workers/<세션>__<지문>.json`), 설정(사람 목록·계정 지도) 10분마다 다시 읽기 |
| `drive/scripts/executor.py` | 실행기 쪽 규칙 `Executor`: 배정 확인(세션 지문), 완전한 식별 묶음으로 보고, 다시 발급 뒤 새 gen으로 다시 보고, 단계별 권한 확인(`Authority`), 단계 기록, 취소·멈춤 표시, 요청 최종 상태 쓰기. 실제 일은 `Handlers`에 넣음 |
| `drive/scripts/worker_cpu.py` | CPU 작업 프로세스 진입점. 종류별 처리기 등록 틀(`register`). 처리기가 없으면 '실패'로 보고 |
| `apps_script/Keeper.gs` | G 계정 Apps Script: 심판 자격, 깨우기(정지 보류 판정 하나, 2차 권한 확인, 중간 장애 뒤 이어 하기), Kaggle로 마스터 노트북 올리기(해시 확인), 감시 메일, 자기 생존 신호 |
| `tests/test_master_433.py` | 폴더 저장소에서 마스터 + 실행기를 끝까지 돌리는 시험 38개 |
| `tests/test_keeper.js` | Keeper 판정·가짜 Drive 시험 40개 |

```bash
python3 tests/test_master_433.py drive
node tests/test_keeper.js apps_script/Keeper.gs
```

## 설계와의 대응

| 설계 절 | 구현 |
| --- | --- |
| 심판 한 회 2·3단계 (입력 읽기·'모름') | `arb_io.snapshot`: 목록 실패 → 종류 이름(`grant`·`requests`·`workers`·`signals`·`state`·`artifacts`), 파일 읽기 실패 → `file:<경로>`. 폴더가 아직 없는 것은 빈 목록 |
| `arb/` 목록을 못 읽음 | `arbiter`: 회차 기록도 쓰지 않음 (옛 기록·처리한 보고 목록을 덮지 않게). 버전 파일 목록을 못 읽으면 보고·신호를 반영하지 않음 |
| 판정 루프는 CVAT를 부르지 않음, 쓰기 실패 | `MasterLoop.run_once`: 판정 함수는 순수 함수, 쓰기는 차례대로·실패 지점에서 멈춤 → 다음 회차가 이어 감 |
| 실행기 규칙 1~9단계 | `Executor._step_tasks`: prepare → 확정 신청 → 승인 확인 → commit(핸들러가 `ctx.auth('recovery_publish')`·`ctx.auth('cvat_write')`로 감싸 호출) → 끝 보고 → 반납 |
| 권한 확인 (M1·H1) | `Executor._task_auth` → `arbiter.executor_may_follow(phase, job)`, 실행형 일은 `arbiter.run_may_follow` |
| 권한 잃음·확정 중 오류 | `AuthorityLost` → 복원하지 않고 멈춤 보고. 그 밖의 예외가 commit 밖으로 나오면 멈춤 보고 → '확인 필요' |
| 받는 중 일 | `_step_read`: fetch(준비 확인) → 게시 잠금 신청 → publish → 결과 |
| 실행형 일 | `_step_run`: run → `done_run`(산출물) / `done_job` |
| 요청 최종 상태 | `_finalize`: 모든 TASK 결과가 있으면 요청 파일 이름을 완료·실패·취소됨으로 |
| Keeper | `keeperDecide_`(입출력 없는 판정) + `keeper_`(Drive·Kaggle·메일) |

## 시험으로 확인한 것 (끝까지)

- 요청 → 배정 → 확정 승인 → CVAT 쓰기(가짜) → 결과 → 요청 완료, 단계 기록·세션 지문
- 승인 전에 CVAT에 쓰려는 처리기 → 권한 확인이 막고 '실패' 보고
- 마스터 쓰기가 중간에 실패 → 다음 회차가 이어 감 / 마스터 교체(새 epoch) → 실행기가 새 gen으로 다시 보고, CVAT 쓰기는 한 번씩
- 파일·목록을 못 읽음 → '모름', 읽히면 이어 감
- 취소(준비 단계는 멈춤), 정지·해제(반납 뒤 다시 배정)
- 확정 중 실행기가 오래 멈춤 → 격리, 깨어난 실행기는 올리기도 복원도 하지 않음
- 백업(받는 중 → 게시 잠금 → 게시), 관리 일(채택)·FORCE_NEW·실패
- rclone 목록에서 소유 계정·시각 읽기, 실패·시간 초과 → '모름'
- Keeper: 자격(회차가 멈춘 심판 교체, 갓 자격 받은 마스터 기다림), 주간 상시·밤 규칙, 정지 보류 판정, 깨우기 신호 거절 사유 9가지, '보류 해제하고 깨우기', 중간 장애 뒤 한 번 재시도, 노트북 해시 불일치, 키가 Drive·메일에 남지 않음

## 아직 하지 않은 것 (2단계)

- Kaggle 마스터 노트북·30번 셀·GPU 작업자에 `MasterLoop`·`Executor` 연결, 기존 처리 코드(track·shape·백업·export·취합·학습)를 `Handlers`로 옮기기
- 실제 CVAT 호출 timeout(`CVAT_CALL_MAX`)·서버 작업 조회·Kaggle 커널 상태 조회(`Probes`)
- 정기 점검의 '멈춘 것 같음', Colab에서 Drive 소유 계정 읽기
- 수집기 `Code.gs`에서 배정·깨우기 빼기, LC·AA·CTRL앱, ULD앱
- **실제 시험이 필요한 것:** `RcloneStore`의 rclone 필터·메타데이터(`owner`·`btime`)가 실제 Drive에서 기대대로 나오는지, `Keeper.gs`의 Kaggle 올리기 API, Apps Script에서 파일 소유 계정·만든 시각 읽기
