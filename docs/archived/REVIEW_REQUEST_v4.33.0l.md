# v4.33.0l 검토 요청 — b18 Y1~Y6 반영

`docs/REVIEW_RESULT_v4.33.0k_b18.md`의 Y1~Y6을 고쳤습니다. 보충 항목 중 두 가지도 함께 고쳤습니다.
- 수집기가 실행할 때마다 실패할 때의 멈춤 알림
- CTRL앱에서 같은 이름 최상위 폴더가 여럿일 때

Y3는 11/16 결정대로 고쳤습니다. 아직 요청을 만들지 않은 같은 TASK·같은 종류의 사건은 최신 하나로 합쳐 최종 상태를 export합니다.

대응표는 `docs/IMPL_STEP2D_v4.33.md`의 'b18 반영'에 있습니다. 설계서의 '보호 모드' 절과 'G 입력' 아래 '수집기 자동 요청'도 보충했습니다. 배포 계획에는 예행 연습 확인 T17(실제 Drive 검색)을 더했습니다.

고친 파일:
- `drive/scripts/arbiter.py`
- `apps_script/G_collector/Collector.gs`
- `apps_script/G_keeper/Keeper.gs`
- `apps/ctrl/index.html`
- 시험 5개

`Uld.gs`, 노트북, v4.32 파일은 고치지 않았습니다.

**코드·노트북·시험·설계서는 고치지 마세요.** 결과는 `docs/REVIEW_RESULT_v4.33.0l_b19.md`에 써 주세요. 새 발견은 Z1부터 번호를 붙여 주세요. 재현 스크립트도 로그와 함께 `rLog/`에 복사해 두시면 다음 검토에서 다시 돌릴 수 있습니다.

```bash
python3 tests/test_arbiter_433.py drive        # 218개
python3 tests/test_access_433.py drive         # 68개
python3 tests/test_master_433.py drive         # 65개
python3 tests/test_master_main_433.py drive    # 61개
python3 tests/test_fuzz_433.py drive           # 9개
FUZZ_SEED=7 FUZZ_N=5 python3 tests/test_fuzz_433.py drive   # 2분 넘게 걸릴 수 있음
node tests/test_collector.js apps_script/G_collector/Collector.gs apps_script/G_collector/Uld.gs   # 61개 — Keeper보다 먼저
node tests/test_keeper.js apps_script/G_keeper/Keeper.gs          # 118개
npm i jsdom && node tests/test_ctrl_app.js apps/ctrl/index.html   # 32개
```

## 검토 질문

1. Y1~Y6 각각에 '해결·부분 해결·미해결'을 적어 주세요. b18 재현(`/tmp/b18_*` 또는 `rLog/`)이 남아 있으면 다시 돌려 주세요.
   - 옛 가짜 Drive에는 0l이 쓰는 `getId`와 `searchFiles`가 없을 수 있습니다. 공식 시험(`tests/test_collector.js`)의 가짜 Drive를 써 주세요.
2. **Y1 관리자 권한:** 관리자 권한은 이제 계획의 `admin` 칸을 쓰지 않습니다. 매번 지금 신호 소유자의 권한으로 정합니다. 다음 경우를 봐 주세요.
   - G가 만든 해제 신호(원래 신호를 연결한 것)
   - 사람 목록을 못 읽은 회차
   - 신호 소유 계정을 모르는 회차
   이때 관리자 권한이 잘못 주어지거나 처리가 멈추는 경로가 있는지 봐 주세요. 퍼징의 새 불변 조건(계획의 admin·requester만 바뀌면 보호 모드이거나 효과가 같음)이 충분한지도 봐 주세요.
3. **Y2 목록 형태 검사:** 형태가 틀리면 수집기가 계속 실패합니다. 이것이 사건을 잃는 것보다 나은 선택인지 봐 주세요. Keeper의 `last_ok` 멈춤 알림과 CTRL앱 표시로 관리자가 알게 되는 경로가 충분한지도 봐 주세요. 검사 칸이 넘치거나 모자란 곳도 찾아 주세요.
4. **Y3 합치기:** 새 사건은 '아직 만들기를 시도하지 않은 묶음'에만 합칩니다. 시도한 묶음 뒤에 같은 TASK 사건이 오면 다음 요청이 됩니다. 이 경계에서 사건이 빠지거나, 지난 상태가 최신으로 잘못 기록되는 경우를 찾아 주세요. 최신을 고르는 기준은 `updated`, 같으면 넣은 시각입니다.
5. **Y4 중복 방지:** 순서는 `attempt_at` 저장 → 만들기 → `file_id` 저장입니다. 다음을 봐 주세요.
   - ID가 있으면 이미 만든 것으로 보는 규칙
   - 10분 기다림
   - 심판의 같은 요청 ID 하나로 접수(최신 수정 파일 기준)와 `duplicate_request` 알림
   - 같은 이름 파일 둘을 rclone이나 실행기가 다룰 때의 문제
6. **Y5 CTRL앱:** 버튼·대화상자 열기·보내기가 같은 판단 함수(`allowed`)를 씁니다. 새로 읽은 뒤에는 대화상자를 다시 확인합니다. 읽기에 실패하면 제어를 막습니다. 이 상태에서도 잘못된 신호가 나가거나, 맞는 신호가 계속 막히는 경우를 찾아 주세요.
7. **Y6 Keeper 보낼 목록:** 보호 모드 알림은 상한과 상관없이 남깁니다. 버린 일반 알림은 '보냄' 이력에서 지우고 요약을 보냅니다. 이때 알림이 끝없이 되풀이되거나 `keeper.json`이 계속 커지는 경우를 봐 주세요.
8. 2b(처리기 옮기기)를 시작하기 전에 더 고칠 것이 있으면 최소 목록으로 적어 주세요.

## 결과 형식

발견은 지금까지와 같은 표로 적어 주세요: 번호·심각도·관점·종류·위치·문제·조건·확신·제안.
