# v4.33.0g 검토 요청 — b13 S1~S3 반영 + 구현 2a (CPU 마스터 노트북 연결)

두 가지를 함께 봅니다.

1. **0g:** `docs/REVIEW_RESULT_v4.33.0f_b13.md`의 S1~S3 반영.
   - S1: `arbiter.py`의 종류별 형태 표 `SCHEMA`·`input_problem`
   - S2·S3: `docs/DEPLOY_PLAN_v4.33.md` 3판 — 6절 옛 배정 경로, 8절 예행 연습 단계 대응표
   - Codex 의견 반영: 사람 상태 해석을 Keeper `kpActive_`와 심판이 같게 함, 서버 가져오기를 모르면 전환·교체를 미룸
2. **2a (새 코드):** 설명은 `docs/IMPL_STEP2A_v4.33.md`에 있습니다.
   - `drive/notebooks/master_boot_v4.33.py`: 뿌리 노트북 셀 원본
   - `script/build_deploy.py`: 배포 묶음
   - `drive/scripts/master_main.py`: 마스터 본체
   - 고친 것: `arbiter.py`(`gpu_needed`·`busy`), `arb_master.py`, `worker_cpu.py`(`--stop-file`)

기존 v4.32.0 파일은 고치지 않았습니다. 처리기 옮기기(2b) 전이라 운영에는 올리지 않습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0g_b14.md`에 써 주세요. 새 발견은 U1부터 번호를 붙이고, 관점(동시성·스케줄링·복구·접근)과 종류(설계·코드·시험)를 적어 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 181개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 53개
python3 tests/test_master_main_433.py drive    # 42개 (새)
node tests/test_keeper.js apps_script/Keeper.gs   # 95개 — 실제 Node.js가 필요합니다
```

## 검토 질문

### A. 0g

1. S1~S3이 해결됐는지 판정해 주세요. `/tmp/egg_b13_probes.py`가 남아 있으면 다시 돌려 주세요.
2. **S1:** `SCHEMA`가 판정 함수에서 문자열 함수·경로 이어 붙이기·정수 변환에 쓰는 칸을 덮는지 봐 주세요. 덮지 않는 칸 하나로 회차 전체가 실패하는 경로가 남았으면 짚어 주세요.

### B. 2a — 신뢰 경계

3. **검증 사슬:** 뿌리 노트북(`MANIFEST_SHA256` 고정) → `manifest.json` → 파일별 해시 → `VerifiedFinder`로 검증한 바이트만 불러오기. 검증하지 않은 코드가 실행되는 경로가 있는지 봐 주세요.
   - 디스크의 같은 이름 모듈
   - 이미 불린 모듈
   - 작업 프로세스용으로 디스크에 쓴 코드(`write_code_dir` → `python -I`)
   - GPU 노트북 바이트
   - 목록에 없는 scripts를 import하는 경우
4. **시험·운영 분리:** `check_remotes`(연결 이름), GPU 주소 `-test` 확인, 묶음의 시험 여부가 예행 연습에서 운영 폴더·운영 노트북에 쓰는 것을 막는지 봐 주세요. 이름 규칙에 기대는 한계가 받아들일 만한지도 의견을 주세요.
5. **비밀 값:** `RCLONE_CONF` 여러 연결 해석(`parse_rclone_conf`), 세션 임시 폴더 0600, 작업 프로세스 환경(`CVAT_TOKEN` 물려받음), Kaggle 응답 원문을 기록하지 않음. 새는 경로가 있는지 봐 주세요.

### C. 2a — 마스터 동작

6. **끝내기 조건(`exit_reason`):** '밤에 할 일 없음'이 실행 가능 0·진행 중 0·GPU 필요 0·다음 깨울 시각 15분 밖일 때입니다. 일이 남았는데 끝나는 경우, 끝나야 하는데 계속 도는 경우를 찾아 주세요. 자격을 잃은 마스터가 10분 동안 하는 일(작업 프로세스는 계속 돎)이 위험한지도 봐 주세요.
7. **작업 프로세스 관리:** 멈춤 파일 → 2분 기다림 → 끊기. 끊긴 작업 프로세스의 일은 심판이 생존 신호 만료로 정리한다고 보았습니다. 마스터가 끝날 때의 순서(작업 프로세스 → 생존 신호 '끝남')에 문제가 있는지 봐 주세요.
8. **GPU 올리기:** `gpu_needed`(맞는 GPU 실행기가 살아 있지 않은 실행 가능한 일) 기준, 10분 간격, Kaggle 상태가 실행 중이면 건너뜀. GPU 작업자를 두 개 띄우거나 영영 안 띄우는 경우를 찾아 주세요.
9. **바깥 조회:** `ProbeCache`는 실패하면 '모름'을 주고 판정 루프를 막지 않습니다. 커널 상태 'ended'가 잘못 나와 '확인 필요'를 너무 일찍 열 수 있는 경로가 있는지 봐 주세요. CVAT `/api/requests` 형식은 실측 전(T10)이므로, 코드가 형식이 다를 때 '없음'이 아니라 '모름'을 주는지만 봐 주세요.

### D. 다음

10. 2b(처리기 옮기기, 30번 셀·GPU 작업자를 `Executor`로)를 시작하기 전에 고칠 것을 최소 목록으로 적어 주세요.

## 결과 형식

- 발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
- S1~S3 각각에 '해결·부분 해결·미해결'을 적어 주세요.
