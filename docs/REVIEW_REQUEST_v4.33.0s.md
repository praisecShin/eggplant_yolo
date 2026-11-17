# v4.33.0s 검토 요청 — 0p(b22 R1·R2) + 2b-1·2b-2·2b-3 (처리기)

이번 검토 범위는 네 가지입니다. 11/16 결정에 따라 0p를 따로 검토받지 않았기 때문에, 0p를 이번에 함께 봅니다.

1. **0p:** `docs/REVIEW_RESULT_v4.33.0o_b22.md`의 R1·R2 반영. 대응표는 `docs/IMPL_STEP2D_v4.33.md`의 'b22 반영'에 있습니다.
2. **2b-1 기반:**
   - 처리기 등록부와 시험 범위(`ScopedCvat`)
   - **필수:** 처리기 진행 시각과 '멈춘 것 같음'
   - **필수:** 산출물 최종 검증(`publish_version`)
3. **2b-2 받는 중 일:** 백업·export 처리기와 실제 CVAT 어댑터(`cvat_ops.RealCvat`)
4. **2b-3 TASK 쓰기:** track·shape·auto·제출본 올리기
   - 업로드 전 백업, 사람 라벨 보호, 권한을 잃은 뒤 되돌리지 않음, 가져오기가 끝났는지 모를 때
   - 11/17 결정: track은 한 단계입니다(만들고 바로 올림).

설명은 `docs/IMPL_STEP2B_v4.33.md`에 있습니다. 계획은 `docs/IMPL_CHECKLIST_v4.33.md`의 '2b 작업 계획'에 있습니다.

**새 파일:**
- 처리기: `drive/scripts/handlers.py`, `h_read.py`, `h_task.py`
- 실제 CVAT 어댑터: `drive/scripts/cvat_ops.py`
- 가짜 CVAT: `tests/fake_cvat.py`
- 시험: `tests/test_handlers_433.py`

**고친 파일:**
- `arbiter.py`: 진행 한도 `STALL_SEC`, 요청 `params` 전달
- `executor.py`: 진행 시각 `busy`, `ctx.progress`, `ctx.env`
- `arb_io.py`: `put_file`·`get_file`
- `worker_cpu.py`: 등록부를 `handlers`로 옮김
- `cvat_task_tools.auto_annotate_frames`: `collect_only` 추가

**아직 하지 않은 것:**
- 처리기를 실행 호스트(GPU 작업자·Colab 30번 셀)에 연결하고, 실제 모델·영상 찾기를 붙이는 일은 2b-6입니다. 그래서 `RealEngine`과 `RealCvat`의 쓰기는 가짜 모듈로만 확인했고, 실제 동작은 예행 연습(T15)에서 봅니다.
- 취합 일(2b-4), 관리 일·학습·만들기(2b-5)

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0s_b23.md`에 써 주세요. 새 발견은 S1부터 번호를 붙이고, 발견마다 '2b-4로 넘어가기 전 필수 여부'를 적어 주세요. 재현 스크립트와 로그는 `rLog/`에 남겨 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 75개 (R1 실행기 회귀 포함)
python3 tests/test_master_main_433.py drive    # 62개 (R2 포함)
python3 tests/test_handlers_433.py drive       # 60개 (2b-1·2b-2·2b-3)
python3 tests/test_fuzz_433.py drive           # 10개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 72개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 125개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 34개
```

## 검토 질문

### A. 0p
1. R1·R2에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b22_*` 재현을 다시 돌려 주세요.
   - 실행기는 읽지 못한 것이 하나라도 있으면 그 차례에 일하지 않습니다(`if unknown: wait`). 객체가 아닌 바깥 입력은 목록에서 빼기만 합니다. 이 규칙이 실행기가 이미 맡은 일을 오래 멈추게 하는 경우가 있는지 봐 주세요. 예: 다른 사람의 요청 파일 읽기 실패.

### B. 2b-1
2. **'멈춘 것 같음':** 한도는 TASK·받기·취합 30분, 관리 일·만들기 1시간, 학습 3시간입니다(`STALL_SEC`). 다음을 봐 주세요.
   - 생존 신호의 `busy`를 심판이 판단하는 방식
   - 멈춘 실행기를 끊긴 것으로 다루는 경로(격리·확인 필요·다시 발급)
   - 처리기가 `ctx.progress`를 부르지 않는 구간(예: 큰 파일 하나 받기)에서 잘못 멈춤으로 볼 위험
   - 생존 신호 스레드와 처리기 스레드가 `busy`를 함께 쓸 때의 경합
3. **산출물 최종 검증:** `publish_version`은 올린 뒤 다시 받아 확인하고, 목록을 쓰기 직전에 권한을 확인합니다. 다음 경우에 확인되지 않은 목록이 '확인됨'으로 남는 경로가 있는지 봐 주세요.
   - 일부만 올리고 멈춤
   - 같은 버전 경로에 다시 게시
   - 확인과 목록 쓰기 사이에 파일이 바뀜
4. **시험 범위(`ScopedCvat`):** 다음 경우에 시험 실행이 운영 TASK에 쓰거나, 운영 실행이 `REH_` TASK에 쓰는 경로가 있는지 봐 주세요.
   - 감싼 객체를 우회해 쓰기 함수를 꺼냄
   - 이름이 바뀐 TASK
   - TASK 정보를 못 읽음
   - `create_task`

### C. 2b-2
5. 받는 중 기록(`backups|exports/pending/<요청>__<TASK>.json`)으로 다음이 맞게 이어지는지 봐 주세요.
   - 실행기가 바뀌어도 다시 요청하지 않음
   - 실패한 기록을 다시 시도함
   - 취소
   - 게시 잠금 아래 받기·올리기·확인
   기록을 쓰다 멈춘 경우와, 두 실행기가 같은 기록을 쓰는 경우도 봐 주세요.
6. `RealCvat`가 `cvat_backup`·`cvat_task_tools`의 기존 함수와 맞게 부르는지, 그리고 토큰이 기록·예외 문구로 새는 경로가 있는지 봐 주세요.

### D. 2b-3
7. **업로드 전 백업과 되돌리기:**
   - 백업을 받지 못하면 쓰지 않는지
   - 가져오기가 실패하면 되돌리는지
   - 권한을 잃었거나 가져오기가 끝났는지 모르면 되돌리지 않는지
   - 되돌리기 자체가 실패하면 어떻게 되는지
   - '지우기 → 가져오기' 사이에 끊기면 남는 상태와, 그 상태에서 복구 자료로 '확인 필요' 선택이 가능한지
8. **사람 라벨 보호:**
   - 이름 규칙(uld·AA·AA_r1)과 `params.allow_replace`(참만)가 맞는지
   - 판단 시점의 이름(확정 때 다시 읽음)이 맞는지
   - 제출본의 '덧붙임(append)'에도 같은 보호를 거는 것이 맞는지
9. **준비와 확정의 분리:** 준비에서 CVAT에 쓰는 경로가 없는지 봐 주세요(shape는 `collect_only`). 또 TASK가 바뀐 것을 알아보는 기준(프레임 수·라벨 정의)이 충분한지 봐 주세요.
10. **결과 확인(라벨 수 비교)과 이름 규칙(`_uld`→`_uld_AA`만):** 이 기준이 충분한지, 결과 문자열(`done`·`held:human_labels`·`failed:…(restored)`)과 요청의 최종 상태가 맞는지 봐 주세요.

### E. 다음
11. 2b-4(취합 일)로 넘어가기 전에 꼭 고칠 것을 적어 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안·2b-4 전 필수 여부.
