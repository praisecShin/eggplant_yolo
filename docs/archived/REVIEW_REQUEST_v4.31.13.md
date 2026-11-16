# v4.31.13 재검토 요청 — v4.31.12 재검토(R14~R16) 수정 확인

결과는 `REVIEW_RESULT.md`에 써 주세요. 형식은 지난번과 같습니다. 새 발견은 R17부터 번호를 붙입니다.

| 번호 | 지적 | 고친 곳 | 시험 |
|---|---|---|---|
| R14 | TASK 기록 받기 실패를 무시하고 빈 기록으로 덮음 | 마스터 `sync_task_record(tid, mutate)`: lsf로 있는지 확인(목록 실패는 '없음'이 아님 · 폴더 자체가 없을 때만 없음) → 있으면 받아 JSON 확인 → mutate → 그 파일만 올림. 어느 단계든 실패하면 False이고 Drive는 그대로. `poll_waiting_backups`는 False면 요청을 끝내지 않고 다음 확인 때 다시. `_history_once`로 같은 이력이 두 번 적히지 않게 함 | test_fix_43113 (받기·목록·깨진 JSON·올리기 실패, 정상, 새 기록, poll 재시도) |
| R15 | 상태 갱신의 relabel 전체 복사에 tasks 포함 | `aggregate_and_sync_state`: 올릴 때 `tasks/**` 제외. `update_tracked`의 '사라짐' 이력은 모아서 `sync_task_record`로 씀. 못 쓰면 `gone_at`을 지워 다음 갱신 때 다시. `handle_aa`: discard는 `sync_task_record`로, 폴더 통째 올리기 두 곳 삭제 | test_fix_43113 (갱신 중 바뀐 TASK 보존 · 사라짐 이력 이어 쓰기·재시도 · discard) |
| R16 | GPU 기동 시험이 앞선 호출 기록을 합산 | 시작 때 `kaggle_calls.log` 삭제 | test_master_gpu 두 번 연속 실행 |
| 시험 시간 | `START_TS`가 import 때 정해짐 · 가짜 동료 heartbeat가 갱신되지 않음 · 실패해도 종료 0 | `main`이 준비 뒤 `START_TS`를 다시 잡음. test_master의 가짜 동료가 15초마다 heartbeat 갱신. 마스터 시험 세 개가 실패하면 종료 1 | — |

## 특히 봐 주세요
- 마스터에 `relabel/tasks`를 쓰는 다른 경로가 남았는지. 지금은 `sync_task_record` 안의 올리기 하나뿐이어야 합니다 (받기 방향 복사는 남아 있음).
- `sync_task_record`의 받기와 올리기 사이 틈, 요청 비교와 쓰기 사이 틈은 2차 F3·F14 대상으로 남겼습니다.
- 30번 셀(Colab·GPU 워커)의 TASK 기록 올리기(`_rl_push`)는 이번에 바꾸지 않았습니다. 2차 F3·F14 대상입니다.
