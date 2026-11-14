# v4.32.0 검토 요청 — 2차-1: F3·F14 공유 파일 단일 작성자

v4.31.8 검토의 F3·F14(여러 작업자가 같은 공유 파일을 덮어씀)를 고쳤습니다. 규칙은 `AGENTS.md` 3장 9번에 있습니다. 결과는 `REVIEW_RESULT.md`에 써 주세요. 새 발견은 S1부터 번호를 붙입니다.

## 설계

| 공유 파일 | 쓰는 곳 | 방법 |
|---|---|---|
| 상태 파일 (`web/state.json`·`relabel/state.json`·`relabel/tracked.json`·`web/label_stats.json`·`web/corrections.json`) | 취합자만 | `jobs/STATE_OWNER.json` 임대. `wb.lease_should_take`: 순위 CPU 마스터 3 > 30번 셀 2, GPU 0은 맡지 않음. 180초 넘게 갱신 없거나 내려놓으면 이어받음. 맡은 직후 다시 읽어 확인. 60초마다 갱신. 취합자가 아니면 `jobs/DIRTY_<세션>.json` 표시만 남기고, 취합자는 표시(DIRTY·DONE)를 보고 새로 만듦. 숨기기·다시 보이기·새로 고침은 취합자만, 배정과 관계없이. 28번 셀은 다른 취합자가 살아 있으면 상태 파일·settle을 하지 않음 |
| 요청 (`requests/`·`relabel/requests/`) | 받은 세션만 | 받기: 쓰고 → `W_CLAIM_CONFIRM_SEC`(2초) 뒤 다시 읽어 이 세션 것인지 확인, 아니면 물러남 (마스터 `claim`, 30번 `_rl_claim`·`_lc_claim`). 쓰기 직전: Drive의 요청이 아직 이 세션 것인지 `wb.request_owned`로 확인 (마스터 `push_req`, 30번 `_rl_status`). '받는 중'은 `wb.may_adopt`(받은 세션이 살아 있지 않음)일 때만 넘겨받고 `taken_session`·`adopted_from`을 기록. `wb.finish(session=)`는 이 세션이 받은 요청만 끝냄 |
| TASK 기록 (`relabel/tasks/<id>.json`) | 누구든, 한 길로 | `rb.sync_record(base, tid, mutate, fetch, put)` — 마스터 `sync_task_record`와 Kaggle 30번 셀(`rb.use_remote`)이 같이 씀. `rb.add_history`·`set_pending_track`이 이 길을 탐. 실패하면 `_REMOTE['queue']`에 남기고 `flush_remote`가 TASK별 순서대로 다시. 같은 이력은 두 번 적지 않음. 30번 셀의 `relabel/**`·`relabel/tasks/<id>.json` 올리기 삭제 |
| 파생 파일 (`backup_status.csv`·작업보드) | 백업을 실행한 작업자 | 세션별 백업 색인(`logs/shards/backup_index`)에서 다시 만들어지므로 단일 작성자로 묶지 않음 (설계표에서 바꿈) |

## 시험
- `tests/test_fix_4320.py`: 임대 판정 8가지, 요청 소유 6가지, 살아 있는 세션·넘겨받기, `finish(session=)`, TASK 기록 줄·순서·중복, 마스터 받기 확인 3가지·올리기 거절, 마스터 임대 맡기·양보·넘겨받기·내려놓기, 30번·28번 셀 정적 확인, GPU 셀 일치.
- `test_worker_gpu`: GPU 워커가 임대를 맡지 않고 state·tracked를 쓰지 않음.
- `test_master`: 숨기기는 취합자(마스터)가 30번 셀이 살아 있어도 받음 · 버리기는 30번 셀이 살아 있으면 받지 않음.

## 특히 봐 주세요
- 상태 파일·요청·TASK 기록을 이 규칙 밖에서 쓰는 경로가 남았는지. Colab은 Drive에 바로 쓰고, Kaggle은 `drive_sync_now`·`drive_push`로 올립니다. LC 셀(5·9·10·13·14·15·29·32번)을 작업자가 실행할 때 끝에 올라가는 파일들도 포함해 봐 주세요.
- 취합자가 바뀌는 순간(마스터가 켜지거나 꺼질 때) 상태 파일이 뒤로 가거나 숨김 표시가 사라지는 경로가 있는지.
- `_lc_waiting`(받는 중 백업·export 받기)과 그 안의 `settle`은 취합자로 묶지 않았습니다. 받은 결과로 같은 판정을 하므로 두 곳이 해도 결과가 같다고 봤습니다. 이 판단이 맞는지 봐 주세요.
- 남은 틈(다시 읽기와 쓰기 사이 몇 초)은 알려진 한계입니다. 이것 말고 다른 경로를 봐 주세요.
- 2차-2 대상(F2·F6·F7·F8·F9)은 이번 범위가 아닙니다.
