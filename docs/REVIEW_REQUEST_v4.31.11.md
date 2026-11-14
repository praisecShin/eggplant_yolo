# v4.31.11 재검토 요청 — v4.31.10 재검토(R6~R10) 수정 확인

결과는 `REVIEW_RESULT.md`에 써 주세요. 형식은 지난번과 같습니다. 새 발견은 R11부터 번호를 붙입니다.

| 번호 | 지적 | 고친 곳 | 시험 |
|---|---|---|---|
| R6 | GPU 워커가 살아 있어도 CPU가 같은 waiting 요청을 처리 · 처음 읽은 사본으로 덮어씀 | 마스터: `send_heartbeat_once`가 `relabel/WORKER_gpu.json`도 읽어 `aa_gpu_peer`에 둠. `aa_worker_alive()`가 둘 중 하나라도 살아 있으면 poll 안 함. 결과를 쓰기 직전에 생존 신호를 다시 읽고, `_same_waiting`으로 Drive 요청을 다시 받아 파일 이름 하나·status·remaining·results·result·taken_session·history(세대)가 처음과 같을 때만 씀 | test_fix_43111 (GPU 생존 · 받는 사이 다른 작업자가 failed로 바꿈) |
| R7 | 최종 상태를 이번 회차 lost만으로 정함 | `wb.failed_results(results)` (실패·포기로 시작하는 상태). 마스터 poll과 30번 `_rl_bk_poll`이 누적 결과로 done/failed를 정함. '모두 받음'은 실패가 없을 때만 | test_fix_43111 |
| R8 | Kaggle에서 CVAT_TOKEN 비밀이 없어도 환경 값으로 계속 | Kaggle이면 환경 값을 지우고 `RuntimeError` | test_fix_43111 |
| R9 | 실패·기한 초과만 남은 waiting track을 아무도 끝내지 않음 | `gpu_pending`이 판정에서 받음뿐 아니라 실패, 또는 `MASTER_TRACK_GIVEUP_H`(6시간, 30번 셀 `RL_BACKUP_GIVEUP_H`와 같음)가 지난 준비 중도 GPU 시작 이유로 셈. 깨어난 GPU 워커의 `_rl_bk_poll`이 이미 실패·기한 초과를 `gave_up`으로 넘겨 `_rl_track_resume`이 마무리함 | test_fix_43111 (실패만 · 기한 안 · 기한 초과) |
| R10 | 빈 `last_file`의 '최신'을 받음으로 인정 | `backup_verdict`: 경로가 있고 `is_file()`이어야 받음. test_fix_43110·4319 표본을 바꿈 | test_fix_43111, test_fix_43110 |

## 특히 봐 주세요
- **R6:** `_same_waiting`과 쓰기 사이에 짧은 틈이 남습니다. Drive에는 원자적 비교-교체가 없기 때문입니다. 이 틈은 2차 F3·F14(요청 파일은 한 작업자만 씀)에서 없애려 합니다. 이번 판에서 그 틈 말고 다른 경로가 남았는지 봐 주세요.
- **R9:** GPU 워커가 깨어난 뒤, 할 일이 없다고 보고 5분 안에 끝나 버리는 경로가 남았는지 봐 주세요. 30번 셀 유휴 판정은 `_RL['ready']`가 채워지면 일하는 중으로 봅니다.
