# v4.33.0n 검토 요청 — b20 Q1~Q4 반영 (2b 전 마지막 확인)

`docs/REVIEW_RESULT_v4.33.0m_b20.md`의 Q1~Q4를 고쳤습니다. 2b 전 필수인 Q1·Q2와, 2b 안에서 해도 되는 Q3·Q4를 함께 고쳤습니다.

- **Q1:** 심판은 '모름'을 '없음'으로 다루지 않습니다.
  - 읽지 못한 경로에는 쓰지 않습니다.
  - 정지 보류를 모르면 새 배정·GPU 기동을 하지 않습니다.
  - 신호의 계획·완료 기록을 모르면 그 신호를 미룹니다.
  - 인계 기록을 모르면 인계를 되풀이하지 않습니다.
- **Q2:** G 해제의 원래 신호를 못 읽으면 미룹니다. 새 신호를 처음 계획할 때도 같습니다.
- **Q3·Q4:** 수집기의 시각을 숫자로 비교하고, 건너뜀 기록에도 '더 최신일 때만' 규칙을 적용합니다.

대응표는 `docs/IMPL_STEP2D_v4.33.md`의 'b20 반영'에 있습니다. 설계서 '보호 모드'와 '수집기 자동 요청' 절을 보충했습니다.

고친 파일:
- `drive/scripts/arbiter.py`
- `apps_script/G_collector/Collector.gs`
- 시험 3개: `test_arbiter_433.py`, `test_fuzz_433.py`, `test_collector.js`

Keeper·CTRL앱·`arb_io.py`·노트북·v4.32 파일은 고치지 않았습니다.

**이번 검토의 쓰임 (11/16 결정):** **높음이 없으면** 남은 것은 알려진 한계로 적고 2b(처리기 옮기기)로 넘어갑니다. 발견마다 '2b 전 필수 여부'를 적어 주세요.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0n_b21.md`에 써 주세요. 새 발견은 P1부터 번호를 붙여 주세요. 재현 스크립트와 로그는 `rLog/`에 남겨 주세요. 다음 묶음으로 바꿀 때도 `rLog/`는 지우지 않고 남겨 두겠습니다.

```bash
python3 tests/test_arbiter_433.py drive        # 236개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 10개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive   # 2분 넘게 걸릴 수 있음
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 72개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 123개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 32개
```

## 검토 질문

1. Q1~Q4와, b20에서 부분 해결이던 Z1·Z3·Z4 각각에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b20_*` 재현을 다시 돌려 주세요.
2. **Q1 쓰기 막기:** 읽지 못한 경로에 쓰지 않는 규칙을 `View.put` 한곳에 두었습니다.
   - 쓰기가 막혔을 때 같은 회차의 다른 판단이 '썼다'고 여기고 진행하는 경로가 있는지 봐 주세요. 신호는 완료를 적지 않게 했습니다. 접수·배정·결과·잠금·인계·채택에서 같은 문제가 있는지 봐 주세요.
   - 퍼징에 '파일 숨기기' 불변 조건을 넣었습니다(그 경로에 쓰지 않음, 보류를 모르면 새 배정 없음). 빠진 불변 조건이 있으면 적어 주세요.
3. **보류 모름:** 정지 보류를 하나라도 모르면 새 배정·GPU 기동을 하지 않습니다. 다음 경우가 막히지 않는지 봐 주세요.
   - 이미 배정된 일의 마무리
   - 보류 만료
   - 해제 신호 처리
   그리고 이 상태가 오래가면 관리자가 알게 되는 경로(알림·CTRL앱 '읽지 못한 것')가 충분한지 봐 주세요.
4. **Q2:** '모름'으로 보는 이유는 `owner_unknown`·`origin_owner_unknown`·`origin_read_unknown` 셋입니다. 나머지(원래 신호 없음·등록 없음·사용 중지·권한 없음)는 거절합니다. 이 분류가 맞는지 봐 주세요.
5. 2b를 시작하기 전에 꼭 고칠 것이 남았는지 적어 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안·2b 전 필수 여부.
