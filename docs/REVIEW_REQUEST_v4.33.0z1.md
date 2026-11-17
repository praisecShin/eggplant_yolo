# v4.33.0z1 검토 요청 (b26) — b25 F1·F2 반영 확인 (좁은 범위)

이번 검토는 2c(사람용 셀)로 넘어가기 전 확인입니다. 범위는 0z1 하나입니다. b25 결과(`docs/REVIEW_RESULT_v4.33.0z_b25.md`)의 F1은 2c 전 필수였습니다.

**범위:**
1. **F1 학습 프로세스 묶음 정리:**
   - 위치: `drive/scripts/h_run.py`의 `RealTrainer.train`의 `finally`, `_group_alive`, `_kill`
   - 리더가 끝났는지가 아니라 묶음에 남은 프로세스가 있는지로 판단합니다.
   - 정리 순서: TERM → 묶음이 빌 때까지 기다림 → 남으면 KILL → 다시 확인 → 그래도 남으면 실패.
   - 정상 끝·리더의 먼저 실패·권한 상실 모두 같은 정리를 거칩니다. 원래 예외는 그대로 전달합니다.
2. **F2 모델 목록 오류 격리:**
   - 위치: `drive/scripts/h_agg.py`의 `_valid_entry`, `adopted_models(store, skipped)`, relabel 상태의 `models_skipped`
   - 깨진 목록이면 그 모델만 빼고, 뺀 이유를 남깁니다.

설명은 `docs/IMPL_STEP2B_v4.33.md`의 'b25 반영' 절에 있습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0z1_b26.md`에 써 주세요.
- 새 발견은 U1부터 번호를 붙여 주세요.
- 발견마다 '2c로 넘어가기 전 필수 여부'를 적어 주세요.
- 재현 스크립트와 로그는 `rLog/b26_*`에 남겨 주세요.

```bash
python3 tests/test_hosts_433.py drive          # 44개 (F1·F2 회귀 포함)
python3 tests/test_handlers_433.py drive       # 140개
python3 tests/test_e2e_433.py drive            # 17개
python3 tests/test_master_433.py drive         # 75개
# b25 재현 다시 실행
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b25_process_probe.py
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b25_model_probe.py
```

## 검토 질문

1. F1·F2에 '해결·부분 해결·미해결'을 적어 주세요. `rLog/b25_process_probe.py`·`b25_model_probe.py`를 다시 실행해 주세요.
2. **F1 경계:**
   - 묶음 확인(`os.killpg(묶음, 0)`)이 다음 경우에 틀리게 판단할 수 있는지 봐 주세요.
     - 좀비만 남은 경우
     - 하위 프로세스가 스스로 새 세션(`setsid`)을 만들어 묶음을 벗어난 경우
     - 권한이 없는 경우(`PermissionError`)
   - Ultralytics DDP(`torch.distributed.run`)의 자식이 같은 묶음에 남는지 봐 주세요. 공개 소스를 기준으로 봐 주시면 됩니다.
   - 묶음을 끝내지 못해 '수동 확인 필요' 실패가 났을 때, 실행기·심판이 그 학습을 어떻게 다루는지 봐 주세요. 결과 보고와 '확인 필요' 연결이 맞는지도 봐 주세요.
3. **F2 경계:**
   - `legacy` 등록(`paths`)이나 `train.json`이 깨진 경우가 정상 모델에 영향을 주는지 봐 주세요.
   - 웹 상태(`WebState._models`)도 같은 격리를 따르는지 봐 주세요.
4. **학습 자식의 쓰기 격리 (11/17 결정):**
   - 결정 내용: 학습 프로세스는 자기 작업 폴더에만 씁니다. 사람 작업자와 앱 작업이 동시에 여럿 돌아도 기록을 덮지 않아야 합니다.
   - Ultralytics가 작업 폴더 밖에 쓰는 것을 봐 주세요. 예: 설정·캐시(`~/.config/Ultralytics`), 자동 연동, 데이터셋 캐시 파일.
   - 실행끼리 겹칠 수 있는 것이 있으면 적어 주세요. b25 '보지 못한 항목'에 있던 내용입니다.
