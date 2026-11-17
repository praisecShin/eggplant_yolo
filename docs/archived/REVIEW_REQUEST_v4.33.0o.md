# v4.33.0o 검토 요청 — 판정 보류 (b21 P1~P4)

`docs/REVIEW_RESULT_v4.33.0n_b21.md`의 P1~P4는 모두 같은 뿌리에서 나왔습니다. 판정 파일 하나를 '모름'으로 받은 회차에도 심판이 나머지 판단을 계속하다가, '모름'과 '없음'을 섞는 지점이 생긴 것입니다. 11/16 결정(A)에 따라 이런 지점을 하나씩 막지 않고 **회차 단위 판정 보류**로 바꿨습니다.

- **규칙:** 읽지 못한 것이 하나라도 있으면(목록 실패·파일 읽기 실패·같은 이름 여럿) 그 회차는 아무 판정도 하지 않습니다.
  - 예외: 사람 목록이 오래된 것(`config`)은 따로 다룹니다.
  - 그 회차에는 회차 기록(`hold_on`·`hold_on_since`)과 알림만 씁니다.
- **알림:** 판정 보류가 30분을 넘으면 `hold_on_long` 알림을 남깁니다. Keeper가 메일·푸시로 보내고, CTRL앱 위쪽에 '판정 보류' 띠가 보입니다.
- **객체가 아닌 JSON:** '모름'이 아니라 그대로 심판에 넘깁니다. 바깥 입력이면 형태 검사로 거절하고, 판정 파일이면 보호 모드로 들어갑니다. 실행기 쪽은 이런 파일을 '모름'(기다림)으로 다룹니다.

대응표와 바뀌는 동작(대가)은 `docs/IMPL_STEP2D_v4.33.md`의 'b21 반영'에 있습니다. 설계서 '보호 모드' 절의 '판정 보류' 항목도 함께 봐 주세요.

고친 파일:
- `drive/scripts/arbiter.py`, `arb_io.py`, `executor.py`
- `apps_script/G_keeper/Keeper.gs`, `apps/ctrl/index.html`
- 시험 5개

이전 회귀 가운데 '모름 회차에도 일부 진행'을 전제로 한 6곳(N1·N3·P3·Q1)은 새 규칙에 맞게 고쳤습니다. 모름 회차에는 아무것도 하지 않고, 다 읽히면 이어서 하는 것으로 바꿨습니다.

**이번 검토의 쓰임 (11/16 결정):** 높음이 없으면 2b로 넘어갑니다. 발견마다 '2b 전 필수 여부'를 적어 주세요.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0o_b22.md`에 써 주세요. 새 발견은 R1부터 번호를 붙여 주세요. 재현 스크립트와 로그는 `rLog/`에 남겨 주세요(지우지 않습니다).

```bash
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 10개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive   # 2분 넘게 걸릴 수 있음
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 72개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 125개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 34개
```

## 검토 질문

1. P1~P4와 b21에서 부분 해결이던 Q1·Z4에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b21_*` 재현을 다시 돌려 주세요.
2. **판정 보류의 뜻:** 입력에 '모름'이 있으면 `ARBITER.json`과 알림 말고는 하나도 쓰지 않는지 봐 주세요.
   - 반대로, 판정 함수 안에서 생기는 '모름'(`internal_unknown`, 형태 오류 등)은 판정 보류가 아닙니다. 이 경우가 다시 모름과 없음을 섞는 경로가 되는지 봐 주세요.
3. **객체가 아닌 JSON:** 이제 '모름'이 아니라 형태 검사로 갑니다. 다음 경우의 처리가 맞는지 봐 주세요.
   - 바깥 입력(실행기·요청·신호·보고·산출물 목록·자격 파일)이 객체가 아닐 때
   - 판정 파일이 객체가 아닐 때
   실행기 쪽에서 이런 파일을 '모름'으로 다루는 것이 마스터 쪽과 어긋나는 경로도 찾아 주세요.
4. **대가:**
   - 잠깐의 읽기 실패로 판정 보류가 자주 생길 때, 진행이 늦어지는 것 말고 다른 문제가 있는지 봐 주세요. 예: 실행기 확정 승인 대기 중 끊김 판단, 보류 만료, 밤 끝내기, Keeper 깨우기.
   - 같은 이름 파일 때문에 시스템 전체가 멈췄을 때 관리자가 알고 정리하는 경로가 충분한지 봐 주세요.
5. 2b를 시작하기 전에 꼭 고칠 것이 남았는지 적어 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안·2b 전 필수 여부.
