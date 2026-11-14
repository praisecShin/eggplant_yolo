"""
CVAT TASK 백업 (CVAT 2.79 / app.cvat.ai) — Colab에서 실행

- 로그인 방식 두 가지 (AUTH_MODE)
    "password" : 공동 아이디 ID/PASS  → Colab 보안 비밀 CVAT_USER, CVAT_PASS
    "token"    : PAT(Google 로그인 계정에서 만든 토큰) → Colab 보안 비밀 CVAT_TOKEN
- TASK 백업(CVAT 'Backup Task' = 영상 + 라벨 + 설정)을 Drive에 시각별로 저장
    backups/<기본 이름>/<종류>/<기본 이름>_<상태>_<종류>_<YYYYMMDD_HHMMSS>.zip
    종류: original(그 TASK의 첫 백업) / work(uld·vf_r2) / revised(vf_r2df·vf_r2df_ok)
- 기록
    backup_index.csv  : 백업 시도 1회 = 1줄 (성공·실패·건너뜀)
    backup_status.csv : TASK 1개 = 1줄 (최신 백업 상태, 보드의 '백업 상태' 탭과 같은 내용)
- 보드: 작업보드의 '백업 상태'·'백업 색인' 탭을 덮어씀 (UPDATE_BOARD) — 기본은 eggplant_yolo/reports/작업보드.xlsx (BOARD_MODE)

비밀번호와 토큰은 Colab 보안 비밀에서만 읽고, 파일·로그·보드에 쓰지 않는다.
"""
__version__ = "4.32.0"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import csv
import datetime
import os
import re
import time
from pathlib import Path

import requests
from urllib.parse import urlparse

try:                                  # 이름 검색은 같은 폴더의 cvat_task_tools.py를 씀
    from cvat_task_tools import match_name, format_detail, select_tasks, parse_task_name as _ctt_parse
    try:
        from cvat_task_tools import log_task as _ctt_log, label_counts as _ctt_counts
    except ImportError:                              # 예전 cvat_task_tools
        _ctt_log = _ctt_counts = None
except ImportError:
    match_name = format_detail = select_tasks = _ctt_parse = _ctt_log = _ctt_counts = None

# ==================================================
# 설정
# ==================================================
HOST = "https://app.cvat.ai"
AUTH_MODE = "password"            # "password"(ID/PASS) 또는 "token"(PAT)
ORGANIZATION_SLUG = None          # 조직 범위: 조직 slug · "" = 개인 작업공간 · None = 구분 안 함 (노트북 0번 셀 CVAT_ORG)
PROJECT_ID = None                 # 프로젝트 범위: None = 전부 · 0 = 프로젝트 없는 TASK만 · 숫자 = 그 프로젝트 (TASK_IDS를 주면 이 범위는 안 봄)

BASE = Path("/content/drive/MyDrive/eggplant_yolo")   # 설계서의 Drive 폴더
TASK_IDS = None                   # None = 전체 TASK, 예: [123, 456]
NAME_QUERY = ""                   # TASK 이름 검색 (cvat_task_tools.match_name 규칙: 공백=그리고, |=또는, ,=묶음, -=빼기, 칸=값, 칸=a..b, *)
                                  # 예: "261019 vf_r2" → 촬영일 261019 이면서 상태 vf_r2 (vf_r2df는 아님)
PREVIEW = False                   # True = 백업하지 않고 대상 목록만 보여 줌 (검색어 확인용)
ONLY_STATES = None                # (예전 설정) 상태만으로 거르기, 예: ["vf_r2df", "vf_r2df_ok"]
SECRET_TOKEN, SECRET_USER, SECRET_PASS = "CVAT_TOKEN", "CVAT_USER", "CVAT_PASS"   # 보안 비밀 이름
CREDENTIALS = None                # 노트북이 넘겨주는 로그인 정보 (token 문자열 또는 (아이디, 비밀번호)) — 있으면 보안 비밀 대신 사용
FORCE = False                     # True면 바뀐 것이 없어도 다시 백업
MODE = "all"                      # "all" = 요청 → 준비되는 대로 받기 / "request" = 요청만 / "download" = 요청해 둔 것 받기
MAX_WAIT = 1800                   # "all"에서 기다리는 최대 시간(초, 전체). 넘으면 남은 것은 나중에 MODE="download"로
POLL = 15                         # 준비 상태 확인 간격(초)
KEEP_WORK = 0                     # work 백업을 최근 몇 개만 남길지 (0 = 모두 보관, 지우지 않음)
UPDATE_BOARD = True               # 작업보드 갱신
BOARD_MODE = "file"               # "file"  = BASE/reports/작업보드.xlsx — Drive 연결만으로 씀 (추가 승인 없음, Kaggle도 됨) · v4.20 기본
                                  # "sheet" = Google 스프레드시트 (Colab에서 Google 계정 승인이 따로 필요) — BASE 폴더 안에 만들고, 밖에 있으면 옮김
BOARD_FILE = "reports/작업보드.xlsx"
BOARD_SHEET_ID = ""               # sheet: 비우면 BASE/config/board_sheet_id.txt → 없으면 BASE 폴더 안에 새로 만듦
TZ = "Asia/Seoul"

# TASK 이름: eggplant_G1_261019_1_1_uld  (상태의 한글 변형도 같은 상태로 읽음)
# 표준이 아닌 이름도 읽음: 날짜 8자리(20261013), 온실·프로젝트 생략, 목록에 없는 상태(vfdf_ok 등)
NAME_RE = re.compile(
    r"^(?P<base>(?:(?P<project>[A-Za-z]+)_)?(?:(?P<gh>G\d+)_)?(?P<date>(?:20)?\d{6})_(?P<row>\d+)_(?P<plant>\d+))"
    r"_(?P<state>[0-9A-Za-z가-힣_]+)$")
STATE_ALIAS = {"vf_r2리뷰": "vf_r2", "vf_r2_리뷰": "vf_r2", "vf_r2리뷰df": "vf_r2df", "vf_r2_리뷰df": "vf_r2df"}
REVISED_STATES = {"vf_r2df", "vf_r2df_ok"}

INDEX_COLUMNS = ["run_time", "task_id", "task_name", "base_name", "state", "kind", "result",
                 "file", "size_mb", "task_updated", "elapsed_s", "auth_mode", "note", "server"]
PENDING_COLUMNS = ["request_time", "server", "task_id", "task_name", "base_name", "state", "kind", "task_updated",
                   "rq_id", "out_path", "status", "progress", "checked_time", "note", "org"]
# org: 요청한 조직 범위 ('' = 구분 없음 · '-' = 개인 작업공간 · slug) — 받을 때 같은 범위로 (v4.22)
STATUS_COLUMNS = ["server", "task_id", "base_name", "task_name", "state", "reviewer", "in_cvat", "task_updated",
                  "backup_state", "last_backup", "last_kind", "last_result", "last_file", "size_mb",
                  "n_original", "n_work", "n_revised", "can_delete"]


# ==================================================
# 공통
# ==================================================
def now(fmt="%Y-%m-%d %H:%M:%S"):
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(TZ)).strftime(fmt)
    except Exception:
        return datetime.datetime.now().strftime(fmt)


def get_secret(name):
    """Colab 보안 비밀 → (없으면) 환경 변수. 값은 출력하지 않는다."""
    val = None
    try:
        from google.colab import userdata
        val = userdata.get(name)
    except Exception:
        val = os.environ.get(name)
    return val.strip().strip("'\"") if val else None


def sanitize(name):
    return re.sub(r'[\\/*?:"<>| ]', "_", name)


def parse_name(task_id, name):
    if _ctt_parse is not None:                     # v4.6 공통 이름 해석 (상태 뒤 표시 AA·AA_r1·test 등을 뗌)
        f = _ctt_parse(name)
        if f is None:
            return f"_unmatched/task_{task_id}_{sanitize(name)}", "", None
        key = (f["gh"], int(f["row"]), int(f["plant"])) if f["gh"] else None
        return f["base"], f["state"], key
    m = NAME_RE.match(name.strip())
    if not m:
        return f"_unmatched/task_{task_id}_{sanitize(name)}", "", None
    st = m["state"]
    for t in ("_AA", "_test"):                     # 표시 떼기: uld_AA → uld (6번 셀 자동 라벨 업로드), _test (시험 복사)
        while st.lower().endswith(t.lower()) and len(st) > len(t):
            st = st[:-len(t)]
    st = STATE_ALIAS.get(st, st)
    key = (m["gh"], int(m["row"]), int(m["plant"])) if m["gh"] else None   # 온실이 없으면 담당 계산 불가
    return m["base"], st, key


def is_revised(state):
    """승인·확정 상태: vf_r2df, vf_r2df_ok, 그리고 df / df_ok로 끝나는 예전 상태(vfdf_ok 등)"""
    return state in REVISED_STATES or bool(re.search(r"df(_ok)?$", state or ""))


def load_rules(path):
    """config/assignment_rules.csv → [(온실, 라인 from, to, 그루 from, to, 담당)]"""
    rules = []
    if path.exists():
        with open(path, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                try:
                    rules.append((r["greenhouse"], int(r["row_from"]), int(r["row_to"]),
                                  int(r["plant_from"]), int(r["plant_to"]), r["reviewer"]))
                except (KeyError, ValueError):
                    pass
    return rules


def reviewer_of(rules, key):
    if not key:
        return "이름 확인"
    gh, row, plant = key
    for g, r0, r1, p0, p1, who in rules:
        if g == gh and r0 <= row <= r1 and p0 <= plant <= p1:
            return who
    return "미배정"


try:                                             # v4.30.1: 백업 색인·대기 목록은 세션마다 따로 쓰고 합쳐 읽음
    import cvat_task_tools as _shard_mod
    if not hasattr(_shard_mod, "is_sharded"):
        _shard_mod = None
except ImportError:
    _shard_mod = None


def read_csv(path):
    if _shard_mod is not None and _shard_mod.is_sharded(path):
        return _shard_mod.read_sharded(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, columns):
    if _shard_mod is not None and _shard_mod.is_sharded(path):
        return _shard_mod.write_sharded(path, rows, columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})
    tmp.replace(path)


def append_index(path, row):
    if _shard_mod is not None:
        path = _shard_mod.shard_path(path)        # v4.30.1: 이 세션 파일에
    new = not path.exists()
    if not new:
        with open(path, encoding="utf-8-sig") as fh:
            head = next(csv.reader(fh), [])
        if head != INDEX_COLUMNS:                    # 새 열이 생겼으면 예전 줄을 새 머리글로 옮김
            with open(path, encoding="utf-8-sig") as fh:
                _old = list(csv.DictReader(fh))
            _tmp = path.with_suffix(".tmp")
            with open(_tmp, "w", newline="", encoding="utf-8-sig") as fh:
                _w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS, extrasaction="ignore")
                _w.writeheader()
                _w.writerows(_old)
            _tmp.replace(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in INDEX_COLUMNS})


# ==================================================
# 로그인
# ==================================================
def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.cvat+json, application/json",
    })
    return s


def login(session, mode):
    """로그인 후 사용자 정보 반환. 실패하면 예외."""
    if mode == "token":
        tok = CREDENTIALS if isinstance(CREDENTIALS, str) else (get_secret(SECRET_TOKEN) or get_secret("TOKEN"))
        if not tok:
            raise RuntimeError(f"Colab 보안 비밀에 {SECRET_TOKEN}이 없습니다.")
        tok = re.sub(r"^(Token|Bearer)\s+", "", tok, flags=re.IGNORECASE).strip()
        session.headers["Authorization"] = f"Bearer {tok}"
    elif mode == "password":
        if isinstance(CREDENTIALS, (tuple, list)):
            user, pw = CREDENTIALS
        else:
            user, pw = get_secret(SECRET_USER), get_secret(SECRET_PASS)
        if not user or not pw:
            raise RuntimeError(f"Colab 보안 비밀에 {SECRET_USER}, {SECRET_PASS}가 없습니다.")
        payload = {"email": user, "password": pw} if "@" in user else {"username": user, "password": pw}
        r = session.post(f"{HOST}/api/auth/login", json=payload, timeout=60)
        if r.status_code != 200:
            hint = ""
            if r.status_code in (400, 401, 403):
                hint = (" — 아이디/비밀번호를 확인하세요. Google 로그인으로 만든 계정은 비밀번호가 없으므로"
                        " CVAT 설정에서 비밀번호를 먼저 정하거나 token 모드를 쓰세요.")
            raise RuntimeError(f"로그인 실패 (HTTP {r.status_code}){hint}")
        try:
            key = r.json().get("key")
        except ValueError:
            key = None
        if key:                                   # 토큰 방식 응답
            session.headers["Authorization"] = f"Token {key}"
        csrf = session.cookies.get("csrftoken")   # 세션(쿠키) 방식 응답
        if csrf:
            session.headers["X-CSRFToken"] = csrf
        session.headers["Referer"] = HOST + "/"
    else:
        raise ValueError("AUTH_MODE는 'password' 또는 'token'")

    r = session.get(f"{HOST}/api/users/self", timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"인증 확인 실패 (HTTP {r.status_code})")
    if ORGANIZATION_SLUG is not None:             # 이후 모든 요청을 이 조직 범위로 (v4.19)
        session.headers["X-Organization"] = ORGANIZATION_SLUG
    return r.json()


def logout(session, mode):
    if mode == "password":
        try:
            session.post(f"{HOST}/api/auth/logout", timeout=30)
        except Exception:
            pass


# ==================================================
# CVAT 호출
# ==================================================
def list_tasks(session):
    """전체 TASK (페이지를 끝까지 따라감)"""
    params = {"page_size": 100}          # 조직 범위는 로그인 뒤 X-Organization 헤더로
    url, out = f"{HOST}/api/tasks", []
    while url:
        r = session.get(url, params=params, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"TASK 목록 조회 실패 (HTTP {r.status_code})")
        j = r.json()
        out += j.get("results", [])
        url, params = j.get("next"), None
    return out


def request_backup(session, task_id):
    """백업 만들기 요청 → rq_id (서버가 백그라운드로 만듦)"""
    r = session.post(f"{HOST}/api/tasks/{task_id}/backup/export", timeout=60)
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"백업 요청 거절 HTTP {r.status_code} {r.text[:120]}")
    j = r.json() if r.content else {}
    rq_id = j.get("rq_id") or j.get("id")
    if not rq_id:
        raise RuntimeError("응답에 request id 없음")
    return rq_id


def check_backup(session, rq_id):
    """요청 상태 → (status, result_url, message, progress). status: finished/failed/started/queued/expired"""
    s = session.get(f"{HOST}/api/requests/{rq_id}", timeout=60)
    if s.status_code in (404, 410):
        return "expired", None, "서버에 요청이 없음(만료)", ""
    if s.status_code != 200:
        return "unknown", None, f"상태 확인 HTTP {s.status_code}", ""
    sj = s.json()
    pr = sj.get("progress")
    return (sj.get("status") or "unknown", sj.get("result_url"), (sj.get("message") or "")[:200],
            f"{float(pr):.0%}" if isinstance(pr, (int, float)) else "")


def fetch_backup(session, url, save_path):
    """준비된 백업 파일 받기 (.part로 받은 뒤 이름 변경)"""
    if not url.startswith("http"):
        url = HOST + url
    part = save_path.with_name(save_path.name + ".part")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=600) as d:
        if d.status_code != 200:
            raise RuntimeError(f"다운로드 실패 HTTP {d.status_code}")
        with open(part, "wb") as fh:
            for chunk in d.iter_content(chunk_size=2 * 1024 * 1024):
                if chunk:
                    fh.write(chunk)
    if part.stat().st_size == 0:
        part.unlink()
        raise RuntimeError("빈 파일")
    part.replace(save_path)


def download_backup(session, task_id, save_path, log=print):
    """(한 TASK) 요청 → 완료 대기 → 다운로드. 성공 여부와 메모 반환."""
    try:
        rq_id = request_backup(session, task_id)
    except Exception as e:
        return False, str(e)[:200]
    log(f"    백업 요청 등록 ({rq_id}), 서버 처리 대기")
    waited, step = 0, 4
    while waited < MAX_WAIT:
        time.sleep(step)
        waited += step
        st, url, msg, _ = check_backup(session, rq_id)
        if st == "finished":
            fetch_backup(session, url, save_path)
            return True, ""
        if st in ("failed", "expired"):
            return False, f"서버 백업 실패: {msg}"[:200]
        step = min(step + 2, 15)
    return False, f"시간 초과 {MAX_WAIT}초"


def same_server(row, server):
    return (row.get("server") or "") in ("", server)


def build_status(tasks, index_rows, rules, server=""):
    """이 서버의 TASK별 최신 백업 상태. CVAT에서 지워진 TASK도 기록에 남아 있으면 포함."""
    live = {str(t["id"]): t for t in tasks}
    by_task = {}
    for r in index_rows:
        if same_server(r, server):
            by_task.setdefault(r["task_id"], []).append(r)

    rows = []
    for tid in sorted(set(live) | set(by_task), key=lambda x: int(x)):
        hist = by_task.get(tid, [])
        ok = [r for r in hist if r["result"] == "성공"]
        t = live.get(tid)
        name = t["name"] if t else (hist[-1]["task_name"] if hist else "")
        base, state, key = parse_name(tid, name)
        updated = str(t.get("updated_date", ""))[:19] if t else (hist[-1]["task_updated"] if hist else "")
        last_ok = ok[-1] if ok else None
        last = hist[-1] if hist else None

        if t is None:
            bstate = "CVAT에서 삭제됨"
        elif last_ok and last_ok["task_name"] == name and last_ok["task_updated"] == updated:
            bstate = "최신"
        elif last and last["result"] == "실패":
            bstate = "실패"
        elif last_ok:
            bstate = "백업 필요"
        else:
            bstate = "없음"
        can_delete = (t is not None and state.endswith("df_ok") and bstate == "최신"
                      and last_ok is not None and last_ok["kind"] == "revised")
        rows.append({
            "server": server, "task_id": tid, "base_name": base, "task_name": name, "state": state or "?",
            "reviewer": reviewer_of(rules, key), "in_cvat": "예" if t else "아니오",
            "task_updated": updated.replace("T", " "), "backup_state": bstate,
            "last_backup": last_ok["run_time"] if last_ok else "",
            "last_kind": last_ok["kind"] if last_ok else "",
            "last_result": last["result"] if last else "",
            "last_file": last_ok["file"] if last_ok else "",
            "size_mb": last_ok["size_mb"] if last_ok else "",
            "n_original": sum(r["kind"] == "original" for r in ok),
            "n_work": sum(r["kind"] == "work" for r in ok),
            "n_revised": sum(r["kind"] == "revised" for r in ok),
            "can_delete": "예" if can_delete else "",
        })
    return rows


def prune_work(base_dir, keep):
    if keep <= 0:
        return []
    files = sorted((base_dir / "work").glob("*.zip"))
    gone = files[:-keep]
    for f in gone:
        f.unlink()
    return gone


# ==================================================
# 보드 (Google 스프레드시트)
# ==================================================
BOARD_HEADERS = {
    "백업 상태": ["서버", "TASK ID", "기본 이름", "TASK 이름", "상태", "담당", "CVAT에 있음", "TASK 수정 시각",
                "백업 상태", "마지막 백업", "종류", "마지막 결과", "파일", "MB",
                "원본 수", "작업본 수", "개정본 수", "삭제 가능"],
    "백업 색인": ["시각", "서버", "TASK ID", "TASK 이름", "기본 이름", "상태", "종류", "결과", "파일", "MB",
                "TASK 수정 시각", "소요(초)", "로그인", "메모"],
}
KIND_KO = {"original": "원본", "work": "작업본", "revised": "개정본"}


def _board_rows(status_rows, index_rows):
    g = lambda r, k: "" if r.get(k) is None else r.get(k)          # 없는 열은 빈칸 (예전 색인·다른 버전의 줄도 보드에)
    srows = [[g(r, "server"), g(r, "task_id"), g(r, "base_name"), g(r, "task_name"), g(r, "state"), g(r, "reviewer"), g(r, "in_cvat"),
              g(r, "task_updated"), g(r, "backup_state"), g(r, "last_backup"), KIND_KO.get(g(r, "last_kind"), g(r, "last_kind")),
              g(r, "last_result"), g(r, "last_file"), g(r, "size_mb"), g(r, "n_original"), g(r, "n_work"), g(r, "n_revised"),
              g(r, "can_delete")] for r in status_rows]
    irows = [[g(r, "run_time"), g(r, "server"), g(r, "task_id"), g(r, "task_name"), g(r, "base_name"), g(r, "state"),
              KIND_KO.get(g(r, "kind"), g(r, "kind")), g(r, "result"), g(r, "file"), g(r, "size_mb"), g(r, "task_updated"),
              g(r, "elapsed_s"), g(r, "auth_mode"), g(r, "note")] for r in index_rows[-1000:][::-1]]   # 최근 것이 위
    return srows, irows


def update_board_file(status_rows, index_rows, path):
    """작업보드를 Drive의 BASE 아래 xlsx 파일로 (탭 '백업 상태'·'백업 색인'). 추가 승인 없이 Drive 연결만으로 씀.
    Drive에서 열면 Google 스프레드시트로 미리 보기·열기가 됨. openpyxl이 없으면 탭마다 CSV"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    srows, irows = _board_rows(status_rows, index_rows)
    tabs = [("백업 상태", srows), ("백업 색인", irows)]
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        out = []
        for title, rows in tabs:
            p = path.with_name(f"{path.stem}_{title.replace(' ', '_')}.csv")
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh).writerows([BOARD_HEADERS[title]] + rows)
            out.append(p)
        return str(out[0])
    wb_ = Workbook()
    wb_.remove(wb_.active)
    for title, rows in tabs:
        ws = wb_.create_sheet(title)
        ws.append(BOARD_HEADERS[title])
        for r in rows:
            ws.append(["" if v is None else v for v in r])
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for i, h in enumerate(BOARD_HEADERS[title], 1):
            width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:300]]) + 2
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(width, 6), 60)
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    wb_.save(tmp)
    os.replace(tmp, path)                          # 다 쓴 뒤 바꿔 넣음 (중간에 끊겨도 예전 파일은 그대로)
    return str(path)


def _drive_folder_id(path):
    """Colab Drive 연결 폴더의 Drive ID (없으면 None)"""
    try:
        return os.getxattr(str(path), "user.drive.id").decode()
    except Exception:
        return None


def update_board(status_rows, index_rows, sheet_id_file):
    try:
        from google.colab import auth
    except ImportError:                            # v4.13: Kaggle 등 Colab 밖 → 보드는 건너뜀 (CSV에는 그대로 기록)
        raise RuntimeError("Colab이 아니어서 작업보드(스프레드시트)는 건너뜀 — 보드가 필요하면 Colab에서 13번 셀")
    import google.auth
    import gspread
    auth.authenticate_user()                       # 운영자 Google 계정으로 시트 쓰기 권한 승인 (처음 한 번)
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets",
                                           "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)

    fid = _drive_folder_id(BASE)                   # 작업보드는 BASE(eggplant_yolo) 폴더 안에 둠 (v4.20)
    sid = BOARD_SHEET_ID or (sheet_id_file.read_text().strip() if sheet_id_file.exists() else "")
    if sid:
        sh = gc.open_by_key(sid)
        if fid:                                    # 예전(v4.19까지)처럼 내 드라이브 맨 위에 있으면 BASE 폴더로 옮김
            try:
                from googleapiclient.discovery import build
                drv = build("drive", "v3", credentials=creds, cache_discovery=False)
                par = drv.files().get(fileId=sid, fields="parents").execute().get("parents", [])
                if fid not in par:
                    drv.files().update(fileId=sid, addParents=fid, removeParents=",".join(par), fields="id").execute()
                    print(f"[보드] '작업보드'를 {BASE.name}/ 폴더 안으로 옮겼습니다")
            except Exception as e:
                print(f"[보드] 작업보드를 {BASE.name}/ 폴더로 옮기지 못했습니다 ({type(e).__name__}) — Drive에서 직접 옮겨도 됩니다")
    else:
        sh = gc.create("작업보드", folder_id=fid) if fid else gc.create("작업보드")
        sheet_id_file.parent.mkdir(parents=True, exist_ok=True)
        sheet_id_file.write_text(sh.id)
        print(f"[보드] 새 스프레드시트 '작업보드'를 만들었습니다 ({BASE.name}/ 폴더 안)" if fid else
              "[보드] 새 스프레드시트 '작업보드'를 만들었습니다 (폴더 ID를 몰라 내 드라이브 맨 위 — 원하는 폴더로 옮겨도 됩니다)")

    def put(title, header, rows):
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=max(100, len(rows) + 10), cols=len(header))
        ws.clear()
        ws.update(range_name="A1", values=[header] + rows)
        ws.format("1:1", {"textFormat": {"bold": True}})
        ws.freeze(rows=1)

    srows, irows = _board_rows(status_rows, index_rows)
    put("백업 상태", BOARD_HEADERS["백업 상태"], srows)
    put("백업 색인", BOARD_HEADERS["백업 색인"], irows)
    return sh.url


# ==================================================
# 실행
# ==================================================
def run_backup():
    try:
        from google.colab import drive
        drive.mount("/content/drive", force_remount=False)
    except Exception:
        pass
    backups = BASE / "backups"
    index_csv, status_csv = BASE / "backup_index.csv", BASE / "backup_status.csv"
    rules = load_rules(BASE / "config" / "assignment_rules.csv")

    session = new_session()
    print(f"[*] CVAT({HOST}) 로그인 중 — 방식: {'ID/PASS' if AUTH_MODE == 'password' else 'PAT 토큰'}")
    me = login(session, AUTH_MODE)
    host = urlparse(HOST).hostname or HOST
    server = f"{me.get('username')}@{host}"               # 서버 + 계정 (대장·보드에서 구분)
    tag = "" if host == "app.cvat.ai" else "_" + sanitize(host)   # app.cvat.ai가 아니면 파일 이름에 서버 표시
    print(f"[*] 로그인 성공: {server}\n")
    if NAME_QUERY and match_name is None:
        raise RuntimeError("NAME_QUERY를 쓰려면 같은 폴더에 cvat_task_tools.py가 있어야 합니다.")

    try:
        tasks = list_tasks(session)
        index_rows = read_csv(index_csv)
        print(f"[*] CVAT TASK {len(tasks)}개")

        _ids = {int(x) for x in (re.split(r"[\s,;]+", TASK_IDS.strip()) if isinstance(TASK_IDS, str) else
                                ([TASK_IDS] if isinstance(TASK_IDS, int) else TASK_IDS)) if str(x).strip()} if TASK_IDS else None   # "123" · [123, "456"] 모두
        if _ids is None and PROJECT_ID is not None:      # 기본 프로젝트 범위 (ID를 직접 주면 안 봄)
            tasks = [t for t in tasks if (t.get("project_id") or 0) == PROJECT_ID]
        if ORGANIZATION_SLUG is not None or PROJECT_ID is not None:
            print(f"[*] 범위: 조직 {ORGANIZATION_SLUG if ORGANIZATION_SLUG else ('개인 작업공간' if ORGANIZATION_SLUG == '' else '구분 없음')}"
                  f" · 프로젝트 {'전부' if PROJECT_ID is None else ('없는 TASK만' if PROJECT_ID == 0 else PROJECT_ID)} → TASK {len(tasks)}개")
        targets = [t for t in tasks if (_ids is None or t["id"] in _ids)
                   and (not NAME_QUERY or match_name(t["name"], NAME_QUERY)[0])
                   and (not ONLY_STATES or parse_name(t["id"], t["name"])[1] in ONLY_STATES)]
        if NAME_QUERY or TASK_IDS or ONLY_STATES:
            print(f"[*] 대상 {len(targets)}개 (검색어 '{NAME_QUERY}'" + (f", TASK {TASK_IDS}" if TASK_IDS else "")
                  + (f", 상태 {ONLY_STATES}" if ONLY_STATES else "") + ")")
        if PREVIEW:
            print("[미리 보기] 백업하지 않습니다. (검색어 규칙은 모든 셀 같음)")
            if select_tasks is not None:
                try:
                    from IPython.display import display as _disp
                except Exception:
                    _disp = None
                rows = [{"task_id": t["id"], "name": t["name"], "updated": str(t.get("updated_date", ""))[:16]} for t in tasks]
                if TASK_IDS:
                    select_tasks(rows, "", ids=TASK_IDS, display=_disp, label="백업 대상")
                else:
                    select_tasks(rows, NAME_QUERY, display=_disp, label="백업 대상")
            else:
                for t in targets:
                    print(f"  ● TASK {t['id']:<10} {t['name']}")
            return []
        assert MODE in ("all", "request", "download"), 'MODE는 "all", "request", "download" 중 하나'
        pending_csv = backups / "pending_backups.csv"
        pending = read_csv(pending_csv)
        open_states = ("요청됨", "준비 중")

        def finish(p, ok, note="", path=None, elapsed=0):
            """받은(또는 실패한) 요청을 백업 색인에 기록"""
            row = {"run_time": now(), "task_id": p["task_id"], "task_name": p["task_name"], "base_name": p["base_name"],
                   "state": p["state"], "kind": p["kind"], "auth_mode": AUTH_MODE, "task_updated": p["task_updated"],
                   "server": server, "elapsed_s": elapsed}
            if ok:
                row.update(result="성공", file=str(path.relative_to(BASE)), size_mb=f"{path.stat().st_size / 2**20:.1f}")
                print(f"    ✅ TASK {p['task_id']} {p['task_name']} → {row['file']} ({row['size_mb']} MB)")
                if p["kind"] == "work":
                    for g in prune_work(backups / p["base_name"], KEEP_WORK):
                        print(f"    오래된 작업본 정리: {g.name}")
            else:
                row.update(result="실패", note=note)
                print(f"    ❌ TASK {p['task_id']} {p['task_name']}: {note}")
            append_index(index_csv, row)
            index_rows.append({k: str(row.get(k, "")) for k in INDEX_COLUMNS})   # CSV와 같은 열 (성공 줄엔 note, 실패 줄엔 file이 없어 보드가 KeyError로 실패하던 것 고침 — v4.24.1)
            if _ctt_log is not None:                   # 시계열 작업 기록 (노트북이 작업을 열어 두었을 때)
                try:
                    c = _ctt_counts(path) if ok and _ctt_counts else {}
                    _ctt_log("backup", p["task_id"], p["task_name"], row["result"], base=str(BASE), server=server,
                             file=row.get("file", ""), size_mb=row.get("size_mb", ""), task_updated=p["task_updated"],
                             sec=elapsed, summary=f"{KIND_KO.get(p['kind'], p['kind'])} {note}".strip(),
                             **{k: v for k, v in c.items() if k in ("frames", "objects", "boxes", "by_label")})
                except Exception:
                    pass

        # ---------- 1) 요청 ----------
        if MODE in ("all", "request"):
            print("=" * 60)
            for n, t in enumerate(targets, 1):
                tid, name = t["id"], t["name"]
                base, state, _ = parse_name(tid, name)
                updated = str(t.get("updated_date", ""))[:19]
                head = f"[{n}/{len(targets)}] TASK {tid} '{name}'"
                ok_rows = [r for r in index_rows if r["task_id"] == str(tid) and r["result"] == "성공"
                           and same_server(r, server)]
                last = ok_rows[-1] if ok_rows else None
                if not FORCE and last and last["task_name"] == name and last["task_updated"] == updated:
                    print(f"{head} — 바뀐 것 없음 (마지막 백업 {last['run_time']}), 건너뜀")
                    continue
                if not FORCE and any(p["task_id"] == str(tid) and p["status"] in open_states and same_server(p, server)
                                     for p in pending):
                    print(f"{head} — 이미 요청해 둠 (받기 대기), 건너뜀")
                    continue
                kind = "revised" if is_revised(state) else ("work" if ok_rows else "original")
                stem = base.split("/")[-1]
                fname = f"{stem}_{state or 'noname'}_{kind}{tag}_{now('%Y%m%d_%H%M%S')}.zip"
                p = {"request_time": now(), "server": server, "task_id": str(tid), "task_name": name, "base_name": base,
                     "state": state, "kind": kind, "task_updated": updated,
                     "out_path": str((backups / base / kind / fname).relative_to(BASE)),
                     "org": "" if ORGANIZATION_SLUG is None else ("-" if ORGANIZATION_SLUG == "" else ORGANIZATION_SLUG)}
                try:
                    p.update(rq_id=request_backup(session, tid), status="요청됨")
                    print(f"{head} → {KIND_KO[kind]} 백업 요청됨")
                except Exception as e:
                    p.update(status="실패", note=f"{type(e).__name__}: {e}"[:200])
                    finish(p, False, p["note"])
                pending.append(p)
            write_csv(pending_csv, pending, PENDING_COLUMNS)

        # ---------- 2) 받기 ----------
        if MODE in ("all", "download"):
            todo = [p for p in pending if p.get("status") in open_states and same_server(p, server)]
            print("=" * 60)
            print(f"[*] 받을 백업 {len(todo)}개 ({server})" + ("" if MODE == "all" else " — 한 번 확인"))
            deadline = time.time() + (MAX_WAIT if MODE == "all" else 0)
            while todo:
                for p in list(todo):
                    p["checked_time"] = now()
                    _o = (p.get("org") or "").strip()                # 요청했던 조직 범위로 확인·받기 (v4.22)
                    if _o:
                        session.headers["X-Organization"] = "" if _o == "-" else _o
                    else:
                        session.headers.pop("X-Organization", None)
                    try:
                        st, url, msg, prog = check_backup(session, p["rq_id"])
                    except Exception as e:
                        p["note"] = f"상태 확인 실패: {e}"[:200]
                        continue
                    if st == "finished":
                        path = BASE / p["out_path"]
                        t0 = time.time()
                        try:
                            fetch_backup(session, url, path)
                            p.update(status="받음", progress="100%", note="")
                            finish(p, True, path=path, elapsed=round(time.time() - t0))
                        except Exception as e:
                            p.update(status="준비 중", note=f"받기 실패: {e}"[:200])
                            print(f"    ⚠️ TASK {p['task_id']} 받기 실패 (다음에 다시): {e}")
                            continue
                        todo.remove(p)
                    elif st in ("failed", "expired"):
                        p.update(status="만료" if st == "expired" else "실패", note=msg)
                        finish(p, False, ("만료 → 다시 요청: " if st == "expired" else "서버 백업 실패: ") + msg)
                        todo.remove(p)
                    else:
                        p.update(status="준비 중", progress=prog)
                write_csv(pending_csv, pending, PENDING_COLUMNS)       # 중간 저장 (세션이 끊겨도 남음)
                if not todo or time.time() >= deadline:
                    break
                print(f"  … 준비 중 {len(todo)}개, {POLL}초 뒤 다시 확인 (최대 {max(0, int(deadline - time.time()))}초)")
                time.sleep(POLL)
            if todo:
                print(f"[*] 아직 준비 중 {len(todo)}개 → 나중에 MODE='download'로 받으세요: "
                      + ", ".join(p["task_name"] for p in todo[:10]) + (" …" if len(todo) > 10 else ""))
            write_csv(pending_csv, pending, PENDING_COLUMNS)
    finally:
        logout(session, AUTH_MODE)

    status = build_status(tasks, index_rows, rules, server)
    others = [r for r in read_csv(status_csv) if not same_server(r, server)]   # 다른 서버의 상태는 그대로 둠
    write_csv(status_csv, others + status, STATUS_COLUMNS)
    print("=" * 60)
    cnt = {}
    for r in status:
        cnt[r["backup_state"]] = cnt.get(r["backup_state"], 0) + 1
    print("[*] 백업 상태:", ", ".join(f"{k} {v}" for k, v in cnt.items()) or "없음")
    dels = [r["task_name"] for r in status if r["can_delete"]]
    if dels:
        print(f"[*] 확정·개정본 백업이 끝나 CVAT에서 지워도 되는 TASK: {', '.join(dels)}")
    try:
        import pandas as pd
        from IPython.display import display
        display(pd.DataFrame(status)[["task_id", "task_name", "reviewer", "backup_state", "last_backup",
                                      "last_kind", "size_mb", "can_delete"]])
    except Exception:
        pass

    if UPDATE_BOARD and BOARD_MODE:
        try:
            if BOARD_MODE == "sheet":
                url = update_board(others + status, index_rows, BASE / "config" / "board_sheet_id.txt")
            else:
                url = os.path.relpath(update_board_file(others + status, index_rows, BASE / BOARD_FILE), BASE)
            print(f"[보드] '백업 상태'·'백업 색인' 탭 갱신: {url}")
        except Exception as e:
            print(f"[보드] 갱신 실패 ({type(e).__name__}: {e}) — CSV는 저장됨: {status_csv}")
    return status


if __name__ == "__main__":      # Colab 셀에 붙여 넣어 실행하면 바로 실행, import하면 실행 안 함
    run_backup()
