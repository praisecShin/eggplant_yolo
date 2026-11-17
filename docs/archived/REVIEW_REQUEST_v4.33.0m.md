# v4.33.0m 검토 요청 — b19 Z1~Z5 반영

`docs/REVIEW_RESULT_v4.33.0l_b19.md`의 Z1~Z5와 보충 항목(중요 알림 누적)을 고쳤습니다. Z1·Z4는 11/16 결정(권장안)대로입니다.

- **Z1:** 계획을 이어 할 때 신호 소유자를 모르면 미루고, 권한이 철회됐으면 아직 적용하지 않은 효과는 거절로 끝냅니다.
- **Z4:** 같은 이름 파일이 여럿이면 그 파일을 처리하지 않고 알림을 남깁니다. 관리자가 하나를 지울 때까지입니다.

대응표는 `docs/IMPL_STEP2D_v4.33.md`의 'b19 반영'에 있습니다. 설계서 '보호 모드'와 '수집기 자동 요청' 절을 보충했고, 배포 계획에는 예행 연습 확인 T18(같은 이름 파일과 rclone)을 더했습니다.

고친 파일:
- `drive/scripts/arbiter.py`, `drive/scripts/arb_io.py`
- `apps_script/G_collector/Collector.gs`, `apps_script/G_keeper/Keeper.gs`
- 시험 4개

CTRL앱·`Uld.gs`·노트북·v4.32 파일은 고치지 않았습니다.

**이번 검토의 쓰임:** 높음이 없으면 남은 보통·낮음은 알려진 한계로 적고 2b(처리기 옮기기)로 넘어가려 합니다(11/16). 그래서 발견마다 다음 두 가지를 함께 적어 주세요.
- 2b 전에 꼭 고쳐야 하는지
- 2b 안에서 또는 예행 연습에서 다뤄도 되는지

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0m_b20.md`에 써 주세요. 새 발견은 Q1부터 번호를 붙여 주세요. 재현 스크립트와 로그는 `rLog/`에 남겨 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 222개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 9개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive   # 2분 넘게 걸릴 수 있음
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 68개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 123개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 32개
```

## 검토 질문

1. Z1~Z5 각각에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b19_*` 재현을 다시 돌려 주세요.
2. **Z1:** '모름'으로 보는 이유는 `owner_unknown`·`origin_owner_unknown` 둘뿐이고, 나머지는 모두 '철회'(거절)로 봅니다. 다음 경우가 맞게 분류되는지 봐 주세요.
   - 원래 신호가 없음
   - 원래 신호를 못 읽음
   - 사람 목록 일부를 읽지 못함
   - G 계정 자체가 신호 소유자
   계획이 영영 미뤄져 신호가 쌓이는 경로가 있는지도 봐 주세요.
3. **Z4:** 같은 경로 감지는 한 목록 호출 안에서만 합니다. 서로 다른 목록이 겹치는 경로는 중복으로 보지 않습니다. 다음 동작이 안전한지 봐 주세요.
   - 판정 파일(`arb/`)이 같은 이름으로 둘이 된 경우: 보호 모드가 아니라 '모름'으로 다룸
   - 이 상태에서 밤 끝내기와 Keeper 깨우기
4. **Z2·Z3·Z5:**
   - 시각 검사의 범위
   - 장부의 '더 최신일 때만' 비교: `updated` 문자열 비교가 같은 형식(ISO)에서만 맞는지
   - `fail_since`가 고정되거나 지워지는 시점
5. **보충:** 중요 알림을 '지금 상태' 하나로 줄일 때 끝남·들어감 순서가 바뀌어 보이는 경우가 있는지 봐 주세요.
6. 2b를 시작하기 전에 꼭 고칠 것을 최소 목록으로 적어 주세요. 2b·예행 연습에서 다룰 것과는 나눠 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안. 표에 '2b 전 필수 여부' 칸을 더해 주세요.
