# v4.33.0y 검토 요청 (b24) — 0t(b23 S 반영) + 2b-4·2b-5·2b-6·2b-7

이번 검토 범위는 다섯 가지입니다. 11/17 결정에 따라 0t는 따로 검토받지 않았으므로 여기서 함께 봅니다.

1. **0t:** `docs/REVIEW_RESULT_v4.33.0s_b23.md`의 S1~S7 반영 (S4는 결정: 확인을 마친 버전은 바꾸지 않음). 대응표는 `docs/IMPL_STEP2B_v4.33.md`의 'b23 반영'.
2. **2b-4 취합 일:** `h_agg.py` — hide·unhide·refresh, 게시 파일의 epoch·회차, 받는 중 기록 요약.
3. **2b-5 관리 일·학습·만들기:**
   - 5a `h_mgmt.py` — dataset·test_tasks33·force_new·cleanup29(표시만)·cleanup34(청소)
   - 5b `h_run.py` — 복구 일(되돌리기·다시 하기)·학습·새 TASK 만들기(16·17)·23번 복원
4. **2b-6 실행 호스트:** `exec_host.py` — CPU 작업 프로세스·Kaggle GPU 작업자(새 GPU 뿌리 노트북)·Colab 30번 셀, 시험 범위 강제, 웹 상태(옛 `web/state.json`) 계산, 복구 자료 청소.
5. **2b-7 연결 시험:** `tests/test_e2e_433.py` — Codex 요청 목록 ①~⑥.

설명은 `docs/IMPL_STEP2B_v4.33.md`(2b-4 이후 절)에 있습니다.

**새 파일:**
- 처리기: `drive/scripts/h_agg.py`, `h_mgmt.py`, `h_run.py`
- 실행 호스트: `drive/scripts/exec_host.py`
- Colab 30번 셀 원문: `drive/notebooks/A0_colab/cell30_v4.33.py` (노트북에는 2c에서 넣음)
- 시험: `tests/test_hosts_433.py`, `tests/test_e2e_433.py`

**고친 파일:**
- `handlers.py`: `ImportRejected`, `ticking`, `ScopedCvat` 읽기 허용 목록·만들기, `publish_version` 다시 게시 거절
- `h_task.py`: S1·S2·S3·S5·S6, 복구 일용 덮어쓰기 값(`allow_replace`·`rename_to`·`exact_count`·`archive`), `result_plan.json`에 업로드 전 백업 해시·원요청 설정
- `cvat_ops.py`: `before_each`, 4xx → `ImportRejected`, `list_tasks`, `create_task`·`upload_video`·`create_from_backup`·`move_task`
- `executor.py`:
  - **작업 번호에 배정 키 해시** — 같은 실행기·같은 TASK의 다른 요청이 복구 자료를 덮어쓰던 문제. 2b-5b 시험에서 발견
  - TASK를 적은 취합 요청의 마무리
  - 생존 신호에 `kernel`
- `arbiter.py`: 복구 요청 intake에 `origin_job`
- `arb_io.py`: `delete`·`list_any`·`pull`
- `worker_cpu.py`·`master_main.py`: 실행 호스트 연결, 작업 프로세스에 `--test`·`--exec-config`. 시험 실행인데 시험 프로젝트 번호가 없으면 마스터가 시작하지 않음
- `master_boot_v4.33.py`·`dev_tools/build_deploy.py`: ROLE(master·gpu), GPU 뿌리 노트북과 `worker_manifest.json`, 패키지 설치
- `relabel_bridge.load_tracked`: `_pub` 키를 TASK로 보지 않음

**아직 하지 않은 것:**
- 실제 CVAT·Drive·Kaggle·Colab 동작은 예행 연습에서 확인합니다. 시험은 가짜 CVAT·폴더 저장소로만 했습니다.
  - `RealCvat`의 만들기·영상 올리기
  - `RealTrainer`
  - `RealBuilder`/`HostBuilder`
  - `WebState`
  - `ColabRclone`
  - GPU 뿌리 노트북
- ULD 사진 TASK(프레임맵)의 track은 2c에서 합니다.
- 관리자 폴더 `config/exec.json`(시험 프로젝트 번호 등)은 배포 때 만듭니다. Drive는 고치지 않았습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0y_b24.md`에 써 주세요.
- 새 발견은 T1부터 번호를 붙여 주세요.
- 발견마다 '2c로 넘어가기 전 필수 여부'를 적어 주세요.
- 재현 스크립트와 로그는 `rLog/`에 남겨 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 75개
python3 tests/test_master_main_433.py drive    # 62개
python3 tests/test_handlers_433.py drive       # 126개 (2b-1~2b-5, b23 회귀)
python3 tests/test_hosts_433.py drive          # 35개 (2b-6)
python3 tests/test_e2e_433.py drive            # 17개 (2b-7, 몇 분 걸림)
python3 tests/test_fuzz_433.py drive           # 10개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 72개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 125개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 34개
```

## 검토 질문

### A. 0t (b23)
1. S1~S7마다 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b23_*` 재현을 다시 돌려 주세요.
2. **S2 판정:** 서버가 '분명히 거절'한 경우를 4xx(408·409·429 제외)와 형식 거절로 정했습니다.
   - cvat-sdk의 `import_annotations`가 서버 처리 실패를 어떤 예외·상태로 돌려주는지 봐 주세요.
   - '응답을 잃음'이 '분명한 거절'로 잘못 분류될 수 있는지 봐 주세요.

### B. 2b-4 취합
3. 게시 파일마다 `_pub(epoch, gen)`를 적고, 더 높은 것이 있으면 덮어쓰지 않습니다. 다음을 봐 주세요.
   - 취합 회차(gen)는 취합 잠금마다 올라갑니다. 같은 epoch에서 옛 실행이 늦게 게시하는 경로가 남는지.
   - `tracked.json`을 읽고 고쳐 쓰는 사이에 다른 작성자가 끼어들 수 있는지. 설계상 작성자는 취합 하나입니다.
4. CVAT 목록이 한도(5000)에 닿으면 '사라짐'을 판단하지 않습니다. 대상 TASK가 실제로 사라졌는데 오래 표시되지 않는 경우를 앱이 알 수 있는지 봐 주세요.

### C. 2b-5 관리 일·학습·만들기
5. **데이터셋:** TASK마다 가장 나중에 받은 export를 쓰고, 해시를 받는 중 기록과 대조합니다. 시험 TASK와 같은 그루·촬영일은 뺍니다. 출처 키를 모르는 TASK가 있으면 `task_keys`를 비웁니다(학습 '호환 확인 불가'). 이 규칙의 빈틈을 봐 주세요.
6. **청소:** 판단 재료를 하나라도 못 읽으면 계획을 만들지 않습니다. 다음 순서로 지웁니다.
   - 버전은 목록(`_files.json`)을 먼저 지움
   - 신호 계획을 먼저, 완료 기록은 그다음
   - 복구 자료는 결과 계획을 먼저 지움

   다음을 봐 주세요.
   - 반쯤 지운 상태가 다른 판단(채택·학습 시작·복구 일)을 속이는지
   - '정리 대상' 표시 파일(`arb/mgmt/<실행>/marks.json`)을 실행기가 쓰는 것이 신뢰 모델에 맞는지. 지금은 끝난 실행의 표시만 쓰고, 시각은 파일 생성 시각과 비교해 늦은 쪽을 씁니다.
7. **복구 일:**
   - 되돌리기는 원래 업로드 전 백업을 해시로 대조한 뒤 같은 확정 절차로 교체합니다. 라벨 수가 정확히 같아야 끝나고, 이름은 원래대로 돌립니다.
   - 다시 하기는 원요청의 종류와 설정으로 다시 계산합니다.
   - 원래 사람 라벨 교체 동의를 이어받는 것이 맞는지 봐 주세요.
   - `before_upload.zip`이 없는(0t 이전) 복구 자료는 해시 기록이 없어 되돌리기가 실패합니다. 이것이 맞는지 봐 주세요.
8. **학습:** 잠금의 고정값(시작 데이터셋·모델 버전)만 쓰고, 에폭마다 권한을 확인합니다. Ultralytics 콜백 안에서 예외를 던져 학습을 멈추는 방식이 안전한지 봐 주세요. DDP(GPU 여럿) 자식 프로세스도 함께 봐 주세요.
9. **만들기:**
   - 17번은 빈 TASK를 먼저 만들고 번호를 기록합니다. 16번은 한 번 호출로 만듭니다.
   - 응답을 잃으면 다시 만들지 않고, 같은 요청의 다음 실행도 사람 확인(`retry_confirmed`) 없이 시작하지 않습니다.
   - DESIGN '새 TASK 만들기'의 후보 찾기(의도 시각 뒤 같은 이름 TASK)는 아직 자동으로 하지 않고 사람에게 맡깁니다. 이것으로 충분한지 봐 주세요.

### D. 2b-6 실행 호스트
10. **시험 범위 강제:** `config/exec.json`의 `test_project_id`가 없으면 마스터·GPU·Colab이 시작하지 않습니다. 운영 실행은 `REH_`에 쓰지 않습니다. 범위를 우회하는 경로가 남았는지 봐 주세요. 특히 다음을 봐 주세요.
    - 엔진의 `make_shapes`가 받는 원래 CVAT 연결 (읽기만 씀)
    - `WebState`의 원래 연결 (읽기만)
    - `create_from_backup` 직후 이름 맞추기
11. **GPU 뿌리 노트북:** 사슬은 '마스터 노트북 → `manifest.json` → (GPU 노트북 → `worker_manifest.json` → scripts)'입니다.
    - GPU 노트북은 마스터 묶음 안에 있고, 마스터가 Kaggle에 올립니다.
    - 사슬이 끊기거나 섞이는 경로가 있는지 봐 주세요. 예: 시험 묶음의 GPU 노트북이 운영 연결을 가리킴.
    - 쉬는 시간 끝내기(15분)가 맡은 일 중에 끝나는 경우가 있는지 봐 주세요.
12. **Colab:**
    - Colab 보안 비밀에는 RCLONE_CONF가 없습니다. 그래서 로그인 접근 토큰으로 세션 전용 rclone 설정(0600, 갱신 토큰 없음)을 만들고 30분마다 다시 씁니다. 이 방식이 보안 규칙에 맞는지 봐 주세요.
    - 토큰이 만료돼 저장소 쓰기가 실패할 때 실행기가 잘못 판단하는 일이 있는지 봐 주세요.
13. **웹 상태:**
    - 옛 `aggregate_and_sync_state`의 계산만 읽기 사본 위에서 다시 씁니다. 샤드 합치기·요청 완료·사라진 TASK 이력·원격 삭제는 하지 않습니다.
    - 옛 화면이 쓰던 값 중 빠진 것이 있는지 봐 주세요. 예: `rb.build_state`의 모델 목록·영상 출처는 이전 상태에서 이어 받음.

### E. 2b-7 연결 시험
14. 시나리오가 요청 항목 ①~⑥을 충분히 덮는지 봐 주세요. 빠진 경계가 있으면 재현해 주세요.
15. **확정 승인 뒤 취소:** 한 실행기는 묶음(최대 5개)을 함께 준비하고 확정 신청을 함께 냅니다. 심판이 함께 승인하면, 취소 뒤에도 그 묶음 전체가 끝까지 쓰입니다.
    - 설계('확정 신청 뒤면 그 TASK를 마침')와는 맞습니다.
    - 사용자 기대(취소하면 곧 멈춤)와 다를 수 있습니다. 확정 신청을 TASK 하나씩 내야 하는지 의견을 주세요.
