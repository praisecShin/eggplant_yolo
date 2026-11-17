# v4.33.0z7 검토 요청 (b31) — b29 W1~W5 반영 확인

번호 안내: b30은 2c-6(노트북 조립) 뒤 노트북 전체 검토로 남겨 두었습니다. 이번 검토가 b31입니다.

이번 검토 범위는 **b29 반영 확인**입니다.
- 결과: `docs/REVIEW_RESULT_v4.33.0z6_b29.md`
- 대응: `docs/IMPL_STEP2C_v4.33.md`의 'b29 반영 (v4.33.0z7)'
- 파일:
  - `drive/scripts/cells_base.py` — `_install_write_wrappers`·`_patch_transport`·`_active_writes`·`_active_cvat`, `WriteGuard.before_*`·`install`·`uninstall`, `TransportGuard.install`·`uninstall`·`patch_class`, `start`, `WriteGuard._booting`, `KST`
  - `drive/notebooks/A0_colab/cells_v4.33/cell00.py` — `_when`, `last_upload`, `BASE` 기본값
  - `cell26.py`(빈 칸 채우기), `cell11.py`(영상 이름)

**특히 봐 주세요:**
- W1: 감싸기를 한 번만 깔고 활성 세션의 가드를 따르는 방식에서 가드가 비는 순서가 남았는지. 예: `start` 도중 예외, `install` 전에 활성 세션이 바뀌는 경우, 0z6에서 깔린 감싸기가 남은 커널에서 0z7 모듈을 다시 불러온 경우, 여러 스레드가 동시에 `start`를 부르는 경우.
- W5: 새 분석 폴더를 만드는 동안의 허용(`_state()["boot"]`)이 그 폴더와 부모 말고 다른 경로로 새지 않는지.
- W2: `_when`이 다른 시각 형식(초 없음, 소수 초, `Z`)에서 틀리게 비교하는 경우.
- b29 재현(`rLog/b29_extra_probe.py`)의 다섯 조건이 모두 고쳐졌는지.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0z7_b31.md`에 써 주세요.
- 새 발견은 X1부터 번호를 붙여 주세요.
- 발견마다 '2c-3으로 넘어가기 전 필수 여부'를 적어 주세요.
- 재현 스크립트와 로그는 `rLog/b31_*`에 남겨 주세요.

```bash
python3 tests/test_cells_433.py drive          # 79개
python3 tests/test_hosts_433.py drive          # 57개
python3 tests/test_handlers_433.py drive       # 143개
python3 tests/test_e2e_433.py drive            # 17개
python3 tests/test_master_433.py drive         # 75개
python3 tests/test_arbiter_433.py drive        # 247개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_main_433.py drive    # 62개
python3 tests/test_fuzz_433.py drive
# b29 재현 다시 실행 (반영 확인)
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b29_extra_probe.py
PYTHONDONTWRITEBYTECODE=1 python3 rLog/b29_supervisor_compat.py
```
셀 시험에는 pandas·requests·IPython이 필요합니다.
