"""
CVAT 태스크 작업 도구 (Colab 노트북에서 import해서 사용)

- PAT로 CVAT 접속, 내 태스크 목록 보기
- 태스크 정보(이름, 종류, 프레임 수, step, 원본 영상 이름) 가져오기
- 현재 라벨을 CVAT for video 1.1로 export (업로드 전 백업 / 검수본 수집)
- track XML 업로드
- 원본 mp4 찾기 (Drive videos/에서 태스크의 원본 파일 이름으로)
- 작업 대장 task_registry.csv 기록·조회 (실행 1회 = 1줄, Google 스프레드시트로 열림)

토큰은 인자로만 받고 파일에 저장하지 않는다.
"""
__version__ = "4.32.0"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import csv
import json
import time
import datetime
import fnmatch
from collections import Counter
import os
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

TZ = "Asia/Seoul"
EXPORT_FORMAT = "CVAT for video 1.1"
IMPORT_FORMAT = "CVAT 1.1"

REGISTRY_COLUMNS = [
    "run_time", "action", "task_id", "task_name", "media", "video", "frames", "step",
    "existing_labels", "model", "tracks", "precision", "recall", "f1",
    "count_error", "fragments", "id_switches", "idf1",
    "backup_file", "result_file", "status", "note", "server",
]
ACTIONS = {"track": "track 생성", "upload": "업로드", "review": "검수 수집", "auto": "프레임별 자동 라벨링",
           "export": "라벨 export", "restore": "백업 복원", "create": "TASK 생성"}


# ---------------- 시간 ----------------
def now(fmt="%Y-%m-%d %H:%M:%S"):
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(TZ)).strftime(fmt)
    except Exception:
        return datetime.datetime.now().strftime(fmt)


def stamp():
    return now("%Y%m%d_%H%M%S")


# ---------------- TASK ID 정리 ----------------
def as_task_ids(v):
    """TASK ID 입력을 정수 목록으로: 2696411 · '2696411' · '2696411, 2696412' · [2696411, '2696412'] · None/''/0 → []"""
    if v is None or v == "" or v == 0:
        return []
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [int(v)]
    if isinstance(v, str):
        v = re.split(r"[\s,;]+", v.strip())
    out = []
    for x in v:
        for y in (re.split(r"[\s,;]+", x.strip()) if isinstance(x, str) else [x]):
            if y in ("", None):
                continue
            try:
                out.append(int(float(y)))
            except (TypeError, ValueError):
                raise ValueError(f"TASK ID는 숫자여야 합니다: {y!r}") from None
    return list(dict.fromkeys(out))


def as_task_id(v):
    """TASK ID 하나 → 정수 (0/None/'' → 0)"""
    ids = as_task_ids(v)
    if len(ids) > 1:
        raise ValueError(f"TASK ID 하나만 적으세요: {v!r}")
    return ids[0] if ids else 0


# ---------------- CVAT 접속 ----------------
def connect(host, token=None, credentials=None):
    """token(PAT) 또는 credentials=(아이디, 비밀번호) 중 하나로 접속 (조직·프로젝트 범위는 set_scope로)"""
    from cvat_sdk import make_client
    if credentials and all(credentials):
        return make_client(host, credentials=tuple(credentials))
    if not token:
        raise ValueError("토큰 또는 아이디/비밀번호가 비어 있습니다.")
    token = re.sub(r"^(Token|Bearer)\s+", "", token.strip(), flags=re.IGNORECASE)   # 앞에 붙은 'Token ' 등 제거
    return with_retry(lambda: make_client(host, access_token=token), what="CVAT 접속")


RETRY_WAITS = (60, 120, 240, 480)       # v4.31.4: 503·429·연결 오류 → 1·2·4·8분 뒤 다시


def cvat_error_hint(e):
    """오류 종류별 안내 (401·403만 토큰 확인, 5xx·429는 서버 일시 장애)"""
    s = f"{type(e).__name__}: {e}"
    code = getattr(e, "status", None) or getattr(e, "status_code", None)
    if code is None:
        m = re.search(r"\b(401|403|404|429|5\d\d)\b", s)
        code = int(m.group(1)) if m else None
    if code in (401, 403):
        return f"CVAT 인증 실패 (HTTP {code}) — 토큰(CVAT_TOKEN 보안 비밀)·조직 권한을 확인하세요"
    if code == 429:
        return "CVAT 요청이 너무 많음 (HTTP 429) — 잠시 뒤 다시 (토큰 문제 아님)"
    if code and 500 <= code < 600:
        return f"CVAT 서버 일시 장애 (HTTP {code}) — 토큰 문제 아님, 잠시 뒤 다시"
    if re.search(r"Connection|Timeout|timed out|Max retries|RemoteDisconnected", s):
        return "CVAT 연결 오류 (네트워크) — 잠시 뒤 다시"
    return ""


def _retryable(e):
    h = cvat_error_hint(e)
    return bool(h) and "인증 실패" not in h


def with_retry(fn, what="CVAT", waits=None, log=print, sleep=None):
    """fn()을 부르고, 일시 장애(503·429·5xx·연결 오류)면 1·2·4·8분 간격으로 다시 시도. 인증 오류 등은 바로 알림"""
    import time as _t
    waits = RETRY_WAITS if waits is None else waits
    sleep = sleep or _t.sleep
    for i in range(len(waits) + 1):
        try:
            return fn()
        except Exception as e:
            hint = cvat_error_hint(e)
            if i >= len(waits) or not _retryable(e):
                if hint:
                    raise RuntimeError(f"{what} 실패 — {hint} ({type(e).__name__}: {str(e)[:200]})") from e
                raise
            if log:
                log(f"⏳ {what}: {hint} → {waits[i] // 60}분 뒤 다시 ({i + 1}/{len(waits)})")
            sleep(waits[i])


def whoami(client):
    try:
        u = client.api_client.users_api.retrieve_self()[0]
        return u.username
    except Exception:
        return "?"


def list_tasks(client, limit=50, project="scope"):
    """지금 조직(client.organization_slug)의 TASK 목록. project: "scope" = set_scope로 정한 기본 프로젝트
    (없으면 전부) · None = 전부 · 0 = 프로젝트 없는 TASK만 · 숫자 = 그 프로젝트만"""
    if project == "scope":
        project = (getattr(client, "eg_scope", None) or {}).get("project_id")
    rows = []
    for t in client.tasks.list():
        pid = getattr(t, "project_id", None) or None
        if project is not None and (pid or 0) != project:
            continue
        rows.append({
            "task_id": t.id, "name": t.name, "status": getattr(t, "status", ""),
            "media": getattr(t, "media_type", "") or getattr(t, "mode", ""),
            "frames": getattr(t, "size", ""), "project": pid or "",
            "org_id": getattr(t, "organization", None) or None,
            "updated": str(getattr(t, "updated_date", ""))[:16].replace("T", " "),
            "updated_utc": str(getattr(t, "updated_date", "") or ""),
            "updated_iso": iso_z(getattr(t, "updated_date", "")),     # v4.31.4: 시간대 붙임 (웹 화면이 KST로 바르게)
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows[:limit]


# ---------------- 조직 · 프로젝트 (v4.19) ----------------
from contextlib import contextmanager as _ctxmgr


@_ctxmgr
def org_context(client, slug):
    """잠깐 다른 조직 범위로 (None = 조직 구분 없이 — 보이는 TASK 전부). 끝나면 원래대로"""
    prev = getattr(client, "organization_slug", None)
    client.organization_slug = slug
    try:
        yield client
    finally:
        client.organization_slug = prev


def list_orgs(client):
    """내가 속한 조직 [{'id','slug','name'}]"""
    try:
        with org_context(client, None):
            return [{"id": o.id, "slug": getattr(o, "slug", "") or "", "name": getattr(o, "name", "") or getattr(o, "slug", "")}
                    for o in client.organizations.list()]
    except Exception:
        return []


def list_projects(client, all_orgs=False):
    """프로젝트 [{'id','name','org_id'}] — 지금 조직 범위 (all_orgs=True면 보이는 것 전부)"""
    def _rows():
        return [{"id": p.id, "name": p.name, "org_id": getattr(p, "organization", None) or None} for p in client.projects.list()]
    if all_orgs:
        with org_context(client, None):
            return _rows()
    return _rows()


def scope_text(sc):
    """'조직 lab · 프로젝트 가지 (12)' 같은 한 줄"""
    if not sc:
        return "조직·프로젝트 구분 없음"
    org = sc.get("org")
    o = "조직 구분 없음 (보이는 TASK 전부)" if org is None else ("개인 작업공간" if org == "" else f"조직 {sc.get('org_name') or org}")
    pid = sc.get("project_id")
    p = "모든 프로젝트" if pid is None else ("프로젝트 없는 TASK만" if pid == 0 else f"프로젝트 {sc.get('project_name', '')} (ID {pid})")
    return f"{o} · {p}"


def set_scope(client, org=None, project=""):
    """클라이언트의 조직·프로젝트 범위를 정함 (노트북 0번 셀 CVAT_ORG·CVAT_PROJECT).
    org: None = 구분 안 함 · '' = 개인 작업공간 · 조직 slug 또는 이름.
    project: '' 또는 None = 모든 프로젝트 · '-' = 프로젝트 없는 TASK만 · 프로젝트 이름 또는 ID (그 조직 안).
    반환 {'org','org_name','project_id','project_name'} — client.eg_scope에도 남음 (list_tasks가 씀).
    이름을 찾지 못하면 ValueError (있는 조직·프로젝트 목록과 함께)"""
    key = (org, str(project if project is not None else ""))
    cache = client.__dict__.setdefault("_eg_scope_cache", {}) if hasattr(client, "__dict__") else {}
    if key in cache:
        sc = dict(cache[key])
    else:
        sc = {"org": None, "org_name": "", "project_id": None, "project_name": ""}
        if org is not None:
            o = str(org).strip()
            if o:
                orgs = list_orgs(client)
                hit = [x for x in orgs if o.lower() in (x["slug"].lower(), x["name"].lower())]
                if not hit:
                    raise ValueError(f"조직 '{o}'를 찾지 못했습니다. 내가 속한 조직(slug / 이름): "
                                     f"{[(x['slug'], x['name']) for x in orgs] or '없음'}")
                sc["org"], sc["org_name"] = hit[0]["slug"], hit[0]["name"]
            else:
                sc["org"], sc["org_name"] = "", "개인 작업공간"
        pr = "" if project is None else str(project).strip()
        if pr == "-":
            sc["project_id"], sc["project_name"] = 0, "(프로젝트 없음)"
        elif pr:
            with org_context(client, sc["org"]):
                projs = list_projects(client)
            hit = [p for p in projs if str(p["id"]) == pr] or [p for p in projs if p["name"].lower() == pr.lower()]
            if not hit:
                raise ValueError(f"프로젝트 '{pr}'를 {'이 조직' if sc['org'] else '이 범위'}에서 찾지 못했습니다. 있는 프로젝트(ID, 이름): "
                                 f"{[(p['id'], p['name']) for p in projs][:20] or '없음'}")
            if len(hit) > 1:
                raise ValueError(f"이름이 '{pr}'인 프로젝트가 {len(hit)}개입니다 → ID로 적으세요: {[p['id'] for p in hit]}")
            sc["project_id"], sc["project_name"] = int(hit[0]["id"]), hit[0]["name"]
        cache[key] = dict(sc)
    client.organization_slug = sc["org"]
    try:
        client.eg_scope = sc
    except Exception:
        pass
    return sc


def list_tasks_all(client, limit=5000):
    """웹 상태 파일용: 보이는 모든 조직의 TASK (조직·프로젝트 이름 포함) + 조직·프로젝트 목록.
    반환 (rows, catalog) — catalog = {'orgs': [...], 'projects': [{'id','name','org'}]}"""
    orgs = list_orgs(client)
    by_id = {o["id"]: o for o in orgs}
    try:
        projs = list_projects(client, all_orgs=True)
    except Exception:
        projs = []
    pname = {p["id"]: p["name"] for p in projs}
    with org_context(client, None):
        rows = list_tasks(client, limit=limit, project=None)
    for r in rows:
        o = by_id.get(r.get("org_id"))
        r["org"] = o["slug"] if o else ("" if r.get("org_id") is None else str(r.get("org_id")))
        r["project_name"] = pname.get(r.get("project") or 0, "")
    cat = {"orgs": [{"slug": o["slug"], "name": o["name"]} for o in orgs],
           "projects": [{"id": p["id"], "name": p["name"],
                         "org": (by_id.get(p["org_id"]) or {}).get("slug", "" if p["org_id"] is None else str(p["org_id"]))} for p in projs]}
    return rows, cat


def task_basic(task):
    def _get(k):
        try:
            return str(getattr(task, k, "") or "")
        except Exception:
            return ""
    media, mode, chunk = _get("media_type"), _get("mode"), _get("data_original_chunk_type")
    # 영상(mp4)으로 만든 TASK: 원본 청크가 video (media_type 값은 서버 버전마다 달라 보조로만 씀)
    is_video = chunk == "video" or media.startswith("video") or (not chunk and not media and mode == "interpolation")
    return {"task_id": task.id, "task_name": task.name, "media": "video" if is_video else (media or chunk or mode),
            "frames": getattr(task, "size", ""), "is_video": is_video,
            "media_detail": f"media_type={media or '-'} · original_chunk={chunk or '-'} · mode={mode or '-'}"}


def _conflict_rq_id(e):
    """409 Conflict(같은 export가 이미 진행 중)일 때 서버가 알려 준 진행 중 요청 ID"""
    import json as _json
    if getattr(e, "status", None) != 409:
        return None
    body = getattr(e, "body", None)
    try:
        b = _json.loads(body.decode("utf-8", "ignore") if isinstance(body, bytes) else (body or "{}"))
        return b.get("rq_id")
    except Exception:
        return None


def _export(task, fmt, path, include_images, max_wait=900):
    """export해서 파일로 저장. 같은 export가 이미 서버에서 진행 중이면(409 Conflict, 이전 실행을 중간에 멈춘 경우 등)
    새로 요청하지 않고 그 요청이 끝나기를 기다려 결과를 받음"""
    import time
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        task.export_dataset(fmt, str(path), include_images=include_images)
        return path
    except Exception as e:
        rq_id = _conflict_rq_id(e)
        if not rq_id:
            raise
    client = task._client
    t0, wait = time.time(), 3
    while time.time() - t0 < max_wait:
        st = export_status(client, rq_id)
        if st["status"] == "finished" and st["result_url"]:
            download_result(client, st["result_url"], path)
            return path
        if st["status"] == "failed":
            raise RuntimeError(f"진행 중이던 export가 실패: {st['message'][:200]}")
        time.sleep(wait)
        wait = min(wait + 2, 15)
    raise RuntimeError(f"진행 중이던 export가 {max_wait}초 안에 끝나지 않음 (rq {rq_id}) — 잠시 뒤 다시 실행")


def export_annotations(task, path):
    """현재 라벨을 CVAT for video 1.1 (이미지 없이)로 받아 저장"""
    return _export(task, EXPORT_FORMAT, path, False)


def export_labels(task, path, fmt="CVAT for images 1.1", include_images=False):
    """라벨을 지정 형식으로 export (무료 플랜은 include_images=False만 가능)"""
    return _export(task, fmt, path, include_images)


# ---------------- export 요청 / 상태 / 받기 (요청과 받기를 나눠서) ----------------
PENDING_COLUMNS = ["request_time", "server", "task_id", "task_name", "format", "images", "rq_id", "out_path",
                   "status", "progress", "checked_time", "expiry", "result_file", "note", "org"]


def org_ctx_value(slug):
    """대기 목록에 남길 조직 범위: None(구분 없음) → '' · 개인 작업공간 '' → '-' · 조직 slug 그대로 (v4.22)"""
    return "" if slug is None else ("-" if slug == "" else str(slug))


def org_ctx_slug(v):
    """org_ctx_value의 반대 — 받을 때 요청했던 조직 범위로 (예전 줄은 '' → 구분 없음)"""
    v = (v or "").strip()
    return None if not v else ("" if v == "-" else v)


def request_export(client, task_id, fmt, include_images=False):
    """서버에 export 준비를 요청만 함 → rq_id (서버가 백그라운드에서 파일을 만듦)"""
    try:
        rq, _ = client.api_client.tasks_api.create_dataset_export(format=fmt, id=int(task_id),
                                                                  save_images=bool(include_images))
        return rq.rq_id
    except Exception as e:
        rq_id = _conflict_rq_id(e)          # 같은 요청이 이미 진행 중 → 그 요청을 이어서 씀
        if rq_id:
            return rq_id
        raise


def export_status(client, rq_id):
    """요청 상태: status(queued/started/finished/failed), progress, message, result_url, expiry"""
    r, _ = client.api_client.requests_api.retrieve(rq_id)
    st = getattr(r, "status", "")
    prog = getattr(r, "progress", None)
    return {"status": getattr(st, "value", str(st)), "progress": "" if prog is None else f"{float(prog):.0%}",
            "message": getattr(r, "message", "") or "", "result_url": getattr(r, "result_url", "") or "",
            "expiry": str(getattr(r, "expiry_date", "") or "")[:19].replace("T", " ")}


def download_result(client, url, path):
    """준비된 export 파일 받기"""
    from cvat_sdk.core.downloading import Downloader
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    return Downloader(client).download_file(url, path)


def read_pending(path):
    return read_sharded(path)                      # v4.30.1: 세션 파일을 합쳐 요청마다 가장 나중 상태


def write_pending(path, rows):
    return write_sharded(path, rows, PENDING_COLUMNS)   # v4.30.1: 이 세션 파일에만


def api_error(e):
    """cvat-sdk 오류를 한 줄로: '403 Forbidden — You do not have permission to perform this action.'"""
    import json as _json
    status, reason, body = getattr(e, "status", None), getattr(e, "reason", ""), getattr(e, "body", None)
    if status is None:
        return f"{type(e).__name__}: {str(e)[:200]}"
    detail = ""
    try:
        b = _json.loads(body) if body else {}
        detail = b.get("detail") or b.get("message") or str(b)[:200] if isinstance(b, dict) else str(b)[:200]
    except Exception:
        detail = (body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body or ""))[:200]
    return f"{status} {reason} — {detail}".strip(" —")


def task_people(task):
    """TASK 소유자·담당자 이름 (권한 문제 안내용)"""
    def name(u):
        return getattr(u, "username", None) or (u.get("username") if isinstance(u, dict) else None) or "-"
    owner = name(getattr(task, "owner", None)) if getattr(task, "owner", None) else "-"
    assignee = name(getattr(task, "assignee", None)) if getattr(task, "assignee", None) else "-"
    return owner, assignee


def import_tracks(task, xml_path, replace=False, backup=None, log=print):
    """track XML 올리기. replace=True면 기존 라벨을 모두 지운 뒤 올림 (실패하면 backup으로 되돌림)"""
    if replace:
        return replace_annotations(task, lambda: task.import_annotations(IMPORT_FORMAT, str(xml_path)), backup, log=log)
    task.import_annotations(IMPORT_FORMAT, str(xml_path))


def annotation_count(task):
    """지금 CVAT 라벨 수 (박스 shape + track)"""
    a = task.get_annotations()
    return len(a.shapes) + len(a.tracks)


def replace_annotations(task, write, backup=None, log=print):
    """기존 라벨 교체: (백업은 미리 받아 둠) → 모두 지움 → write()로 새 라벨 올림.
    올리다 실패하면 backup(업로드 직전 export zip)을 다시 올려 원래대로 되돌리고 오류를 다시 냄"""
    before = annotation_count(task)
    task.remove_annotations()
    log(f"  기존 라벨 {before}개 지움 (백업: {Path(backup).name if backup else '없음'})")
    try:
        write()
    except Exception:
        if backup:
            log("  ⚠️ 새 라벨 올리기 실패 → 백업으로 되돌리는 중")
            try:
                task.remove_annotations()
                task.import_annotations(IMPORT_FORMAT, str(backup))
                log(f"  되돌림 완료 (라벨 {annotation_count(task)}개)")
            except Exception as e2:
                log(f"  ❌ 되돌리기도 실패: {api_error(e2)} → CVAT 작업 화면 Upload annotations에서 "
                    f"{IMPORT_FORMAT} 형식으로 {backup} 를 올리세요")
        raise
    return before


# ---------------- export 파일 읽기 ----------------
def _root(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.replace("\\", "/").split("/")[-1] == "annotations.xml")
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def read_export(path):
    """export 파일에서 원본 영상 이름, 프레임 설정, 기존 라벨 수"""
    root = _root(path)
    t = root.find("meta/task")
    if t is None:
        t = root.find("meta/job")
    ff = (t.findtext("frame_filter") or "").strip() if t is not None else ""
    start = int(t.findtext("start_frame") or 0) if t is not None else 0
    stop = int(t.findtext("stop_frame") or 0) if t is not None else 0
    step = int(ff.split("=")[1]) if ff.startswith("step=") else 1
    n_boxes = sum(1 for tr in root.findall("track") for b in tr.findall("box") if b.get("outside") != "1")
    n_boxes += len(root.findall("box")) + len(root.findall("image/box"))
    return {"source": (t.findtext("source") or "") if t is not None else "",
            "start": start, "stop": stop, "step": step,
            "task_frames": len(range(start, stop + 1, step)),
            "labels": [l.findtext("name") for l in root.iter("label")],
            "existing_boxes": n_boxes, "is_images": root.find("image") is not None}


VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv")
STATUS_SUFFIX = re.compile(r"_(vf_r2df_ok|vf_r2_?리뷰df|vf_r2df|vf_r2_?리뷰|vf_r2|vf|uld)$")


def base_name(task_name):
    """TASK 이름에서 상태 표시를 뺀 기본 이름 (eggplant_G1_261019_1_1_uld → eggplant_G1_261019_1_1)"""
    f = parse_task_name(task_name)
    return f["base"] if f else STATUS_SUFFIX.sub("", (task_name or "").strip())


def find_video(videos_dir, source, task_name=None):
    """Drive videos/(하위 폴더 포함)에서 영상 찾기.
    순서: CVAT 원본 파일 이름 그대로 → 대소문자 무시 → 확장자만 다른 이름 → TASK 기본 이름"""
    videos_dir = Path(videos_dir)
    files = [f for f in videos_dir.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXT]
    if source:
        name = Path(source).name
        for f in files:
            if f.name == name:
                return f
        for f in files:
            if f.name.lower() == name.lower():
                return f
        for f in files:
            if f.stem.lower() == Path(name).stem.lower():
                return f
    if task_name:
        b = base_name(task_name).lower()
        for f in files:
            if f.stem.lower() == b:
                return f
    return None


def video_from_backups(backups_dir, task_name, videos_dir):
    """TASK 백업 zip(13번 셀, 영상 포함)에서 원본 영상을 꺼내 videos/_from_backup/<기본 이름>.<확장자>로 저장.
    backups/<기본 이름>/ 아래 최신 백업부터 찾음. 없으면 None"""
    b = base_name(task_name)
    zips = sorted(Path(backups_dir, b).rglob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    # 이름 규칙에 안 맞아 backups/_unmatched/task_<ID>_<이름>/ 에 들어간 백업도 찾음
    norm = lambda x: re.sub(r"[^0-9A-Za-z가-힣]", "", x).lower()
    um = Path(backups_dir, "_unmatched")
    if um.is_dir():
        for d in um.iterdir():
            m = re.match(r"task_\d+_(.+)$", d.name)
            if d.is_dir() and m and norm(m.group(1)) == norm(task_name):
                zips += sorted(d.rglob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for z in zips:
        try:
            with zipfile.ZipFile(z) as zf:
                vids = [n for n in zf.namelist() if Path(n).suffix.lower() in VIDEO_EXT]
                if not vids:
                    continue
                n = max(vids, key=lambda n: zf.getinfo(n).file_size)
                out = Path(videos_dir, "_from_backup", b + Path(n).suffix.lower())
                if not out.exists() or out.stat().st_size != zf.getinfo(n).file_size:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(n) as src, open(out, "wb") as dst:
                        while True:
                            chunk = src.read(8 * 2**20)
                            if not chunk:
                                break
                            dst.write(chunk)
                return out, z
        except zipfile.BadZipFile:
            continue
    return None, None


# ---------------- 라벨 요약 (업로드 전 확인 / CVAT 현재 라벨 확인) ----------------
def backup_content(zip_path):
    """TASK 백업 zip 안의 데이터 종류: ('video', 파일 이름) 또는 ('images', 장수) 또는 ('?', '')"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    except Exception:
        return "?", ""
    vids = [n for n in names if Path(n).suffix.lower() in VIDEO_EXT]
    if vids:
        return "video", Path(vids[0]).name
    imgs = [n for n in names if Path(n).suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")]
    return ("images", len(imgs)) if imgs else ("?", "")


def load_annotations(path):
    """CVAT XML(track XML, export zip/xml — video·images 형식 모두)을 TASK 프레임별 박스로 펼침.
    반환: {'kind', 'meta', 'frames', 'boxes': {frame: [(track_id, label, occluded, (x1,y1,x2,y2), keyframe)]},
           'tracks': {track_id: label}, 'shapes': 단독 박스 수}"""
    root = _root(path)
    t = root.find("meta/task")
    if t is None:
        t = root.find("meta/job")
    meta = {"name": "", "source": "", "start": 0, "stop": 0, "step": 1, "W": None, "H": None}
    if t is not None:
        ff = (t.findtext("frame_filter") or "").strip()
        meta.update(name=t.findtext("name") or "", source=t.findtext("source") or "",
                    start=int(t.findtext("start_frame") or 0), stop=int(t.findtext("stop_frame") or 0),
                    step=int(ff.split("=")[1]) if ff.startswith("step=") else 1)
        if t.findtext("original_size/width"):
            meta["W"], meta["H"] = float(t.findtext("original_size/width")), float(t.findtext("original_size/height"))
    boxes, tracks, n_shapes = {}, {}, 0
    xy = lambda b: tuple(float(b.get(k)) for k in ("xtl", "ytl", "xbr", "ybr"))
    if root.find("image") is not None:                        # CVAT for images 형식
        kind = "images"
        frames = []
        for img in root.findall("image"):
            m = re.search(r"frame_(\d+)", img.get("name", ""))
            f = int(m.group(1)) if m else int(img.get("id", len(frames)))
            frames.append(f)
            meta["W"] = meta["W"] or float(img.get("width", 0) or 0)
            meta["H"] = meta["H"] or float(img.get("height", 0) or 0)
            for b in img.findall("box"):
                if b.get("outside") == "1":
                    continue
                tid = b.get("track_id") or f"s{n_shapes}"
                if b.get("track_id"):
                    tracks[tid] = b.get("label")
                else:
                    n_shapes += 1
                boxes.setdefault(f, []).append((tid, b.get("label"), b.get("occluded") == "1", xy(b), True))
        return {"kind": kind, "meta": meta, "frames": sorted(set(frames)), "boxes": boxes, "tracks": tracks, "shapes": n_shapes}
    frames = list(range(meta["start"], meta["stop"] + 1, meta["step"])) if t is not None else []
    kind = "track" if root.find("track") is not None else "shapes"
    for tr in root.findall("track"):
        tid, label = tr.get("id"), tr.get("label")
        tracks[tid] = label
        kf = sorted(((int(b.get("frame")), b) for b in tr.findall("box")), key=lambda x: x[0])
        for i, (f0, b0) in enumerate(kf):
            if b0.get("outside") == "1":
                continue
            nxt = kf[i + 1] if i + 1 < len(kf) else None
            c0, oc = xy(b0), b0.get("occluded") == "1"
            for g in frames:
                if g < f0 or (nxt is not None and g >= nxt[0]):
                    continue
                if g == f0:
                    c = c0
                elif nxt is not None and nxt[1].get("outside") != "1":
                    c1, r = xy(nxt[1]), (g - f0) / (nxt[0] - f0)
                    c = tuple(a + (b - a) * r for a, b in zip(c0, c1))
                else:
                    c = c0
                boxes.setdefault(g, []).append((tid, label, oc, c, g == f0))
    for b in root.findall("box"):                             # 단독 박스 (track 아님)
        n_shapes += 1
        boxes.setdefault(int(b.get("frame")), []).append((f"s{n_shapes}", b.get("label"), b.get("occluded") == "1", xy(b), True))
    return {"kind": kind, "meta": meta, "frames": frames, "boxes": boxes, "tracks": tracks, "shapes": n_shapes}


def label_change_report(before, after):
    """교체 전·후 라벨 비교 (export zip 두 개 또는 load_annotations 결과).
    반환: (라벨별 rows, 프레임별 rows, 한 줄 요약)
      라벨별: 라벨, 기존/새 객체 수(track 또는 단독 박스), 기존/새 박스 수(프레임마다 보이는 박스 합), 기존/새 라벨 있는 프레임 수
      프레임별: 프레임, 라벨마다 '기존→새' 박스 수 (둘 중 하나라도 있는 프레임만)"""
    from collections import Counter, defaultdict
    A = load_annotations(before) if not isinstance(before, dict) else before
    B = load_annotations(after) if not isinstance(after, dict) else after

    def stats(ann):
        objs, boxes, frames, per_frame = defaultdict(set), Counter(), defaultdict(set), defaultdict(Counter)
        for f, lst in ann["boxes"].items():
            for tid, label, *_ in lst:
                objs[label].add(tid)
                boxes[label] += 1
                frames[label].add(f)
                per_frame[f][label] += 1
        return objs, boxes, frames, per_frame
    oa, ba, fa, pa = stats(A)
    ob, bb, fb, pb = stats(B)
    labels = sorted(set(ba) | set(bb))
    rows = [{"라벨": l, "기존 객체": len(oa[l]), "새 객체": len(ob[l]), "기존 박스": ba[l], "새 박스": bb[l],
             "기존 프레임": len(fa[l]), "새 프레임": len(fb[l])} for l in labels]
    rows.append({"라벨": "합계", "기존 객체": sum(r["기존 객체"] for r in rows), "새 객체": sum(r["새 객체"] for r in rows),
                 "기존 박스": sum(ba.values()), "새 박스": sum(bb.values()),
                 "기존 프레임": len(set(pa)), "새 프레임": len(set(pb))})
    frame_rows = []
    for f in sorted(set(pa) | set(pb)):
        r = {"프레임": f}
        for l in labels:
            x, y = pa[f][l], pb[f][l]
            r[l] = f"{x}→{y}" if (x or y) else ""
        r["합계"] = f"{sum(pa[f].values())}→{sum(pb[f].values())}"
        frame_rows.append(r)
    t = rows[-1]
    text = (f"기존 객체 {t['기존 객체']}개·박스 {t['기존 박스']}개({t['기존 프레임']}프레임) → "
            f"새 객체 {t['새 객체']}개·박스 {t['새 박스']}개({t['새 프레임']}프레임) · "
            + ", ".join(f"{r['라벨']} {r['기존 박스']}→{r['새 박스']}" for r in rows[:-1]))
    return rows, frame_rows, text


def save_change_report(rows, frame_rows, path):
    """label_change_report 결과를 CSV 하나로 (라벨별 표 + 빈 줄 + 프레임별 표)"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if rows:
            w.writerow(list(rows[0]))
            w.writerows([list(r.values()) for r in rows])
        w.writerow([])
        if frame_rows:
            w.writerow(list(frame_rows[0]))
            w.writerows([list(r.values()) for r in frame_rows])
    return path


def annotation_tables(ann):
    """라벨별 표와 프레임별 박스 수 요약"""
    from collections import defaultdict
    per = defaultdict(lambda: {"track": set(), "boxes": 0, "keyframes": 0, "occluded": 0, "w": [], "h": []})
    for f, lst in ann["boxes"].items():
        for tid, label, oc, (x1, y1, x2, y2), key in lst:
            d = per[label]
            if not str(tid).startswith("s"):
                d["track"].add(tid)
            d["boxes"] += 1
            d["keyframes"] += key
            d["occluded"] += oc
            d["w"].append(x2 - x1)
            d["h"].append(y2 - y1)
    label_rows = []
    for label, d in sorted(per.items()):
        n = d["boxes"]
        label_rows.append({"라벨": label, "track 수": len(d["track"]), "박스 수(보간 포함)": n,
                           "키프레임/직접 박스": d["keyframes"], "가림": d["occluded"],
                           "가림 비율": f"{d['occluded'] / n:.0%}" if n else "",
                           "평균 크기(px)": f"{sum(d['w']) / n:.0f}x{sum(d['h']) / n:.0f}" if n else ""})
    counts = [len(ann["boxes"].get(f, [])) for f in ann["frames"]]
    track_len = {}
    for f, lst in ann["boxes"].items():
        for tid, *_ in lst:
            if not str(tid).startswith("s"):
                track_len[tid] = track_len.get(tid, 0) + 1
    frame_summary = {"TASK 프레임": len(ann["frames"]), "박스가 있는 프레임": sum(1 for c in counts if c),
                     "프레임당 박스 (최소/평균/최대)": f"{min(counts, default=0)} / {sum(counts) / max(1, len(counts)):.1f} / {max(counts, default=0)}",
                     "track 수": len(ann["tracks"]), "단독 박스": ann["shapes"],
                     "track 길이(프레임, 최소/평균/최대)": (f"{min(track_len.values())} / {sum(track_len.values()) / len(track_len):.1f} / "
                                                     f"{max(track_len.values())}") if track_len else "-"}
    return label_rows, frame_summary, counts


def draw_annotations(ann, get_image, n=6, cols=3, title=""):
    """프레임 n장을 골라 박스를 그려 보여 줌. get_image(frame) → PIL.Image 또는 None"""
    import matplotlib.pyplot as plt
    from PIL import ImageDraw
    frames = ann["frames"]
    if not frames:
        print("프레임 정보가 없습니다.")
        return
    with_boxes = [f for f in frames if ann["boxes"].get(f)] or frames
    pick = [with_boxes[round(i * (len(with_boxes) - 1) / max(1, n - 1))] for i in range(min(n, len(with_boxes)))]
    palette = {"healthy_fruit": (255, 235, 0), "disease_fruit": (255, 40, 40), "healthy_bud": (0, 230, 255), "disease_bud": (255, 0, 255)}
    rows = (len(pick) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 7 * rows))
    axes = list(axes.flat) if hasattr(axes, "flat") else [axes]
    for ax, f in zip(axes, pick):
        img = get_image(f)
        ax.axis("off")
        if img is None:
            ax.set_title(f"frame {f}: no image")
            continue
        img = img.convert("RGB")
        sx = img.width / ann["meta"]["W"] if ann["meta"].get("W") else 1
        sy = img.height / ann["meta"]["H"] if ann["meta"].get("H") else 1
        d = ImageDraw.Draw(img)
        lw = max(2, img.width // 300)
        for tid, label, oc, (x1, y1, x2, y2), key in ann["boxes"].get(f, []):
            col = palette.get(label, (255, 255, 0))
            box = (x1 * sx, y1 * sy, x2 * sx, y2 * sy)
            d.rectangle((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1), outline=(0, 0, 0), width=lw + 2)   # 검은 테두리
            if oc:                                                # 가림: 안쪽에 흰 선을 한 줄 더
                d.rectangle(box, outline=col, width=max(1, lw // 2))
                d.rectangle((box[0] + lw, box[1] + lw, box[2] - lw, box[3] - lw), outline=(255, 255, 255), width=1)
            else:
                d.rectangle(box, outline=col, width=lw)
            tag = f"{tid}{'*' if key else ''}"
            d.rectangle((box[0], box[1] - 12, box[0] + 7 * len(tag) + 4, box[1]), fill=(0, 0, 0))
            d.text((box[0] + 2, box[1] - 12), tag, fill=col)
        ax.imshow(img)
        ax.set_title(f"frame {f}: {len(ann['boxes'].get(f, []))} boxes")
    for ax in axes[len(pick):]:
        ax.axis("off")
    if title:
        fig.suptitle(title)
    plt.tight_layout()
    plt.show()


def video_frame_getter(video_path, scale_to=None):
    """영상에서 프레임 번호로 이미지를 읽는 함수 (미리 보기용, 위치 이동 방식)"""
    import cv2
    from PIL import Image

    def get(f):
        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, img = cap.read()
        cap.release()
        return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)) if ok else None
    return get


def cvat_frame_getter(task, meta):
    """CVAT TASK에서 프레임 이미지를 받는 함수 (TASK 프레임 번호 → API 순번)"""
    from PIL import Image

    def get(f):
        try:
            idx = (int(f) - meta.get("start", 0)) // max(1, meta.get("step", 1))
            return Image.open(task.get_frame(idx, quality="compressed"))
        except Exception:
            return None
    return get


# ---------------- 작업 대장 ----------------
def _migrate_header(path, columns):
    """기존 CSV의 열이 columns와 다르면(새 열 추가 등) 새 머리글로 다시 씀. 기존 값은 그대로"""
    with open(path, encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        if rd.fieldnames == columns:
            return
        rows = list(rd)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") or "" for k in columns})
    tmp.replace(path)


def append_registry(path, **row):
    path = shard_path(path)                        # v4.30.1: 이 세션 파일에
    new = not path.exists()
    if not new:
        _migrate_header(path, REGISTRY_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    row.setdefault("run_time", now())
    if row.get("action") in ACTIONS:
        row["action"] = ACTIONS[row["action"]]
    for k in ("precision", "recall", "f1", "idf1"):
        v = row.get(k)
        if isinstance(v, float):
            row[k] = f"{v:.1%}"
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REGISTRY_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in REGISTRY_COLUMNS})
    _registry_to_activity(row)


def read_registry(path):
    return read_sharded(path)                      # v4.30.1: 예전 한 파일 + 세션 파일


def same_server(row, server):
    """대장 한 줄이 이 서버의 것인지. server 기록이 없는 예전 줄은 어느 서버에도 해당하는 것으로 봄"""
    return server is None or (row.get("server") or "") in ("", server)


def last_row(path, task_id, action=None, server=None):
    rows = [r for r in read_registry(path) if str(r["task_id"]) == str(task_id) and same_server(r, server)
            and (action is None or r["action"] == ACTIONS.get(action, action))]
    return rows[-1] if rows else None


# ---------------- TASK 이름 검색 (v4.6 공통 표현식 — 모든 셀이 같은 규칙) ----------------
# 이름 규칙: 프로젝트_온실_촬영일_조사구역_그루_상태[_표시]   예: eggplant_G6_261019_2_9_uld_AA_r1
#   상태 = uld · vf · vf_r2 · vf_r2df · vf_r2df_ok (한글 변형 vf_r2리뷰 등 포함, 목록에 없는 상태도 읽음)
#   표시 = 상태 뒤에 붙은 나머지 전부 (AA, AA_r1, test, test_AA …)
#   표준이 아닌 이름도 읽음: 날짜 8자리(20261013), 온실·프로젝트 생략, 상태 없음(영상 파일 이름)
NAME_RE = re.compile(r"^(?P<base>(?:(?P<project>[A-Za-z]+)_)?(?:(?P<gh>G\d+)_)?(?P<date>(?:20)?\d{6})"
                     r"_(?P<row>\d+)_(?P<plant>\d+))(?:_(?P<rest>[0-9A-Za-z가-힣_]+))?$")
KNOWN_STATES = {"uld", "vf", "vf_r1", "vf_r2", "vfdf", "vfdf_ok", "vf_r2df", "vf_r2df_ok"}
# v4.31.5 이름 규칙 (11/10 확정): _uld → (라벨 업로드) _uld_AA → (사람 검토) _vf → (최종 검토·확정) df · ok
#   vf_r1·vf_r2 = vf · vf_r2df = vfdf · vf_r2df_ok = vfdf_ok · AA_r1·AA_r2 = AA · _test = 기본 TASK 계열 (표시일 뿐)
_VF_RE = re.compile(r"^(vf)(?:_r\d+)?(?:_?리뷰)?(df)?(_ok)?$", re.I)


def state_group(state):
    """같은 것으로 보는 상태끼리 묶은 이름: vf_r1·vf_r2 → vf · vf_r2df → vfdf · vf_r2df_ok → vfdf_ok (그 밖은 그대로)"""
    m = _VF_RE.match(state or "")
    return ("vf" + (m.group(2) or "") + (m.group(3) or "")).lower() if m else (state or "")


def tag_group(tag):
    """AA_r1·AA_r2 → AA (그 밖은 그대로)"""
    return "AA" if re.fullmatch(r"AA(_r\d+)?", tag or "", re.I) else (tag or "")


def is_aa_name(name):
    """모델이 라벨을 올린 TASK 이름인가 (…_AA · …_AA_r1)"""
    f = parse_task_name(name)
    return tag_group(f["tag"]) == "AA" if f else bool(re.search(r"_AA(_r\d+)?$", name or "", re.I))


def aa_name_after_upload(name):
    """라벨을 CVAT에 올린 뒤의 TASK 이름 (v4.31.5): …_uld → …_uld_AA · 그 밖(…_AA, …_vf 등)은 그대로"""
    n = (name or "").strip()
    return n + "_AA" if n.lower().endswith("_uld") else n

STATE_ALIAS = {"vf_r2리뷰": "vf_r2", "vf_r2_리뷰": "vf_r2", "vf_r2리뷰df": "vf_r2df", "vf_r2_리뷰df": "vf_r2df"}
_STATE_WORDS = sorted(set(KNOWN_STATES) | set(STATE_ALIAS), key=len, reverse=True)   # 긴 것부터 (vf_r2df_ok → … → vf)
FIELD_KEYS = ("project", "gh", "date", "row", "plant", "state", "tag")
NAME_TAGS = ("AA", "test")   # 목록에 없는 상태 뒤에서 표시를 알아보는 첫 단어 (예: vfdf_ok_AA_r1 → 상태 vfdf_ok, 표시 AA_r1)
QUERY_KEYS = {"project": "project", "프로젝트": "project",
              "gh": "gh", "house": "gh", "farm": "gh", "농장": "gh", "온실": "gh",
              "date": "date", "촬영일": "date", "일자": "date",
              "row": "row", "line": "row", "조사구역": "row", "구역": "row", "라인": "row",
              "plant": "plant", "그루": "plant",
              "state": "state", "상태": "state",
              "tag": "tag", "표시": "tag"}


def _norm_date(d):
    """20261013 → 261013 (8자리 날짜는 YYMMDD로)"""
    return d[2:] if len(d) == 8 and d.startswith("20") else d


def _split_state(rest):
    """'uld_AA_r1' → ('uld', 'AA_r1') · 'vf_r2리뷰' → ('vf_r2', '') · 'vfdf_ok_AA' → ('vfdf_ok', 'AA')"""
    if not rest:
        return "", ""
    low = rest.lower()
    m = re.match(r"^(vf(?:_r\d+)?(?:df(?:_ok)?)?)(?:_(.*))?$", rest, re.I)
    if re.match(r"^test(_|$)", rest, re.I):
        return "", rest                            # …_test = 상태 없는 기본 TASK 계열 + 표시 test
    if m and (m.group(2) is None or not re.match(r"^(r\d+|df|ok|리뷰)", m.group(2), re.I)):
        return m.group(1), m.group(2) or ""        # vf · vf_r1 · vf_r3 · vfdf · vf_r2df_ok … (v4.31.5)
    for s in _STATE_WORDS:                         # 알려진 상태로 시작하면 그 뒤는 표시
        if low == s.lower() or low.startswith(s.lower() + "_"):
            return STATE_ALIAS.get(s, s), rest[len(s) + 1:]
    m = re.match(r"^(.*?)_((?:%s)(?:_.*)?)$" % "|".join(NAME_TAGS), rest, re.I)
    if m:                                          # 목록에 없는 상태 + 표시
        return m.group(1), m.group(2)
    return rest, ""


def parse_task_name(name):
    """{'project','gh','date'(YYMMDD),'row','plant','state','tag','base','variant'} 또는 None (규칙 밖 이름).
    variant = 표준과 다른 점 목록 (없으면 표준 이름)"""
    m = NAME_RE.match((name or "").strip())
    if not m:
        return None
    f = {k: (v or "") for k, v in m.groupdict().items()}
    variant = []
    if len(f["date"]) == 8:
        variant.append("날짜 8자리")
    f["date"] = _norm_date(f["date"])
    if not f["project"]:
        variant.append("프로젝트 없음")
    if not f["gh"]:
        variant.append("온실 없음")
    f["state"], f["tag"] = _split_state(f.pop("rest"))
    if not f["state"]:
        variant.append("상태 없음")
    elif f["state"] not in KNOWN_STATES and state_group(f["state"]) not in KNOWN_STATES:
        variant.append(f"상태 {f['state']}")
    f["row"], f["plant"] = str(int(f["row"])), str(int(f["plant"]))
    f["variant"] = variant
    f["state_group"], f["tag_group"] = state_group(f["state"]), tag_group(f["tag"])
    return f


def add_name_tag(name, tag="AA"):
    """TASK 이름 끝에 _<tag>를 붙임 (이미 있으면 그대로). 예: eggplant_G6_261019_1_5_uld → …_uld_AA"""
    name = (name or "").strip()
    return name if name.lower().endswith("_" + tag.lower()) or not tag else f"{name}_{tag}"


def rule_text(f):
    if f is None:
        return "규칙 밖(부분 문자열로 검색)"
    t = f" · 표시 {f['tag']}" if f.get("tag") else ""
    return ("맞음" if not f["variant"] else "변형: " + ", ".join(f["variant"])) + t


def _field_like(word):
    """칸 값으로 알아보는 단어인가: 상태 이름, G숫자, 숫자(날짜·라인·그루)"""
    w = word.lower()
    if _VF_RE.match(w) or re.fullmatch(r"aa(_r\d+)?", w):
        return True
    return (w in {s.lower() for s in _STATE_WORDS} or bool(re.fullmatch(r"g\d+", w)) or w.isdigit())


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _value_match(key, field_value, pattern):
    """칸 하나와 값 비교: 범위 a..b, 와일드카드, 정확히 같음"""
    fv = field_value or ""
    if ".." in pattern:                            # 범위 (라인·그루·날짜 등 숫자 칸)
        a, b = (x.strip() for x in pattern.split("..", 1))
        if key == "date":
            a, b = _norm_date(a), _norm_date(b)
        x, lo, hi = _num(fv), _num(a), _num(b)
        return x is not None and (lo is None or x >= lo) and (hi is None or x <= hi)
    if key == "state":
        pattern = STATE_ALIAS.get(pattern, pattern)
    if key == "date":
        pattern = _norm_date(pattern)
    if key in ("row", "plant") and pattern.isdigit():
        pattern = str(int(pattern))
    if key == "state" and fnmatch.fnmatchcase(state_group(fv).lower(), pattern.lower()):
        return True                                # state=vf 는 vf_r1·vf_r2도 (v4.31.5)
    if key == "tag" and fnmatch.fnmatchcase(tag_group(fv).lower(), pattern.lower()):
        return True                                # tag=AA 는 AA_r1도
    return fnmatch.fnmatchcase(fv.lower(), pattern.lower())


REVIEWED_RULE = "vf"        # 검색어 '검토'가 쓰는 검토 완료 규칙 — 노트북 0번 셀 REVIEWED_RULE이 넣어 줌 (v4.24)
REVIEW_WORDS = ("검토", "reviewed")


def _alt_match(alt, name, f):
    a = alt.strip()
    if not a:
        return False
    if a.lower() in REVIEW_WORDS:                 # '검토' = 검토 완료 TASK (0번 셀 REVIEWED_RULE과 같은 판단) — v4.24
        return is_reviewed(name, REVIEWED_RULE)
    if "=" in a:                                   # 칸 지정: gh=G6 date=261019 row=2 plant=6..10 state=vf* tag=AA*
        k, v = (x.strip() for x in a.split("=", 1))
        k = QUERY_KEYS.get(k.lower(), k.lower())
        if not f or k not in FIELD_KEYS:
            return False
        return _value_match(k, f[k], v)
    if any(ch in a for ch in "*?["):               # 와일드카드: 이름 전체 또는 칸 하나와 비교
        p = a.lower()
        return fnmatch.fnmatchcase((name or "").lower(), p) or bool(
            f and any(fnmatch.fnmatchcase(f[k].lower(), p) for k in FIELD_KEYS if f[k]))
    if not f:                                      # 규칙 밖 이름: 부분 문자열
        return a.lower() in (name or "").lower()
    v = _norm_date(STATE_ALIAS.get(a, a)).lower()
    if v in [f[k].lower() for k in FIELD_KEYS + ("state_group", "tag_group") if f.get(k)]:
        return True                                # 칸 하나와 정확히 같음
    if a.isdigit() and str(int(a)) in (f["row"], f["plant"]):
        return True                                # 숫자 하나 = 라인 또는 그루
    if _field_like(a):
        return False                               # 상태·온실·숫자는 칸과 정확히만 (vf_r2 ≠ vf_r2df)
    return a.lower() in (name or "").lower()       # 그 밖의 단어(AA_r1 등)는 이름에 들어 있으면


def _match_group(name, f, group):
    detail = []
    for t in group.split():
        neg = t[0] in "-!" and len(t) > 1
        body = t[1:] if neg else t
        hit = any(_alt_match(alt, name, f) for alt in body.split("|"))
        detail.append((t, hit != neg))
    return all(ok for _, ok in detail), detail


def match_name(name, query):
    """TASK 이름 검색 (v4.6 공통 규칙 — 4·5·9·13·14·16·17·21번 셀 모두 같음).
    - 공백 = 그리고(AND)                     '261019 vf_r2'
    - |   = 또는(OR, 단어 안에서)            'vf|vf_r2'
    - , ; = 묶음 또는                         'G6 uld, G2 plant=6..10 uld'
    - 앞에 - 또는 ! = 빼기(NOT)               'G6 uld -tag=AA*'
    - 칸=값  gh date row plant state tag project ('tag=' = 표시 없음)
    - 칸=a..b 범위                             'plant=6..10', 'date=261015..261019'
    - * ? 와일드카드 (이름 전체 또는 칸)        '*AA_r1*', 'date=2610*'
    - 보통 단어: 상태·G숫자·숫자는 칸과 정확히 (숫자 하나 = 라인 또는 그루),
                그 밖의 단어는 이름에 들어 있으면 맞음 ('AA_r1')
    - 이름 규칙 밖의 이름은 단어가 이름에 들어 있으면 맞음
    - 검토 (또는 reviewed) = 검토 완료 TASK — 0번 셀 REVIEWED_RULE과 똑같이 (상태에 'vf'가 들어 있음). '-검토' = 미검토 (v4.24)
    반환: (맞음 여부, [(단어, 맞음 여부), ...]) — 묶음 사이에는 ('/', None)"""
    groups = [g for g in re.split(r"[,;]", query or "") if g.split()]
    if not groups:
        return True, []
    f = parse_task_name(name)
    ok_any, detail = False, []
    for k, g in enumerate(groups):
        ok, det = _match_group(name, f, g)
        ok_any = ok_any or ok
        detail += ([("/", None)] if k else []) + det
    return ok_any, detail


def format_detail(detail):
    """[(단어, 맞음)] → '261015✓ vf✗ / 261019✓ vf_r2✓'"""
    return " ".join(t if o is None else f"{t}{'✓' if o else '✗'}" for t, o in detail)


def explain_query(names, query):
    """검색어 확인용 표: 이름마다 맞음 여부와 단어별 결과"""
    rows = []
    for n in names:
        ok, det = match_name(n, query)
        f = parse_task_name(n)
        rows.append({"TASK 이름": n, "맞음": "예" if ok else "",
                     "단어별": format_detail(det), "이름 규칙": rule_text(f)})
    return rows


def explain_tasks(tasks, query):
    """list_tasks() 결과에 검색 결과 열을 붙임 (TASK마다 한 줄 — 같은 이름의 TASK가 있어도 섞이지 않음)"""
    same = Counter(t["name"] for t in tasks)
    out = []
    for t in tasks:
        ok, det = match_name(t["name"], query)
        out.append({**t, "맞음": "예" if ok else "", "단어별": format_detail(det),
                    "이름 규칙": rule_text(parse_task_name(t["name"])),
                    "같은 이름": same[t["name"]] if same[t["name"]] > 1 else ""})
    return out


SELECT_COLUMNS = ["task_id", "name", "단어별", "이름 규칙", "frames", "status", "updated", "같은 이름"]


def select_tasks(tasks, query, ids=None, show=print, display=None, show_all=False, label="대상"):
    """모든 셀이 같은 방식으로 대상 TASK를 고르고 같은 표로 보여 줌.
    tasks = list_tasks() 결과 (또는 {'task_id','name',…} 목록), ids가 있으면 query 대신 ID로.
    반환: 고른 행 목록 (이름순). show_all=True면 맞지 않는 것도 표에 (4번 셀 검색어 확인용)"""
    if ids:
        want = {str(i) for i in ids}
        rows = [{**t, "맞음": "예", "단어별": "(ID 지정)", "이름 규칙": rule_text(parse_task_name(t["name"])), "같은 이름": ""}
                for t in tasks if str(t.get("task_id")) in want]
        missing = sorted(want - {str(r.get("task_id")) for r in rows})
        show(f"{label}: TASK ID {len(rows)}개" + (f" · 목록에 없는 ID {missing} (지운 TASK이거나 지금 조직·프로젝트 범위 밖 — 0번 셀 CVAT_ORG·CVAT_PROJECT)" if missing else ""))
    else:
        rows = explain_tasks(tasks, query or "")
        hits = [r for r in rows if r["맞음"] == "예"]
        show(f"{label}: 검색어 '{query}' → {len(hits)}/{len(rows)}개 (✓/✗ = 단어별, - = 빼기)" if query
             else f"{label}: 검색어 없음 → 전체 {len(rows)}개")
        dup = sorted({r["name"] for r in hits if r["같은 이름"] != ""})
        if dup:
            show(f"⚠️ 같은 이름의 TASK가 여러 개: {', '.join(dup)} — TASK ID로 구분하세요")
        rows = rows if show_all else hits
    rows = sorted(rows, key=lambda r: (r.get("맞음") != "예", r["name"]))
    if display is not None and rows:
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            cols = (["맞음"] if show_all else []) + [c for c in SELECT_COLUMNS if c in df.columns]
            display(df[cols])
        except Exception:
            for r in rows:
                show(f"  {r.get('task_id', ''):<10} {r['name']:<45} {r.get('단어별', '')}")
    return [r for r in rows if r.get("맞음") == "예"]



# ---------------- 학습 잠금 (두 사람이 같은 학습 이름으로 동시에 쓰지 않게) ----------------
RUN_LOCK_FILE = "RUNNING.json"


def _now_utc():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)


def _kst_str(iso):
    import datetime as _dt
    t = _to_utc(iso)
    return t.astimezone(_dt.timezone(_dt.timedelta(hours=9))).strftime("%m-%d %H:%M") + " KST" if t else "?"


def read_run_lock(run_dir):
    """runs/<이름>/RUNNING.json → dict (+ 'age_min' = 마지막 갱신 뒤 지난 분) 또는 None"""
    import json as _json
    p = Path(run_dir) / RUN_LOCK_FILE
    if not p.exists():
        return None
    try:
        d = _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    hb = _to_utc(d.get("heartbeat"))
    d["age_min"] = (_now_utc() - hb).total_seconds() / 60 if hb else 1e9
    return d


def _write_lock(run_dir, d):
    import json as _json
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    tmp = Path(run_dir) / (RUN_LOCK_FILE + ".tmp")
    tmp.write_text(_json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(Path(run_dir) / RUN_LOCK_FILE)


def acquire_run_lock(run_dir, session, who="", stage="", stale_min=45, takeover=False):
    """학습 잠금 잡기. 다른 세션이 최근(stale_min분 안)에 갱신한 잠금이 있으면 (False, 안내문).
    같은 세션이거나 오래 갱신이 없으면(끊긴 학습) 잡음."""
    cur = read_run_lock(run_dir)
    if cur and cur.get("session") != session and cur["age_min"] < stale_min and not takeover:
        return False, (f"⛔ 다른 사람이 이 학습 이름으로 작업 중입니다: {cur.get('who') or '이름 없음'} "
                       f"(세션 {cur.get('session')}, 단계 {cur.get('stage')}, 에폭 {cur.get('epoch', '')}, "
                       f"시작 {_kst_str(cur.get('started'))}, 마지막 갱신 {cur['age_min']:.0f}분 전)\n"
                       f"   → 다른 TRAIN_NAME을 쓰거나, 그 작업이 끝난 뒤 실행하세요. "
                       f"(그 세션이 확실히 끊겼다면 {stale_min}분 뒤 자동으로 넘겨받음 · 지금 넘겨받기: TAKEOVER_LOCK = True)")
    now = _now_utc().isoformat()
    _write_lock(run_dir, {"session": session, "who": who, "stage": stage, "epoch": "",
                          "started": (cur or {}).get("started") if cur and cur.get("session") == session else now,
                          "heartbeat": now,
                          "took_over_from": (cur or {}).get("session", "") if cur and cur.get("session") != session else ""})
    return True, ("이전 잠금(끊긴 세션)을 넘겨받음" if cur and cur.get("session") != session else "")


def touch_run_lock(run_dir, session, **fields):
    """잠금 갱신 (에폭마다). 다른 세션이 잠금을 넘겨받았으면 False → 학습을 멈춰야 함"""
    cur = read_run_lock(run_dir)
    if cur and cur.get("session") not in (None, session):
        return False
    d = {k: v for k, v in (cur or {}).items() if k != "age_min"}
    d.update(session=session, heartbeat=_now_utc().isoformat(), **fields)
    _write_lock(run_dir, d)
    return True


def release_run_lock(run_dir, session):
    cur = read_run_lock(run_dir)
    if cur and cur.get("session") == session:
        try:
            (Path(run_dir) / RUN_LOCK_FILE).unlink()
        except FileNotFoundError:
            pass


# ---------------- export 현황 (이미 받은 export 재사용) ----------------
def iso_z(v):
    """CVAT 시각 → '2026-11-07T06:00:12Z' (UTC, 시간대 표시 붙임 — v4.31.4). 못 읽으면 ''"""
    d = _to_utc(v)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


def _to_utc(v):
    """'2026-10-25 08:14:11.12+00:00' / datetime / 파일 시각(float) → aware datetime(UTC) 또는 None"""
    import datetime as _dt
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return _dt.datetime.fromtimestamp(v, _dt.timezone.utc)
    if isinstance(v, _dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=_dt.timezone.utc)
    s = str(v).strip().replace("T", " ").replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            d = _dt.datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def read_export_info(zip_path):
    """export zip의 머리말만 읽어 TASK 정보: id, name, updated(그 export가 반영한 TASK 수정 시각), 형식, 이미지 포함 여부"""
    import xml.etree.ElementTree as _ET
    zip_path = Path(zip_path)
    info = {"zip": str(zip_path), "folder": zip_path.parent.name, "file": zip_path.name, "task_id": "", "name": "",
            "updated": "", "kind": "", "images": False, "mtime": zip_path.stat().st_mtime, "error": ""}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            info["images"] = any(n.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")) for n in names)
            xn = next((n for n in names if n.replace("\\", "/").split("/")[-1] == "annotations.xml"), None)
            if not xn:
                info["error"] = "annotations.xml 없음"
                return info
            with zf.open(xn) as fh:
                for ev, el in _ET.iterparse(fh, events=("end",)):
                    tag = el.tag
                    if tag in ("image", "track"):
                        info["kind"] = "images" if tag == "image" else "video"
                        break
                    if tag in ("task", "job") and not info["task_id"]:
                        info["task_id"] = el.findtext("id") or ""
                        info["name"] = el.findtext("name") or ""
                        info["updated"] = el.findtext("updated") or ""
                    if tag == "annotations":
                        break
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {str(e)[:80]}"
    if not info["kind"]:                           # 박스가 없는 export: 폴더 이름으로 짐작
        info["kind"] = "images" if "images" in info["folder"] else ("video" if "video" in info["folder"] else "")
    return info


def export_file_stem(task_name):
    """14번 셀이 export zip 파일 이름으로 쓰는 TASK 이름 (특수문자 → _)"""
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", task_name or "")


INDEX_COLUMNS_EXPORT = ["zip", "size", "mtime", "task_id", "name", "updated", "kind", "images", "error"]


def scan_exports(exports_dir, names=None, log=print, every=25):
    """exports/*/*.zip의 머리말 목록. Drive에서 zip을 여는 것은 느리므로
    - names(TASK 이름 목록)를 주면 파일 이름이 그 TASK인 zip만 읽음 (파일 이름 = TASK 이름[__ID].zip)
    - 한 번 읽은 zip은 exports/_export_index.csv에 적어 두고, 크기·수정 시각이 같으면 다시 열지 않음"""
    exports_dir = Path(exports_dir)
    files = sorted(exports_dir.glob("*/*.zip"))
    if names is not None:
        want = {export_file_stem(n) for n in names}
        files = [z for z in files if z.stem.split("__")[0] in want]
    idx_path = exports_dir / "_export_index.csv"
    cache = {}
    if idx_path.exists():
        try:
            with open(idx_path, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    cache[r["zip"]] = r
        except Exception:
            cache = {}
    rows, new, t0 = [], 0, time.time()
    for k, z in enumerate(files, 1):
        rel = str(z.relative_to(exports_dir))
        st = z.stat()
        c = cache.get(rel)
        if c and c.get("size") == str(st.st_size) and c.get("mtime") == f"{st.st_mtime:.0f}":
            r = {**c, "zip": str(z), "folder": z.parent.name, "file": z.name, "images": c.get("images") == "True",
                 "mtime": st.st_mtime}
        else:
            r = read_export_info(z)
            new += 1
            cache[rel] = {**{k2: r.get(k2, "") for k2 in INDEX_COLUMNS_EXPORT}, "zip": rel, "size": str(st.st_size),
                          "mtime": f"{st.st_mtime:.0f}", "images": str(bool(r["images"]))}
        rows.append(r)
        if log and every and k % every == 0:
            log(f"  export 파일 {k}/{len(files)} 확인 (새로 연 것 {new}개, {time.time() - t0:.0f}초)")
    if new:
        try:
            with open(idx_path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=INDEX_COLUMNS_EXPORT, extrasaction="ignore")
                w.writeheader()
                for r in cache.values():
                    w.writerow(r)
        except Exception:
            pass
    if log:
        log(f"  export 파일 {len(files)}개 확인 (새로 연 것 {new}개, {time.time() - t0:.0f}초)")
    return rows


def best_export(scan, task_id, task_updated=None, kind=None, need_images=False):
    """그 TASK의 export 중 조건에 맞는 가장 최근 것과 상태.
    상태: '최신'(export가 지금 CVAT 라벨과 같음) / '수정됨'(export 뒤에 CVAT에서 바뀜) / '없음'
    같은지 판단: export 머리말의 TASK 수정 시각(updated) ≥ CVAT 지금 수정 시각. 머리말에 없으면 파일 받은 시각으로"""
    cands = [r for r in scan if str(r["task_id"]) == str(task_id) and not r["error"]
             and (not kind or r["kind"] == kind) and (not need_images or r["images"])]
    if not cands:
        return None, "없음"
    def stamp_of(r):
        return _to_utc(r["updated"]) or _to_utc(r["mtime"])
    cands.sort(key=lambda r: (stamp_of(r) or _to_utc(0), r["mtime"]))
    best = cands[-1]
    cu, eu = _to_utc(task_updated), stamp_of(best)
    if cu is None or eu is None:
        return best, "최신"
    return best, ("최신" if eu.replace(microsecond=0) >= cu.replace(microsecond=0) else "수정됨")


# ---------------- 자동 track ↔ CVAT 반영 결과 비교 ----------------
def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def compare_annotations(local, cvat, same_iou=0.95, near_iou=0.5):
    """load_annotations() 결과 두 개를 프레임·라벨별로 맞춰 봄.
    같음 = IoU ≥ same_iou (가림 표시까지 같으면 '같음', 다르면 '가림 다름'),
    수정 = near_iou ≤ IoU < same_iou (위치·크기를 고친 박스), 없어짐 = 로컬에만, 추가 = CVAT에만,
    라벨 바뀜 = 다른 라벨끼리 IoU ≥ same_iou.
    반환: (라벨별 표 rows, 전체 합계 dict, 프레임별 차이 rows)"""
    from collections import defaultdict
    per = defaultdict(lambda: defaultdict(int))
    frame_rows = []
    for f in sorted(set(local["boxes"]) | set(cvat["boxes"])):
        A = list(local["boxes"].get(f, []))
        B = list(cvat["boxes"].get(f, []))
        used = set()
        diff = defaultdict(int)
        rest = []
        for a in A:                                          # 같은 라벨끼리 가장 많이 겹치는 박스
            best, bj = 0.0, None
            for j, b in enumerate(B):
                if j in used or b[1] != a[1]:
                    continue
                v = _iou(a[3], b[3])
                if v > best:
                    best, bj = v, j
            if bj is not None and best >= near_iou:
                used.add(bj)
                k = ("같음" if a[2] == B[bj][2] else "가림 다름") if best >= same_iou else "수정"
            else:
                rest.append(a)
                continue
            per[a[1]][k] += 1
            diff[k] += 1
        for a in rest:                                       # 라벨만 바뀐 박스
            hit = None
            for j, b in enumerate(B):
                if j not in used and _iou(a[3], b[3]) >= same_iou:
                    hit = j
                    break
            k = "라벨 바뀜" if hit is not None else "없어짐"
            if hit is not None:
                used.add(hit)
            per[a[1]][k] += 1
            diff[k] += 1
        for j, b in enumerate(B):
            if j not in used:
                per[b[1]]["추가"] += 1
                diff["추가"] += 1
        if any(diff[k] for k in diff if k != "같음"):
            frame_rows.append({"프레임": f, "로컬": len(A), "CVAT": len(B), **{k: v for k, v in diff.items() if v}})
    cols = ["같음", "가림 다름", "수정", "라벨 바뀜", "없어짐", "추가"]
    loc_n = defaultdict(int)
    cv_n = defaultdict(int)
    for lst in local["boxes"].values():
        for x in lst:
            loc_n[x[1]] += 1
    for lst in cvat["boxes"].values():
        for x in lst:
            cv_n[x[1]] += 1
    rows = []
    for label in sorted(set(per) | set(loc_n) | set(cv_n)):
        rows.append({"라벨": label, "로컬 박스": loc_n[label], "CVAT 박스": cv_n[label],
                     **{c: per[label][c] for c in cols}})
    total = {c: sum(r[c] for r in rows) for c in ["로컬 박스", "CVAT 박스"] + cols}
    total["로컬 track"] = len(local["tracks"])
    total["CVAT track"] = len(cvat["tracks"])
    total["CVAT 단독 박스"] = cvat["shapes"]
    n = max(1, total["로컬 박스"])
    total["일치율"] = f"{total['같음'] / n:.1%}"
    return rows, total, frame_rows


# ---------------- 프레임별 자동 라벨링 (영상 TASK 포함) ----------------
def task_frame_map(meta):
    """TASK 프레임 순번 k(0,1,2…) → 원본 영상의 CVAT 프레임 번호 (start + k*step)"""
    start = int(getattr(meta, "start_frame", 0) or 0)
    ff = str(getattr(meta, "frame_filter", "") or "")
    step = int(ff.split("=")[1]) if ff.startswith("step=") else 1
    return start, step


# ---- 세로로 찍은 영상 (v4.24.5) ----
# 휴대폰·카메라를 세워 찍은 영상은 화면이 가로로 저장되고 '돌려서 보여 줘라'는 회전 정보가 붙는다.
# CVAT(FFmpeg)는 이 값대로 돌려 보여 주고 라벨도 돌린 화면 기준이다. PyAV는 돌리지 않으므로 여기서 같게 돌린다.
# (OpenCV는 스스로 돌려 줌.) 값 = 시계 반대 방향 도수: 90 → 반시계 90°, -90(=270) → 시계 90°, 180.
def pyav_rotation(frame, stream=None):
    """PyAV 프레임의 화면 회전(0·90·180·270). frame.rotation(PyAV 14+) → 없으면 스트림 'rotate' 태그(예전 FFmpeg, 시계 방향)"""
    r = getattr(frame, "rotation", None)
    try:
        if r is not None:
            return int(round(float(r))) % 360
        tag = (getattr(stream, "metadata", None) or {}).get("rotate") if stream is not None else None
        return (-int(round(float(tag)))) % 360 if tag not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def upright_array(arr, rotation):
    """numpy 이미지(H×W×C)를 회전 정보대로 돌림 — FFmpeg 자동 회전(CVAT 화면)과 같은 결과"""
    k = (int(rotation) // 90) % 4
    if not k:
        return arr
    import numpy as _np
    return _np.ascontiguousarray(_np.rot90(arr, k))


def upright_image(img, rotation):
    """PIL 이미지를 회전 정보대로 돌림 (upright_array와 같은 방향)"""
    k = (int(rotation) // 90) % 4
    if not k:
        return img
    from PIL import Image as _I
    return img.transpose({1: _I.Transpose.ROTATE_90, 2: _I.Transpose.ROTATE_180, 3: _I.Transpose.ROTATE_270}[k])


def video_frames(video_path, wanted, decoder="pyav"):
    """영상을 처음부터 순서대로 읽으며 wanted(영상 프레임 번호들)만 꺼냄 → (번호, PIL 이미지)
    pyav = CVAT와 같은 FFmpeg 방식으로 프레임을 셈 (권장), opencv = 대신 쓸 수 있음"""
    import PIL.Image
    want = sorted({int(v) for v in wanted if v >= 0})
    if not want:
        return
    j = 0
    if decoder == "pyav":
        import av
        with av.open(str(video_path)) as c:
            st = c.streams.video[0]
            st.thread_type = "AUTO"
            for i, fr in enumerate(c.decode(st)):
                if i == want[j]:
                    yield i, upright_image(fr.to_image(), pyav_rotation(fr, st))   # v4.24.5: 세로 영상은 CVAT처럼 돌림
                    j += 1
                    if j == len(want):
                        return
    else:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        i = 0
        try:
            while j < len(want):
                if i < want[j]:
                    if not cap.grab():
                        return
                else:
                    ok, img = cap.read()
                    if not ok:
                        return
                    yield i, PIL.Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                    j += 1
                i += 1
        finally:
            cap.release()


def check_video_alignment(task, video_path, offset=0, decoder="pyav", probes=(0, 5), search=2):
    """영상 프레임과 CVAT 프레임이 같은 장면인지 확인 (작게 줄인 흑백 이미지 차이).
    probes = 확인할 TASK 프레임 순번, search = 앞뒤로 몇 프레임까지 맞춰 볼지.
    반환: {'best_shift': d (맞는 보정값 = offset - d, 0이면 지금 offset이 맞음), 'diffs': {d: 평균 차이}, 'ok': bool}"""
    import numpy as np
    import PIL.Image
    meta = task.get_meta()
    start, step = task_frame_map(meta)
    ks = [k for k in probes if k < task.size]
    small = lambda im: np.asarray(im.convert("L").resize((96, 96)), dtype=np.float32)
    ref = {k: small(PIL.Image.open(task.get_frame(k, quality="compressed"))) for k in ks}
    want = {}
    for k in ks:
        for d in range(-search, search + 1):
            want.setdefault(start + k * step - offset + d, []).append((k, d))
    got = {}
    for vi, im in video_frames(video_path, want, decoder):
        got[vi] = small(im)
    diffs = {}
    for vi, kds in want.items():
        if vi in got:
            for k, d in kds:
                diffs.setdefault(d, []).append(float(np.abs(got[vi] - ref[k]).mean()))
    diffs = {d: round(sum(v) / len(v), 2) for d, v in diffs.items() if len(v) == len(ks)}
    if not diffs:
        return {"best_shift": None, "diffs": {}, "ok": False}
    best = min(diffs, key=diffs.get)
    # 0이 최선이거나 최선과 거의 같으면 맞는 것으로 봄 (움직임이 적은 장면은 앞뒤 프레임 차이가 작음)
    ok = best == 0 or (0 in diffs and diffs[0] <= diffs[best] * 1.05 + 0.5)
    return {"best_shift": 0 if ok else best, "diffs": diffs, "ok": ok}


def auto_annotate_frames(task, function_file, model, imgsz=1920, device="0", conf=0.3, tile=False,
                         quality="original", frames=None, batch=50, log=print, prefetch=4, replace=False, backup=None,
                         video=None, video_offset=0, decoder="pyav", collect_only=False):
    """cvat-cli task auto-annotate는 영상으로 만든 TASK에서
    'Chunk-based media access is only supported for … image sets'로 멈춘다.
    이 함수는 TASK 프레임을 하나씩 받아(task.get_frame) 같은 함수 파일(cvat_yolo_function.py)로 탐지하고
    박스를 기존 라벨에 덧붙여(create) 올린다. frames=None이면 전체(삭제된 프레임 제외).
    replace=True: 전체 프레임을 먼저 모두 탐지한 뒤 기존 라벨을 지우고 올림 (교체, 실패하면 backup으로 되돌림).
    video=원본 영상 경로: 프레임을 CVAT에서 받지 않고 원본 영상에서 직접 읽음 (원본 화질, 서버 압축 없음).
      TASK 프레임 k ↔ 영상 프레임 start + k*step - video_offset (video_offset = 20번 셀이 알려 주는 보정값)
    collect_only=True (v4.33 2b-3): CVAT에 아무것도 쓰지 않고 탐지 결과만 'shapes'(라벨 이름 포함 dict 목록)로 돌려줌 —
      실행기의 준비 단계(로컬에서 끝까지)에서 쓰고, 올리기는 승인 뒤 확정 단계가 따로 함.
    반환: {'frames': 처리 프레임 수, 'boxes': 올린 박스 수, 'per_label': {라벨: 수}, 'skipped_labels': {...},
           'replaced': 지운 기존 라벨 수(교체일 때)}"""
    if collect_only and replace:
        raise ValueError("collect_only와 replace는 함께 쓰지 않음 (교체는 확정 단계가 함)")
    import importlib.util
    import time
    from types import SimpleNamespace
    from cvat_sdk.api_client import models
    from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
    import PIL.Image

    spec = importlib.util.spec_from_file_location("cvat_yolo_function_aa", str(function_file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = mod.create(model=str(model), imgsz=int(imgsz), device=str(device), tile=bool(tile))
    spec_names = [l.name for l in fn.spec.labels]
    task_ids = {l.name: l.id for l in task.get_labels()}
    meta = task.get_meta()
    deleted = set(getattr(meta, "deleted_frames", None) or [])
    if replace and frames is not None:
        raise ValueError("교체(replace)는 TASK 전체 프레임에서만 됩니다 (일부 프레임만 하면 나머지 프레임 라벨이 사라짐) → AA_FRAMES = None")
    todo = [k for k in (frames if frames is not None else range(task.size)) if k not in deleted]
    collected = []
    ctx = SimpleNamespace(conf_threshold=conf, conv_mask_to_poly=False)
    pending, per_label, skipped, total, t0 = [], {}, {}, 0, time.time()

    def flush():
        nonlocal pending
        if pending:
            if replace or collect_only:              # 교체: 다 모은 뒤 한꺼번에 (탐지 도중 실패해도 기존 라벨은 그대로)
                collected.extend(pending)
            else:
                task.update_annotations(models.PatchedLabeledDataRequest(shapes=pending),
                                        action=AnnotationUpdateAction.CREATE)
            pending = []

    def write_all():
        for i in range(0, len(collected), 500):
            task.update_annotations(models.PatchedLabeledDataRequest(shapes=collected[i:i + 500]),
                                    action=AnnotationUpdateAction.CREATE)

    fr0 = (getattr(meta, "frames", None) or [None])[0]
    W0, H0 = (getattr(fr0, "width", None), getattr(fr0, "height", None)) if fr0 is not None else (None, None)
    state = {"q": quality, "said": False}

    def fetch(k):
        """프레임 받기. 고해상도 영상이라 서버가 원본 프레임을 못 만들면(400, cvat#7425) 압축 프레임으로 바꿈"""
        q = state["q"]                             # 이 요청을 보낼 때의 화질 (여러 프레임을 동시에 받으므로 따로 기억)
        try:
            return PIL.Image.open(task.get_frame(k, quality=q)).convert("RGB")
        except Exception as e:
            if q == "original" and "resolution" in str(e):
                state["q"] = "compressed"
                if not state["said"]:
                    state["said"] = True
                    log("  참고: 서버가 이 영상의 원본 프레임을 만들지 못합니다(고해상도, cvat#7425) → 압축 프레임(compressed)으로 진행")
                return PIL.Image.open(task.get_frame(k, quality="compressed")).convert("RGB")
            raise

    # 프레임 받기(네트워크·디코딩)와 탐지(GPU)를 겹쳐서 진행
    from concurrent.futures import ThreadPoolExecutor
    import queue as _queue
    import threading as _threading
    pool = ThreadPoolExecutor(max_workers=max(1, int(prefetch)))
    missing = []

    def cvat_source():
        futs = {}
        def ahead(j):
            for jj in range(j, min(len(todo), j + max(1, int(prefetch)) + 1)):
                if jj not in futs:
                    futs[jj] = pool.submit(fetch, todo[jj])
        if todo:                                  # 첫 프레임을 먼저 받아 화질(원본/압축)을 정한 뒤 동시에 받기 시작
            first = fetch(todo[0])
            futs[0] = pool.submit(lambda: first)
        for i, k in enumerate(todo):
            ahead(i)
            yield k, futs.pop(i).result()

    def video_source():
        start, step = task_frame_map(meta)
        vmap = {start + k * step - int(video_offset): k for k in todo}
        q_, stop_, END = _queue.Queue(maxsize=max(2, int(prefetch) * 2)), _threading.Event(), object()
        def produce():
            try:
                for vi, im in video_frames(video, vmap, decoder):
                    if stop_.is_set():
                        return
                    q_.put((vmap[vi], im.convert("RGB")))
            except Exception as e:
                q_.put(e)
            finally:
                q_.put(END)
        th = _threading.Thread(target=produce, daemon=True)
        th.start()
        seen = set()
        try:
            while True:
                it = q_.get()
                if it is END:
                    break
                if isinstance(it, Exception):
                    raise it
                seen.add(it[0])
                yield it
        finally:
            stop_.set()
        missing.extend(k for k in todo if k not in seen)

    if video:
        state["q"] = f"영상 {Path(video).name} ({decoder}, 보정 {int(video_offset):+d})"
    try:
        for i, (k, img) in enumerate(video_source() if video else cvat_source()):
            q = state["q"]
            if video and i == 0 and W0 and (img.width, img.height) != (int(W0), int(H0)):
                if (img.height, img.width) == (int(W0), int(H0)):
                    raise RuntimeError(f"영상이 {img.width}x{img.height}로 읽혀 CVAT({W0}x{H0})와 가로세로가 뒤바뀜 (회전 정보) "
                                       "→ AA_SOURCE = 'cvat'로 실행하세요")
            sx = (W0 / img.width) if W0 else 1.0       # 압축 프레임이 원본보다 작으면 좌표를 원본 크기로 환산
            sy = (H0 / img.height) if H0 else 1.0
            if i == 0:
                log(f"  프레임 크기 {img.width}x{img.height} ({q})" + (f" → 원본 {W0}x{H0}로 좌표 환산" if (sx, sy) != (1.0, 1.0) else ""))
            for s in fn.detect(ctx, img):
                name = spec_names[s.label_id]
                if name not in task_ids:
                    skipped[name] = skipped.get(name, 0) + 1
                    continue
                x1, y1, x2, y2 = [float(v) for v in s.points]
                pending.append(models.LabeledShapeRequest(type="rectangle", frame=k, label_id=task_ids[name],
                                                          points=[x1 * sx, y1 * sy, x2 * sx, y2 * sy],
                                                          occluded=bool(getattr(s, "occluded", False)), source="auto"))
                per_label[name] = per_label.get(name, 0) + 1
                total += 1
            if (i + 1) % batch == 0:
                flush()
                el = time.time() - t0
                log(f"  {i + 1}/{len(todo)} 프레임 · 박스 {total}개 · 남은 시간 약 {el / (i + 1) * (len(todo) - i - 1) / 60:.0f}분")
        flush()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    replaced = None
    if collect_only:
        id2name = {v: k for k, v in task_ids.items()}
        shapes = [{"type": "rectangle", "frame": int(s.frame), "label": id2name.get(s.label_id, str(s.label_id)),
                   "points": [float(v) for v in s.points], "occluded": bool(getattr(s, "occluded", False))} for s in collected]
        return {"frames": len(todo) - len(missing), "boxes": total, "per_label": per_label, "skipped_labels": skipped,
                "quality": state["q"], "replaced": None, "missing_frames": missing, "shapes": shapes}
    if replace:
        log(f"  탐지 끝: 박스 {len(collected)}개 → 기존 라벨을 지우고 올림 (교체)")
        replaced = replace_annotations(task, write_all, backup, log=log)
    if missing:
        log(f"  ⚠️ 영상에서 찾지 못한 프레임 {len(missing)}장 (영상이 짧거나 보정값이 맞지 않음): {missing[:10]}")
    return {"frames": len(todo) - len(missing), "boxes": total, "per_label": per_label, "skipped_labels": skipped,
            "quality": state["q"], "replaced": replaced, "missing_frames": missing}


# ---------------- TASK별 개체 수 통계 ----------------
def count_objects(task):
    """TASK의 지금 라벨을 API로 읽어 라벨별로 셈 (export 없이 빠름, 읽기만).
    track 1개 = 개체 1개 (화면에 한 번이라도 보인 track만). 프레임별 박스(shape)는 개체 수를 알 수 없어
    박스 수와 '한 프레임 최대 박스 수'(개체 수의 하한)를 함께 줌.
    반환: {라벨: {'track': n, 'box': n, 'max_frame': n, 'occluded_track': n}}, 종류('track'/'박스'/'혼합'/'없음')"""
    names = {l.id: l.name for l in task.get_labels()}
    ann = task.get_annotations()
    per = {}

    def d(label):
        return per.setdefault(label, {"track": 0, "box": 0, "max_frame": 0, "occluded_track": 0})

    for tr in ann.tracks:
        shapes = [s for s in tr.shapes if not s.outside]
        if not shapes:
            continue
        x = d(names.get(tr.label_id, f"label_{tr.label_id}"))
        x["track"] += 1
        x["occluded_track"] += any(s.occluded for s in shapes)
    frame_cnt = {}
    for s in ann.shapes:
        lab = names.get(s.label_id, f"label_{s.label_id}")
        d(lab)["box"] += 1
        frame_cnt[(lab, s.frame)] = frame_cnt.get((lab, s.frame), 0) + 1
    for (lab, _f), n in frame_cnt.items():
        per[lab]["max_frame"] = max(per[lab]["max_frame"], n)
    has_t, has_s = bool(ann.tracks), bool(ann.shapes)
    kind = "혼합" if has_t and has_s else "track" if has_t else "박스" if has_s else "없음"
    return per, kind


# ---------------- 업로드 상세 로그 (5·6·10번 셀) ----------------
UPLOAD_LOG_COLUMNS = [
    "log_id", "start", "end", "sec", "status", "method", "mode", "task_id", "task_name", "task_name_after",
    "server", "profile", "cvat_user", "operator", "session", "app_version",
    "model", "model_time", "model_md5", "source", "settings",
    "before_total", "after_total", "before_by_label", "after_by_label", "uploaded",
    "backup_file", "result_file", "after_file", "change_csv", "detail_json", "error",
]
_LOG_LOCK = __import__("threading").Lock()


def file_fingerprint(path, _cache={}):
    """(수정 시각, md5 앞 12자리) — 같은 모델인지 나중에 확인하는 용도. 크기·시각이 같으면 다시 계산 안 함"""
    import hashlib
    p = Path(path)
    if not p.exists():
        return "", ""
    st = p.stat()
    key = (str(p), st.st_size, int(st.st_mtime))
    if key not in _cache:
        h = hashlib.md5()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(8 * 2**20), b""):
                h.update(chunk)
        _cache[key] = h.hexdigest()[:12]
    t = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    return t, _cache[key]


class UploadLog:
    """업로드 한 건의 상세 기록.
    tasks/<ID>/upload_<시각>.json (전체) + .log (읽기용 글) + logs/uploads.csv (한 줄씩 누적)"""

    def __init__(self, base, folder, task_id, method, echo=print, **ctx):
        self.base, self.folder, self.echo = Path(base), Path(folder), echo
        self.t0 = time.time()
        import uuid
        ts = f"{stamp()}_{uuid.uuid4().hex[:4]}"           # 같은 초에 두 건이어도 겹치지 않게
        self.rec = {"log_id": f"{task_id}_{ts}", "start": now(), "task_id": task_id, "method": method,
                    "status": "진행 중", "messages": [], **ctx}
        self.json_path = self.folder / f"upload_{ts}.json"

    def say(self, msg):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S')} {str(msg).strip()}"
        self.rec["messages"].append(line)
        if self.echo:
            self.echo(msg)

    def set(self, **kw):
        self.rec.update(kw)

    def counts(self, before_zip=None, after_zip=None):
        """백업·업로드 후 export에서 라벨별 박스 수"""
        from collections import Counter
        for key, z in (("before", before_zip), ("after", after_zip)):
            if z:
                a = load_annotations(z)
                c = Counter(b[1] for lst in a["boxes"].values() for b in lst)
                self.rec[f"{key}_total"] = sum(c.values())
                self.rec[f"{key}_by_label"] = dict(c)
                self.rec[f"{key}_objects"] = len({b[0] for lst in a["boxes"].values() for b in lst})

    def finish(self, status, error=None):
        import json as _json
        import traceback
        self.rec.update(status=status, end=now(), sec=round(time.time() - self.t0, 1))
        if error is not None:
            self.rec["error"] = api_error(error)
            self.rec["traceback"] = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-4000:]
        self.folder.mkdir(parents=True, exist_ok=True)
        rel = lambda p: os.path.relpath(p, self.base)
        self.rec["detail_json"] = rel(self.json_path)
        self.json_path.write_text(_json.dumps(self.rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        lines = [f"[{self.rec['log_id']}] {status}"]
        for k in UPLOAD_LOG_COLUMNS:
            v = self.rec.get(k)
            if v not in (None, "", {}, []) and k not in ("log_id", "status"):
                lines.append(f"{k:16}: {v}")
        lines += ["", "--- 진행 메시지 ---"] + self.rec["messages"]
        if self.rec.get("traceback"):
            lines += ["", "--- 오류 상세 ---", self.rec["traceback"]]
        self.json_path.with_suffix(".log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        row = {k: (_json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v)
               for k, v in self.rec.items() if k in UPLOAD_LOG_COLUMNS}
        path = shard_path(self.base / "logs" / "uploads.csv")   # v4.30.1: 이 세션 파일에
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                _migrate_header(path, UPLOAD_LOG_COLUMNS)
            new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=UPLOAD_LOG_COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(row)
        try:                                               # 시계열 작업 기록에도 한 줄
            r = self.rec
            log_task("upload" if r.get("method") == "track" else "auto", r.get("task_id"),
                     r.get("task_name_after") or r.get("task_name", ""), status, base=str(self.base),
                     model=f"{r.get('model', '')} ({r.get('model_time', '')}, md5 {r.get('model_md5', '')})",
                     boxes=r.get("after_total", ""), by_label=r.get("after_by_label", ""),
                     objects=r.get("after_objects", ""),
                     boxes_before=r.get("before_total", ""), by_label_before=r.get("before_by_label", ""),
                     file=r.get("after_file") or r.get("result_file", ""), sec=r.get("sec"),
                     summary=" · ".join(str(x) for x in [r.get("mode"), r.get("uploaded"), r.get("error")] if x),
                     settings=r.get("settings", ""), source=r.get("source", ""))
        except Exception:
            pass
        return self.json_path


# ---------------- 작업 기록 (시계열) — logs/activity.csv ----------------
# 셀 한 번 실행 = '작업(job)' 하나 (시작·끝 줄), 그 안에서 TASK마다 한 줄 (무엇을 했고 라벨이 어떻게 바뀌었나)
ACTIVITY_COLUMNS = [
    "time", "job_id", "row", "cell", "action", "status", "task_id", "task_name",
    "who", "session", "server", "model",
    "frames", "objects", "boxes", "by_label", "boxes_before", "by_label_before",
    "task_updated", "file", "size_mb", "sec", "summary", "settings", "source",
]
ACTION_KO = {"track": "track 생성", "upload": "업로드(track)", "auto": "자동 라벨(shape)", "review": "검수 수집",
             "export": "export", "backup": "백업", "dataset": "데이터셋", "train": "학습", "train_data": "학습 데이터",
             "restore": "백업 복원", "create": "TASK 생성", "revision_restore": "학습 복원", "cleanup": "모델 정리", "compare": "모델 비교"}
class _ActJob:
    """지금 열린 작업(job) — 스레드마다 따로 (v4.29: 재처리 작업자가 여러 일을 동시에 할 때 작업 기록이 섞이지 않게).
    작업을 연 적 없는 스레드는 주 스레드의 작업을 봄 (예전과 같음)"""
    def __init__(self):
        import threading as _th
        self._th, self._main, self._tl = _th, None, _th.local()

    def __getitem__(self, k):
        return self._tl.job if getattr(self._tl, "own", False) else self._main

    def __setitem__(self, k, v):
        if self._th.current_thread() is self._th.main_thread():
            self._main = v
        else:
            self._tl.own, self._tl.job = True, v


_ACT = _ActJob()
_ACT_LOCK = __import__("threading").Lock()


def _act_path(base):
    return Path(base) / "logs" / "activity.csv"


def _act_write(base, row):
    import json as _json
    row = {k: (_json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list, tuple)) else v)
           for k, v in row.items()}
    row.setdefault("time", now())
    path = shard_path(_act_path(base))             # v4.30.1: 이 세션 파일에
    with _ACT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            _migrate_header(path, ACTIVITY_COLUMNS)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=ACTIVITY_COLUMNS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in ACTIVITY_COLUMNS})


def start_job(base, cell, action, who="", session="", server="", model="", settings=None, summary=""):
    """작업 시작 — 이후 append_registry·log_task가 이 작업에 묶여 기록됨"""
    import uuid
    job = {"base": str(base), "job_id": f"{stamp()}_{cell}_{uuid.uuid4().hex[:4]}", "cell": str(cell), "action": action,
           "who": who, "session": session, "server": server, "model": model, "t0": time.time(), "n": {},
           "settings": settings or {}}
    _ACT["job"] = job
    _act_write(base, {"job_id": job["job_id"], "row": "작업 시작", "cell": cell, "action": ACTION_KO.get(action, action),
                      "status": "시작", "who": who, "session": session, "server": server, "model": model,
                      "settings": settings or {}, "summary": summary})
    return job


def log_task(action, task_id="", task_name="", status="", job=None, **fields):
    """TASK 한 줄. 작업(job)이 없으면 작업 없이 기록"""
    job = job or _ACT["job"]
    base = (job or {}).get("base") or fields.pop("base", None)
    if not base:
        return
    if job:
        job["n"][status or "?"] = job["n"].get(status or "?", 0) + 1
    _act_write(base, {"job_id": (job or {}).get("job_id", ""), "row": "TASK", "cell": (job or {}).get("cell", ""),
                      "action": ACTION_KO.get(action, action), "status": status, "task_id": task_id, "task_name": task_name,
                      "who": (job or {}).get("who", ""), "session": (job or {}).get("session", ""),
                      "server": fields.pop("server", None) or (job or {}).get("server", ""),
                      "model": fields.pop("model", None) or (job or {}).get("model", ""), **fields})


def end_job(status="끝", summary="", **fields):
    job = _ACT["job"]
    if not job:
        return
    _ACT["job"] = None
    n = ", ".join(f"{k} {v}" for k, v in job["n"].items())
    _act_write(job["base"], {"job_id": job["job_id"], "row": "작업 끝", "cell": job["cell"],
                             "action": ACTION_KO.get(job["action"], job["action"]), "status": status,
                             "who": job["who"], "session": job["session"], "server": job["server"], "model": job["model"],
                             "sec": round(time.time() - job["t0"], 1),
                             "summary": " · ".join(x for x in [summary, f"TASK {sum(job['n'].values())}건 ({n})" if n else ""] if x),
                             **fields})


def current_job():
    return _ACT["job"]


def label_counts(path):
    """export zip(annotations.xml)·track XML·CVAT TASK 백업 zip(annotations.json)의 라벨 수
    → {'frames': 라벨 있는 프레임 수, 'objects': track+단독 박스, 'boxes': 프레임마다 보이는 박스 합, 'by_label': {라벨: 박스}}"""
    import json as _json
    from collections import Counter
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if not any(n.split("/")[-1] == "annotations.xml" for n in names):
                js = [n for n in names if n.split("/")[-1] == "annotations.json"]
                if not js:
                    return {}
                data = _json.loads(z.read(js[0]))
                jobs = data if isinstance(data, list) else [data]
                c, frames, objs = Counter(), set(), 0
                for j in jobs:
                    for sh in j.get("shapes", []):
                        c[sh.get("label", "?")] += 1; frames.add(sh.get("frame")); objs += 1
                    for tr in j.get("tracks", []):
                        objs += 1
                        for sh in tr.get("shapes", []):
                            if not sh.get("outside"):
                                c[tr.get("label", "?")] += 1; frames.add(sh.get("frame"))
                return {"frames": len(frames), "objects": objs, "boxes": sum(c.values()), "by_label": dict(c),
                        "note": "백업: track은 키프레임만 셈"}
    a = load_annotations(p)
    c = Counter(b[1] for lst in a["boxes"].values() for b in lst)
    return {"frames": sum(1 for v in a["boxes"].values() if v), "objects": len({b[0] for lst in a["boxes"].values() for b in lst}),
            "boxes": sum(c.values()), "by_label": dict(c)}


def _registry_to_activity(row):
    """작업 대장 한 줄을 작업 기록에도 (작업이 열려 있을 때만). 업로드·자동 라벨은 UploadLog가 더 자세히 기록하므로 뺌"""
    job = _ACT["job"]
    if not job:
        return
    act = {v: k for k, v in ACTIONS.items()}.get(row.get("action"), row.get("action"))
    if act in ("upload", "auto"):
        return
    f = {"file": row.get("result_file") or row.get("backup_file") or "", "summary": row.get("note", ""),
         "server": row.get("server")}
    if row.get("tracks") not in (None, ""):
        f["objects"] = row.get("tracks")
    if act == "export" and f["file"] and str(row.get("status", "")).startswith("완료"):
        try:
            fp = Path(job["base"]) / f["file"]
            f.update({k: v for k, v in label_counts(fp).items() if k in ("frames", "objects", "boxes", "by_label")})
            f["size_mb"] = round(fp.stat().st_size / 2**20, 2)
            info = read_export_info(fp)
            f["task_updated"] = info.get("updated", "")
        except Exception:
            pass
    if act == "review" and row.get("backup_file"):
        try:
            fp = Path(job["base"]) / row["backup_file"]
            f.update({k: v for k, v in label_counts(fp).items() if k in ("frames", "objects", "boxes", "by_label")})
            f["file"] = row["backup_file"]
        except Exception:
            pass
    if act == "track" and row.get("existing_labels") not in (None, ""):
        f["boxes_before"] = row.get("existing_labels")
    log_task(act, row.get("task_id", ""), row.get("task_name", ""), row.get("status", ""), **f)


# ---------------- 학습 데이터 상태 (v4.13): 검토 완료 · train/val 역할 · TASK 학습 대장 ----------------
TRAIN_TASK_COLUMNS = ["time", "model", "data_sig", "role", "task_id", "task_name", "state", "frames", "boxes",
                      "label_updated", "export_zip", "who", "session", "app_version",
                      "frames_from"]   # v4.24.4: 학습 이미지 출처 (export 이미지 / mp4 pyav 14.0.1 / mp4 opencv 4.10.0 …)


def is_reviewed(name, rule="vf"):
    """검토 완료 TASK인가: 이름의 상태(state)에 rule 글자가 들어 있으면 True (예: vf, vf_r2df_ok, vf_AA).
    이름 규칙 밖이면 이름 전체에서 찾음. rule이 ''이면 모두 True"""
    if not rule:
        return True
    f = parse_task_name(name)
    state = (f or {}).get("state", "") if f else (name or "")
    return rule.lower() in state.lower()


def split_role(name, val_rule):
    """val 규칙(검색어)에 맞으면 'val', 아니면 'train'. 이름 규칙 밖이면 '규칙 밖'(학습에서는 train), 규칙이 없으면 ''"""
    if not val_rule:
        return ""
    if parse_task_name(name) is None:
        return "규칙 밖"
    return "val" if match_name(name, val_rule)[0] else "train"


def _train_tasks_path(base):
    return Path(base) / "logs" / "train_tasks.csv"


def read_train_tasks(base):
    """logs/train_tasks.csv (TASK × 학습 이름 × 역할) — 없으면 [] · v4.30.1: 세션 파일 합침"""
    return read_sharded(_train_tasks_path(base))


def append_train_tasks(base, model, data_sig, split_csv, info=None, **common):
    """데이터셋의 split_tasks.csv(cvat_to_yolo가 만듦)를 TASK 학습 대장에 옮김. 같은 학습 이름·데이터 서명이면 다시 쓰지 않음.
    info = {task_id: {'state':…, 'label_updated':…, 'export_zip':…}} (15번 셀이 export에서 읽은 값). 반환: 새로 쓴 줄 수"""
    p = shard_path(_train_tasks_path(base))        # v4.30.1: 이 세션 파일에
    if any(r.get("model") == model and r.get("data_sig") == data_sig for r in read_train_tasks(base)):
        return 0
    with open(split_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    info = info or {}
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        _migrate_header(p, TRAIN_TASK_COLUMNS)
    new = not p.exists()
    t = now()
    with open(p, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TRAIN_TASK_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            tid = str(r.get("task_id", ""))
            extra = info.get(tid, {})
            f = parse_task_name(r.get("task_name", "")) or {}
            w.writerow({**common, "time": t, "model": model, "data_sig": data_sig, "role": r.get("split", ""),
                        "task_id": tid, "task_name": r.get("task_name", ""), "state": extra.get("state", f.get("state", "")),
                        "frames": r.get("frames", ""), "boxes": r.get("boxes", ""),
                        "label_updated": extra.get("label_updated", ""), "export_zip": extra.get("export_zip", ""),
                        "frames_from": r.get("frames_from", "")})
    return len(rows)


def last_trained(base):
    """TASK ID → 그 TASK가 들어간 가장 최근 학습 데이터의 줄 (TASK 학습 대장 기준)"""
    out = {}
    for r in read_train_tasks(base):
        tid = str(r.get("task_id", ""))
        if tid and (tid not in out or r.get("time", "") >= out[tid].get("time", "")):
            out[tid] = r
    return out


def train_change(task_updated_utc, last_row):
    """학습 뒤 라벨 변화: '🆕 학습 안 함' / '🔁 라벨 바뀜' (CVAT 수정 시각 > 학습에 쓴 라벨 시각) / '—'"""
    if not last_row:
        return "🆕 학습 안 함"
    cu, lu = _to_utc(task_updated_utc), _to_utc(last_row.get("label_updated"))
    if cu is None or lu is None:
        return "—"
    return "🔁 라벨 바뀜" if cu.replace(microsecond=0) > lu.replace(microsecond=0) else "—"


def import_old_records(base, log=print):
    """v4.10 이전 기록을 작업 기록으로 한 번 옮김: 작업 대장, 백업 색인, export 색인, runs/의 학습 완료.
    source='예전 기록'. 이미 옮겼으면(logs/activity_imported.txt) 건너뜀"""
    base = Path(base)
    flag = base / "logs" / "activity_imported.txt"
    if flag.exists():
        return 0
    cut = "9999"                                       # 이미 v4.10 작업 기록이 있으면 그보다 앞선 예전 줄만 (겹치지 않게)
    ap = _act_path(base)
    _rows = read_sharded(ap)
    if _rows:
        ts = [r["time"] for r in _rows if r.get("row") == "작업 시작" and r.get("time")]
        cut = min(ts) if ts else cut
    n = 0
    rev = {v: k for k, v in ACTIONS.items()}
    for r in read_registry(base / "task_registry.csv"):
        if (r.get("run_time") or "") >= cut:
            continue
        act = rev.get(r.get("action"), r.get("action"))
        log_task(act, r.get("task_id", ""), r.get("task_name", ""), r.get("status", ""), base=str(base),
                 time=r.get("run_time", ""), file=r.get("result_file") or r.get("backup_file") or "",
                 summary=r.get("note", ""), server=r.get("server", ""), model=r.get("model", ""),
                 objects=r.get("tracks", ""), boxes_before=r.get("existing_labels", ""), source="예전 기록(작업 대장)")
        n += 1
    bi = base / "backup_index.csv"
    if True:
        if True:
            for r in read_sharded(bi):
                if (r.get("run_time") or "") >= cut:
                    continue
                log_task("backup", r.get("task_id", ""), r.get("task_name", ""), r.get("result", ""), base=str(base),
                         time=r.get("run_time", ""), file=r.get("file", ""), size_mb=r.get("size_mb", ""),
                         task_updated=r.get("task_updated", ""), server=r.get("server", ""),
                         summary=f"{r.get('kind', '')} {r.get('note', '')}".strip(), source="예전 기록(백업 색인)")
                n += 1
    for root in (base / "runs").glob("*/TRAINING_DONE"):
        rd = root.parent
        t = datetime.datetime.fromtimestamp(root.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        log_task("train", "", rd.name, "완료", base=str(base), time=t, file=os.path.relpath(rd, base),
                 summary=root.read_text(encoding="utf-8", errors="ignore")[:200], source="예전 기록(runs)")
        n += 1
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(f"{now()} {n}줄", encoding="utf-8")
    log(f"예전 기록 {n}줄을 작업 기록으로 옮김 (작업 대장·백업 색인·runs)")
    return n


# ---------------- 모델 정리 (v4.24.8): 안 쓰는 모델의 큰 파일만 지우고 기록은 남김 ----------------
# 지우는 것: runs/<이름>/weights/*.pt (slim은 best.pt를 남김) · datasets/<이름>.zip (그 데이터셋을 쓰는 다른 학습이 없을 때)
# 남기는 것: results.csv · args.yaml · DATASET_SIG · TRAINING_DONE · 그래프 · datasets/<이름>.sig·.json·_report.html
#   → 이름 중복 보호(같은 이름을 다른 데이터로 다시 쓰지 못함), TASK 학습 대장·작업 기록·업로드 기록의 출처가 그대로 남음
MODEL_CLEANUP_FILE = "CLEANUP.json"
CLEANUP_ACTIONS = {"slim": "가볍게 (best.pt만 남김)", "archive": "보관 (가중치 모두 지움)"}
_USE_ACTIONS = ("track 생성", "업로드(track)", "자동 라벨(shape)", "프레임별 자동 라벨링", "업로드")


def model_files(base, prefixes=("runs", "datasets")):
    """BASE 아래 runs/·datasets/의 파일 → {BASE 기준 경로: (크기, 수정 시각 epoch)} (Kaggle은 노트북이 Drive 목록으로 줌)"""
    out = {}
    for pre in prefixes:
        root = Path(base) / pre
        if not root.exists():
            continue
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    st = p.stat()
                    out[p.relative_to(base).as_posix()] = (st.st_size, st.st_mtime)
            except OSError:
                pass
    return out


def _read_text(base, rel):
    p = Path(base) / rel
    try:
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""
    except OSError:
        return ""


def read_cleanup(base, name):
    """runs/<이름>/CLEANUP.json → {'archived': bool, 'history': [...]}"""
    import json as _json
    t = _read_text(base, f"runs/{name}/{MODEL_CLEANUP_FILE}")
    try:
        d = _json.loads(t) if t else {}
    except ValueError:
        d = {}
    return {"archived": bool(d.get("archived")), "history": list(d.get("history") or [])}


def model_usage(base, names):
    """학습 이름 → 자동 라벨링·업로드에 쓴 기록 (logs/uploads.csv의 업로드 · logs/activity.csv의 track·자동 라벨 작업)"""
    import json as _json
    names = list(names)
    rx = {n: re.compile(r"(^|[^\w.-])" + re.escape(n) + r"([^\w.-]|$)") for n in names}
    out = {n: {"uploads": 0, "jobs": 0, "last": ""} for n in names}
    p = Path(base) / "logs" / "uploads.csv"
    if True:                                       # v4.30.1: 세션 파일 합침
        if True:
            for r in read_sharded(p):
                m = r.get("model") or ""
                for n, x in rx.items():
                    if m and x.search(m):
                        out[n]["uploads"] += 1
                        out[n]["last"] = max(out[n]["last"], r.get("start") or "")
    p = Path(base) / "logs" / "activity.csv"
    if True:
        if True:
            for r in read_sharded(p):
                if r.get("row") != "작업 시작" or r.get("action") not in _USE_ACTIONS:
                    continue
                txt = (r.get("model") or "") + " " + (r.get("settings") or "")
                for n, x in rx.items():
                    if x.search(txt):
                        out[n]["jobs"] += 1
                        out[n]["last"] = max(out[n]["last"], r.get("time") or "")
    return out


def _dataset_users(base, files, names):
    """데이터셋 이름 → 그 데이터셋을 DATASET_NAME으로 쓴 다른 학습들 (15번 셀 작업 기록의 dataset_name, v4.24.6~).
    v4.24.6 이전에는 학습마다 자기 데이터셋을 만들었으므로 다른 학습이 쓸 수 없었음"""
    import json as _json
    from collections import defaultdict
    users = defaultdict(set)
    p = Path(base) / "logs" / "activity.csv"
    if True:                                       # v4.30.1: 세션 파일 합침
        if True:
            for r in read_sharded(p):
                if r.get("row") != "작업 시작" or r.get("action") != "학습":
                    continue
                try:
                    st = _json.loads(r.get("settings") or "{}")
                except ValueError:
                    continue
                d, t = st.get("dataset_name"), st.get("train_name")
                if d and t and d != t:
                    users[d].add(t)
    return users


def model_inventory(base, files=None, stale_min=45):
    """runs/의 학습마다 상태·크기·쓰임 → 목록 (최근 것 먼저). files = model_files() 형식 (None이면 BASE를 직접 봄)"""
    files = model_files(base) if files is None else files
    names = {k.split("/")[1] for k in files if k.startswith("runs/") and k.count("/") >= 2}
    names |= {k[len("datasets/"):-len(".zip")] for k in files if k.startswith("datasets/") and k.endswith(".zip") and k.count("/") == 1}
    names = sorted(names)                         # 데이터셋만 만든 것(BUILD_ONLY)도 공간을 차지하므로 포함
    names = [n for n in names if not n.startswith((".", "_"))]
    use = model_usage(base, names)
    users = _dataset_users(base, files, names)
    now = time.time()
    rows = []
    for n in names:
        mb = lambda rel: round(files[rel][0] / 2**20, 1) if rel in files else 0.0
        pts = {k: v for k, v in files.items() if k.startswith(f"runs/{n}/weights/") and k.endswith(".pt")}
        best, last = f"runs/{n}/weights/best.pt", f"runs/{n}/weights/last.pt"
        other = sum(v[0] for k, v in pts.items() if k not in (best, last)) / 2**20
        lock = files.get(f"runs/{n}/{RUN_LOCK_FILE}")
        lock_age = (now - lock[1]) / 60 if lock else None
        cl = read_cleanup(base, n)
        done = f"runs/{n}/TRAINING_DONE" in files
        ds_only = not any(k.startswith(f"runs/{n}/") for k in files)
        running = lock_age is not None and lock_age < stale_min
        u = use.get(n, {})
        rows.append({
            "name": n, "status": ("학습 중" if running else "보관됨" if cl["archived"] else "완료" if done
                                  else "데이터셋만" if ds_only else "중단됨"),
            "done": done, "dataset_only": ds_only, "running": running, "archived": cl["archived"],
            "best_mb": mb(best), "last_mb": mb(last), "other_pt_mb": round(other, 1), "dataset_mb": mb(f"datasets/{n}.zip"),
            "dataset_users": sorted(users.get(n, ())), "used_uploads": u.get("uploads", 0), "used_jobs": u.get("jobs", 0),
            "used_last": u.get("last", ""), "last_cleanup": (cl["history"][-1] if cl["history"] else None),
            "time": max([v[1] for k, v in files.items() if k.startswith(f"runs/{n}/")] or [0]),
        })
    for r in rows:
        r["slim_mb"] = round(r["last_mb"] + r["other_pt_mb"] + (0 if r["dataset_users"] else r["dataset_mb"]), 1)
        r["archive_mb"] = round(r["slim_mb"] + r["best_mb"], 1)
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


def cleanup_plan(base, name, action, files=None, inventory=None, allow_used=False, protect=()):
    """정리 계획 → {'name','action','delete':[(경로, MB)], 'keep':[(경로, 이유)], 'blockers':[...], 'freed_mb'} (지우지 않음)"""
    files = model_files(base) if files is None else files
    inv = {r["name"]: r for r in (inventory or model_inventory(base, files))}
    plan = {"name": name, "action": action, "delete": [], "keep": [], "blockers": [], "freed_mb": 0.0}
    r = inv.get(name)
    if action not in CLEANUP_ACTIONS:
        plan["blockers"].append(f"정리 방식 '{action}' 모름 — 'slim' 또는 'archive'")
        return plan
    if r is None:
        plan["blockers"].append(f"runs/{name} 없음")
        return plan
    if r["running"]:
        plan["blockers"].append("학습 중 (잠금이 최근에 갱신됨) — 끝난 뒤에 정리")
    if action == "slim" and not r["done"] and f"runs/{name}/weights/last.pt" in files:
        plan["blockers"].append("학습이 끝나지 않음 (TRAINING_DONE 없음) — last.pt가 이어 학습에 필요. 버릴 학습이면 'archive'")
    if action == "archive" and name in set(protect or ()):
        plan["blockers"].append("0번 셀에서 지금 고른 모델 — 다른 모델을 고른 뒤 정리")
    used = r["used_uploads"] + r["used_jobs"]
    if action == "archive" and used and not allow_used:
        plan["blockers"].append(f"자동 라벨링에 쓴 모델 (업로드 {r['used_uploads']}건 · 작업 {r['used_jobs']}회, 마지막 {r['used_last'][:16]}) "
                                "— 출처 확인용으로 best.pt를 남기길 권함. 그래도 지우려면 ALLOW_USED = True")
    for k, v in sorted(files.items()):
        if not (k.startswith(f"runs/{name}/weights/") and k.endswith(".pt")):
            continue
        if k.endswith("/best.pt") and action == "slim":
            plan["keep"].append((k, "slim: 쓰는 모델"))
        else:
            plan["delete"].append((k, round(v[0] / 2**20, 1)))
    dz = f"datasets/{name}.zip"
    if dz in files:
        if r["dataset_users"]:
            plan["keep"].append((dz, "이 데이터셋으로 학습한 다른 학습: " + ", ".join(r["dataset_users"])))
        else:
            plan["delete"].append((dz, round(files[dz][0] / 2**20, 1)))
    plan["keep"].append((f"runs/{name}/ 기록", "results.csv · args.yaml · DATASET_SIG · TRAINING_DONE · 그래프 (이름·출처 보호)"))
    plan["freed_mb"] = round(sum(m for _, m in plan["delete"]), 1)
    if not plan["delete"] and not plan["blockers"]:
        plan["blockers"].append("지울 파일 없음 (이미 정리됨)")
    return plan


def cleanup_apply(base, plan, remove=None, who="", reason="", log=print):
    """계획대로 지우고 runs/<이름>/CLEANUP.json에 이력. remove(경로) = 지우는 함수 (기본: BASE의 파일 삭제 → Drive 휴지통)
    반환: {'name','ok','deleted':[...],'errors':[...],'freed_mb'}"""
    import json as _json
    name = plan["name"]
    res = {"name": name, "ok": False, "deleted": [], "errors": [], "freed_mb": 0.0}
    if plan["blockers"]:
        res["errors"] = list(plan["blockers"])
        return res
    def _rm(rel):
        p = Path(base) / rel
        if p.exists():
            p.unlink()
    remove = remove or _rm
    for rel, mb_ in plan["delete"]:
        try:
            remove(rel)
            res["deleted"].append(rel)
            res["freed_mb"] += mb_
        except Exception as e:
            res["errors"].append(f"{rel}: {e}")
    res["freed_mb"] = round(res["freed_mb"], 1)
    cl = read_cleanup(base, name)
    cl["history"].append({"time": now(), "who": who, "action": plan["action"], "reason": reason,
                          "deleted": res["deleted"], "freed_mb": res["freed_mb"], "errors": res["errors"]})
    if plan["action"] == "archive" and res["deleted"]:
        cl["archived"] = True
    p = Path(base) / "runs" / name / MODEL_CLEANUP_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(cl, ensure_ascii=False, indent=1), encoding="utf-8")
    res["ok"] = not res["errors"]
    if log:
        log(f"{'✅' if res['ok'] else '⚠️'} {name}: {CLEANUP_ACTIONS[plan['action']]} — {len(res['deleted'])}개 파일, "
            f"{res['freed_mb']:.0f} MB" + (f" · 오류 {len(res['errors'])}개" if res["errors"] else ""))
    return res


# ======================= 세션별 기록 (v4.30.1) — 여러 세션(Colab·Kaggle)이 동시에 써도 줄이 사라지지 않게 =======================
# 함께 쓰는 기록(작업 대장·업로드·작업 기록·학습 대장·모델 비교·백업 색인)과 대기 목록은 세션마다 따로 씀:
#   logs/shards/<이름>/<세션>.csv  (예: logs/shards/task_registry/3f9a1c2e.csv)
# 읽을 때는 예전 한 파일 + 모든 세션 파일을 합침 (같은 줄은 하나로, 시각 순). 대기 목록은 요청마다 가장 나중 상태 하나.
# 예전처럼 한 파일에 쓰면 두 세션이 각자 사본에 줄을 더한 뒤 파일 전체를 올려 한쪽 줄이 사라졌음.
SHARD = {"id": os.environ.get("EGGPLANT_SHARD", "")}
SHARD_DIR = "logs/shards"
SHARDED = {                       # 기준 경로(BASE 기준) → (세션 파일 폴더 이름, 시각 열)
    "task_registry.csv": ("task_registry", "run_time"),
    "logs/uploads.csv": ("uploads", "start"),
    "logs/activity.csv": ("activity", "time"),
    "logs/train_tasks.csv": ("train_tasks", "time"),
    "logs/model_compare.csv": ("model_compare", "time"),
    "backup_index.csv": ("backup_index", "run_time"),
    "backups/pending_backups.csv": ("pending_backups", "request_time"),
    "exports/pending_exports.csv": ("pending_exports", "request_time"),
}
PENDING_KINDS = ("pending_backups", "pending_exports")
_P_RANK = {"요청됨": 1, "준비 중": 2, "실패": 3, "만료": 3, "오류": 3, "받음": 4, "완료": 4, "완료(복사)": 4}
_SHARD_LOCK = __import__("threading").Lock()


def set_shard(session_id):
    """이 세션의 기록 파일 이름 (0번 셀이 SESSION_ID로 정함). 빈 값 = 예전처럼 한 파일에"""
    sid = re.sub(r"[^\w.-]+", "_", str(session_id or ""))
    SHARD["id"] = sid
    os.environ["EGGPLANT_SHARD"] = sid          # 모듈을 다시 불러와도 유지
    return sid


def _shard_key(path):
    """경로가 세션별로 쓰는 기록이면 (BASE, 기준 경로, 폴더 이름, 시각 열), 아니면 None"""
    p = str(path).replace("\\", "/")
    for rel, (name, tcol) in SHARDED.items():
        if p == rel or p.endswith("/" + rel):
            return Path(p[: len(p) - len(rel)] or "."), rel, name, tcol
    return None


def is_sharded(path):
    return _shard_key(path) is not None


def shard_path(path):
    """이 세션이 쓸 파일 — 세션 표시가 없거나 세션별 기록이 아니면 원래 경로"""
    k = _shard_key(path)
    if k is None or not SHARD["id"]:
        return Path(path)
    base, _, name, _ = k
    return base / SHARD_DIR / name / f"{SHARD['id']}.csv"


def shard_files(path):
    """읽을 파일: 예전 한 파일 + 모든 세션 파일"""
    k = _shard_key(path)
    out = [Path(path)] if Path(path).exists() else []
    if k is not None:
        base, _, name, _ = k
        d = base / SHARD_DIR / name
        if d.is_dir():
            out += sorted(d.glob("*.csv"))
    return out


def _read_rows(p):
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except (FileNotFoundError, OSError):
        return []


def _p_key(r):
    return r.get("rq_id") or f"{r.get('server', '')}|{r.get('task_id', '')}|{r.get('request_time', '')}"


def _p_order(r):
    # 가장 나중에 바뀐 줄이 이김 (write_sharded가 바꾼 줄에만 checked_time을 새로 찍음) → 같으면 더 나아간 상태
    return (str(r.get("checked_time") or r.get("request_time") or ""), _P_RANK.get(r.get("status", ""), 0))


def merge_pending(rows):
    """대기 목록 합치기: 요청(rq_id)마다 한 줄 — 가장 나중에 바뀐 줄, 같은 시각이면 더 나아간 상태.
    다른 세션이 예전에 읽어 둔 낡은 줄은 시각이 그대로라 새 줄을 덮지 못하고,
    '받음' → '만료'처럼 되돌리는 고침도 시각이 새로워 반영됨"""
    best = {}
    for r in rows:
        k = _p_key(r)
        o = best.get(k)
        if o is None or _p_order(r) >= _p_order(o):
            best[k] = r
    return sorted(best.values(), key=lambda r: str(r.get("request_time") or ""))


def read_sharded(path):
    """세션별 기록 읽기 — 예전 한 파일 + 세션 파일을 합침. 같은 줄은 하나로, 시각 순 (대기 목록은 요청마다 하나)"""
    k = _shard_key(path)
    rows = []
    for f in shard_files(path):
        rows += _read_rows(f)
    if k is None:
        return rows
    _, _, name, tcol = k
    if name in PENDING_KINDS:
        return merge_pending(rows)
    seen, out = set(), []
    for r in rows:
        key = tuple(sorted((a, b) for a, b in r.items() if a is not None and b not in (None, "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: str(r.get(tcol) or ""))   # 시각 순 (같은 시각은 읽은 순서 그대로)
    return out


def write_sharded(path, rows, columns):
    """대기 목록처럼 통째로 다시 쓰는 기록 — 이 세션 파일에만 (다른 세션 줄과는 읽을 때 합침)"""
    p = shard_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if "checked_time" in columns:                   # 바뀐 줄에만 시각을 찍어 다른 세션의 낡은 줄을 이기게
        cur = {_p_key(r): r for r in read_sharded(path)}
        stamp = now()
        rows = [dict(r) for r in rows]
        for r in rows:
            o = cur.get(_p_key(r))
            if o is None or any(str(r.get(c) or "") != str(o.get(c) or "") for c in columns if c != "checked_time"):
                if str(r.get("checked_time") or "") <= str((o or {}).get("checked_time") or ""):
                    r["checked_time"] = stamp
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})
    os.replace(tmp, p)
    return p


def compact_shards(base, min_age_h=48, min_files=8, log=print):
    """오래된 세션 파일을 하나로 합침 (파일이 너무 많아지지 않게, 28번 셀이 가끔) — 이 세션 파일·최근 파일은 그대로.
    두 세션이 동시에 합쳐도 같은 줄은 읽을 때 하나로 보이므로 안전"""
    base = Path(base)
    done = 0
    for rel, (name, tcol) in SHARDED.items():
        d = base / SHARD_DIR / name
        if not d.is_dir():
            continue
        cut = time.time() - min_age_h * 3600
        old = [f for f in d.glob("*.csv") if f.stem != SHARD["id"] and f.stat().st_mtime < cut]
        if len(old) < min_files:
            continue
        rows = []
        for f in old:
            rows += _read_rows(f)
        rows = merge_pending(rows) if name in PENDING_KINDS else rows
        cols = list(dict.fromkeys(c for r in rows for c in r if c))
        out = d / f"merged_{stamp()}_{SHARD['id'] or 'x'}.csv"
        tmp = out.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, out)
        for f in old:
            try:
                f.unlink()
            except OSError:
                pass
        done += len(old)
        if log:
            log(f"세션 기록 합침: {SHARD_DIR}/{name} 파일 {len(old)}개 → {out.name} ({len(rows)}줄)")
    return done


# ======================= 고정 시험 TASK (v4.31.8) =======================
# config/test_tasks.json: 학습에도 모델 고르기(val)에도 쓰지 않고 마지막 평가에만 쓰는 TASK 묶음.
# 같은 그루·촬영일(온실·날짜·줄·그루)의 다른 TASK도 학습에서 뺌 — 이웃 프레임이 새어 시험이 쉬워지지 않게.
TEST_TASKS_FILE = "config/test_tasks.json"


def test_key(name):
    """TASK 이름 → (온실, 촬영일 YYMMDD, 줄, 그루) · 규칙 밖 이름은 None"""
    f = parse_task_name(name)
    if not f:
        return None
    return (str(f.get("gh") or "").upper(), str(f.get("date") or "")[-6:], str(f.get("row") or ""), str(f.get("plant") or ""))


def read_test_tasks(base):
    """{'ids': {TASK ID 문자열}, 'names': {id: 이름}, 'keys': {(온실, 날짜, 줄, 그루)}, 'note', 'updated', 'history'} · 파일이 없으면 ids가 빈 것"""
    p = Path(base) / TEST_TASKS_FILE
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    names = {str(k): v for k, v in (d.get("names") or {}).items()}
    ids = {str(x) for x in (d.get("ids") or [])}
    keys = {k for k in (test_key(names.get(i, "")) for i in ids) if k}
    return {"ids": ids, "names": names, "keys": keys, "note": d.get("note", ""), "updated": d.get("updated", ""),
            "history": d.get("history") or []}


def write_test_tasks(base, id_names, by="", note=""):
    """고정 시험 TASK를 저장 (id_names = {TASK ID: 이름}). 바꿀 때마다 history에 남김 — 바꾸기 전후 성적은 서로 비교하지 않음"""
    p = Path(base) / TEST_TASKS_FILE
    old = read_test_tasks(base)
    ids = sorted({str(k) for k in id_names}, key=lambda x: (len(x), x))
    hist = list(old["history"]) + [{"time": now(), "by": by, "note": note, "n": len(ids),
                                     "added": sorted(set(ids) - old["ids"]), "removed": sorted(old["ids"] - set(ids))}]
    nm = {str(a): b for a, b in id_names.items()}
    d = {"version": 1, "ids": [int(x) if x.isdigit() else x for x in ids], "names": {k: nm.get(k, "") for k in ids},
         "note": note, "updated": now(), "by": by, "history": hist[-50:]}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def test_conflict(test, task_id, name):
    """학습에서 뺄 TASK인가 → '시험 TASK' · '같은 그루·촬영일' · '' (뺄 것 없음)"""
    if not test or not test.get("ids"):
        return ""
    if str(task_id) in test["ids"]:
        return "시험 TASK"
    k = test_key(name)
    return "같은 그루·촬영일" if k and k in test["keys"] else ""
