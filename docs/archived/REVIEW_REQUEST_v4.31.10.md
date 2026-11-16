# v4.31.10 재검토 요청 — v4.31.9 재검토(R1~R5) 수정 확인

v4.31.9 재검토에서 받은 R1~R5와 시험 환경 문제를 아래처럼 고쳤습니다. 각 항목이 해결됐는지, 고치면서 새 문제가 생기지 않았는지 확인해 주세요.

결과는 `REVIEW_RESULT.md`에 써 주세요. 형식은 v4.31.9와 같습니다. 항목마다 해결·부분 해결·미해결로 판정하고, 새로 발견한 문제는 R6부터 번호를 붙입니다.

| 번호 | 지적 | 고친 곳 | 시험 |
|---|---|---|---|
| R1 | 30번 `_rl_bk_poll`이 열린 백업이 없어진 것만으로 완료 처리 | `web_bridge.backup_verdict` 새로 만듦 (받음 = '최신'이고 파일 있음 · 받는 중 = 이 서버의 열린 요청 · 그 밖 = 실패). 30번 `_rl_backup`이 `_RL['bk_rows']`를 남기고 `_rl_bk_poll`이 이 함수로 판정. 실패한 TASK는 백업 요청이면 결과에 실패로, track 요청이면 `gave_up`으로. CPU 마스터 `backup_verdict`도 이 함수를 부름 | test_fix_43110 (판정, 30번 사용) |
| R2 | Kaggle 0번 셀·CPU 마스터가 환경 변수를 먼저 읽고 홈 폴더에 설정 파일을 씀 | 0번 셀: `_kg_secret`만 읽음. `tempfile.mkdtemp` 세션 폴더에 `os.open(...,0o600)`으로 만들고 `RCLONE_CONFIG`로 연결. 마스터: `setup_credentials`가 Kaggle이면 `kaggle_secrets`만 읽음(Kaggle이 아닌 로컬 시험만 환경 변수). rclone.conf·kaggle.json을 세션 폴더에 0600으로 만들고 `RCLONE_CONFIG`·`KAGGLE_CONFIG_DIR`로 연결. `KAGGLE_KEY`는 환경에 두지 않음 | test_fix_43110 (Kaggle 흉내: 환경 변수 무시·0600·홈에 안 씀) |
| R3 | 0번 셀 `_need` 함수가 끝부분 `_need = [...]`에 덮임 | 함수 이름을 `_need_secret`으로 바꿈. 시험: 0번 셀 맨 바깥 함수 이름을 어느 셀이든 맨 바깥 대입으로 덮으면 실패 (v4.31.9에서는 0번·15번 셀에서 걸림) | test_fix_43110 |
| R4 | 준비 중 백업만 남기고 GPU 워커가 끝나면 아무도 받지 않음 | CPU 마스터 `poll_waiting_backups`: 30번 셀 작업자가 없으면 `MASTER_BK_POLL_SEC`(300초)마다 '받는 중' AA 요청의 남은 TASK를 download 모드로 받음. 백업 요청은 판정해 완료·실패·받는 중을 기록하고, `MASTER_BK_GIVEUP_H`(24시간)가 지나면 포기. track·shape 요청은 손대지 않고, `gpu_pending`이 판정상 받은 TASK가 있으면 GPU 워커를 깨움 | test_fix_43110 (마스터 받기·30번 셀 작업자가 있을 때는 안 함) |
| R5 | 13번 사전 검색 0건이면 전체 백업으로 넓어짐 | 0건이면 `SystemExit` | test_fix_43110 |
| 환경 | setup.sh가 pip 없이 실패 · 마스터 시험 25초 부족 | ensurepip → get-pip.py 순서로 설치. 마스터 시험 시간은 `MASTER_TEST_SEC`(기본 40) | setup.sh 문법 확인 |

## 특히 봐 주세요
- **R4:** 같은 '받는 중' 요청을 30번 셀과 마스터가 동시에 처리할 수 있는지. 마스터는 `_STATE['aa_peer']`가 있으면 손대지 않습니다. 하지만 GPU 워커가 일하는 중에 마스터가 백업 요청 결과를 덮어쓸 가능성이 남아 있는지 봐 주세요. 이 부분은 2차 F3·F14(단일 작성자)와 이어집니다.
- **R1:** `backup_status`의 `last_file`이 비어 있는 '최신' 행을 받음으로 보는 것이 맞는지.
