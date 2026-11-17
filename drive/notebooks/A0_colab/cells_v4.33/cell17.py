# 17. 영상으로 새 TASK 만들기 요청 — videos/의 mp4 → 실행기(CPU)가 CVAT에 빈 TASK를 만들고 영상을 올림
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
VC_FILES      = []         # 영상 경로 (BASE 기준), 예: ['videos/261013/eggplant_G6_20261013_2_4.mp4']
VC_QUERY      = ''         # 또는 videos/의 영상 파일 이름 검색 (TASK 이름과 같은 규칙)
VC_STATE      = 'uld'      # 이름에 붙일 상태
VC_SUFFIX     = '_test'    # 이름 끝에 붙일 글자 ('' = 없음)
VC_FRAME_STEP = 10         # 프레임 간격
VC_PROJECT    = None       # 넣을 프로젝트 ID (숫자) · None = 프로젝트 없이 VC_LABELS로 라벨을 만듦
VC_LABELS     = ['healthy_fruit', 'disease_fruit', 'healthy_bud', 'disease_bud']
VC_IMAGE_QUALITY = 70
VC_RETRY_CONFIRMED = False # True = 앞선 만들기가 '확인 필요'였고 CVAT에서 만들어지지 않았음을 확인했을 때만
SEND          = False

import os as _os
_files = list(VC_FILES)
if not _files and VC_QUERY:
    _files = [os.path.relpath(p, BASE) for p in sorted(glob.glob(f'{BASE}/videos/**/*.mp4', recursive=True))
              if ctt.match_name(os.path.basename(p)[:-4], VC_QUERY)[0]]
assert all(str(f).startswith('videos/') for f in _files), "VC_FILES는 BASE 기준 'videos/…' 경로"
print(f'만들 TASK {len(_files)}개')
VC_RIDS = []
for f in _files:
    _name = f"{os.path.basename(f)[:-4]}_{VC_STATE}{VC_SUFFIX}" if VC_STATE else os.path.basename(f)[:-4] + VC_SUFFIX
    _p = {'video': f, 'frame_step': int(VC_FRAME_STEP), 'image_quality': int(VC_IMAGE_QUALITY)}
    if VC_PROJECT is not None:
        _p['project_id'] = VC_PROJECT
    else:
        _p['labels'] = list(VC_LABELS)
    if VC_RETRY_CONFIRMED:
        _p['retry_confirmed'] = True
    VC_RIDS.append(send('create17', [], _p, go=SEND, name=_name, note=f'← {f}'))
