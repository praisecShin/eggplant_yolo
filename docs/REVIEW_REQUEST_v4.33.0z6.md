# v4.33.0z6 검토 요청 (b29) — b28 V1~V5 반영 확인 + 2c-2 읽기 셀

이번 검토 범위는 두 가지입니다.

1. **b28 반영 확인 (주 범위):**
   - 결과: `docs/REVIEW_RESULT_v4.33.0z4_b28.md`
   - 대응: `docs/IMPL_STEP2C_v4.33.md`의 'b28 반영 (v4.33.0z6)'
   - 파일: `drive/scripts/cells_base.py`(가드·`start`·`_state`·`S.model`), `drive/scripts/train_supervisor.py`, `drive/scripts/h_run.py`(`RealTrainer.train`의 `setup_failed`), `drive/notebooks/A0_colab/cells_v4.33/cell00.py`
   - 결정(11/17): D10 취소는 지금대로(등록된 사람이면 누구의 요청이든). D11은 `last_adopted`(최근 채택)로 이름을 바꾸고 `latest`는 거절. `docs/DESIGN_v4.33.md`의 'b28 반영'
2. **2c-2 읽기 셀 (v4.33.0z5):**
   - 셀 원문 15개: `drive/notebooks/A0_colab/cells_v4.33/cell02·03·04·07·08·11·18·19·20·21·22·24·25·26·32.py`
   - 기록 돌리기: `cells_base.redirect_records`(옛 세션별 기록 쓰기 → 내 분석 폴더 `records/`, 읽을 때 합침), 0번 셀 `last_upload`·`pick_model`·`job_start`
   - 처리기: `h_task.py`가 올린 결과 파일을 복구 자료에 해시와 함께 게시 (`result_plan.json`의 `result_file`·`result_sha256`·`model`)
   - 설명: `docs/IMPL_STEP2C_v4.33.md`의 '2c-2 읽기 셀'

**특히 봐 주세요:**
- V1·V2: 0번 셀을 여러 번 다시 실행하거나, reload 뒤 시작이 실패하거나, 다른 스레드가 쓰는 중에 세션이 바뀌어도 가드가 하나만 남고 풀리지 않는지. 새 분석 폴더를 만드는 동안의 허용(`_state()["boot"]`)이 다른 경로로 새지 않는지.
- V3·V5: 표(`OS_ARGS`·`SH_ARGS`)에 빠진 함수나 인자, `dir_fd` 풀기의 빈틈, 항목/내용 구분이 틀린 곳.
- V4: 감독 준비 실패가 '확인 필요'가 아니라 일반 실패로 가는 판단이 맞는지 (학습 자식을 띄우지 않았으므로 남은 것이 없다는 근거).
- 2c-2: 읽기 셀이 공유 폴더·CVAT에 쓰는 경로가 남았는지. `last_upload`가 되돌리기(revert) 뒤의 업로드를 쓰지 않는 판단, 옛 기록과 v4.33 결과를 합치는 순서가 맞는지.

**아직 하지 않은 것:**
- 바꾸는 셀(2c-3), 제출본(2c-4), 30·31·34번(2c-5), 노트북 조립·전 셀 분석 시험(2c-6, b30)
- 읽기 셀 중 모델·영상이 필요한 10개(2·3·11·18·20·21·22·24·32·4번 일부)는 원문 검사만 합니다. 실제 실행 시험은 5개(7·8·19·25·26번)
- 실제 Colab·Drive·CVAT·Kaggle은 예행 연습에서

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0z6_b29.md`에 써 주세요.
- 새 발견은 W1부터 번호를 붙여 주세요.
- 발견마다 '2c-3으로 넘어가기 전 필수 여부'를 적어 주세요.
- 재현 스크립트와 로그는 `rLog/b29_*`에 남겨 주세요. b28 재현(`rLog/b28_guard_probe.py`·`b28_supervisor_probe.py`·`b28_import_probe.py`)을 다시 돌려 반영을 확인해 주세요.

```bash
python3 tests/test_cells_433.py drive          # 69개 (2c-1·2c-2·b28)
python3 tests/test_hosts_433.py drive          # 57개 (b28 V4 포함)
python3 tests/test_handlers_433.py drive       # 143개
python3 tests/test_e2e_433.py drive            # 17개
python3 tests/test_master_433.py drive         # 75개
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 62개
python3 tests/test_fuzz_433.py drive
# b28 재현 다시 실행 (반영 확인)
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b28_guard_probe.py
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b28_supervisor_probe.py
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b28_import_probe.py
```
셀 시험에는 pandas·requests가 필요합니다.
