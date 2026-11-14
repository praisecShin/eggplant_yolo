# v4.33 구현 점검표

2026-11-14 · 설계 4판(`docs/DESIGN_v4.33.md`)을 구현할 때 하나씩 바꾸고 시험으로 확인할 목록입니다. 출처는 3판 검토 `docs/REVIEW_RESULT_b2.md`의 G5~G8·G11과 3~5절입니다. 위치는 v4.32.0 기준이며, 셀 줄은 각 코드 셀 안의 줄 번호입니다.

표시: [ ] 할 일 · 각 항목 끝의 (시험)은 그 항목을 확인할 시험입니다.

## A. 실행 컨텍스트와 모드 (G5)

- [ ] 모드 변수 이름을 `EGG_ACCESS`로 새로 둠. 12번 셀의 `RUN_MODE='cli'`와 섞이지 않게. 값은 `analysis`·`exec` 둘만, 모르는 값은 쓰기 거절 (시험: 12번 실행 뒤에도 analysis 유지)
- [ ] 실행 권한은 `ExecContext(요청ID, 세션S, decisionID, 허용 자원)` 객체로 넘기고 finally에서 거둠. 30번 셀이 다른 셀 코드를 실행할 때도 이 객체만 씀 (시험: 30번 중단 뒤 다른 셀에서 쓰기 거절)
- [ ] CVAT 접속 factory 하나: `ctt.connect`, 0번 `cvat_client`·`use_cvat`(765~773, 808~845), `_CVAT_SESSIONS` 캐시. 분석 caller에게 raw client·캐시를 넘기지 않음
- [ ] 허용 동작 목록 (분석): 읽기, 참조용 export 준비·상태·받기(`ctt.request_export` 366·`ctt._export` 313~338). 메서드 이름 추측으로 막지 않음
- [ ] 막을 동작 (분석, 컨텍스트 없을 때): `ctt.import_tracks`(427~432), `ctt.replace_annotations`(441~460, 최초 remove와 복원 모두), `ctt.auto_annotate_frames`(1583~1589 update_annotations), 0번 `label_uploaded`(1298 task.update), 16번(75~82 create_from_backup·update), 17번(85 create_from_data), 27번(151~164) (시험: 각각 분석 모드에서 거절)
- [ ] `cvat_backup.new_session/login/logout`(214~271)·`request_backup`(292~302): factory 경유 또는 분석에서 호출하지 않게 분기. 13번은 분석에서 상태 보기만
- [ ] 12번 CLI/module: 분석 허용 스크립트 목록과 출력 인자를 넘김
- [ ] 보안 비밀을 명령행·요청·작업 파일에 넣지 않음 (기존 0600 임시 파일 약속 유지)

## B. 파일 쓰기 (G6)

- [ ] 공유 입력 BASE(읽기)와 분석 출력 OUTPUT_ROOT 분리. BASE를 통째로 바꾸지 않음 (모델·기록 입력을 찾아야 하므로)
- [ ] 저장 도우미: 모든 저장이 출력 위치·컨텍스트를 받고, 돌려준 경로가 허가 범위인지 확인
- [ ] 좁은 예외 API: 요청 만들기, 확인 결과 신호, 자기 `workers/` 생존 신호, 제출본
- [ ] 0번 613~622 `logs/versions.csv` 직접 append → 세션 로그로 (시작만 해도 쓰는 곳)
- [ ] 0번 133~145·320~338 `drive_push`·백그라운드 push·변경 전부 업로드·삭제 → 분석은 OUTPUT_ROOT만, 실행기는 승인 범위 목록만, 원격 삭제 없음
- [ ] 0번 `task_dir/upload_log/change_report/job_start` → 분석 출력과 실행 기록을 컨텍스트로 구분
- [ ] 4번 23~26·67 `compute_stats`의 label_stats 캐시·reports CSV → 저장 안 하는 조회 또는 분석 폴더
- [ ] 5·7·11번 XML·기준/검수 export·subprocess 로그·진단 png → 부모가 정한 출력 경로를 하위 스크립트에 넘김
- [ ] 14번 96·162 export 재사용 copy·pending CSV·manifest → 분석은 상태 보기만
- [ ] 21번 97·110, 24번 208~209·261, 26번 95 HTML·CSV 직접 쓰기 → OUTPUT_ROOT
- [ ] 23번 9·32~33 reports/revisions CSV·복원 목적지, `drive_revisions.pin`(206~219) → 분석에서 `RV_PIN` 끔, pin·restore는 관리 일 (시험: 분석 23번 실행 시 revisions.update 0회)
- [ ] 27·32·33번 json.dump·to_csv·TASK history·sim CSV → 분석 폴더. `rb.add_history`·`write_test_tasks`를 분석에서 부르지 않음
- [ ] 28번 snapshots refresh·stats/corrections/state 저장·settle → 분석은 읽기만, 새로 고침은 요청
- [ ] scripts 전반 `Path.write_text`·csv writer·이미지 save·`shutil`·`os.replace` → 저장 도우미로 (시험: 분석 모드로 전 셀 실행 뒤 BASE 변경 0건)

## C. '이 결과 올리기' (G7)

- [ ] `submissions/<M>/<제출ID>/` 고정 사본과 제출 정보(해시·크기·형식·TASK ID·서버·프레임 범위·프레임맵·라벨 이름·모델·설정·교체/덧붙임 동의)
- [ ] 5번 track_settings, 9·10번 자동 라벨, 27번 앙상블(67~111) 결과를 제출본 형식으로 내보내기
- [ ] 실행기 처리기: 받기 → 해시 확인 → TASK 프레임 수·라벨 정의 검사 → 그 바이트를 올리기. shape·ensemble 형식 지원 (지금 올리기는 track_pending 중심)
- [ ] 시험: 제출 뒤 분석 파일 변경·삭제, 다른 TASK에 붙인 제출, 라벨 정의가 바뀐 TASK

## D. 모델·데이터셋 읽기 보호 (G8)

- [ ] 0번 `need_file`·`drive_pull`, 27번 25~38, 32번 모델 로드, 2·3번 검증: 받을 때 해시 확인, 사라졌거나 다르면 '다시 시도' 실패
- [ ] `ctt.cleanup_plan`(2276~2310)·29번·FORCE_NEW·23번 복원: 바로 지우지 않고 `trash/`로
- [ ] 학습 출처의 지문과 실제 받은 모델 해시가 같은지 기록
- [ ] 시험: 정리 중 모델 받기, 초기화 중 분석 모델 읽기

## E. 취합 일 분리 (G11)

- [ ] CPU 마스터 `aggregate_and_sync_state`(887~953)·AA_STATE_KINDS(74)의 쓰기 전수 분리:
  - settle(요청 종료) → 요청 소유 실행기
  - repair_pending·shard 쓰기 → 해당 실행기
  - 사라진 TASK 이력 → 그 TASK 권한 경로
  - compaction·원격 삭제 → 청소(관리 일)
- [ ] `relabel_bridge.update_tracked`(84~115): 숨김·숨김 해제·새로 고침은 취합 일만 처리
- [ ] 취합 전 최신 `tracked.json` 받기, 게시 파일에 epoch·회차
- [ ] 시험: 숨김 요청과 취합 동시, 취합 재시작 뒤 같은 결과

## F. 확정·결과 (b2 4절)

- [ ] `replace_annotations`의 최초 remove를 try 안으로, 삭제·업로드·복원 성공 여부를 구조화해 돌려줌 (`완료`, `실패(복원됨)`, `부분 반영`, `확인 필요`)
- [ ] `auto_annotate_frames`를 '로컬 완성'과 '올리기'로 분리. 올리기는 전체 프레임 검사·500개씩 쓰기·사람 라벨 보호·프레임 매핑·직전 백업·기존 반환/기록 호환 (b1 4절)
- [ ] 30번 `_rl_shape_one`(449~488)·`_rl_track_one`(535~579): shape도 결과 파일로 저장 → 복구 자료 게시 → CVAT 쓰기 순서
- [ ] `UploadLog.finish`(1795~1810): 단계 기록과 연결
- [ ] 확정 신청 파일 이름에 작업번호, 필드에 요청ID·묶음ID·epoch·gen·decision ID

## G. 프로세스 분리와 기능 보존 (b2 5절)

| 기능 | 할 일 |
| --- | --- |
| 백업 | [ ] `run_cpu_backup_and_export`를 worker_cpu로, 호출별 설정·자기 임시 폴더·자기 S. 5개 분할과 검토 완료 export 자동 결합 유지 |
| export | [ ] 새 파일·TASK manifest 게시와 완료 근거 보존 |
| 받는 중 | [ ] `poll_waiting_backups`: 소유자 확인, 받기만으로 요청 완료하지 않음, 다음 확인 시각을 ARBITER 깨우기 정보로 |
| 취합 | [ ] CPU 전담. 긴 백업·관리 일과 같은 프로세스에서 기다리지 않게 취합은 별도 실행 |
| GPU 깨우기 | [ ] `start_gpu_worker_if_needed`·routing·kernel metadata·중복 기동 완화를 작업 프로세스로, GPU 큐 작성자는 마스터 |
| 정지 | [ ] STOP hold/until·수동 기상·TASK 사이 중지·부모 종료 시 GPU 멈춤을 신호 3단계와 배정 '멈춤'으로 (`read_stop_signal` 602~624) |
| 생성·복원 | [ ] 16·17번 생성/복원 요청 종류·처리기·routing·실패 결과 (지금 30번 `_LC_CELL`에 없음) |
| 23번 | [ ] Colab 실행기 전용 관리 일, Drive OAuth 경로 유지 |
| 27번 | [ ] '이 결과 올리기'로 (EN_UPLOAD 대체) |
| 관리 일 대기열 | [ ] 들어온 순서·취소, 앱에 대기 순서 표시 |
| 상태 갱신 | [ ] 앱이 캐시 상태와 마지막 갱신 시각을 구분해 표시 |
| 스냅숏 소비자 | [ ] `wb.snapshots(refresh=True)`, `_manifest.json/.csv`, 15번·수집기 CSV → 새 `_manifest/*.json`·`web/snapshots.json`. 학습 폴더·TASK 최신본 선택·고정 시험 제외 유지 |
| 청소·가중치 | [ ] 34번이 `trash/runs/` 30일 정리 (결정 5) |
| worker_cpu 경계 | [ ] 실행마다 별도 임시 root·세션 ID·작성 파일 목록. 부모의 initial_pull·aggregate copy가 자식 작업 파일을 덮지 않게 |

## H. 행동 시험 (b2 6절)

- [ ] 분석 모드: 전 셀·하위 스크립트·Drive pin이 허용 범위 밖에 쓰지 않음. 12번·30번 뒤에도 유지
- [ ] 승인 직전 취소·만료·모름, 부분 decision 게시, epoch 교체와 이전 실행기 끝 보고, 관리 프로세스 실종 → 두 실행이 같은 곳에 쓰지 않음
- [ ] CVAT 반영 전후 단계별 종료 → 복구 자료가 남음. 사람이 고른 복구가 앞 실행과 겹치지 않음 (권한 잃은 실행기가 복원하지 않음)
- [ ] 신호 효과 뒤 완료 전 종료 → 효과 한 번. heartbeat와 판정 저장 교차 없음(작성자 분리). waiting만 남은 재기상. STOP/RELEASE 재시작 뒤 한 번만
- [ ] 재시작 점검 보고서가 위 상황을 모두 '이상'으로 찾음
- [ ] 제출본 변경·다른 TASK 매핑, 정리 중 모델 받기, 스냅숏 요약·15번 학습 입력·고정 시험 제외 연결
