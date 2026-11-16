# v4.33.0i 검토 요청 — b15 V1~V5 반영 + 무작위 입력 시험

`docs/REVIEW_RESULT_v4.33.0h_b15.md`의 V1~V5를 반영했습니다. 대응표는 `docs/IMPL_STEP2A_v4.33.md`의 'b15 반영 (v4.33.0i)'에 있습니다.

형태 표에서 빠진 칸이 검토마다 하나씩 나와서, 이번에는 **무작위 입력 시험** `tests/test_fuzz_433.py`를 새로 넣었습니다.
- 기존 시나리오 시험에서 심판이 실제로 받은 입력을 모읍니다.
- 바깥 입력과 심판이 쓴 판정 파일의 칸을 하나씩 이상한 값으로 바꿔 판정 회차를 다시 돌립니다.
- 이 시험이 찾은 것도 함께 고쳤습니다: 자격 파일·신호 필수 칸, 판정 파일 형태 3천여 건, 형태가 틀린 신호를 버려 Keeper가 밤마다 깨우던 문제.

고친 파일:
- 코드: `drive/scripts/arbiter.py`, `arb_master.py`, `master_main.py`, `drive/notebooks/master_boot_v4.33.py`, `script/build_deploy.py`
- 시험: `tests/test_arbiter_433.py`, `tests/test_master_433.py`, `tests/test_master_main_433.py`, `tests/test_fuzz_433.py`(새)
- 문서: `docs/IMPL_STEP2A_v4.33.md`, `docs/DEPLOY_PLAN_v4.33.md` 4판(GPU 노트북 처음 올리기, T5·T6 통과 조건), `AGENTS.md`

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0i_b16.md`에 써 주세요. 새 발견은 W1부터 번호를 붙이고, 관점(동시성·스케줄링·복구·접근)과 종류(설계·코드·시험)를 적어 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 202개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 60개
python3 tests/test_master_main_433.py drive    # 60개
python3 tests/test_fuzz_433.py drive           # 3개 (약 4만 4천 회차, 15초)
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive   # 더 넓게 (약 10만 회차)
node tests/test_keeper.js apps_script/Keeper.gs   # 95개 — 실제 Node.js가 필요합니다
```

## 검토 질문

1. V1~V5가 해결됐는지 판정해 주세요. `/tmp/egg_b15_probes.py`가 남아 있으면 다시 돌려 주세요.
2. **무작위 입력 시험의 범위:** 이 시험이 덮지 못하는 입력 경로를 짚어 주세요. 예를 들면 다음과 같은 것입니다.
   - 시나리오 시험에 한 번도 나오지 않은 파일 종류·칸
   - 두 칸을 함께 바꿔야 나오는 경우
   - 같은 파일의 여러 회차
   - 마스터 루프 밖(Keeper, `master_main`의 조회·GPU)

   빠진 범위가 있으면 시험을 어떻게 넓힐지도 제안해 주세요.
3. **판정 파일이 틀어지면 '모름':** 심판이 쓴 파일(`arb/`·`CURRENT.json`)의 형태가 틀리면 그 파일을 '모름'으로 둡니다. 이 선택이 잘못 동작하는 경우가 있는지 봐 주세요.
   - 잠금·배정이 '모름'이면 영영 풀리지 않는가
   - 회차 기록(`ARBITER.json`)이 틀어지면 처리한 보고 목록을 잃고 다시 처리하는데, 이것이 안전한가
   - 인계 기록이 틀어지면 어떻게 되는가
4. **형태가 틀린 신호·요청:** 이제 버리지 않고 '거절' 완료·접수 기록을 남깁니다. 같은 신호가 나중에 바로잡혀도 다시 처리되지 않는데(신호는 매번 새 이름으로 만드는 약속), 이것이 앱 쪽 약속과 맞는지 봐 주세요.
5. **V3:** 가지 앱 모듈 이름(예약 이름)은 묶음을 만들 때의 scripts 이름과 옛 이름 몇 개입니다. 이 목록 관리가 실제로 지켜질 수 있는 방식인지 의견을 주세요.

## 결과 형식

- 발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
- V1~V5 각각에 '해결·부분 해결·미해결'을 적어 주세요.
