# v4.33.0h 검토 요청 — b14 U1~U7 반영 확인 (짧은 검토)

`docs/REVIEW_RESULT_v4.33.0g_b14.md`의 U1~U7을 반영했습니다. 대응표는 `docs/IMPL_STEP2A_v4.33.md`의 'b14 반영 (v4.33.0h)'에 있습니다. 이번 검토는 U1~U7만 보는 짧은 검토입니다.

고친 파일:
- 코드: `drive/scripts/arbiter.py`(형태 표, 산출물 목록·자격 파일 확인, 정지 기한, `_busy_count`), `arb_master.py`(사람 목록 칸 확인, `last_clean_at`·`last_run_at`), `master_main.py`(커널 상태 해석, 조회 최신성, CVAT 응답, 밤 끝내기, GPU 상태 모름), `drive/notebooks/master_boot_v4.33.py`(`lock_imports`)
- 시험: `tests/test_arbiter_433.py`, `tests/test_master_433.py`, `tests/test_master_main_433.py`
- 문서: `docs/IMPL_STEP2A_v4.33.md`, `docs/DESIGN_v4.33.md`(알려진 한계에 '밤의 확인 필요')

결정 (11/15): '확인 필요'(사람이 고르기를 기다리는 일)는 마스터의 '진행 중'으로 세지 않습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0h_b15.md`에 써 주세요. 새 발견은 V1부터 번호를 붙이고, 관점(동시성·스케줄링·복구·접근)과 종류(설계·코드·시험)를 적어 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 192개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 56개
python3 tests/test_master_main_433.py drive    # 56개
node tests/test_keeper.js apps_script/Keeper.gs   # 95개 — 실제 Node.js가 필요합니다
```

## 검토 질문

1. U1~U7이 해결됐는지 판정해 주세요. `/tmp/egg_b14_probes.py`가 남아 있으면 다시 돌려 주세요.
2. **U1:** 판정 함수가 읽는 칸을 모두 훑어 형태 표에 넣었다고 보았습니다. 빠진 칸이 있으면 짚어 주세요. 사람 목록의 칸이 틀리면 설정 전체를 쓰지 않는 선택(20분 뒤 '사람 목록 모름')이 지나친지도 의견을 주세요.
3. **U2:** `lock_imports`는 `sys.path`를 표준 라이브러리·설치된 패키지 폴더로 좁힙니다. 이 범위가 Kaggle 환경에서 필요한 패키지(cvat_sdk, kaggle, ultralytics 등)를 막을 수 있는지, 반대로 너무 넓은지(설치된 패키지 폴더에 우리 모듈 이름의 파일이 있는 경우) 봐 주세요.
4. **U3·U7:** Kaggle 출력 형식은 실측 전(T5·T6)입니다. 해석하지 못하면 '모름'이 되고, 그러면 '확인 필요' 선택은 15분 대기 규칙대로 열리고 GPU는 올리지 않습니다. 이 기본값으로 GPU가 영영 안 뜨는 경우가 있는지 봐 주세요.
5. **U6:** '바로 직전 회차가 빠짐없음' 조건이 너무 엄격해서, 파일 하나를 계속 못 읽는 밤에 마스터가 실행 한도까지 켜져 있는 것이 받아들일 만한지 의견을 주세요.

## 결과 형식

- 발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
- U1~U7 각각에 '해결·부분 해결·미해결'을 적어 주세요.
