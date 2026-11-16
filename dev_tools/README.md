# dev_tools — 개발 기계에서만 쓰는 도구

`drive/scripts/`(Drive에 올라가 노트북·작업자가 실행하는 부품)와 달리, 이 폴더는 **Drive에 올리지 않습니다.**

| 파일 | 쓰임 |
| --- | --- |
| `setup.sh` | 시험 환경 준비 — rclone·Node.js를 사용자 폴더에 설치 (`AGENTS.md` 4장) |
| `build_deploy.py` | v4.33 배포 묶음 만들기 — 배포 목록(manifest) → 뿌리 노트북에 목록 해시 고정 → Keeper용 노트북 해시 출력. 결과 폴더를 관리자 폴더 `deploy/`에 올림 (`docs/DEPLOY_PLAN_v4.33.md` 6절 10번) |
