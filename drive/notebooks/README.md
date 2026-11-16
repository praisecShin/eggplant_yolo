# 노트북 — 계정별

| 폴더 | 어디서 | 무엇 |
| --- | --- | --- |
| `A0_colab/` | A0 Colab | 사람이 쓰는 노트북 (v4.32) |
| `A0_kaggle/` | A0 Kaggle | 학습 노트북 (지금은 K의 보조). A0 Kaggle의 보조 실행기는 `K_kaggle/`의 GPU 작업자 노트북을 같이 씀 |
| `K_kaggle/` | K Kaggle | CPU 상주 마스터·GPU 작업자 (v4.32), v4.33 마스터 뿌리 셀 원본 `master_boot_v4.33.py` |

- **Drive에 올릴 때는 하위 폴더 없이** `eggplant_yolo/notebooks/`에 올립니다. v4.32 CPU 마스터는 Drive `notebooks/`에서 GPU 작업자 노트북을 찾습니다.
- v4.33부터 마스터·GPU 작업자 노트북은 Drive `notebooks/`가 아니라 관리자 폴더 `eggplant_admin/deploy/`에서 나옵니다. `dev_tools/build_deploy.py`가 만들고, Keeper와 마스터가 해시로 검증합니다 (`docs/DESIGN_v4.33.md` '실행 코드의 신뢰 경계').
