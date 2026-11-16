# v4.33.0j 검토 요청 — b16 W1~W3(보호 모드) + 2d 수집기 + CTRL앱

세 가지를 함께 봅니다.

1. **0j:** `docs/REVIEW_RESULT_v4.33.0i_b16.md`의 W1~W3 반영 — 대응표는 `docs/IMPL_STEP2A_v4.33.md`의 'b16 반영'.
   - 판정 파일은 칸별로 막지 않고 **보호 모드**로 처리합니다 (설계 '보호 모드', 11/15 결정).
   - 무작위 입력 시험이 이제 뜻도 확인합니다.
   - Keeper가 보호 모드 들어감·끝남을 메일과 ntfy 푸시로 알립니다.
2. **2d:** `apps_script/G_collector/Collector.gs` — `Code.gs`에서 배정·깨우기를 뺀 수집기. 자동 요청 규칙도 바꿨습니다(11/12 결정: backup은 `_uld`로 올라올 때, export는 검토 단계로 바뀔 때, _AA 감지는 그만둠). 운영에서 받아 온 `apps_script/G_collector/Uld.gs`(고치지 않음)와 함께 씁니다. `docs/IMPL_STEP2D_v4.33.md`.
3. **2e 일부:** `apps/ctrl/index.html` — CTRL앱. 같은 문서.

**폴더 정리 (11/15):** 내용은 그대로 두고 자리만 옮겼습니다. 새 구조는 `AGENTS.md` 2장에 있습니다.
- 지난 검토 문서는 `docs/archived/`로 옮겼습니다.
- `script/`는 `dev_tools/`로 바꿨습니다. 개발 기계에서만 쓰고 Drive에 올리지 않는 폴더입니다.
- Apps Script는 계정·프로젝트별로 `apps_script/G_collector/`·`G_keeper/`·`K_legacy_v4.32/`에 나눠 담았습니다. G 프로젝트의 `appsscript.json`에는 메일 권한(`script.send_mail`)을 더했습니다. Keeper 알림과 Uld.gs 메일에 필요합니다.
- 노트북은 `drive/notebooks/A0_colab/`·`A0_kaggle/`·`K_kaggle/`에 나눠 담았습니다. Drive에는 예전처럼 하위 폴더 없이 올립니다.
- v4.32 시험은 노트북 경로만 새 자리로 고쳤습니다.

기존 v4.32.0 파일(`Code.gs` 포함)의 내용은 고치지 않았습니다. 처리기 옮기기(2b) 전이라 운영에는 올리지 않습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0j_b17.md`에 써 주세요. 새 발견은 X1부터 번호를 붙이고, 관점(동시성·스케줄링·복구·접근)과 종류(설계·코드·시험)를 적어 주세요.

```bash
python3 tests/test_arbiter_433.py drive        # 202개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 65개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 6개 (약 4만 6천 회차)
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 101개
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 35개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 13개
```

## 검토 질문

### A. 보호 모드 (0j)

1. W1~W3이 해결됐는지 판정해 주세요. `/tmp/egg_b16_probes.py`가 남아 있으면 다시 돌려 주세요.
2. **들어가는 조건:** 판정 파일 종류별 필수 칸(`REQUIRED["judgement:*"]`), 상태 값(`STATE_VALUES`·`RESULT_VALUES`), 세션 지문을 봅니다. 이 조건이 다음 두 경우에 맞는지 봐 주세요.
   - **너무 넓은 경우:** 정상 운영에서 심판 자신이 쓴 파일로 보호 모드에 들어가는 경로. 예를 들어 옛 epoch의 파일, 인계 중인 파일, 형태가 바뀐 옛 판 파일.
   - **너무 좁은 경우:** 손상됐는데도 '정상'으로 지나가 W1·W2 같은 결과가 나는 경로.
3. **보호 모드 중 동작:** 회차 기록·알림만 씁니다. 다음이 맞는지 봐 주세요.
   - 실행기가 이 동안 하는 일
   - Keeper가 깨우기·자격에서 이 상태를 다루는 방식
   - 마스터의 밤 끝내기
   - 무작위 입력 시험의 '살아 있는 정지 보류 아래 새 배정 없음' 검사에서, 같은 회차에 해제된 보류를 뺀 것
4. **알림:** Keeper가 보호 모드에 들어갈 때와 끝날 때 메일·ntfy를 한 번씩 보냅니다. 되풀이되거나 빠지는 경우를 봐 주세요. 예: 손상 파일이 바뀜, 심판이 멈춤, `keeper.json`을 못 읽음. ntfy 주제 이름이 새는 경로도 봐 주세요.
5. **W3:** 가지 앱 이름 전체를 이미 불린 모듈 목록에서 버리는 방식이 Kaggle 노트북 환경에서 다른 것을 깨뜨릴 수 있는지 봐 주세요. 예: IPython이 들고 있는 참조.

### B. 수집기 (2d)

6. 배정·깨우기가 완전히 빠졌는지, 그리고 수집기가 심판의 영역(`arb/`·`jobs/`·`workers/`)에 쓰지 않는지 봐 주세요.
7. 자동 요청 파일이 심판의 요청 형태 확인(`input_problem("request")`)과 접수 규칙(`system:G`, `AUTO_KINDS`)을 통과하는지 봐 주세요. 예: `params` 객체, `task_names`. 같은 TASK가 이미 진행 중인 요청에 들어 있을 때의 동작도 봐 주세요.
8. **`Uld.gs`와 함께:** 수집기가 `Uld.gs`에 기대는 방식(`typeof` 확인), 그리고 `Uld.gs`가 수집기 함수를 쓰는 방식이 서로 맞는지 봐 주세요. `Uld.gs`는 ULD앱 원본 목록을 `CVAT_UpLoader/registry/sources.json`에 씁니다. 'CVAT_UpLoader는 읽기 전용'(AGENTS 3장 5)은 우리 노트북·앱의 약속이고, 이 파일은 ULD앱 쪽 산출물로 보았습니다.
9. **자동 요청 규칙:** 다음 경우에 요청이 빠지거나 겹치는지 봐 주세요.
   - backup: `_uld`로 올라올 때. 원본이 있으면(videos/·ULD 기록·ULD 장부) 하지 않음
   - export: 검토 단계로 바뀔 때마다
   - 수집기의 증분 읽기가 바뀜을 놓칠 때(10분 사이 두 번 바뀜, 전체 맞추기에서만 보이는 바뀜)
   - 같은 TASK가 진행 중인 다른 요청에 이미 들어 있을 때
   - 범위(`AUTO_PROJECT_ID`·`AUTO_NAME_PREFIX`)

### C. CTRL앱 (2e 일부)

10. 신호 파일의 이름·내용이 심판(`SIGNAL_REQUIRED`, `input_problem("signal")`)과 Keeper(깨우기 2차 확인)의 기대와 맞는지 봐 주세요.
11. 화면의 막힘 조건이 설계 'CTRL앱' 절과 맞는지 봐 주세요. 대상은 깨우기·보류 해제하고 깨우기·정지·해제입니다. 화면이 '살아 있음'·'보류 없음'을 잘못 보여 사람이 잘못된 신호를 보내게 되는 경우를 찾아 주세요.

### D. 다음

12. 2b(처리기 옮기기)와 LC·AA앱을 시작하기 전에 고칠 것을 최소 목록으로 적어 주세요.

## 결과 형식

- 발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
- W1~W3 각각에 '해결·부분 해결·미해결'을 적어 주세요.
