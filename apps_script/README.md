# Apps Script — 계정·프로젝트별

| 폴더 | 계정·프로젝트 | 트리거 | 상태 |
| --- | --- | --- | --- |
| `G_collector/` | G 계정, 프로젝트 '수집기' — `Collector.gs` + `Uld.gs` + `appsscript.json` | `installTrigger()` (10분) | v4.33, 전환 때 설치 |
| `G_keeper/` | G 계정, 프로젝트 'Keeper' (수집기와 **다른 프로젝트**) — `Keeper.gs` + `appsscript.json` | `installKeeperTrigger()` (1분) | v4.33, 전환 때 설치 |
| `K_legacy_v4.32/` | K 계정, 지금 운영 중인 프로젝트 — `Code.gs`(+ 운영 프로젝트에는 `Uld.gs`도 있음, `G_collector/Uld.gs`와 같은 파일) | collect·dispatch | v4.32 운영. 전환 때 트리거를 끄고 CVAT 토큰을 지움 |

- A0 계정에는 Apps Script가 없습니다.
- 모든 프로젝트는 웹앱으로 배포하지 않습니다 (`doGet`/`doPost` 없음).
- Script Properties는 `docs/DEPLOY_PLAN_v4.33.md` 2절 표를 따릅니다. 예행 연습은 같은 G 계정에 `collector_test`·`keeper_test` 프로젝트를 따로 만들고 속성만 시험 값으로 넣습니다 (8절).
- `G_*`의 `appsscript.json`에는 메일 권한(`script.send_mail`)이 있습니다 — Keeper 알림, Uld.gs 중복 알림.
