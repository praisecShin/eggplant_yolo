# v4.33.0k 검토 요청 — b17 X1~X6 반영

`docs/REVIEW_RESULT_v4.33.0j_b17.md`의 X1~X6과 '검토 질문별 보충'의 알림 두 가지(keeper.json을 못 읽을 때, 메일·ntfy 전송 실패)를 고쳤습니다. 대응표는 `docs/IMPL_STEP2D_v4.33.md`의 'b17 반영'에 있습니다. 설계는 '보호 모드' 절의 들어가는 조건과 알림을 보충했습니다.

고친 파일:
- `drive/scripts/arbiter.py` (`View._check_plans`)
- `apps/ctrl/index.html`
- `apps_script/G_collector/Collector.gs`
- `apps_script/G_keeper/Keeper.gs`
- 시험: `tests/test_arbiter_433.py`, `test_fuzz_433.py`, `test_ctrl_app.js`, `test_collector.js`, `test_keeper.js`

`Uld.gs`, 노트북, v4.32 파일은 고치지 않았습니다. 지난 요청서와 b16 결과는 `docs/archived/`로 옮겼습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0k_b18.md`에 써 주세요. 새 발견은 Y1부터 번호를 붙이고, 관점(동시성·스케줄링·복구·접근)과 종류(설계·코드·시험)를 적어 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 211개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 65개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 8개 (약 4만 7천 회차)
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 44개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 112개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 24개
```

## 검토 질문

1. X1~X6 각각에 '해결·부분 해결·미해결'을 적어 주세요. b17 재현(`/tmp/b17_*.py`·`.js`)이 남아 있으면 다시 돌려 주세요.
2. **X1 계획 대조:** 효과 목록은 신호만으로 다시 계산할 수 있다고 보았습니다. 이 가정이 깨지는 신호 종류가 있는지 봐 주세요. 대조하지 않는 경우가 셋 있습니다: 끝난 계획, 신호 파일이 없거나 읽지 못한 경우, 신호 형태가 틀린 경우. 이 셋에서 손상된 계획이 효과를 내는 경로가 있는지 봐 주세요. 계획의 `requester`·`admin`·`seq`는 대조하지 않습니다. 이 칸이 바뀌면 생기는 결과도 봐 주세요.
3. **퍼징의 독립 정답:** `tests/test_fuzz_433.py`의 `expected_effects`·`plan_mismatch`가 구현과 따로 판단하는지, 그리고 아직 구현의 검사 함수를 빌려 쓰는 곳(`input_problem`)이 놓치게 만드는 것이 있는지 봐 주세요.
4. **X2·X6 CTRL앱:** 읽기 세대·환경 확인 뒤에도 다른 환경으로 신호가 가거나, '보류 없음'·'살아 있음'을 잘못 보이는 경우를 찾아 주세요. 예: 60초 자동 새로고침과 대화상자가 겹칠 때, 운영과 시험 폴더 이름이 같은 Drive에 둘 다 있을 때.
5. **X3 보낼 목록:** `status/auto_pending.json`의 순서(사건 넣기 → 스냅숏 → 요청 ID 저장 → 요청 파일 → 장부 → 목록에서 빼기)를 봐 주세요. 어느 단계에서 멈춰도 요청이 빠지거나 겹치지 않는지 확인해 주세요. 다음 경우도 봐 주세요.
   - 목록 파일이 깨짐(읽기 실패는 던짐 → 수집 실패)
   - 같은 TASK가 두 번 바뀜(사건 키에 `updated` 포함)
   - `backfillVfNow`와 10분 수집이 겹침(스크립트 잠금)
   - Drive 검색(`searchFiles`)의 반영 지연
6. **X4·보충 Keeper 알림:** 보호 구간 판단(`prevProtectKey`)과 이력 지우기(`forget`), 보낼 목록(`outbox`)을 봐 주세요. 알림이 되풀이되거나 빠지는 경우, `keeper.json` 크기가 커지는 경우, 주제 이름이나 메일 주소가 새는 경로를 찾아 주세요.
7. **X5:** 생존 기록 계약(맨 위 `time`·`ok`)을 CTRL앱·Keeper·수집기가 같은 뜻으로 쓰는지 봐 주세요.
8. 2b(처리기 옮기기)를 시작하기 전에 더 고칠 것이 있으면 최소 목록으로 적어 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
