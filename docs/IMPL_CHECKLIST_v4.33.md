# v4.33 구현 점검표

2026-11-14 · 설계 8판(`docs/DESIGN_v4.33.md`)을 구현할 때 하나씩 바꾸고 시험으로 확인할 목록입니다. 출처는 3판 검토 `docs/REVIEW_RESULT_b2.md`의 G5~G8·G11과 3~5절, 4판 검토 `docs/REVIEW_RESULT_v4.33_b4.md`의 H1~H7, 5판 검토 `docs/REVIEW_RESULT_v4.33_b5.md`의 J1~J10, 6판 검토 `docs/REVIEW_RESULT_v4.33_b6.md`의 K1~K6, 7판 검토 `docs/archived/REVIEW_RESULT_v4.33_b7.md`의 L1~L3입니다. 구현 1a에서 끝낸 항목은 [x]로 표시했습니다 (`docs/IMPL_STEP1A_v4.33.md`). 위치는 v4.32.0 기준이며, 셀 줄은 각 코드 셀 안의 줄 번호입니다.

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
- [ ] `ctt.cleanup_plan`(2276~2310)·29번: 지우지 않고 채택 안 된 버전에 '정리 대상' 표시만. FORCE_NEW는 채택 표시만 바꿈. 23번은 새 버전 경로로 복원 뒤 채택
- [ ] 학습 출처의 지문과 실제 받은 모델 해시가 같은지 기록
- [ ] 시험: 정리 중 모델 받기, 초기화 중 분석 모델 읽기

## E. 취합 일 분리 (G11)

- [ ] CPU 마스터 `aggregate_and_sync_state`(887~953)·AA_STATE_KINDS(74)의 쓰기 전수 분리:
  - settle(요청 종료) → 요청 소유 실행기
  - repair_pending·shard 쓰기 → 해당 실행기
  - 사라진 TASK 이력 → 그 TASK 권한 경로
  - compaction·원격 삭제 → 청소(관리 일)
- [ ] `relabel_bridge.update_tracked`(84~115): 숨김·숨김 해제·새로 고침은 취합 일만 처리. 이 요청은 처음부터 취합 일에 배정하고, 취합 일이 반영 뒤 요청 최종 상태를 씀 (H7)
- [ ] 취합 전 최신 `tracked.json` 받기, 게시 파일에 epoch·회차
- [ ] 시험: 숨김 요청과 취합 동시, 취합 재시작 뒤 같은 결과

## F. 확정·결과 (b2 4절)

- [ ] `replace_annotations`의 최초 remove를 try 안으로, 삭제·업로드·복원 성공 여부를 구조화해 돌려줌 (`완료`, `실패(복원됨)`, `부분 반영`, `확인 필요`)
- [ ] `auto_annotate_frames`를 '로컬 완성'과 '올리기'로 분리. 올리기는 전체 프레임 검사·500개씩 쓰기·사람 라벨 보호·프레임 매핑·직전 백업·기존 반환/기록 호환 (b1 4절)
- [ ] 30번 `_rl_shape_one`(449~488)·`_rl_track_one`(535~579): shape도 결과 파일로 저장 → 복구 자료 게시 → CVAT 쓰기 순서
- [ ] `UploadLog.finish`(1795~1810): 단계 기록과 연결
- [ ] 확정 신청 파일 이름에 작업번호, 필드에 요청ID·묶음ID·작업번호·epoch·gen·decision ID·S·TASK
- [ ] 승인·확정 끝·반납·결과 보고도 같은 식별 묶음. 심판은 묶음 전체가 맞을 때만 반영, 옛 보고는 거절·기록 (H7) (시험: 같은 세션의 이전 TASK 끝 보고가 늦게 도착)
- [ ] 확인-호출 틈 재확인: 권한 확인 시각(단조 시계)과 호출 직전 차이 5초 초과면 다시 확인 (H1)
- [ ] 단계 기록 의도/결과를 CVAT 호출마다, 결과 구조에 `확인 필요` 포함
- [ ] '확인 필요' TASK가 남은 요청은 '완료' 불가, 복구 일 결과를 원요청 TASK 결과에 연결 (시험)

## F2. 신호·관리 일·감시 (H2·H3·b4 4절)

- [ ] 버전 경로 `runs/<모델>/v/<실행ID>/`·`datasets/<이름>/v/<실행ID>/`·`config/test_tasks/v/<실행ID>.json`, 끝에 `_files.json`(파일·해시·실행 ID·decision·gen) (J2·J5)
- [ ] 채택 표시 `CURRENT.json`은 심판만 씀. 관리·학습 잠금의 decision·gen·실행 ID가 맞는 완료 보고만 채택 (시험: B 채택 뒤 A의 늦은 목록 파일 → 채택 안 됨)
- [ ] 읽는 쪽 전환: 학습 목록(`runs/*` 열거), 추론·검증·27·32번 모델 선택, 데이터셋 사용, 15번 학습 입력, 시험 TASK 제외(`load_test_tasks` 등)가 `CURRENT.json`만 따름
- [ ] 옛 산출물을 `v/legacy/`로 등록(옮기지 않고 목록만), 운영 전환 단계에 포함
- [x] (1a) 학습 시작 호환: 데이터셋 출처 `task_keys`와 지금 시험 설정 대조, 겹치면 시작 안 함, 출처 없으면 '호환 확인 불가' → 결과 채택 대기
- [x] (1a) 같은 회차 시험 설정 채택·모델 완료는 도착 순서와 상관없이 같은 결과
- [ ] 학습 줄: `locks/train/<모델>.json`, 시작 때 데이터셋·시험 설정·시작 가중치 버전 고정, 채택 gen이 바뀌었으면 '채택 대기' (시험: 학습 중 복원 → 채택 대기, A→B→A도)
- [ ] 0번 학습 callback(934~963)의 에폭별 Drive 게시·DDP 프로세스를 실행별 버전 경로로. background push가 끝난 뒤 `_files.json` 게시, 그 뒤 버전 파일 불변 (시험)
- [ ] 학습 중 설정 변경: 새 시험 설정 채택 때 모델 학습 출처(학습·검증 TASK 키, 그루·촬영일 묶음)와 대조 → '새 시험 기준 오염'·평가 제외·채택 대기 (K5) (시험: T0 학습 중 T1에 학습 TASK 추가 → 오염 표시·자동 채택 안 됨)
- [ ] `AGENTS.md` 약속 8에 '학습 시작 때 채택된 시험 설정 버전 기준, 이후 변경은 오염 표시' 문구
- [ ] 청소: 심판의 버전 참조 등록과 청소 대상 확정 순서, 참조 상태를 못 읽으면 삭제 보류 (시험: 청소 계획 뒤 새 참조 생김)
- [ ] legacy 등록: 목록이 버전 경로 밖 옛 파일을 가리키는 형식·허용 경로, 청소는 legacy 원본을 지우지 않음 (시험: 전환 뒤 파일 삭제·학습 재실행 없음)
- [ ] 관리 일 비켜 두기: 실행기가 돌아오면 원접수 순서상 앞인 비켜 둔 일부터, 실행 중 관리 일은 선점 안 함
- [ ] 관리 일 대기열 '실행기 대기' 비켜 두기 (시험: 23번이 앞에 있고 Colab 없음 → 다음 CPU 관리 일 진행)
- [ ] '끝난 것으로 처리'는 버전 목록 검증·decision 일치 때만 (시험: 일부 게시 상태에서 선택 거절)
- [ ] 신호: 계획에 관측 순번·논리 대상·효과 목록. 효과마다 신호 ID 완료 증거(`by_signal`·`REQ_rcv__<ID>`·`cancel_signal`). 재시작 때 다시 발급 뒤 효과별로 반영됨/적용/무효화(이유)/새 소유자 적용. gen 불일치만으로 완료 처리 금지 (K1) (시험: 취소 계획 gen3 → 종료 → gen4 재배정 → 복구 뒤 취소 적용됨. 잠금만 반영 뒤 종료 → 복구 요청 생성됨. 효과 게시 → epoch 교체 → 새 상태 유지)
- [ ] 취소는 요청 접수 기록의 `cancel_signal`, 실행기는 매 TASK 시작 전 확인
- [ ] Kaggle 커널 실행 상태 조회로 옛 실행기 종료 확인 (마스터 작업 프로세스에서)
- [ ] CVAT 진행 중 가져오기 조회(지원 버전일 때)
- [ ] 승인 없는 쓰기 감시: 수집기 `updated_date`와 단계 기록의 승인 쓰기 기간 대조, 밖이면 알림·'확인 필요' (시험: 승인 기간 밖 수정 감지. 승인 기간 안의 늦은 쓰기는 못 잡음을 시험에 명시)
- [ ] 강제 해제·종료 미확인 해제 TASK의 사후 비교: 다음 실행 뒤 export 결과와 기대 결과를 정규화한 내용으로 비교, shape·track·덧붙임별 기대 최종 상태 (J6)
- [ ] 관리자 강제 해제: 남는 위험 문구 표시·관리자 확인·기록
- [ ] 정기 점검 '멈춘 것 같음'(단계 기록 정체), '실행기 필요'(Colab 전용 대기) 표시
- [ ] 공용 `exports/pending_exports.csv`·`backups/pending_backups.csv` → 요청·TASK별 `…/pending/<요청ID>__<TASK>.json`, 요약은 취합 일. CPU 마스터 `run_cpu_export`(781~823), `cvat_backup.py`(596~597·658·697·705) 전환 (J1) (시험: 서로 다른 TASK 동시 백업·export 뒤 두 기록 모두 남음)
- [x] (1a 판정) 번호 모르는 새 TASK 후보 판정 `judge_create_candidates`: 빈 후보는 서버 작업 ID 증거 없으면 확인 필요 (L3)
- [ ] 새 TASK 만들기(16·17번): `locks/create/<이름 해시>` 하나씩, 작업번호별 의도, 빈 TASK 만들기 → 번호 기록 → 미디어 올리기 → 이름 꼬리표, 응답 모르면 후보 검색·원본·프레임 수 검증, 못 정하면 '확인 필요' (J7·K6) (시험: 같은 이름 동시 요청, 서로 다른 원본, 꼬리표 전 종료, 한 요청의 여러 만들기)
- [ ] 청소 보존 조건: 완료 없는 신호 계획, '확인 필요'·'채택 대기' 실행과 단계 기록, 복구 참조 자료, 진행 중 참조 버전, 채택 버전은 기간과 무관하게 보존. 완료 기록을 원신호보다 먼저 지우지 않음
- [ ] `AGENTS.md` 약속 7에 '읽기만 하는 백업·export의 받는 중은 TASK 순서 예외(라벨 버전 기록)' 문구 반영 (G9)

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
| 청소·가중치 | [ ] 34번이 정리 대상 표시 뒤 30일 지난, 채택 안 되고 참조 없는 버전만 지움 |
| worker_cpu 경계 | [ ] 실행마다 별도 임시 root·세션 ID·작성 파일 목록. 부모의 initial_pull·aggregate copy가 자식 작업 파일을 덮지 않게 |

## I. Keeper·CTRL앱·people.json (11/14 결정, H4·H6)

- [ ] `Code.gs`에서 `triggerGhDispatch_`(719~731)·`wakeUpCpuMaster_`(639~659)의 GitHub 경로, 설정 점검의 `GITHUB_TOKEN`·`GITHUB_REPO` 출력(126~127) 삭제
- [ ] 새 `Keeper.gs`: Kaggle API push (CPU slug·GPU 끔·기동 이유·시각을 push metadata/기록으로 이관), `deploy/` 노트북 해시를 `MASTER_NB_SHA256`과 비교, 다르면 push 안 함·알림
- [ ] Script Properties `KAGGLE_USERNAME`·`KAGGLE_KEY`·`MASTER_NB_SHA256`. 오류 기록·메일에 Kaggle 응답 원문 넣지 않음. Keeper 프로젝트 편집자는 관리자 하나
- [ ] 정지 보류 판정 하나: 주간 상시·할 일 깨우기·버튼 모두 거침. 예외는 관리자 '보류 해제하고 깨우기' + 정지 ID 정확히 일치 (시험: 보류 중 일반 깨우기·해제 신호만 있는 경우 안 깨움)
- [ ] 기존 의미 이관: 주간 08~19 상시, 야간 승인 작업 깨우기, STOP hold/until, `wakeCpuMasterNow`(STOP 지우고 깨움) → 관리자 동작
- [ ] 깨우기 2차 확인: Drive 소유 계정, 최신 people `active`·`wake`(못 읽으면 거절), 신호 생성 뒤 미수정·10분 이내, 심판 없음, 10분 제한 (시험: 다른 계정 소유 신호, stopped 사람, 수정된 신호, 오래된 신호)
- [ ] `jobs/wake_done/<신호ID>.json` 시도 ID·단계 기록 → push → 결과. 재시작 때 심판 생존·Kaggle 커널 상태로 판정, 모르면 10분 뒤 한 번만 재시도 (J8) (시험: 예약 직후 종료, push 접수 직후 종료)
- [ ] '보류 해제하고 깨우기' 동작 ID 하나로 두 단계 묶기, 남은 단계만 이어 함
- [ ] 깨우기 조건: ARBITER의 `next_wake_at`(현재 시각과 비교), '지금 실행할 수 있는 일 수'(밤에는 야간 승인 일만), `observed_from`과 본 요청 ID 목록 밖의 새 요청, 새 실행기 등장, 깨우기 신호는 `wake_done`과 비교, 거절·실패도 처리됨, 밤에는 복구·제어 신호만 (J3·K4) (시험: 완료 wake만 남은 밤·미승인 대기만 남은 밤 → 안 깨움, count=0으로 꺼진 뒤 next_check 도래 → 깨움, 목록 읽기와 회차 게시 사이 새 요청 → 깨움)
- [ ] Keeper 재시도 때 최신 보류·권한·정지 ID 다시 검사, '처리 중'은 완료 파일 존재만으로 건너뛰지 않음
- [ ] `config/people.json`: M1만(admin, request·wake·release, active). 마스터·Keeper 10분마다 재읽기, 미등록·stopped는 분석 모드만·요청 거절
- [ ] `deploy/` 폴더 권한: 관리자 편집, 다른 계정 보기 (운영 점검)
- [ ] CTRL앱: 감시·점검·관리 일·제어 화면, 깨우기 버튼(1차 확인), 진행 6단계 표시, 관리자 강제 해제 화면
- [ ] 관리자 Google 계정 2단계 인증 확인 (운영 점검)

## J. 계정·신원·실행 코드 (J9·J10·K2·K3)

- [ ] `config/accounts.json`: A0(재웅님 Google)·K(Kaggle 실행 환경, Drive는 A0 토큰)·G(Apps Script Google)와 역할
- [ ] 심판 입력 읽기: 소유 계정으로 허용 입력 표 판단, 파일 안 사람 번호 불신, 미등록·stopped·권한 없음 거절, 소유 계정 못 읽으면 '모름'
- [ ] 접수 기록 `jobs/intake/<요청ID>.json`(요청자·소유 계정·시각·권한). 상태 이름 바뀜·재게시 뒤에도 요청자 유지, 접수 기록 없는 요청은 실행 안 함 (시험: 다른 계정 실행기가 상태 바꾼 뒤 요청자 유지)
- [x] (1a 판정 쪽) 판정 파일은 세션 지문(`by_session`·`by_epoch`)이 자격과 맞을 때만 믿음, 자격은 G 소유만 (시험: 표시 없는 손 파일·같은 epoch 다른 세션 무시)
- [ ] (1b 실행기 쪽) 30번 셀·GPU 작업자가 `executor_may_follow`로 판정 파일을 확인
- [ ] 세션 ID `<환경>-<지문>-<시각>-<난수>`, 생존 신호 `workers/<세션>__<지문>.json`, 같은 세션 두 지문이면 일 주지 않음 (1a 판정 쪽 [x], 실행기 쪽 1b)
- [ ] 복구 요청은 신호 계획 + 세션 지문 있는 것만 '시스템(심판)' 접수 (1a [x])
- [ ] 배정 때 지금 people로 권한 재확인 (1a [x])
- [ ] Keeper가 만든 해제 신호: G 소유 + 원래 관리자 신호 ID, 심판이 원래 신호의 A0 소유·관리자 권한 재확인
- [ ] 관리자 강제 해제·`config/*` 변경도 소비자가 소유 계정·역할 검사
- [ ] 사람 추가 전 조건: 앱이 사용하는 사람의 계정으로 파일을 만들게 전환 (지금은 M1만)
- [ ] `deploy/`에 마스터 노트북·`manifest.json`·`scripts/`·`notebook_cells.json`·GPU 노트북·실행 설정. 관리자(A0) 편집, G 보기. GPU 노트북 안에 목록 해시를 다시 넣지 않음 (마스터가 검증한 목록·파일을 넘김)
- [ ] 한 방향 사슬: Keeper `MASTER_NB_SHA256` → 노트북 안 목록 해시 → 파일별 해시. 목록에 마스터 노트북·목록 자신 제외 (K2) (시험: 실제 배포 순서로 만든 바이트가 검증 통과)
- [ ] 검증 지점: 마스터 `initial_pull`(284~304)·`main`(1164~1176), 0번 `load_script`(871~)·673~687, 30번 `_lc_run`(1040 부근)·1018~, subprocess 진입점, `start_gpu_worker_if_needed`(532~557)는 `deploy/` GPU 노트북만. 검증한 바이트를 그대로 실행 (시험: scripts·GPU 노트북·셀 사본 한 줄 변조 → 실행 거절)
- [ ] 배포 절차 문서 (파일 → 목록 → 노트북 → Keeper)
- [ ] 운영 전환: K Kaggle 보안 비밀에 `KAGGLE_USERNAME`·`KAGGLE_KEY` 추가(`RCLONE_CONF`는 A0 토큰 그대로), G 계정 Apps Script 두 프로젝트(수집기·Keeper), K Kaggle 계정 쪽 옛 Apps Script는 전환 단계에서 트리거 끄고 CVAT 토큰 속성 삭제
- [ ] legacy 등록은 새 심판의 첫 회에 (세션 지문 표시), 옛 `config/test_tasks.json` → `sets/test_tasks/v/legacy/`
- [ ] 시험 설정 경로 전환: `ctt.TEST_TASKS_FILE`·`write_test_tasks`(2532·2557~)·15번 셀 제외·33번 셀이 `sets/test_tasks/CURRENT.json`이 가리키는 버전을 읽게 (L1)
- [ ] `eggplant_admin/`(A0 소유, 공유 폴더 밖)에 `deploy/`·정책 `config/`, G는 보기 권한만. 코드·앱의 config·deploy 경로 변경, 옛 공유 `config/`로 되돌아가 읽지 않음
- [ ] A0·G 계정(그리고 K Kaggle 계정) 2단계 인증, Keeper 알림 메일 받는 곳을 A0로
- [ ] A0 Kaggle 보조 실행기: routing에 실행기 종류 등록(자동 기동 없음, 사람이 켬), `deploy/` 검증 노트북만, A0 Kaggle 보안 비밀(`RCLONE_CONF`·CVAT 토큰) 확인, 마스터는 K에서만
- [ ] 수집기(G)는 CVAT 읽기 호출만 쓰도록 코드 확인 (CVAT 계정이 하나라 토큰은 쓰기 가능)
- [ ] CVAT 토큰 교체 절차 문서: Colab(A0)·Kaggle(K·A0)·수집기(G) 동시 교체
- [ ] 설계·앱 문구에 분석 모드를 '보안 경계'로 표현하지 않음 (신뢰 모델)

## H. 행동 시험 (b2 6절)

- [ ] 분석 모드: 전 셀·하위 스크립트·Drive pin이 허용 범위 밖에 쓰지 않음. 12번·30번 뒤에도 유지
- [ ] 승인 직전 취소·만료·모름, 부분 decision 게시(decision·epoch·S·TASK 집합·gen 전체 일치 검사), epoch 교체와 이전 실행기 끝 보고, 관리 프로세스 실종 → 두 실행이 같은 곳에 쓰지 않음
- [ ] CVAT 반영 전후 단계별 종료 → 복구 자료가 남음. 사람이 고른 복구가 앞 실행과 겹치지 않음 (권한 잃은 실행기가 복원하지 않음)
- [ ] 신호 효과 뒤 완료 전 종료 → 효과 한 번. heartbeat와 판정 저장 교차 없음(작성자 분리). waiting만 남은 재기상. STOP/RELEASE 재시작 뒤 한 번만
- [ ] 재시작 점검 보고서가 위 상황을 모두 '이상'으로 찾음
- [ ] 제출본 변경·다른 TASK 매핑, 정리 중 모델 받기, 스냅숏 요약·15번 학습 입력·고정 시험 제외 연결
