# 16. 백업에서 새 TASK 만들기 요청 — backups/의 zip → 실행기(CPU)가 CVAT에 새 TASK (원본 TASK는 그대로)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
RS_FILES    = []         # 백업 파일 (BASE 기준), 예: ['backups/<요청ID>/eggplant_G3_20261013_2_3_vf__2687720.zip']
RS_QUERY    = ''         # 또는 백업 파일 이름 검색 (TASK 이름 규칙)
RS_LATEST_ONLY = True    # 검색 때 TASK마다 가장 최근 백업만
RS_SUFFIX   = '_test'    # 새 TASK 이름 끝에 붙일 글자 ('' = 원래 이름 그대로)
RS_PROJECT  = None       # 넣을 프로젝트 ID (숫자) · None = 프로젝트 없이
RS_RETRY_CONFIRMED = False   # True = 앞선 만들기가 '확인 필요'였고 CVAT에서 만들어지지 않았음을 확인했을 때만
SEND        = False

import re as _re
_files = [f for f in RS_FILES]
if not _files and RS_QUERY:
    _all = [os.path.relpath(p, BASE) for p in glob.glob(f'{BASE}/backups/**/*.zip', recursive=True) if '/pending/' not in p]
    _m = [p for p in _all if ctt.match_name(p.rsplit('/', 1)[-1].split('__')[0], RS_QUERY)[0]]
    if RS_LATEST_ONLY:
        _by = {}
        for p in sorted(_m):
            _by[p.rsplit('/', 1)[-1].split('__')[0]] = p
        _m = sorted(_by.values())
    _files = _m
assert all(str(f).startswith('backups/') for f in _files), "RS_FILES는 BASE 기준 'backups/…' 경로"
print(f'만들 TASK {len(_files)}개')
RS_RIDS = []
for f in _files:
    _name = _re.sub(r'__\d+$', '', f.rsplit('/', 1)[-1][:-4]) + RS_SUFFIX
    _p = {'backup': f, 'project_id': RS_PROJECT}
    if RS_RETRY_CONFIRMED:
        _p['retry_confirmed'] = True
    RS_RIDS.append(send('create16', [], {k: v for k, v in _p.items() if v is not None}, go=SEND, name=_name, note=f'← {f}'))
