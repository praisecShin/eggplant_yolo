# v4.33.0z4 검토 요청 (b28) — 2c-1 사람용 셀 기반 + 0z2·0z3 반영 확인

이번 검토 범위는 세 가지입니다.

1. **2c-1 사람용 셀 기반 (주 범위):**
   - 분석 모드, 쓰기 가드, CVAT 전송 가드, 요청·신호 API, 채택 모델·데이터셋 받기, 같은 커널의 30번 셀 실행 범위
   - 파일: `drive/scripts/cells_base.py`, `drive/notebooks/A0_colab/cells_v4.33/cell00.py`, `access.exec_scope`, `exec_host.run_loop`·`main_colab`
   - 설명: `docs/IMPL_STEP2C_v4.33.md`. 계획과 11/17 결정: `docs/IMPL_STEP2C_PLAN_v4.33.md`
2. **0z2 (b26 U1~U5 반영):**
   - 결과: `docs/REVIEW_RESULT_v4.33.0z1_b26.md`
   - 대응: `docs/IMPL_STEP2B_v4.33.md`의 'b26 반영'
3. **0z3 (b27 F1 반영):**
   - 학습 감독 프로세스 `drive/scripts/train_supervisor.py`
   - 결과: `docs/REVIEW_RESULT_v4.33.0z2_b27.md`
   - 대응: 'b27 반영'

**아직 하지 않은 것:**
- 0번 셀 밖의 셀(1~34번)은 아직 옛 원문입니다. 2c-2·2c-3에서 옮깁니다. 지금은 옛 셀이 공유 폴더나 CVAT에 쓰려고 하면 가드가 거절하는 상태입니다.
- v4.33 노트북 파일(.ipynb) 조립은 2c-6입니다.
- 실제 Colab·Drive 마운트·CVAT·GPU 동작은 예행 연습에서 확인합니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0z4_b28.md`에 써 주세요.
- 새 발견은 V1부터 번호를 붙여 주세요.
- 발견마다 '2c-2로 넘어가기 전 필수 여부'를 적어 주세요.
- 재현 스크립트와 로그는 `rLog/b28_*`에 남겨 주세요.

```bash
python3 tests/test_cells_433.py drive          # 44개 (2c-1)
python3 tests/test_hosts_433.py drive          # 54개 (0z2·0z3 포함)
python3 tests/test_handlers_433.py drive       # 142개
python3 tests/test_e2e_433.py drive            # 17개
python3 tests/test_master_433.py drive         # 75개
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 62개
python3 tests/test_fuzz_433.py drive
# 이전 재현 다시 실행
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b27_orphan_probe.py
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b26_process_boundaries.py
```

## 검토 질문

### A. 0z2·0z3
1. b26 U1~U5와 b27 F1에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b27_orphan_probe.py`·`b26_process_boundaries.py`를 다시 실행해 주세요. 새 구조(실행기 → 감독 → 학습 자식)에 맞춘 호환본이 필요하면 그렇게 표시해 주세요.
2. **감독(`train_supervisor.py`):**
   - 감독은 아래에 살아 있는 프로세스가 하나도 없을 때까지 끝나지 않고, 끝날 때 `clean`을 남깁니다.
   - 실행기는 감독에게만 TERM을 보내고 90초 기다립니다. 감독이 안 끝나거나 `clean`이 없으면 '확인 필요'로 보냅니다.
   - 다음을 봐 주세요.
     - 감독 자신이 KILL되는 경계
     - 감독 아래 프로세스가 감독보다 오래 사는 경로
     - `waitpid(-1)`이 학습 자식의 종료 코드를 잃는 경로
     - 감독의 TERM 신호 처리기가 다시 들어오는 경우
3. **학습 자식 환경(U4):**
   - 설정·캐시·임시·홈 폴더를 실행별 작업 폴더 안으로 둡니다.
   - 외부 기록 연동 변수는 넘기지 않고, 자식은 실행 전용 설정에서 연동을 끕니다.
   - 실행끼리 겹치는 쓰기가 남는지 봐 주세요.

### B. 2c-1 쓰기 가드
4. **우회 경로:** 쓰기 가드가 감싸지 않은 쓰기 경로가 옛 셀·scripts(`cvat_task_tools`·`web_bridge`·`relabel_bridge`·`cvat_backup`·`cvat_to_yolo` 등)에서 흔히 쓰이는지 봐 주세요.
   - 예: `os.open`, `pathlib.Path.touch`, `tempfile`을 BASE 안에 만들기, `zipfile.ZipFile(…, 'w')`, `PIL.Image.save`, `cv2.imwrite`, `np.save`, matplotlib `savefig`, `sqlite3`
   - 설계상 실수 방지 장치이므로 고의 우회는 범위 밖입니다. 다만 옛 셀이 흔히 쓰는 경로는 막혀야 합니다.
5. **판정 오류:** `Saver.allowed`의 경로 판정을 봐 주세요.
   - 심볼릭 링크, Drive 바로가기(`.shortcut-targets-by-id`), 대소문자, 상대 경로, `..` 같은 경우에 오판이 있는지 봐 주세요.
   - 같은 Drive 폴더를 두 경로(내 드라이브 바로가기와 shortcut-targets)로 볼 때 BASE 밖으로 판단하는 경로가 있는지 봐 주세요.
6. **가드 설치:**
   - 가드는 `builtins.open`·`io.open`·`os.*`·`shutil.*`을 바꿔 끼웁니다.
   - 0번 셀을 다시 실행하거나 모듈을 다시 불렀을 때(`importlib.reload`) 가드가 겹치거나 풀리지 않는 경로가 있는지 봐 주세요.
   - 같은 커널의 다른 스레드(30번 셀의 생존 신호 스레드 등)와의 상호 작용도 봐 주세요.

### C. 2c-1 CVAT 전송 가드
7. **허용 목록:** CVAT 2.79의 다음이 허용 목록과 맞는지 봐 주세요.
   - `cvat_sdk`의 읽기·참조용 export 경로
   - `cvat_backup`의 자체 세션 경로
   - GET으로 서버 상태를 바꾸는 API가 남아 있는지
   - export 준비 POST의 경로 형식(쿼리·끝 슬래시)
   - 로그인 경로(`/api/auth/login`), 조직 헤더
8. **감싸지 않은 클라이언트:**
   - urllib3를 직접 쓰는 경우, `cvat_sdk`의 다른 전송 경로(업로드 tus의 PATCH 등)
   - cvat-cli 하위 프로세스(`run()` 밖에서 `subprocess`로 부르는 옛 셀)
   - 위 두 가지가 실제로 가드를 지나는지, 막아야 할 쓰기가 남는지 봐 주세요.
9. **실행 범위:**
   - 실행 범위(`exec_scope`)는 contextvar라 실행기 스레드에만 걸립니다.
   - 실행기 처리기가 다른 스레드에서 CVAT를 부르는 경로(진행 알림 스레드 등)가 있어 실행기의 정상 쓰기가 막히는 경우가 있는지 봐 주세요.
   - 반대로 분석 셀이 실행 범위를 얻는 경로가 있는지 봐 주세요.

### D. 2c-1 요청 API·모델
10. **요청 파일:**
    - `request()`가 만드는 요청 파일의 칸이 심판 스키마와 2b 처리기 params에 맞는지 봐 주세요. 추가 칸 `by_person`·`by_analysis_session`이 영향을 주는지도 함께 봐 주세요.
    - 요청 ID가 겹칠 가능성이 있는지 봐 주세요. 형식은 초 단위 시각·사람·세션·순번입니다.
    - 사람이 다른 사람의 요청을 취소하는 신호가 신원 규칙대로 거절되는지 봐 주세요.
11. **모델 'latest':** 'latest'는 채택 시각(`adopted_at`)이 가장 늦은 모델입니다. 다음에 맞는지 봐 주세요.
    - 옛 0번 셀의 '가장 최근 학습 완료'와 같은 뜻인지
    - legacy 등록 모델의 채택 시각이 없을 때의 동작
