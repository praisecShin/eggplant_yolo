# 0. 공통 설정 · 준비 (v4.33, Colab 전용) — 세션이 새로 열릴 때마다 가장 먼저 실행 (다시 실행해도 안전)
#    사람용 셀은 **분석 모드**입니다: 공유 폴더는 읽기만, 결과는 내 분석 폴더(OUT)에만, CVAT는 읽기·참조용 export만.
#    CVAT·공유 상태를 바꾸는 일은 request(...)로 요청을 보내면 실행기(30번 셀·Kaggle)가 처리합니다.
APP_VERSION = '4.33'
# ====================== 설정 (여기만 고치세요) ======================
BASE     = ''                  # ← 꼭 적기: 공유 폴더 경로. 운영 '/content/drive/MyDrive/eggplant_yolo' · 예행 연습은 시험 폴더
OPERATOR = ''                  # 내 사람 ID (people.json의 id, 예 'M1') — 분석 폴더 이름 analysis/<OPERATOR>/
MODEL_CHOICE = 'last_adopted'  # 쓸 모델: 'last_adopted' = 최근 채택된 모델 (최근 학습 완료가 아님) · 또는 모델 이름
MODEL_NAMES = {}               # 자주 쓰는 모델에 번호 (선택), 예 {1: 'fruit_1920', 3: 'fruit_r261101_2class_rotate'} — 24번 셀 MODEL_PICK 번호
MODEL    = 'yolo11s.pt'        # 사전학습 가중치 (학습 요청의 기본 시작점)
IMGSZ    = 1920
EPOCHS   = 100
PATIENCE = 30
BATCH    = -1
DEVICE   = None
TRACK_CONF = 0.25
TRACK_FILL_GAPS = 3
TRACK_BUFFER = 90
TRACK_DECODER = 'pyav'
TRACK_FRAME_OFFSET = 0
TRACK_BOX_SOURCE = 'detection'
TRACK_NEAR = 1
UPLOAD_MIN_PRECISION = 0.8
AA_CONF    = 0.25
REVIEWED_RULE = 'vf'
VAL_RULE   = 'plant=3|plant=7'
CVAT_PROFILES = {             # 'token'·'user'·'pass' 값 = Colab 보안 비밀 이름
    'token':    {'host': 'https://app.cvat.ai', 'login': 'token',    'token': 'CVAT_TOKEN'},
    'password': {'host': 'https://app.cvat.ai', 'login': 'password', 'user': 'CVAT_USER', 'pass': 'CVAT_PASS'},
    'B':        {'host': 'https://app.cvat.ai', 'login': 'token',    'token': 'CVAT_TOKEN_B'},
}
CVAT_SDK_VERSION = 'auto'
CVAT_AUTH    = 'auto'
CVAT_ORG     = 'horti'
CVAT_PROJECT = ''
LOCAL    = '/content/egg_local'  # Colab 로컬 디스크 (모델·데이터셋 받기, 임시 파일)
# ====================================================================
import glob, importlib, json, os, re, shutil, subprocess, sys, time, zipfile
from pathlib import Path
from urllib.parse import urlparse

if not BASE:
    raise SystemExit("⛔ 0번 셀 위쪽의 BASE를 적으세요 (운영 '/content/drive/MyDrive/eggplant_yolo' 또는 시험 폴더) — "
                     "기본값으로 운영 폴더를 잘못 가리키지 않게 비워 둠")
if not os.path.exists('/content/drive/MyDrive'):
    from google.colab import drive
    drive.mount('/content/drive')
if not os.path.isdir(BASE):
    _c = glob.glob(f'/content/drive/.shortcut-targets-by-id/*/{os.path.basename(BASE)}') + \
         glob.glob(f'/content/drive/Shareddrives/*/{os.path.basename(BASE)}')
    _c = [c for c in _c if os.path.isdir(f'{c}/scripts')]
    if not _c:
        raise SystemExit(f'⛔ {BASE} 폴더가 없습니다 — 공유 폴더의 바로가기를 내 드라이브에 추가한 뒤 세션 다시 시작')
    BASE = _c[0]
SCRIPTS = f'{BASE}/scripts'
VIDEOS, TASKS_DIR = f'{BASE}/videos', f'{BASE}/tasks'

# ---- 패키지 (없을 때만) — 서버와 같은 X.Y의 cvat-sdk
from importlib import metadata
def _ver(pkg):
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None
CVAT_HOST = CVAT_PROFILES[CVAT_AUTH if CVAT_AUTH in CVAT_PROFILES else next(iter(CVAT_PROFILES))]['host']
def cvat_server_version(host=None):
    try:
        import requests
        r = requests.get(f'{host or CVAT_HOST}/api/server/about', timeout=15)
        return r.json().get('version') if r.ok else None
    except Exception:
        return None
CVAT_LAST_KNOWN = '2.79.0'
SERVER_VER = cvat_server_version()
_b = (SERVER_VER or CVAT_LAST_KNOWN) if CVAT_SDK_VERSION == 'auto' else CVAT_SDK_VERSION
_mj, _mn = _b.split('.')[:2]
cvat_spec = f'cvat-cli~={_mj}.{_mn}.0' if CVAT_SDK_VERSION == 'auto' else f'cvat-cli=={CVAT_SDK_VERSION}'
need = [p for p, m in [('ultralytics', 'ultralytics'), ('lap', 'lap'), ('av', 'av')] if importlib.util.find_spec(m) is None]
if not (_ver('cvat-cli') and _ver('cvat-cli') == _ver('cvat-sdk') and _ver('cvat-cli').startswith(f'{_mj}.{_mn}.')):
    need.append(cvat_spec)
if need and not os.environ.get('SKIP_INSTALL'):
    print('설치:', need)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', *need])
    importlib.invalidate_caches()
CVAT_CLI_VER, CVAT_SDK_VER = _ver('cvat-cli'), _ver('cvat-sdk')

# ---- 분석 모드 기반 (쓰기 가드·CVAT 가드·요청 API·채택 모델)
sys.dont_write_bytecode = True                      # 공유 scripts/를 불러올 때 __pycache__를 만들지 않음 (b28 B4)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import cells_base as cb
importlib.reload(cb)
S = cb.start(BASE, OPERATOR, [p['host'] for p in CVAT_PROFILES.values()], local=LOCAL)
OUT = str(S.out)                                   # 내 분석 폴더 — 셀의 모든 결과는 여기
request, signal, out_path, run = S.request, S.signal, S.out_path, S.run
SESSION_ID = S.session
import cvat_task_tools as ctt
importlib.reload(ctt)
if hasattr(ctt, 'REVIEW_WORDS'):
    ctt.REVIEWED_RULE = REVIEWED_RULE
try:
    import web_bridge as wb, relabel_bridge as rb
    importlib.reload(wb); importlib.reload(rb)
except ImportError:
    wb = rb = None
cb.redirect_records(S, ctt, wb)                    # 옛 기록 쓰기(작업 대장·작업 기록·통계 캐시)는 내 분석 폴더로 — 공유 기록은 읽기만
REGISTRY = f'{BASE}/task_registry.csv'              # 옛 작업 대장 (읽기 — 읽을 때는 옛 기록과 내 기록을 합쳐 읽음)
LOCAL_VIDEOS = f'{LOCAL}/videos'                    # 백업에서 꺼낸 영상 (Colab 로컬)

def who_am_i():
    return OPERATOR

def need_file(p):                                  # v4.32의 Kaggle 받기 — Colab은 Drive 그대로
    return p

def task_reviewed(name):
    return ctt.is_reviewed(name, REVIEWED_RULE)

def task_role(name):
    return ctt.split_role(name, VAL_RULE)

def load_script(name):
    spec = importlib.util.spec_from_file_location(os.path.splitext(name)[0], f'{SCRIPTS}/{name}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

# ---- CVAT 접속 (보안 비밀은 Colab 보안 비밀에서만, 값은 출력하지 않음). 쓰기는 전송 경계에서 막힘
def _secret(name):
    try:
        from google.colab import userdata
        v = userdata.get(name)
    except Exception:
        v = None
    return v.strip().strip("'\"") if v else None

def prof_login(name):
    p = CVAT_PROFILES[name]
    return p.get('login') or ('token' if 'token' in p else 'password')

def _has_secret(name):
    p = CVAT_PROFILES[name]
    return bool(_secret(p['token'])) if prof_login(name) == 'token' else bool(_secret(p['user']) and _secret(p['pass']))

def cvat_mode(mode=None):
    m = mode or globals().get('CVAT_LOGIN_MODE') or CVAT_AUTH
    if m == 'auto':
        m = next((k for k in CVAT_PROFILES if _has_secret(k)), next(iter(CVAT_PROFILES)))
    assert m in CVAT_PROFILES, f"LOGIN은 'auto' 또는 {list(CVAT_PROFILES)} 중 하나 (지금 값: {m!r})"
    return m

_CRED_TYPED = globals().get('_CRED_TYPED', {})     # 보안 비밀이 없을 때 입력창 값 (이 세션 메모리에만)

def cvat_auth(mode=None):
    from getpass import getpass
    m = cvat_mode(mode)
    prof, kind = CVAT_PROFILES[m], prof_login(m)
    if kind == 'password':
        u = _secret(prof['user']) or _CRED_TYPED.get((m, 'u')) or input(f"[{m}] CVAT 아이디 ({prof['host']}): ")
        p = _secret(prof['pass']) or _CRED_TYPED.get((m, 'p')) or getpass(f'[{m}] CVAT 비밀번호: ')
        _CRED_TYPED[(m, 'u')], _CRED_TYPED[(m, 'p')] = u, p
        return kind, (u, p)
    t = _secret(prof['token']) or _CRED_TYPED.get((m, 't')) or getpass(f"[{m}] CVAT Personal Access Token ({prof['host']}): ")
    _CRED_TYPED[(m, 't')] = t
    return kind, re.sub(r'^(Token|Bearer)\s+', '', t.strip(), flags=re.IGNORECASE)

_SCOPE_TMP = {}
CVAT_SCOPE = globals().get('CVAT_SCOPE') or {}

def scope_want(mode=None):
    p = CVAT_PROFILES.get(cvat_mode(mode), {})
    return p.get('org', CVAT_ORG), p.get('project', CVAT_PROJECT)

def apply_scope(cl, mode=None):
    org, proj = scope_want(mode)
    try:
        return ctt.set_scope(cl, org, proj)
    except ValueError as e:
        raise SystemExit(f'⛔ {e}\n→ 0번 셀 CVAT_ORG·CVAT_PROJECT를 고치고 다시 실행하세요')

def cvat_client(mode=None):
    m = cvat_mode(mode)
    kind, v = cvat_auth(m)
    host = CVAT_PROFILES[m]['host']
    cl = ctt.connect(host, credentials=v) if kind == 'password' else ctt.connect(host, v)
    apply_scope(cl, m)
    return cl

def cvat_cli_auth(mode=None):
    kind, v = cvat_auth(mode)
    return (['--auth', v[0]], {'PASS': v[1]}) if kind == 'password' else ([], {'CVAT_ACCESS_TOKEN': v})

_CVAT_SESSIONS = globals().get('_CVAT_SESSIONS', {})

def cvat_forget(name=None):
    for k in ([name] if name else list(_CVAT_SESSIONS)):
        _CVAT_SESSIONS.pop(k, None)
    for k in [k for k in _CRED_TYPED if name is None or k[0] == name]:
        _CRED_TYPED.pop(k, None)

def use_cvat(login=None):
    global CLIENT, CVAT_LOGIN_MODE, CVAT_HOST, CVAT_SERVER, CVAT_SCOPE
    import hashlib
    m = cvat_mode(login)
    host = CVAT_PROFILES[m]['host']
    sig = hashlib.sha256(repr((host,) + cvat_auth(m)).encode()).hexdigest()[:16]
    sess = _CVAT_SESSIONS.get(m)
    if sess is None or sess[2] != sig:
        cl = ctt.with_retry(lambda: cvat_client(m), what=f'CVAT 접속 [{m}]') if hasattr(ctt, 'with_retry') else cvat_client(m)
        user = cl.api_client.users_api.retrieve_self()[0].username
        _CVAT_SESSIONS[m] = (cl, f'{user}@{urlparse(host).hostname}', sig)
    CLIENT, CVAT_SERVER, _ = _CVAT_SESSIONS[m]
    CVAT_LOGIN_MODE, CVAT_HOST = m, host
    CVAT_SCOPE = apply_scope(CLIENT, m) or {}
    print(f"▶ CVAT 서버: {CVAT_SERVER} · 프로필 {m} · 분석 모드(읽기·참조용 export만)")
    return CLIENT

def task_dir(tid):                                 # TASK별 분석 폴더 (공유 tasks/는 읽기만)
    return str(S.out_path(f'tasks/{tid}/.keep').parent)

# ---- 모델·데이터셋: 채택된 버전을 해시 대조해 받음 (공유 runs/는 읽기만)
try:
    NAME, MODEL_VERSION, BEST = S.model(MODEL_CHOICE)
except cb.AnalysisRefused as e:
    NAME, MODEL_VERSION, BEST = '', '', ''
    print(f'⚠️ 모델: {e}')
RUN_DIR = S.run_dir(NAME, MODEL_VERSION) if NAME else ''
try:
    _dsv, DS = S.dataset_of_model(NAME, MODEL_VERSION) if NAME else ('', None)
except cb.AnalysisRefused:
    DS = None

def model_label():
    return f'{NAME}@{MODEL_VERSION}' if NAME else ''

def pick_model(choice=None):
    """셀에서 모델 고르기: None = 0번 셀 선택 모델 · 이름 = 그 모델의 채택 버전 · '.pt' 경로 = 그 파일 (분석용)
    → (표시 이름, 로컬 best.pt)"""
    if choice is None:
        return model_label(), BEST
    if str(choice).endswith('.pt'):
        p_ = choice if os.path.isabs(str(choice)) else f'{BASE}/{choice}'
        assert os.path.exists(p_), f'모델 파일이 없습니다: {p_}'
        return os.path.basename(str(p_)), p_
    n_, v_, p_ = S.model(choice)
    return f'{n_}@{v_}', p_

REPORTS = str(S.out_path('reports/.keep').parent)   # 보고서·표 저장 (내 분석 폴더 — 공유 reports/는 읽기만)

def V433_STATUS(s):
    """v4.33 실행기 결과 상태 → 한국어 (done·failed:<이유>·cancelled·needs_check …)"""
    s = str(s or '')
    head, _, why = s.partition(':')
    ko = {'done': '완료', 'failed': '실패', 'cancelled': '취소', 'needs_check': '확인 필요', 'held': '보류'}.get(head, head)
    return f'{ko} ({why})' if why else ko

def _when(t):
    """기록 시각 → epoch 초. 옛 기록 'YYYY-MM-DD HH:MM:SS'(시간대 없음 = 한국 시각)와 실행기 'YYYY-MM-DDTHH:MM:SS+09:00'를
    같은 기준으로 (글자 그대로 비교하면 같은 날 실행기 결과가 늘 이김 — b29 W2). 읽지 못하면 0."""
    import datetime as _dt
    try:
        t = str(t).strip()
        if t.endswith(('Z', 'z')):                   # Python 3.10의 fromisoformat은 'Z'를 못 읽음 (b31 X4)
            t = t[:-1] + '+00:00'
        d = _dt.datetime.fromisoformat(t.replace(' ', 'T', 1))
    except ValueError:
        return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=9)))
    return d.timestamp()

def last_upload(tid, include_track=False):
    """이 TASK에 마지막으로 올린 자동 라벨 — v4.33 실행기 결과(복구 자료의 결과 파일)와 옛 작업 대장 중 나중 것.
    돌려줌: {'result_file'(BASE 기준), 'run_time', 'model', 'kind', 'source', 'before_file'} 또는 None"""
    u = None
    for h in S.uploads(tid):                        # 시각 순. 되돌리기(revert)가 끝나면 그 앞에 올린 것은 지금 CVAT에 없음
        if h.get('status') != 'done':
            continue
        if h.get('kind') == 'recovery' and h.get('mode') == 'revert':
            u = None
        elif h.get('result_file') and h.get('kind') != 'recovery' or (h.get('kind') == 'recovery' and h.get('mode') == 'redo' and h.get('result_file')):
            u = h
    cand = []
    if u:
        cand.append({'result_file': u['result_file'], 'run_time': u['time'], 'model': u.get('model') or '', 'kind': u['kind'],
                     'source': 'v4.33', 'before_file': u.get('before_file', ''), 'status': '업로드 완료'})
    old = [r for r in ctt.read_registry(REGISTRY) if str(r.get('task_id')) == str(tid) and r.get('result_file')
           and ((r.get('action') == '업로드' and r.get('status') == '업로드 완료') or (include_track and r.get('action') == 'track 생성'))]
    if old:
        r = old[-1]
        cand.append({'result_file': r['result_file'], 'run_time': r.get('run_time', ''), 'model': r.get('model', ''),
                     'kind': 'track' if r.get('action') != '업로드' else 'upload', 'source': 'v4.32', 'before_file': r.get('backup_file', ''),
                     'status': r.get('status', ''), 'video': r.get('video', ''), 'task_name': r.get('task_name', '')})
    return max(cand, key=lambda c: _when(c['run_time'])) if cand else None

def job_start(cell, action, settings=None, summary=''):   # 작업 기록 → 내 분석 폴더의 records/ (공유 logs/는 읽기만)
    try:
        return ctt.start_job(BASE, cell, action, who=who_am_i(), session=SESSION_ID, server=globals().get('CVAT_SERVER', ''),
                             model=model_label(), settings=settings, summary=summary)
    except Exception as e:
        print(f'(작업 기록 시작 실패: {e})')

def job_end(status='끝', summary='', **kw):
    try:
        if ctt.current_job():
            ctt.end_job(status, summary, **kw)
    except Exception as e:
        print(f'(작업 기록 끝 실패: {e})')

# ---- 바꾸는 셀의 공통: 미리 보기 → 요청 (2c-3)
STATUS_KO = {'pending': '대기', 'accepted': '받음', 'running': '실행 중', 'done': '완료', 'failed': '실패',
             'canceled': '취소됨', 'needs_check': '확인 필요'}

def pick_tasks(ids=None, query='', label='대상 TASK', show=True):
    """TASK 고르기 (읽기만): ids가 있으면 그 TASK, 없으면 이름 검색어. → [{'task_id', 'name', 'updated', …}]"""
    import pandas as _pd
    from IPython.display import display as _display
    if 'CLIENT' not in globals():
        use_cvat(None)
    allt = ctt.list_tasks(CLIENT, limit=5000)
    want = ctt.as_task_ids(ids) if ids else []
    if want:
        by = {int(t['task_id']): t for t in allt}
        miss = [i for i in want if int(i) not in by]
        if miss:
            print(f'⚠️ 이 계정에서 찾지 못한 TASK: {miss}')
        hits = [by[int(i)] for i in want if int(i) in by]
    elif query:
        hits = ctt.select_tasks(allt, query, display=None, label=label)
    else:
        hits = []
    if show:
        print(f'{label} {len(hits)}개' + (f" (검색어 '{query}')" if query and not want else ''))
        if hits:
            _display(_pd.DataFrame([{'task_id': t['task_id'], 'TASK 이름': t['name'], 'CVAT 수정': t.get('updated', '')}
                                    for t in hits]).set_index('task_id'))
    return hits

def send(kind, tasks=(), params=None, go=False, note='', **fields):
    """요청 보내기. go=False면 무엇을 보낼지만 보여 줌 (미리 보기). go=True면 requests/에 요청 파일 하나 → 심판이 접수·배정.
    돌려줌: 요청 ID 또는 None"""
    ids = [str(t['task_id'] if isinstance(t, dict) else t) for t in tasks]
    body = {k: v for k, v in dict(fields, params=params or {}).items() if v not in (None, {}, '')}
    print(f"▶ 요청 '{kind}'" + (f' · TASK {len(ids)}개' if ids else '') + (f' · {body}' if body else '') + (f' · {note}' if note else ''))
    if not go:
        print('   미리 보기입니다 — 위 내용이 맞으면 이 셀의 SEND = True로 바꿔 다시 실행')
        return None
    rid = request(kind, ids, params=params or {}, **fields)
    print(f'   ✅ 요청 {rid} 보냄 → 실행기가 처리합니다. 상태: show_requests() 또는 6번 셀')
    return rid

def show_requests(all_sessions=False):
    """내가 보낸 요청과 상태 (읽기만). all_sessions=True면 이 사람의 다른 세션 것도."""
    import pandas as _pd
    from IPython.display import display as _display
    rows = []
    for r in S.my_requests(all_sessions):
        st = S.status(r['rid'])
        it = st.get('intake') or {}
        res = st.get('results') or {}
        rows.append({'요청': r['rid'], '종류': r['kind'], '상태': STATUS_KO.get(st['status'], st['status']),
                     '접수': ('' if not it else ('받음' if it.get('ok') else f"거절: {it.get('reason')}")),
                     'TASK': ', '.join(map(str, r['tasks'][:5])) + (f" 외 {len(r['tasks']) - 5}" if len(r['tasks']) > 5 else ''),
                     '결과': ', '.join(f'{t}:{V433_STATUS(v)}' for t, v in list(res.items())[:5]),
                     '보낸 시각': time.strftime('%m-%d %H:%M', time.localtime(r['created'])) if r['created'] else ''})
    if rows:
        _display(_pd.DataFrame(rows).set_index('요청'))
    else:
        print('보낸 요청이 없습니다' + ('' if all_sessions else ' (이 세션) — 다른 세션 것도 보려면 show_requests(True)'))
    return rows

# ---- v4.32의 쓰기 함수는 v4.33에서 요청으로 바뀜 (부르면 이유를 알려 줌)
lock_run = cb.refused('lock_run', '학습은 request("train", model=..., dataset=...)')
unlock_run = cb.refused('unlock_run')
run_training = cb.refused('run_training', '학습은 request("train", model=..., dataset=...)')
upload_log = cb.refused('upload_log', '올리기는 실행기가 기록함')
label_uploaded = cb.refused('label_uploaded', '이름 규칙은 실행기가 올리면서 적용')
req_use = cb.refused('req_use', '앱 요청은 실행기가 처리 — 셀에서 받지 않음')
drive_push = drive_pull = drive_sync_now = drive_get_videos = cb.refused('Kaggle 동기화', 'v4.33 사람용 셀은 Colab 전용')

print(f'앱 버전    : {APP_VERSION} (기반 {cb.CELLS_VERSION}) · 분석 모드 · 세션 {SESSION_ID}')
print(f'내 분석 폴더: {OUT}')
_ma = (S.model_meta or {}).get('adopted_at') if NAME else None
_ma = time.strftime('%m-%d %H:%M', time.localtime(float(_ma))) if isinstance(_ma, (int, float)) and _ma > 0 else ''
print(f'선택 모델  : {NAME or "(없음)"} {MODEL_VERSION}' + (f' (최근 채택 {_ma})' if MODEL_CHOICE == 'last_adopted' and _ma else
      (f' (채택 {_ma})' if _ma else '')) + f' → {BEST or "-"}')
_m = cvat_mode()
for _k, _p in CVAT_PROFILES.items():
    print(f"CVAT {_k:<8}: {_p['host']} · {'PAT' if prof_login(_k) == 'token' else 'ID/PASS'} · 보안 비밀 "
          f"{'있음' if _has_secret(_k) else '없음(실행 때 입력창)'}" + ('  ← 처음 접속' if _k == _m else ''))
print("바꾸는 일   : request('track', [TASK ID], params={...}) 처럼 요청 → 실행기가 처리 (요청 종류: "
      + ", ".join(cb.REQUEST_KINDS) + ")")
