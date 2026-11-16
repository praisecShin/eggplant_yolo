# v4.33 구현 2a — CPU 마스터 노트북 연결 (v4.33.0g)

배포 계획 5절의 2a입니다. 0g(b13 S1 수정)도 같은 판에 들어 있습니다.

## 만든 것

| 파일 | 역할 |
| --- | --- |
| `drive/notebooks/K_kaggle/master_boot_v4.33.py` | **뿌리 노트북의 셀 원본.** 고정 해시 자리(`__MANIFEST_SHA256__`)·시험 여부·rclone 연결 이름을 `build_deploy.py`가 채워 노트북으로 만듦 |
| `dev_tools/build_deploy.py` | 배포 묶음 만들기: ① scripts·GPU 노트북·실행 설정 → ② `manifest.json` → ③ 목록 해시를 마스터 노트북에 고정 → ④ 마스터 노트북 해시(Keeper `MASTER_NB_SHA256`) 출력 |
| `drive/scripts/master_main.py` | 마스터 본체 (배포 목록으로 검증된 뒤 불림) |
| `tests/test_master_main_433.py` | 60개 (0i) |
| `tests/test_fuzz_433.py` | 무작위 입력 시험 (0i) |

고친 것: `arbiter.py`(회차 요약에 `gpu_needed`·`busy`), `arb_master.py`(마지막 회차 기록·마지막 자격 시각, 생존 신호에 `stopping`), `worker_cpu.py`(`--stop-file`).

## 뿌리 노트북이 하는 일 (순서)

1. rclone 설치 (붙인 Kaggle 데이터셋이 있으면 복사), kaggle 패키지
2. 보안 비밀 → 세션 임시 폴더(0600): `RCLONE_CONF`(연결 여럿을 한 줄에서 되살림 — `gdrive`·`gadmin`·`…_test`), `CVAT_TOKEN`(없으면 멈춤), `KAGGLE_USERNAME`·`KAGGLE_KEY`. 필요한 연결(`gdrive:`·`gadmin:` 또는 시험 연결)이 없으면 멈춤
3. 관리자 폴더의 `deploy/`를 받아 **목록 해시를 고정값과 대조 → 파일별 해시 대조**. 하나라도 다르면 실행하지 않음
4. scripts 모듈은 `VerifiedFinder`로 **검증한 바이트에서만** 불러옴 (디스크의 같은 이름 파일을 보지 않음)
5. `master_main.main(Boot)`

## 마스터 본체가 하는 일

| 단계 | 내용 |
| --- | --- |
| 시작 조건 | 시험 실행은 시험 연결만, 운영 실행은 운영 연결만 (`check_remotes`). 관리자 폴더 `config/min_version.json`의 `master` 값보다 낮거나 못 읽으면 시작하지 않음 — 자격 신청·생존 신호도 쓰지 않음 |
| 자격·판정 | `jobs/arbiter_ask/<세션>.json` 자격 신청 → `MasterLoop` 회차 25초. 사람 목록·계정 지도는 관리자 폴더에서 10분마다 |
| 생존 신호 | `Beat` 스레드 60초, 끝낼 때 같은 스레드가 '끝남' |
| 바깥 조회 | `ProbeCache` 스레드 60초: 생존 신호에 `kernel`을 적은 실행기(GPU 작업자, 2b)의 Kaggle 상태 → `kernel_status`, 확정 승인·확인 필요 TASK의 CVAT 진행 중 가져오기 → `import_pending`. 실패하면 '모름' |
| CPU 작업 프로세스 | 검증한 scripts를 본인 전용 폴더(0700)에 쓰고 `python -I`로 `worker_cpu` 실행 (`EGG_ACCESS=exec`, 능력 `cpu,agg`, 멈춤 파일). 죽으면 새 세션으로 다시 띄움, 한 시간에 5번을 넘으면 그만두고 기록 |
| GPU 작업자 | 회차 요약의 `gpu_needed > 0`이고 정지 보류가 없을 때만. 배포 목록의 GPU 실행 설정·노트북 바이트만 씀. 시험·운영 주소가 실행 환경과 다르면 거절. Kaggle 상태가 실행 중이면 올리지 않음, 올린 뒤 10분은 다시 올리지 않음 |
| 끝내기 | 실행 11.2시간 / 10분 안에 자격을 못 받음 / 자격을 잃고 10분 / 밤에 할 일 없음(실행 가능 0·진행 중 0·GPU 필요 0·다음 깨울 시각이 15분 밖). 끝낼 때 작업 프로세스에 멈춤 파일 → 최대 2분 기다림 → 마지막 생존 신호 '끝남' |

## 운영자가 하는 일 (배포 때)

```bash
python3 dev_tools/build_deploy.py --out /tmp/deploy_test --kaggle-user <K 계정> --test --gpu-notebook <GPU 노트북>
```

- 출력 폴더 전체를 `eggplant_admin_test/deploy/`(운영은 `eggplant_admin/deploy/`)에 올림
- 출력된 `MASTER_NB_SHA256`을 Keeper Script Properties에 넣음
- `config/min_version.json`: `{"master": "4.33.0"}` 같은 형식

## b14 반영 (v4.33.0h)

| 지적 | 반영 | 시험 |
| --- | --- | --- |
| U1 보고의 복합 칸 | 판정 함수가 보고·신호·요청·실행기에서 읽는 칸을 전부 훑어 형태 표에 넣음: `current_change`(객체, 종류는 model·dataset·test_tasks, 이름은 문자열), `train_keys`(문자열 목록), `recovery_dir`·`task_id`·`state`. 산출물 목록(`_files.json`)의 `files`·`verified`·`train_keys`·`keys`, 자격 파일의 `epoch`·`session`, 사람 목록의 칸(`perms`는 목록)도 확인. 정지 기한은 ISO 문자열도 초로 바꿔 둠 | 잘못된 보고 둘·산출물 목록 하나 옆에서 정상 요청 완료, 형태 표 9가지, 자격 파일 epoch 오류, 사람 목록 perms가 문자열 |
| U2 import 경계 | 뿌리 노트북 `lock_imports`: `sys.path`를 표준 라이브러리·설치된 패키지 폴더로 좁힘, 그 밖에서 먼저 불린 모듈과 배포 모듈 같은 이름은 버림, 검증한 바이트를 맨 앞에서 내줌. 목록에 없는 우리 코드는 찾을 곳이 없어 거절. 작업 프로세스는 검증한 파일만 든 폴더 + `python -I` | 새 프로세스에서 디스크 같은 이름·목록 밖 import·먼저 불린 모듈·표준 라이브러리 |
| U3 커널 상태 | `has status "…"`의 값만 정확히 맞춤 (`KernelWorkerStatus.` 접두어 처리). running·queued·cancelRequested → 실행 중, complete·error·cancelAcknowledged → 끝남, 404 → 노트북 없음, 그 밖은 모름 | 주소에 error·running, 상태가 둘, 404·시간 초과 |
| U4 조회 최신성 | 마지막 성공 조회 시각을 두고, 실패하면 대상별 '모름', 3분보다 오래되면 '모름' | 성공 → 실패 → 회복 → 오래됨 |
| U5 CVAT 응답 | 행마다 상태가 알려진 값(queued·started·finished·failed)인지, 다음 페이지까지(최대 5쪽). 하나라도 모르면 '모름' | 상태 칸 없음·빈 행·처음 보는 값·둘째 쪽 진행 중·끝없는 페이지 |
| U6 밤 끝내기 | 바로 직전 회차가 모름 없이 읽고 모두 썼을 때만 '할 일 없음'으로 끝냄 (`last_clean_at == last_run_at`) | 요청 목록을 못 읽는 밤에는 끝내지 않음 |
| U7 GPU 상태 모름 | 상태가 '끝남'이거나 '노트북 없음'(처음 만들 때)일 때만 올림. 모르면 다음 회차에 다시 조회 | 조회 실패·처음 보는 값·404 |
| 결정 (11/15) | '확인 필요'는 진행 중으로 세지 않음 — 밤에 사람 확인만 남으면 마스터는 끝내고, 사람이 고르면 `run_choice`·`confirm_choice`로 Keeper가 깨움 | `_busy_count` |

## b15 반영 (v4.33.0i)

| 지적 | 반영 | 시험 |
| --- | --- | --- |
| V1 형태 확인의 예외·사람 필수 칸 | `input_problem`은 어떤 입력에도 예외를 내지 않음(확인 중 예외는 `unreadable`). `current_change.type`은 문자열인지 먼저 봄. 사람 목록은 `id`·`account`·`perms`가 꼭 있어야 하고, `id`·`account`가 겹치면 받지 않음. 받지 않은 이유와 마지막 정상 시각은 마스터 생존 신호의 `status.config`에 | 형태 표 7가지, 잘못된 보고 옆 정상 요청, 사람 목록 거절 이유 |
| V2 산출물 목록 `task_keys` | 형태 표에 넣음. 형태가 틀린 목록은 '모름'으로 두고 내용을 지움, 모든 읽기는 `View.vfile()`로만. 데이터셋 목록이 '모름'이면 학습을 시작하지 않음 | 데이터셋 목록 오류 옆 정상 요청 배정, 학습 시작 안 함 |
| V3 import 경계 | 폴더 이름(`site-packages`)으로 허락하지 않고 실제 설치 폴더(`sysconfig`·`site.getsitepackages`)만. 가지 앱 모듈 이름(지금 scripts + 옛 이름, 묶음이 노트북에 고정)은 목록에 없으면 설치 폴더에서도 거절 | 가짜 site-packages 폴더, 예약 이름 |
| V4 조회 시각 | 조회 묶음 **시작** 시각을 붙임 — 도중에 3분이 지나면 앞의 값도 '모름' | 조회 도중 시간 흐름 |
| V5 GPU '노트북 없음' | 실패 응답은 오류 문구와 상관없이 모두 '모름'. GPU 노트북은 배포 때 관리자가 처음 한 번 올림. 'GPU 상태 모름' 시작 시각을 생존 신호 `status.gpu_status_unknown_since`에 | 404·not found |
| 무작위 입력 시험 | `tests/test_fuzz_433.py`: 시나리오 시험에서 심판이 실제로 받은 입력 5천여 개를 모아, 바깥 입력과 판정 파일의 칸을 하나씩(한 단계 안쪽까지, 통째로도) 이상한 값 15가지로 바꿔 약 4만 4천 회차를 돌림. 예외 0건. `FUZZ_SEED`·`FUZZ_N`으로 넓힐 수 있음 (씨앗 3개 × 5 = 약 29만 회차도 0건) | 3 |
| 시험이 찾은 것 | ① 자격 파일 `epoch` 없음 ② 신호의 필수 칸 없음(`confirm_choice`의 `choice` 등) ③ 심판이 쓴 파일(`arb/`·`CURRENT.json`)이 틀어진 경우 3천여 건. → 판정 파일 형태 표 `JUDGEMENT`: 틀리면 그 파일은 '없음'이 아니라 '모름'(잠금이 사라진 것으로 보고 다시 배정하지 않음) + 알림. 신호 종류별 필수 칸 `SIGNAL_REQUIRED` | 퍼징 |
| 덤으로 고친 것 | 형태가 틀린 신호를 버리던 것(0e 이후)을 '거절' 완료 기록으로 바꿈 — 버리면 Keeper가 '처리 안 된 밤 신호'로 보고 10분마다 깨움. 형태가 틀린 요청도 '거절' 접수 기록(이유 `bad_input:<칸>`)을 남겨 앱에 보이게 함 | 기존 시험 기대값 수정 |

## b16 반영 (v4.33.0j)

| 지적 | 반영 | 시험 |
| --- | --- | --- |
| W1·W2 판정 파일 | **보호 모드** (설계 '보호 모드'): 판정 파일 종류별 필수 칸(`REQUIRED["judgement:*"]`)·상태 값(`STATE_VALUES`)·세션 지문을 회차 시작에 확인. 하나라도 믿을 수 없으면 회차 기록(`protect`)·알림만 쓰고 끝냄. `trusted()`도 이상한 `by_epoch`에서 예외를 내지 않음. 보호 모드·안쪽 '모름'은 마스터가 '빠짐없는 회차'로 세지 않음 | 정지 보류 손상 → 접수·배정 없음 → 바로잡으면 재개, 배정 지문 삭제 → 덮지 않음 |
| W3 먼저 불린 모듈 | 뿌리 노트북이 가지 앱 이름(배포 목록 + 예약 이름) 전체와 하위 모듈을 어디서 불렸든 `sys.modules`에서 버림 | 설치 폴더에서 먼저 불린 예약 모듈·하위 모듈·목록 안 모듈 |
| 무작위 입력 시험 | 뜻도 확인: 판정 파일이 믿을 수 없으면 보호 모드(회차 기록·알림만), 보호 모드가 아니면 살아 있는 정지 보류 아래 새 배정 없음·살아 있는 배정을 다른 세션으로 덮지 않음. 판정 파일 종류·상태·종류별로 나눠 고름, 같은 파일의 칸 두 개 조합 1,668개, 씨앗 7 사례 고정 시험, 재료 시험이 실패하면 실패 | 씨앗 4330·7·1·2 × 5 모두 통과 |
| 알림 (11/15 결정) | Keeper: 보호 모드 들어감·끝남 → 메일 + ntfy 푸시(`NTFY_TOPIC`, 들어갈 때 최고 우선순위). 앱 띠는 CTRL앱(2e)에서 `ARBITER.json`의 `protect`로 | Keeper 6가지 |

## 아직 하지 않은 것

- GPU 작업자 노트북 새 판(2b): 지금 `--gpu-notebook`에는 무엇이든 넣을 수 있지만, 실제로 일할 GPU 작업자는 2b에서 만듦
- 작업 프로세스의 처리기(2b): 지금 `worker_cpu`에 등록된 처리기가 없어, 배정된 CPU 일은 '실패(처리기 없음)'로 보고됨 — **2b 전에는 운영에 올리지 않음**
- 받는 중 백업의 다음 확인 시각(`waiting` 조회, 2b)
- 시험 TASK 범위 강제(`REH_`·`eggplant_AA`, 2b 처리기에서)

## 실제 계정에서 확인할 것 (배포 계획 4절)

- T5·T6: `kaggle kernels push`·`status`의 실제 출력 형식 (`parse_kernel_status`)
- T10: CVAT `/api/requests` 조회 형식 (`cvat_import_query`) — 다르면 모든 TASK가 '모름'으로 나오고, 심판은 '확인 필요'를 넓게 잡음
- T11: `gadmin` 연결로 deploy/·config 읽기
- 뿌리 노트북 해시: Keeper가 Drive에서 읽은 노트북 바이트로 계산한 값이 `build_deploy.py`의 값과 같은지
