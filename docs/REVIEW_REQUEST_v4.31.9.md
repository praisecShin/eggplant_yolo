# v4.31.9 재검토 요청 — 1차 수정 확인

`docs/REVIEW_RESULT.md`(v4.31.8 점검, F1~F20)를 받고, 작성자가 판정한 뒤 **1차**로 아래를 고쳤습니다. `AGENTS.md`를 따르고, 코드는 고치지 말고 보고만 해 주세요.

## 부탁하는 것
1. **수정 확인:** 아래 표의 발견마다 고친 내용이 원래 문제를 해결하는지 판정해 주세요(해결 / 일부 / 안 됨).
2. **새 문제 확인:** 고친 코드 때문에 새로 생긴 문제나 약속 위반이 있는지 봐 주세요.
3. **2차 대상은 보지 않아도 됩니다:** F2, F3, F6, F7, F8, F9, F14는 아직 고치지 않았습니다(2차 예정). 다만 이번 수정이 그 문제를 더 나쁘게 만들었다면 알려 주세요.
4. **시험:** `bash script/setup.sh` 후 `AGENTS.md` 4장의 시험을 모두 돌려 주세요. `tests/test_fix_4319.py`가 새로 생겼습니다.
5. **결과:** `docs/REVIEW_CHECKLIST_v4.31.8.md` 8장 형식으로 `docs/REVIEW_RESULT_v4.31.9.md`에 써 주세요. 번호는 R1, R2 …로 하고, 맨 위에 '수정 확인' 표(F번호 · 판정 · 근거)를 둡니다.

## 바뀐 약속 (작성자 결정, 위반으로 보지 않음)
- **비밀 값(F11):** 도구가 설정 파일을 요구할 때(rclone, kaggle 명령)는 세션 임시 폴더의 본인 전용 파일(0600)에 둘 수 있습니다. 보안 비밀이 없을 때 직접 입력은 Colab에서 사람이 셀을 직접 실행할 때만 허용합니다. Kaggle·작업자 실행에서는 멈춥니다. Colab은 Colab 보안 비밀만, Kaggle은 Kaggle 보안 비밀만 읽고, 환경 변수는 둘 다 아닌 로컬 실행에서만 씁니다.
- **복원 TASK 이름(F12):** 백업으로 새로 복원한 TASK에 붙이는 꼬리표(16번 셀 `RS_SUFFIX`)는 이름 규칙의 예외입니다.
- **앱 이름:** '재처리 앱'은 **AA앱**입니다. 코드 안의 relabel·재처리는 같은 앱입니다.

## 1차 수정 내용

| F | 고친 곳 | 내용 |
|---|---|---|
| F1 | `kaggle_cpu_master.py` `backup_verdict`, `handle_aa` | AA앱 백업을 TASK별로 판정. '최신'만 받음, CVAT 준비 중이면 요청을 `waiting`(remaining)으로, 그 밖은 실패. 받음이 하나도 없으면 `failed`. 결과(results)를 TASK마다 남김 |
| F4 | `web_bridge.py` `take`, `_assigned_to_me` | '진행 중'(taken)은 `taken_session`이 이 세션인 것만 반환. 읽을 수 없는 배정 파일은 False(보류) |
| F5 | 30번 셀 `_rl_shape_one`, `_rl_upload_one`, 설정 `RL_REPLACE_ANY` | 교체 직전 지금 이름을 다시 봄. 기존 라벨이 있고 이름이 uld·AA가 아니면(`rb.is_target`) 백업만 하고 '보류'. upload는 확인 대기 track을 남김 |
| F10 | 30번 셀 유휴 판정 · `kaggle_cpu_master.py` `gpu_pending` | GPU 워커는 자기가 받은 `waiting` track 중 백업이 준비된 것이 있으면 끝나지 않음. CPU 마스터는 `kaggle_gpu`가 받은 `waiting` track/shape의 백업이 준비되면 워커를 다시 켬 |
| F11 | 0번 셀 `_secret`, `_may_prompt`, `_need`, `cvat_auth` | 위 '바뀐 약속'대로. Kaggle·작업자 실행 중(`_W`가 돌고 있음)에는 입력창 대신 멈춤 |
| F13 | `Code.gs` `splitState_`, `COLLECTOR_VERSION` 4.31.9 | `_test` = 상태 없음 + 표시 test, `vf_rN`·`vf_rNdf(_ok)`를 파이썬과 같게. 표본 6개로 양쪽 결과 일치 확인 |
| F15 | `web_bridge.py` `uld_scan`(새로), 0번 셀 `uld_index` | ULD 기록 읽기를 scripts로 옮김(CPU 마스터와 공용). 교체 연결은 처음 이름이 같고 **나중 기록이 ULD '바꾸기'(request.task.replace)로 만든 것**일 때만. 시각은 시간대를 맞춘 epoch로 비교. 여러 번 바꾸면 가장 나중 TASK로 |
| F16 | `kaggle_cpu_master.py` `uld_info`, `aggregate_and_sync_state` | 상태를 만들 때 `status/cvat_tasks.json`을 받고, ULD 기록(읽기 전용, 작업 폴더 밖 임시 폴더)으로 두 앱 상태에 `uld`·`replaced`를 넘김 |
| F17 | `train_sim.py` `pick_frames` | n=1이면 가운데 한 장 |
| F18 | 33번 셀 | 프레임을 하나도 받지 못하면 저장하지 않고 다음 실행에 다시 |
| F19 | 13번 셀 | `BK_SKIP_ULD=True`이고 직접 실행(요청 아님)이면 검색어 대상을 먼저 ID로 정한 뒤 ULD를 뺌 |
| F20 | 5번 셀, 30번 셀 `track_settings.json` | 실제로 쓴 decoder·frame_offset을 기록 |

함께: `script/setup.sh`(시험 환경), `.gitattributes`(줄 끝 LF), CPU 마스터 ipynb의 판 번호 맞춤.
