"""
웹 관리 화면 연동 (v4.14) — 28번 셀과 5·9·13·14·15번 셀이 씀

1) 상태 파일  web/state.json
   CVAT TASK 목록 + Drive 기록(작업 대장·백업 상태·export·TASK 학습 대장·업로드 기록·작업 기록·runs/)을 합쳐
   TASK마다 생애주기(단계)·검토·역할·백업·export·학습 상태를, 모델마다 성능·설정·학습 데이터를 한 파일로 만든다.
   웹 화면(Claude 웹 페이지)은 이 파일만 읽어 보여 준다.

3) 검토 수정량 (v4.27)  web/corrections.json — 자동 라벨 업로드 직후 ↔ 검토 뒤 export, 모델별로 모아 상태 파일에
4) 백업 기록 (v4.27)  backup_index.csv → TASK마다 최근 백업 (웹 '백업' 탭)

2) 웹 요청  requests/REQ_<id>__<kind>__<status>.json
   웹 화면이 만든 요청(백업·export·track·자동 라벨·학습). 상태는 파일 이름에 있다 (웹은 목록만 보고 상태를 안다).
   pending(웹이 만듦) → taken(셀이 받음) → [waiting(CVAT 준비 중, 받을 것 남음)] → done / failed · canceled(웹에서 취소)
   백업·export 요청은 그 TASK를 모두 받아야 done (v4.22). params.mode = 'all'(요청하고 받기) · 'request'(요청만) · 'download'(받기)
   셀은 FROM_REQUESTS = True일 때 req_use(kind)로 받고, 그 셀의 작업 기록(job_end)이 끝날 때 완료로 바꾼다.
   v4.26: 31번 셀 LC 작업자가 켜져 있으면 요청을 받아 그 셀을 대신 실행 (학습은 사람이 15번 셀로).
   받을 때 taken_by·taken_at·taken_host(Colab/Kaggle)를 남기고, 웹 화면은 결과를 본 사람을 requests/acks/에 남긴다.
"""
__version__ = "4.31.9"
import csv
import datetime
import glob
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import cvat_task_tools as ctt

# 요청 종류: (표시 이름, 셀 번호, 작업 기록 action)
KINDS = {
    "backup": ("백업", 13, "backup"),
    "export": ("export", 14, "export"),
    "track": ("track 생성", 5, "track"),
    "aa": ("자동 라벨(shape)", 9, "auto"),
    "train": ("학습", 15, "train"),
    "cleanup": ("모델 정리", 29, "cleanup"),
    "compare": ("모델 비교", 32, "compare"),
}
STATUS_KO = {"pending": "대기", "taken": "진행 중", "waiting": "받는 중", "done": "완료", "failed": "실패", "canceled": "취소"}
_RANK = {"pending": 1, "taken": 2, "waiting": 3, "failed": 4, "done": 4, "canceled": 5}
MODES = {"all": "요청하고 받기", "request": "요청만 (나중에 받기)", "download": "준비된 것 받기"}

# ---------- CVAT 쪽 준비 상태 (셀·웹이 요청한 백업·export의 대기 목록) — v4.22 ----------
PENDING_FILES = {"backup": "backups/pending_backups.csv", "export": "exports/pending_exports.csv"}
P_OPEN, P_OK, P_BAD = ("요청됨", "준비 중"), ("받음", "완료", "완료(복사)"), ("실패", "만료", "오류")


def pending_rows(base, kind):
    """대기 목록(CSV) 그대로"""
    return _read_csv(Path(base) / PENDING_FILES[kind])


def pending_latest(base, kind):
    """TASK별 가장 최근 요청 줄 {task_id: row}"""
    out = {}
    for r in pending_rows(base, kind):
        tid = str(r.get("task_id") or "")
        if tid and (tid not in out or str(r.get("request_time", "")) >= str(out[tid].get("request_time", ""))):
            out[tid] = r
    return out


def repair_pending(base, log=print):
    """'만료'·'실패'로 적혔는데 받은 파일이 Drive에 있는 줄 → '받음'으로 되돌림 (v4.23).
    Kaggle에서 다른 세션이 받은 export를 '파일 없음'으로 잘못 보고 다시 받다가 '만료'로 바꾼 경우 등. 고친 줄 수를 돌려줌"""
    fixed = 0
    for kind, rel in PENDING_FILES.items():
        path = Path(base) / rel
        rows = _read_csv(path)                     # v4.30.1: 세션 파일 합침
        if not rows:
            continue
        cols = list(dict.fromkeys(c for r in rows for c in r if c))
        n = 0
        for r in rows:
            f = (r.get("result_file") or r.get("out_path") or "").strip()
            if r.get("status") in P_BAD and f and (Path(base) / f).is_file():
                r["status"], r["note"] = "받음", "파일이 Drive에 있어 '받음'으로 되돌림 (v4.23)"
                if "result_file" in cols:
                    r["result_file"] = f
                n += 1
        if n:
            if hasattr(ctt, "write_sharded"):
                ctt.write_sharded(path, rows, cols)
            else:
                tmp = path.with_suffix(".tmp")
                with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
                    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                os.replace(tmp, path)
            if log:
                log(f"대기 목록 고침 ({rel}): 파일이 있는데 만료·실패로 적힌 {n}줄 → '받음'")
            fixed += n
    return fixed


def pending_open(base):
    """아직 받지 않은(요청됨·준비 중) 것 [{kind, task_id, task_name, status, request_time, server, …}]"""
    out = []
    for kind in PENDING_FILES:
        for r in pending_latest(base, kind).values():
            if r.get("status") in P_OPEN:
                out.append({"kind": kind, **{k: r.get(k, "") for k in ("task_id", "task_name", "status", "request_time",
                                                                        "server", "checked_time", "expiry", "progress",
                                                                        "format", "out_path")}})
    out.sort(key=lambda x: x["request_time"])
    return out


def _req_eval(base, req, cache=None):
    """백업·export 요청의 TASK가 다 받아졌나 → (상태, 요약). 대기 목록에 줄이 없는 TASK = 바뀐 것 없어 건너뜀(완료)"""
    kind = req.get("kind")
    if kind not in PENDING_FILES:
        return "done", ""
    if (req.get("params") or {}).get("mode") == "download" and not req.get("task_ids"):
        n = sum(1 for r in pending_open(base) if r["kind"] == kind)
        return "done", (f"아직 준비 중 {n}개" if n else "받을 것 모두 받음")
    lat = (cache or {}).get(kind) if cache is not None else None
    if lat is None:
        lat = pending_latest(base, kind)
        if cache is not None:
            cache[kind] = lat
    c = Counter()
    for t in req.get("task_ids") or []:
        st = (lat.get(str(t)) or {}).get("status", "")
        c["open" if st in P_OPEN else "bad" if st in P_BAD else "ok"] += 1
    summ = " · ".join(x for x in [f"받음 {c['ok']}" if c["ok"] else "", f"준비 중 {c['open']}" if c["open"] else "",
                                  f"실패·만료 {c['bad']}" if c["bad"] else ""] if x)
    if c["open"]:
        return "waiting", summ
    if c["bad"] and not c["ok"]:
        return "failed", summ
    return "done", summ


def settle(base, kinds=("backup", "export"), who="", job_id=""):
    """'받는 중' 요청을 대기 목록과 맞춰 봄: 다 받았으면 완료(실패만 있으면 실패). 13·14·28번 셀이 부름"""
    out, cache = [], {}
    for r in list_requests(base):
        # '받는 중', 그리고 대기 목록 때문에 '실패'가 된 요청(progress 있음)도 다시 봄 — 대기 목록을 고친 뒤 완료가 될 수 있음 (v4.23)
        if r["kind"] in kinds and (r["status"] == "waiting" or (r["status"] == "failed" and r.get("progress"))):
            st, summ = _req_eval(base, r, cache)
            if r["status"] == "failed" and st != "done":
                continue
            if st != "waiting":
                out.append(set_status(base, r, st, done_at=_now(), result=summ, progress=summ, by=who, job_id=job_id,
                                      summary=f"나중에 받기로 끝남 · {summ}"))
            elif summ != r.get("progress"):
                out.append(set_status(base, r, "waiting", progress=summ, by=who, summary=summ))
    return out
REQ_NAME = re.compile(r"^REQ_(?P<id>[0-9A-Za-z_.-]+?)__(?P<kind>[a-z]+)__(?P<status>[a-z]+)\.json$")
STAGES = ["라벨 작업 중", "자동 라벨", "검토 완료", "export 최신", "학습 반영"]


def age_hours(t):
    """시각 문자열 → 지금까지 몇 시간 (v4.31.4). 시간대 없는 값('2026-11-07 15:00:00', ctt.now())은 KST로 봄. 못 읽으면 0"""
    if not t:
        return 0
    try:
        d = datetime.datetime.fromisoformat(str(t).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
        return (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds() / 3600
    except Exception:
        return 0


def collector_tasks(base):
    """Apps Script 수집기의 TASK 스냅숏 status/cvat_tasks.json → {TASK ID: 행} (gone·gone_at 포함) · 없으면 {} (v4.31.8)"""
    try:
        return {str(k): v for k, v in (json.loads((Path(base) / "status" / "cvat_tasks.json").read_text(encoding="utf-8")).get("tasks") or {}).items()}
    except Exception:
        return {}


def _ts_utc(v):
    """시각 문자열 → UTC epoch 초 (시간대 없으면 KST) · 못 읽으면 None (v4.31.9 F15)"""
    try:
        d = datetime.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    return d.timestamp()


def uld_scan(folder):
    """ULD 기록 폴더(CVAT_UpLoader/registry/tasks/*.json, 받아 둔 사본) → {'index': {TASK ID: 'images'|'video'},
    'lineage': {옛 TASK ID: 새 TASK ID}, 'recs': {TASK ID: 기록}} (v4.31.9 — 0번 셀과 CPU 마스터가 같이 씀)
    교체 연결(F15): 처음 이름(_AA 꼬리 뗌)이 같고, 나중 기록이 ULD 요청에서 '바꾸기'(request.task.replace)로 만든 것일 때만.
    순서는 시간대를 맞춘 만든 시각으로"""
    idx, recs = {}, {}
    for p in sorted(Path(folder).glob("*.json")) if Path(folder).exists() else []:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tid = str(rec.get("task_id") or p.stem)
        recs[tid] = rec
        idx[tid] = "images" if rec.get("upload_as") == "images" and rec.get("frame_map") else "video"
    grp = defaultdict(list)
    for tid, r in recs.items():
        n = re.sub(r"_AA(_r\d+)?$", "", str(r.get("task_name_initial") or ""))
        t = _ts_utc(r.get("created_at"))
        if n and t is not None:
            grp[n].append((t, tid))
    lin = {}
    for n, v in grp.items():
        v.sort()
        for i in range(1, len(v)):
            r = recs[v[i][1]]
            if ((r.get("request") or {}).get("task") or {}).get("replace") is True:
                for _, old in v[:i]:
                    lin[old] = v[i][1]
    for old in list(lin):                          # 여러 번 바꿨으면 가장 나중 TASK로
        seen, new = {old}, lin[old]
        while new in lin and new not in seen:
            seen.add(new); new = lin[new]
        lin[old] = new
    return {"index": idx, "lineage": lin, "recs": recs}


def gone_tasks(base):
    """CVAT에서 사라진 TASK {ID: {'name', 'gone_at'}} — 수집기가 끝까지 읽은 전체 맞추기에서만 정함 (범위·개수 제한으로 안 보인 것과 구분)"""
    return {k: {"name": v.get("name", ""), "gone_at": v.get("gone_at") or ""} for k, v in collector_tasks(base).items() if v.get("gone")}


def _user_of(r):
    """요청자 이름 (뒤의 '(AA 교체)' 같은 설명은 뺌) — 공정 차례용"""
    return re.sub(r"\s*\(.*\)\s*$", "", str(r.get("by") or "")).strip() or "?"


def fair_order(reqs, light=(), served=None):
    """대기 요청을 공정한 차례로 (v4.31.6 — 30번 통합 작업자):
    ① 가벼운 일(light: 새로 고침·숨기기 등) 먼저
    ② 사람마다 돌아가며 — 각자 가장 오래된 요청 하나씩, 그다음 두 번째 … (밀린 요청이 많은 사람이 다른 사람의 새 요청을 막지 않게)
    ③ 같은 차례 안에서는 오래 기다린 것 먼저. 요청 시각은 형식(KST·UTC)이 달라도 바르게 비교
    served = {사람: 최근에 맡긴 무거운 일 수} — 방금 차례를 받은 사람은 그만큼 뒤로 (돌아가며가 요청을 하나 끝낼 때마다 이어지게)"""
    ages = [(age_hours(r.get("created")), i, r) for i, r in enumerate(reqs)]
    ages.sort(key=lambda x: (-x[0], x[1]))
    rank, keyed = Counter({str(k): int(v) for k, v in (served or {}).items()}), []
    for a, i, r in ages:
        u = _user_of(r)
        keyed.append(((r.get("kind") not in light), rank[u], -a, i, r))
        rank[u] += 1
    keyed.sort(key=lambda k: k[:4])
    return [k[-1] for k in keyed]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


# ======================= 웹 요청 =======================
def req_dir(base):
    d = Path(base) / "requests"
    d.mkdir(parents=True, exist_ok=True)
    return d


def req_path(base, rid, kind, status):
    return req_dir(base) / f"REQ_{rid}__{kind}__{status}.json"


def _mtime(p):
    """파일 수정 시각 — 그 사이 지워졌으면 None (v4.29.5)"""
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def list_requests(base):
    """requests/의 요청 목록. 같은 id의 파일이 여럿이면(동기화 중 남은 것) 끝난 상태 → 진행 중 → 대기 순으로 하나만"""
    by_id = defaultdict(list)
    for p in req_dir(base).glob("REQ_*.json"):
        m = REQ_NAME.match(p.name)
        if not m:
            continue
        by_id[m.group("id")].append((p, m.groupdict()))
    out = []
    for rid, items in by_id.items():
        data = None
        for _try in range(3):        # v4.29.5: 작업자의 다른 줄이 상태를 바꾸며(새 이름으로 쓰고 예전 것 지움) 파일이 사라질 수 있음 → 다시 찾아 읽기
            items = [x for x in items if _mtime(x[0]) is not None]
            if not items:
                break
            items.sort(key=lambda x: (_RANK.get(x[1]["status"], 0), _mtime(x[0]) or 0))
            p, g = items[-1]
            try:
                data = json.loads(p.read_text(encoding="utf-8") or "{}")
            except FileNotFoundError:
                data = None
                items = [(q, REQ_NAME.match(q.name).groupdict()) for q in req_dir(base).glob(f"REQ_{rid}__*.json") if REQ_NAME.match(q.name)]
                continue
            except Exception as e:
                data = {"error": f"읽기 실패: {e}"}
            break
        if data is None:
            continue
        data.update(id=rid, kind=g["kind"], status=g["status"], _path=str(p), _dups=[str(x[0]) for x in items[:-1]])
        out.append(data)
    out.sort(key=lambda r: str(r.get("created", "")))
    return out


def set_status(base, req, status, **fields):
    """요청 상태를 바꿈: 내용(상태·시각·기록)을 고쳐 새 이름으로 쓰고, 예전 이름의 파일은 지움"""
    data = {k: v for k, v in req.items() if not k.startswith("_")}
    data["status"] = status
    data.update(fields)
    data.setdefault("history", []).append({"time": _now(), "status": status,
                                           **{k: v for k, v in fields.items() if k in ("by", "job_id", "summary", "host")}})
    new = req_path(base, req["id"], req["kind"], status)
    tmp = new.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, new)
    for old in [req.get("_path")] + list(req.get("_dups") or []):
        if old and os.path.abspath(old) != os.path.abspath(new) and os.path.exists(old):
            os.remove(old)
    data.update(_path=str(new), _dups=[])
    return data



def _assigned_to_me(base, req_id, host):
    """단일 배정자(Apps Script LockService)가 requests/assign/ASSIGN_<id>.json 에 기록한 라우팅 및 야간 승인 여부 확인.
    배정 파일이 없으면(배정자 미가동/수동 실행) 하위 호환을 위해 True 반환."""
    assign_file = Path(base) / "requests" / "assign" / f"ASSIGN_{req_id}.json"
    if not assign_file.exists():
        return True
    try:
        a = json.loads(assign_file.read_text(encoding="utf-8"))
        if a.get("status") == "awaiting_night_approval" and not a.get("approved"):
            return False
        route = str(a.get("route") or "")
        if not route:
            return True
        h = str(host or "").lower()
        if "kaggle_cpu" in h:
            return route in ("kaggle_cpu", "kaggle", "cloud")
        if "kaggle_gpu" in h:
            return route in ("kaggle_gpu", "kaggle_train", "kaggle")
        if "kaggle" in h:
            return route.startswith("kaggle")
        if "action" in h or "cloud" in h or "gha" in h:
            return route in ("cloud", "kaggle_cpu")
        return route == "colab"
    except Exception:
        return False                               # v4.31.9 (F4): 읽을 수 없는 배정 파일은 받지 않음 (보류)


def take(base, kind, who="", session="", limit=None, host=""):
    """그 종류의 대기 요청을 받음(taken). 이미 받아 둔(taken) 요청도 함께 돌려줌.
    학습 스냅숏 export(params.snapshot)는 다른 요청과 섞지 않고 한 번에 하나만 (폴더·설정이 요청마다 다름)"""
    out = []
    # v4.31.9 (F4): '진행 중'(taken)은 이 세션이 받아 둔 것만 — 다른 세션이 진행 중인 요청을 함께 처리·완료하지 않게
    cands = [r for r in list_requests(base) if r["kind"] == kind and (
        (r["status"] == "taken" and session and r.get("taken_session") == session)
        or (r["status"] == "pending" and _assigned_to_me(base, r["id"], host)))]
    if cands:                                    # 방식(mode)이 다른 요청은 섞지 않음 — v4.22
        m0 = (cands[0].get("params") or {}).get("mode") or "all"
        cands = [r for r in cands if ((r.get("params") or {}).get("mode") or "all") == m0]
    snap = [r for r in cands if (r.get("params") or {}).get("snapshot")]
    if snap:
        cands = snap[:1]
    if cands:                                    # 조직이 다른 요청은 섞지 않음 (한 셀은 한 조직 범위로) — v4.19
        org0 = (cands[0].get("params") or {}).get("org")
        cands = [r for r in cands if (r.get("params") or {}).get("org") == org0]
    for r in cands:
        if r["status"] == "pending":
            r = set_status(base, r, "taken", taken_by=who, taken_session=session, taken_at=_now(), taken_host=host, by=who, host=host)
        out.append(r)
        if limit and len(out) >= limit:
            break
    return out


def finish(base, req_ids, ok=True, summary="", job_id="", who=""):
    """셀 작업이 끝났을 때: 받은 요청을 완료/실패로. 백업·export는 그 TASK를 모두 받았을 때만 완료,
    아직 CVAT가 준비 중이면 '받는 중'(waiting) — 나중에 받기(download)가 끝나면 settle()이 완료로"""
    done, cache = [], {}
    for r in list_requests(base):
        if r["id"] in req_ids and r["status"] in ("pending", "taken"):
            st, summ = ("failed", "") if not ok else _req_eval(base, r, cache)
            text = " · ".join(x for x in [summary, summ] if x)
            done.append(set_status(base, r, st, done_at=_now() if st != "waiting" else "", result=text, progress=summ,
                                   job_id=job_id, by=who, summary=text))
    return done


def new_request(base, kind, task_ids, params=None, by="", note="", task_names=None):
    """노트북이 LC 요청 파일을 직접 만듦 (v4.31.5 — _AA TASK를 다시 라벨할 때 영상이 없으면 백업 요청).
    같은 종류의 열린 요청(대기·진행·받는 중)에 이미 들어 있는 TASK는 빼고, 남는 것이 없으면 None"""
    ids = [int(x) for x in task_ids]
    busy = {int(t) for r in list_requests(base) if r["kind"] == kind and r["status"] in ("pending", "taken", "waiting")
            for t in (r.get("task_ids") or []) if str(t).isdigit()}
    ids = [t for t in ids if t not in busy]
    if not ids:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    kst = now.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    rid = kst.strftime("%Y%m%d_%H%M%S") + "_nb" + os.urandom(1).hex()
    body = {"id": rid, "kind": kind, "status": "pending", "created": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "by": by or "노트북", "note": note, "task_ids": ids, "task_names": list(task_names or []),
            "params": dict(params or {}), "app": "notebook"}
    p = req_path(base, rid, kind, "pending")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return body


def task_ids_of(reqs):
    return sorted({int(t) for r in reqs for t in (r.get("task_ids") or []) if str(t).strip().isdigit()})


# ======================= 상태 파일 =======================
def _read_csv(path):
    if hasattr(ctt, "is_sharded") and ctt.is_sharded(path):   # v4.30.1: 세션별 기록은 합쳐 읽음
        return ctt.read_sharded(path)
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def _yaml_flat(path):
    """ultralytics args.yaml 같은 한 줄 'key: value' 형식만 읽음"""
    out = {}
    try:
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", ln)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
    except Exception:
        pass
    return out


def _f(v, nd=3):
    try:
        return round(float(v), nd)
    except Exception:
        return None


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def model_info(base, run_dir, ledger_rows=(), train_jobs=None, upload_rows=()):
    run_dir = Path(run_dir)
    name = run_dir.name
    m = {"name": name, "done": (run_dir / "TRAINING_DONE").exists(), "done_text": "", "running": None,
         "epochs": 0, "best": {}, "last": {}, "args": {}, "data_sig": "", "weights_mb": None, "weights_time": "",
         "train_tasks": 0, "val_tasks": 0, "train_frames": 0, "val_frames": 0, "by_gh": {}, "settings": {},
         "who": "", "uploads": 0, "rule": {}, "curve": [], "plateau_epoch": None, "split": {"train": [], "val": []}}
    if m["done"]:
        m["done_text"] = (run_dir / "TRAINING_DONE").read_text(encoding="utf-8", errors="replace").strip()[:300]
    lock = ctt.read_run_lock(str(run_dir)) if hasattr(ctt, "read_run_lock") else None
    if lock:
        m["running"] = {"who": lock.get("who", ""), "stage": lock.get("stage", ""), "epoch": lock.get("epoch", ""),
                        "age_min": round(float(lock.get("age_min", 0)), 1)}
    res = _read_csv(run_dir / "results.csv")
    if res:
        rows = [{k.strip(): v for k, v in r.items() if k} for r in res]
        m["epochs"] = len(rows)
        key = "metrics/mAP50-95(B)"
        def pick(r):
            return {"epoch": int(float(r.get("epoch", 0) or 0)), "map50": _f(r.get("metrics/mAP50(B)")),
                    "map5095": _f(r.get(key)), "precision": _f(r.get("metrics/precision(B)")),
                    "recall": _f(r.get("metrics/recall(B)"))}
        if key in rows[0]:
            best = max(rows, key=lambda r: _f(r.get(key)) or -1)
            m["best"], m["last"] = pick(best), pick(rows[-1])
            m["curve"] = [_f(r.get(key), 4) for r in rows]          # v4.30: 에폭별 mAP50-95 (추가 학습 계획의 에폭 정하기)
            b = m["best"].get("map5095")
            if b:
                m["plateau_epoch"] = next((i + 1 for i, v in enumerate(m["curve"]) if v is not None and v >= 0.98 * b), None)   # 최고의 98%에 처음 닿은 에폭
    args = _yaml_flat(run_dir / "args.yaml")
    m["args"] = {k: args[k] for k in ("model", "imgsz", "epochs", "batch", "patience", "optimizer", "lr0", "device",
                                      "mosaic", "close_mosaic", "fliplr", "hsv_v") if k in args}
    sig = run_dir / "DATASET_SIG"
    m["data_sig"] = sig.read_text().strip() if sig.exists() else ""
    w = run_dir / "weights" / "best.pt"
    if w.exists():
        st = w.stat()
        m["weights_mb"], m["weights_time"] = round(st.st_size / 2**20, 1), _iso(st.st_mtime)
    gh = Counter()
    split = {"train": set(), "val": set()}                 # v4.30: 이 모델이 학습에 쓴 TASK ID (추가 학습 계획: 이전 데이터·val 고정)
    for r in ledger_rows:
        if r.get("model") != name:
            continue
        role = r.get("role", "")
        _tid = str(r.get("task_id") or "")
        if _tid:
            split["val" if role == "val" else "train"].add(int(_tid) if _tid.isdigit() else _tid)
        fr = int(float(r.get("frames") or 0))
        if role == "val":
            m["val_tasks"] += 1
            m["val_frames"] += fr
        else:
            m["train_tasks"] += 1
            m["train_frames"] += fr
        f = ctt.parse_task_name(r.get("task_name", "")) or {}
        gh[(f.get("gh") or "?", role)] += 1
    m["by_gh"] = {f"{g}|{r}": n for (g, r), n in sorted(gh.items())}
    m["split"] = {k: sorted(v, key=str) for k, v in split.items()}
    job = (train_jobs or {}).get(name)
    if job:
        m["settings"], m["who"] = job.get("settings", {}), job.get("who", "")
        m["rule"] = {k: job["settings"].get(k) for k in ("reviewed_rule", "val_rule") if k in job.get("settings", {})}
    m["uploads"] = sum(1 for u in upload_rows if f"runs/{name}/" in (u.get("model") or ""))
    return m


def _train_jobs(activity):
    """작업 기록에서 학습 작업(15번)의 설정·작업자 → {학습 이름: {...}}"""
    starts, out = {}, {}
    for r in activity:
        if r.get("action") != "학습":
            continue
        if r.get("row") == "작업 시작":
            try:
                starts[r.get("job_id")] = {"settings": json.loads(r.get("settings") or "{}"), "who": r.get("who", ""),
                                           "time": r.get("time", "")}
            except Exception:
                starts[r.get("job_id")] = {"settings": {}, "who": r.get("who", ""), "time": r.get("time", "")}
        elif r.get("row") == "작업 끝" and (r.get("file") or "").startswith("runs/"):
            name = r["file"].split("/", 1)[1].strip("/")
            if r.get("job_id") in starts:
                out[name] = {**starts[r["job_id"]], "summary": r.get("summary", ""), "end": r.get("time", "")}
    return out


def stage_of(t):
    if not t["reviewed"]:
        return STAGES[1] if t["origin"] == "auto" else STAGES[0]
    if t["train"].get("model") and t["train"].get("change") == "—":
        return STAGES[4]
    if t["export"].get("state") == "최신":
        return STAGES[3]
    return STAGES[2]


def media_names(base, videos_dir=None, remote_videos=None, remote_backups=None):
    """이미지를 얻을 수 있는 곳의 이름: 영상 파일 이름(확장자 없이, 소문자)과 TASK 백업 폴더 이름(기본 이름).
    Kaggle처럼 영상을 받아 두지 않은 곳에서는 remote_*(Drive 목록의 경로)를 넘김"""
    base = Path(base)
    vids, bks = set(), set()
    ext = (".mp4", ".mov", ".avi", ".mkv")
    if remote_videos is not None:
        vids |= {Path(p).stem.lower() for p in remote_videos if str(p).lower().endswith(ext)}
    else:
        vroot = Path(videos_dir or base / "videos")
        if vroot.exists():
            vids |= {p.stem.lower() for p in vroot.rglob("*") if p.suffix.lower() in ext}
    if remote_backups is not None:
        bks |= {str(p).split("/")[0] for p in remote_backups if str(p).lower().endswith(".zip")}
    else:
        broot = base / "backups"
        if broot.exists():
            bks |= {p.name for p in broot.iterdir() if p.is_dir() and any(p.rglob("*.zip"))}
    return vids, bks


def build_state(base, cvat_tasks, operator="", app_version="", reviewed_rule="vf", val_rule="", server="",
                events_per_task=8, log=print, video_stems=None, backup_bases=None, stats=None, snaps=None,
                scope=None, catalog=None, files=None, corrections=None, uld=None, replaced=None):
    """CVAT TASK 목록(ctt.list_tasks) + Drive 기록 → 웹 화면용 상태 dict.
    video_stems·backup_bases: 이미지를 얻을 곳 (media_names). None이면 BASE의 videos/·backups/를 봄"""
    base = Path(base)
    t0 = time.time()
    backups = {str(r.get("task_id")): r for r in _read_csv(base / "backup_status.csv")}
    bk_hist = backup_history(base)                 # v4.27: TASK별 백업 기록 (웹 '백업' 탭)
    cmp_hist = read_compares(base)                 # v4.28: TASK별 모델 비교 (웹 TASK 상세)
    lab_hist = labeling_history(base)              # v4.29: TASK별 자동 라벨 기록 (웹 '자동 라벨' 탭)
    registry = defaultdict(list)
    for r in _read_csv(base / "task_registry.csv"):
        registry[str(r.get("task_id"))].append(r)
    uploads = _read_csv(base / "logs" / "uploads.csv")
    up_by = defaultdict(list)
    for u in uploads:
        up_by[str(u.get("task_id"))].append(u)
    activity = _read_csv(base / "logs" / "activity.csv")
    ev_by = defaultdict(list)
    for r in activity:
        if r.get("row") == "TASK" and r.get("task_id"):
            ev_by[str(r["task_id"])].append(r)
    ledger = ctt.read_train_tasks(base) if hasattr(ctt, "read_train_tasks") else []
    last = ctt.last_trained(base) if hasattr(ctt, "last_trained") else {}
    names = sorted({t["name"] for t in cvat_tasks if t.get("name")}
                   | {b["task_name"] for b in backups.values() if b.get("task_name")}
                   | {r["task_name"] for r in ledger if r.get("task_name")})
    scan = ctt.scan_exports(base / "exports", names=names, log=None) if (base / "exports").exists() else []
    if video_stems is None or backup_bases is None:
        v, b = media_names(base)
        video_stems = v if video_stems is None else video_stems
        backup_bases = b if backup_bases is None else backup_bases
    media = {"videos": set(video_stems), "backups": set(backup_bases),
             "uld": {str(k): v for k, v in (uld or {}).items()}}          # v4.31.6: ULD가 만든 TASK {ID: 'images'|'video'} (clip이 원본 영상)
    for r in [x for rows in registry.values() for x in rows]:   # 작업 대장에 남은 원본 영상 이름 → TASK
        if r.get("video"):
            media.setdefault("task_video", {})[str(r.get("task_id"))] = Path(r["video"]).stem.lower()

    p_open = pending_open(base)
    p_by = defaultdict(dict)
    for x in p_open:
        p_by[str(x["task_id"])][x["kind"]] = {"status": x["status"], "time": x["request_time"]}
    tasks, seen = [], set()
    for t in cvat_tasks:
        tid = str(t["task_id"])
        seen.add(tid)
        tasks.append(_task_row(t, tid, True, backups, registry, up_by, ev_by, last, scan, reviewed_rule, val_rule,
                               events_per_task, media))
    for tid, b in backups.items():                  # CVAT에서 지워졌지만 백업이 남은 TASK
        if tid and tid not in seen and b.get("task_name"):
            seen.add(tid)
            t = {"task_id": tid, "name": b.get("task_name", ""), "status": "", "media": "", "frames": "",
                 "updated": b.get("task_updated", ""), "updated_utc": b.get("task_updated", "")}
            tasks.append(_task_row(t, tid, False, backups, registry, up_by, ev_by, last, scan, reviewed_rule,
                                   val_rule, events_per_task, media))
    gone = gone_tasks(base)                         # v4.31.8: 수집기가 'CVAT에서 사라짐'으로 본 TASK (백업이 없어도 기록에 남김)
    for tid, g in gone.items():
        if tid not in seen and g.get("name"):
            seen.add(tid)
            t = {"task_id": tid, "name": g["name"], "status": "", "media": "", "frames": "", "updated": "", "updated_utc": ""}
            row = _task_row(t, tid, False, backups, registry, up_by, ev_by, last, scan, reviewed_rule, val_rule, events_per_task, media)
            row["stage"] = "CVAT에서 사라짐"
            tasks.append(row)
    rep = {str(k): str(v) for k, v in (replaced or {}).items()}
    for row in tasks:
        k = str(row["id"])
        if k in gone and not row.get("in_cvat"):
            row["gone_at"] = gone[k]["gone_at"]
        if k in rep:
            row["replaced_by"] = rep[k]                # ULD가 같은 구간을 새 TASK로 바꿈 → 새 TASK 번호
        olds = sorted(o for o, n in rep.items() if n == k)
        if olds:
            row["replaces"] = olds
    stats = stats or {}
    keep = ("frames", "labeled", "zero", "by_label", "mean", "total", "total_mean", "total_max", "max_frame", "max_idx", "cv", "occluded",
            "src", "stale", "file", "error")
    corr = corrections or {}
    for r in tasks:
        r["pending"] = p_by.get(str(r["id"])) or None
        r["backups"] = bk_hist.get(str(r["id"]), [])
        r["compares"] = cmp_hist.get(str(r["id"]), [])
        r["labelings"] = lab_hist.get(str(r["id"]), [])
        c = (corr.get("by_task") or {}).get(str(r["id"]))
        r["correction"] = ({k: c.get(k) for k in ("model", "method", "uploaded", "status", "export", "total")} if c else None)
    for r in tasks:
        s = stats.get(str(r["id"]))
        r["stats"] = {k: s[k] for k in keep if k in s} if s else None
    peer_outliers(tasks)
    jobs = _train_jobs(activity)
    run_dirs = {os.path.basename(d): d for d in glob.glob(str(base / "runs" / "*")) if os.path.isdir(d)}
    for k in (files or {}):                       # v4.24.8: Kaggle은 Drive 목록에만 있는 학습도 (다른 세션·컴퓨터가 학습)
        if k.startswith("runs/") and k.count("/") >= 2:
            n = k.split("/")[1]
            run_dirs.setdefault(n, str(base / "runs" / n))
    models = [model_info(base, d, ledger, jobs, uploads) for n, d in sorted(run_dirs.items()) if not n.startswith((".", "_"))]
    for m in models:                              # 가중치가 이 컴퓨터에 없으면 Drive 목록의 크기·시각
        f = (files or {}).get(f"runs/{m['name']}/weights/best.pt")
        if f and m["weights_mb"] is None:
            m["weights_mb"], m["weights_time"] = round(f[0] / 2**20, 1), _iso(f[1])
    models.sort(key=lambda m: m["weights_time"] or "", reverse=True)
    for m in models:                              # v4.27: 검토 수정량
        m["corrections"] = (corr.get("by_model") or {}).get(m["name"])
    if hasattr(ctt, "model_inventory"):           # v4.24.8: 크기·데이터셋을 함께 쓰는 학습·자동 라벨에 쓴 기록·보관 (모델 정리)
        try:
            inv = {r["name"]: r for r in ctt.model_inventory(base, files=files)}
            for m in models:
                r = inv.get(m["name"])
                if r:
                    m["cleanup"] = {k: r[k] for k in ("status", "archived", "best_mb", "last_mb", "other_pt_mb", "dataset_mb",
                                                      "dataset_users", "used_uploads", "used_jobs", "used_last", "slim_mb",
                                                      "archive_mb", "last_cleanup", "done", "running")}
        except Exception as e:
            log(f"(모델 크기 읽기 실패: {e})")
    st = {
        "version": 1, "app_version": app_version, "generated": _now(), "by": operator, "server": server,
        "rules": {"reviewed": reviewed_rule, "val": val_rule}, "stages": STAGES,
        "scope": ({k: scope.get(k) for k in ("org", "org_name", "project_id", "project_name")} if scope else None),
        "orgs": (catalog or {}).get("orgs") if catalog else None, "projects": (catalog or {}).get("projects") if catalog else None,
        "kinds": {k: {"label": v[0], "cell": v[1]} for k, v in KINDS.items()},
        "tasks": tasks, "models": models,
        "pending": p_open, "modes": MODES,
        "summary": {"tasks": len(tasks), "in_cvat": sum(t["in_cvat"] for t in tasks),
                    "by_stage": dict(Counter(t["stage"] for t in tasks)),
                    "reviewed": sum(t["reviewed"] for t in tasks),
                    "by_role": dict(Counter(t["role"] for t in tasks if t["reviewed"])),
                    "changed_after_train": sum(1 for t in tasks if t["train"].get("change") == "🔁 라벨 바뀜"),
                    "models": len(models), "models_done": sum(m["done"] for m in models),
                    "prep": dict(Counter(("준비됨" if t["ready"] else "+".join(t["need"]) or "?") for t in tasks if t["reviewed"])),
                    "stats": sum(1 for t in tasks if t.get("stats")), "outliers": sum(1 for t in tasks if (t.get("peer") or {}).get("flags")),
                    "backup_stale": sum(1 for t in tasks if t["reviewed"] and t["backup"].get("fresh") != "최신"),
                    "corrections": dict(Counter(r["status"] for r in (corr.get("by_task") or {}).values()))},
        "corrections_other": {k: v for k, v in (corr.get("by_model") or {}).items() if k not in run_dirs},
        "snapshots": [{k: m.get(k) for k in ("folder", "train_name", "created", "summary", "by_label", "error")}
                      | {"n": len(m.get("tasks") or []),
                         "tasks": [{"task_id": x.get("task_id"), "task_name": x.get("task_name"), "frames": x.get("frames"),
                                    "total": x.get("total"), "by_label": x.get("by_label"),
                                    "vs_export": {"state": (x.get("vs_export") or {}).get("state", x.get("error", "")),
                                                  "diff": (x.get("vs_export") or {}).get("diff", {}), "folder": (x.get("vs_export") or {}).get("folder", "")},
                                    "vs_backup": {"state": (x.get("vs_backup") or {}).get("state", "")},
                                    "vs_train": {"state": (x.get("vs_train") or {}).get("state", ""), "model": (x.get("vs_train") or {}).get("model", "")}}
                                   for x in (m.get("tasks") or [])]}
                      for m in (snaps or [])],
        "export_folders": sorted({r["folder"] for r in scan if not r.get("error")}),
        "media": {"videos": len(media["videos"]), "backups": len(media["backups"])},
    }
    if log:
        log(f"상태 파일: TASK {len(tasks)}개 · 모델 {len(models)}개 ({time.time() - t0:.0f}초)")
    return st


def _task_row(t, tid, in_cvat, backups, registry, up_by, ev_by, last, scan, reviewed_rule, val_rule, n_ev, media=None):
    name = t.get("name", "")
    f = ctt.parse_task_name(name) or {}
    reviewed = ctt.is_reviewed(name, reviewed_rule)
    ups = up_by.get(tid, [])
    reg = registry.get(tid, [])
    auto = bool(ups) or "aa" in (f.get("tag") or "").lower() or any(r.get("action") in ("upload", "auto") for r in reg)
    b = backups.get(tid) or {}
    ex, ex_state = ctt.best_export(scan, tid, t.get("updated_utc")) if scan else (None, "없음")
    exi, exi_state = ctt.best_export(scan, tid, t.get("updated_utc"), kind="images") if scan else (None, "없음")
    media = media or {}
    base_name = ctt.base_name(name) if name else ""
    stems = {x for x in (base_name.lower(), (media.get("task_video") or {}).get(tid, "")) if x}
    if exi and exi.get("images"):
        img = "zip"
    elif stems & media.get("videos", set()):
        img = "video"
    elif base_name in media.get("backups", set()) or (backups.get(tid) or {}).get("last_file"):
        img = "backup"
    elif media.get("uld", {}).get(tid):
        img = "uld"                                # v4.31.6: ULD clip에서 사진을 다시 뽑을 수 있음 → 백업 필요 없음
    else:
        img = "none"
    lt = last.get(tid)
    row = {
        "id": int(tid) if tid.isdigit() else tid, "name": name, "in_cvat": in_cvat,
        "org": t.get("org") if in_cvat else None, "cvat_project_id": (t.get("project") or 0) if in_cvat and "org" in t else None,
        "cvat_project": t.get("project_name", "") if in_cvat else "",
        "project": f.get("project", ""), "gh": f.get("gh", ""), "date": f.get("date", ""), "row": f.get("row", ""), "plant": f.get("plant", ""),
        "state": f.get("state", ""), "tag": f.get("tag", ""), "rule_ok": bool(f),
        "frames": t.get("frames", ""), "cvat_status": t.get("status", ""), "updated": t.get("updated_iso") or t.get("updated", ""),
        "reviewed": reviewed, "role": (ctt.split_role(name, val_rule) or "무작위") if reviewed else "",
        "origin": "auto" if auto else "manual",
        "backup": {"state": b.get("backup_state", "") or ("없음" if in_cvat else ""), "last": b.get("last_backup", ""),
                   "fresh": _backup_fresh(b, t.get("updated_utc")),
                   "kind": b.get("last_kind", ""), "mb": b.get("size_mb", ""), "reviewer": b.get("reviewer", ""),
                   "n": {k: int(b.get(f"n_{k}") or 0) for k in ("original", "work", "revised")},
                   "can_delete": (str(b.get("can_delete", "")).lower() in ("true", "1", "예")) and (exi_state == "최신")},
        "export": {"state": ex_state, "folder": ex["folder"] if ex else "",
                   "updated": str(ex.get("updated", "")) if ex else ""},
        "export_img": {"state": exi_state, "folder": exi["folder"] if exi else "",
                       "zip": exi["file"] if exi else "", "images": bool(exi and exi.get("images"))},
        "img": img,
        "uld": media.get("uld", {}).get(tid, ""),   # v4.31.6: 'images' = ULD 사진 TASK · 'video' = ULD 영상 TASK · '' = ULD 아님
        "train": ({"model": lt.get("model", ""), "role": lt.get("role", ""), "label_updated": lt.get("label_updated", ""),
                   "change": ctt.train_change(t.get("updated_utc"), lt)} if lt
                  else {"change": "🆕 학습 안 함" if reviewed else ""}),
        "uploads": len(ups),
        "last_upload": ({k: ups[-1].get(k, "") for k in ("start", "method", "model", "status", "after_total")} if ups else {}),
        "events": [{k: e.get(k, "") for k in ("time", "action", "status", "who", "model", "boxes", "summary")}
                   for e in ev_by.get(tid, [])[-n_ev:]],
    }
    for e in row["events"]:
        e["summary"] = (e.get("summary") or "")[:160]
    row["stage"] = stage_of(row) if in_cvat else "CVAT에 없음 (백업만)"
    # 학습 준비: CVAT for images export가 최신이고, 이미지를 얻을 곳(zip 안·영상·백업)이 있으면 준비됨
    row["need"] = [x for x, bad in (("export", exi_state != "최신"), ("backup", img == "none")) if bad] if reviewed else []
    row["ready"] = bool(reviewed and in_cvat and not row["need"])
    return row


def _backup_fresh(b, cvat_updated):
    """마지막 백업이 지금 CVAT 라벨을 담고 있나: '최신' / '백업 뒤 바뀜' / '없음' (백업 때의 TASK 수정 시각과 비교)"""
    if not b or not b.get("last_backup"):
        return "없음"
    bu, cu = ctt._to_utc(b.get("task_updated")), ctt._to_utc(cvat_updated)
    if bu is None or cu is None:
        return "최신"
    return "최신" if bu.replace(microsecond=0) >= cu.replace(microsecond=0) else "백업 뒤 바뀜"


def write_state(base, state):
    d = Path(base) / "web"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p


# ======================= 라벨 통계 (v4.16): 프레임별 · 클래스별 박스 수 =======================
STATS_CACHE = "web/label_stats.json"


def frame_stats(ann):
    """프레임별 박스로 펼친 라벨(ctt.load_annotations 형식) → 통계.
    frames: TASK 프레임 수 · labeled: 박스가 있는 프레임 · zero: 박스가 없는 프레임 · by_label: 라벨별 박스 합 ·
    mean: 라벨별 프레임당 평균 · total_mean·total_max: 모든 라벨 합의 프레임당 평균·최대 · cv: 프레임 사이 변동계수 ·
    occluded: 가림 박스 수 · objects: track + 단독 박스 ·
    max_frame: 박스가 가장 많은 프레임의 원본 번호 · max_idx: 그 프레임의 TASK 순번(0부터, CVAT 화면의 프레임 번호)"""
    frames = list(ann.get("frames") or sorted(ann.get("boxes", {})))
    boxes = ann.get("boxes", {})
    n = len(frames) or 1
    per_label, totals, occ = Counter(), [], 0
    for f in frames:
        bl = boxes.get(f, [])
        totals.append(len(bl))
        for b in bl:
            per_label[b[1]] += 1
            occ += bool(b[2])
    mx = max(totals or [0])
    k = totals.index(mx) if totals and mx else None
    mean_t = sum(totals) / n
    var = sum((x - mean_t) ** 2 for x in totals) / n
    return {"frames": len(frames), "labeled": sum(1 for x in totals if x), "zero": sum(1 for x in totals if not x),
            "by_label": dict(per_label), "mean": {k: round(v / n, 3) for k, v in per_label.items()},
            "total": sum(totals), "total_mean": round(mean_t, 3), "total_max": max(totals or [0]),
            "cv": round((var ** 0.5) / mean_t, 3) if mean_t else None, "occluded": occ,
            "max_frame": frames[k] if k is not None else None, "max_idx": k,
            "objects": len(ann.get("tracks", {})) + int(ann.get("shapes", 0) or 0)}


def stats_from_zip(path):
    return frame_stats(ctt.load_annotations(path))


def stats_from_cvat(task):
    """CVAT의 지금 라벨(API)로 같은 통계 — export가 없거나 export 뒤에 바뀐 TASK용"""
    names = {l.id: l.name for l in task.get_labels()}
    ann = task.get_annotations()
    size = int(getattr(task, "size", 0) or 0)
    start, step = ctt.task_frame_map(task.get_meta())
    used = [s.frame for s in ann.shapes] + [s.frame for t in ann.tracks for s in t.shapes]
    absf = [start + k * step for k in range(size)]
    frames = absf if (used and set(used) <= set(absf) and (start or step > 1)) else list(range(size))
    boxes, tracks, n_shapes = {}, {}, 0
    for s in ann.shapes:
        if str(getattr(s, "type", "rectangle")).endswith("rectangle"):
            n_shapes += 1
            boxes.setdefault(s.frame, []).append((f"s{n_shapes}", names.get(s.label_id, "?"), bool(s.occluded), None, True))
    for tr in ann.tracks:
        lab = names.get(tr.label_id, "?")
        tracks[tr.id] = lab
        kf = sorted(tr.shapes, key=lambda s: s.frame)
        for i, s in enumerate(kf):
            if s.outside:
                continue
            nxt = kf[i + 1].frame if i + 1 < len(kf) else None
            for g in frames:
                if g >= s.frame and (nxt is None or g < nxt):
                    boxes.setdefault(g, []).append((tr.id, lab, bool(s.occluded), None, g == s.frame))
    return frame_stats({"frames": frames, "boxes": boxes, "tracks": tracks, "shapes": n_shapes})


def _wants_stats(name):
    """통계 대상: 이름이 uld로 끝나지 않는 TASK (검토 완료·검토 중·자동 라벨 올린 것)"""
    return not (name or "").lower().endswith("uld")


def compute_stats(base, cvat_tasks, scan=None, client=None, cvat_max=40, log=print):
    """TASK별 라벨 통계. 최신 export zip이 있으면 그것으로(빠름, 캐시), 없거나 export 뒤에 바뀌었으면 CVAT에서(cvat_max개까지).
    캐시: web/label_stats.json — 같은 파일·같은 CVAT 수정 시각이면 다시 세지 않음. 반환 {task_id: {...통계, src, key, stale}}"""
    base = Path(base)
    cp = base / STATS_CACHE
    try:
        cache = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    except Exception:
        cache = {}
    if scan is None:
        scan = ctt.scan_exports(base / "exports", names=[t["name"] for t in cvat_tasks], log=None) if (base / "exports").exists() else []
    out, n_zip, n_cvat, n_hit, skipped = {}, 0, 0, 0, 0
    for t in cvat_tasks:
        if not _wants_stats(t["name"]):
            continue
        tid = str(t["task_id"])
        ex, st = ctt.best_export(scan, tid, t.get("updated_utc"))
        c = cache.get(tid)
        if ex and st == "최신":
            zp = Path(ex["zip"])
            key = f"zip:{zp.parent.name}/{zp.name}:{zp.stat().st_size}" if zp.exists() else ""
            if c and c.get("key") == key and "max_idx" in c:
                out[tid] = c; n_hit += 1; continue
            try:
                s = stats_from_zip(zp)
                out[tid] = {**s, "src": "export", "key": key, "file": f"{zp.parent.name}/{zp.name}", "stale": False}
                n_zip += 1
            except Exception as e:
                out[tid] = {"error": f"{type(e).__name__}: {e}"[:200], "src": "export", "key": key}
            continue
        key = f"cvat:{t.get('updated_utc')}"
        if c and c.get("key") == key and "max_idx" in c:
            out[tid] = c; n_hit += 1; continue
        if client is not None and n_cvat < cvat_max:
            try:
                s = stats_from_cvat(client.tasks.retrieve(int(tid)))
                out[tid] = {**s, "src": "cvat", "key": key, "file": "", "stale": False}
                n_cvat += 1
                continue
            except Exception as e:
                out[tid] = {"error": f"CVAT: {ctt.api_error(e) if hasattr(ctt, 'api_error') else e}"[:200], "src": "cvat", "key": ""}
                continue
        if ex:                                         # export가 오래됨(수정됨) → 그 export로 세되 '오래됨' 표시
            try:
                zp = Path(ex["zip"])
                out[tid] = {**stats_from_zip(zp), "src": "export", "key": "", "file": f"{zp.parent.name}/{zp.name}", "stale": True}
            except Exception:
                skipped += 1
        else:
            skipped += 1
    cache.update({k: v for k, v in out.items() if v.get("key")})
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, cp)
    if log:
        log(f"라벨 통계: export로 {n_zip}개 · CVAT로 {n_cvat}개 · 저장된 것 {n_hit}개 · 아직 못 셈 {skipped}개"
            + (f" (CVAT로 셀 수 있는 수 {cvat_max}개를 다 씀 → 28번 셀을 한 번 더 실행)" if n_cvat >= cvat_max else ""))
    return out


def peer_outliers(rows, min_group=4, z_cut=3.5, ratio_cut=0.35):
    """같은 온실·촬영일 TASK끼리 프레임당 박스 수 비교 (중앙값·MAD 기준 robust z). rows: state의 task dict(stats 포함).
    각 row에 'peer' = {group, n, median, ratio, z, flags} 를 넣음. flags 예: '전체 적음 (0.42×)', 'healthy_fruit 많음 (2.3×)'"""
    groups = defaultdict(list)
    for r in rows:
        s = r.get("stats") or {}
        if s.get("frames") and r.get("gh") and r.get("date"):
            groups[(r["gh"], r["date"])].append(r)

    def robust(vals, x):
        srt = sorted(vals)
        m = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
        dev = sorted(abs(v - m) for v in vals)
        mad = dev[len(dev) // 2] if len(dev) % 2 else (dev[len(dev) // 2 - 1] + dev[len(dev) // 2]) / 2
        z = 0.6745 * (x - m) / mad if mad else (0.0 if x == m else float("inf") if x > m else float("-inf"))
        return m, z

    for (gh, date), g in groups.items():
        labels = sorted({k for r in g for k in (r["stats"].get("mean") or {})})
        for r in g:
            s = r["stats"]
            peer = {"group": f"{gh}·{date}", "n": len(g), "flags": []}
            if len(g) >= min_group:
                others = [o["stats"]["total_mean"] for o in g]
                m, z = robust(others, s["total_mean"])
                peer.update(median=round(m, 2), ratio=round(s["total_mean"] / m, 2) if m else None, z=round(z, 1) if abs(z) != float("inf") else None)
                if abs(z) >= z_cut and m and abs(s["total_mean"] / m - 1) >= ratio_cut:
                    peer["flags"].append(f"전체 {'많음' if z > 0 else '적음'} ({s['total_mean'] / m:.2f}×)")
                for lab in labels:
                    vals = [(o["stats"].get("mean") or {}).get(lab, 0.0) for o in g]
                    x = (s.get("mean") or {}).get(lab, 0.0)
                    lm, lz = robust(vals, x)
                    if lm >= 0.3 and abs(lz) >= z_cut and abs(x / lm - 1) >= ratio_cut:
                        peer["flags"].append(f"{lab} {'많음' if lz > 0 else '적음'} ({x / lm:.2f}×)")
            r["peer"] = peer
    return rows


# ======================= 학습 스냅숏 (v4.16): exports/_train_<학습 이름>/ + _manifest.json =======================
SNAP_PREFIX = "_train_"


def snapshot_folder(train_name):
    return SNAP_PREFIX + re.sub(r"[^\w.-]+", "_", train_name or "").strip("_")


def _diff_labels(a, b):
    keys = sorted(set(a or {}) | set(b or {}))
    return {k: int((b or {}).get(k, 0)) - int((a or {}).get(k, 0)) for k in keys if int((b or {}).get(k, 0)) != int((a or {}).get(k, 0))}


def write_snapshot_manifest(base, folder, log=print):
    """학습 스냅숏 폴더의 TASK마다: 스냅숏 라벨(시각·클래스별 박스 수)과
    ① 가장 최근 정기 export(스냅숏 폴더 밖) ② 마지막 TASK 백업 ③ 마지막 학습(TASK 학습 대장)을 비교해 _manifest.json·.csv로"""
    base = Path(base)
    d = base / "exports" / folder
    zips = sorted(d.glob("*.zip"))
    names = [ctt.read_export_info(z).get("name", "") for z in zips]
    scan = [r for r in ctt.scan_exports(base / "exports", names=names, log=None)
            if not r["folder"].startswith(SNAP_PREFIX) and not r.get("error")]
    backups = {str(r.get("task_id")): r for r in _read_csv(base / "backup_status.csv")}
    last = ctt.last_trained(base) if hasattr(ctt, "last_trained") else {}
    rows = []
    for z in zips:
        info = ctt.read_export_info(z)
        tid = str(info.get("task_id", ""))
        try:
            s = stats_from_zip(z)
        except Exception as e:
            rows.append({"task_id": tid, "task_name": info.get("name", ""), "file": z.name, "error": str(e)[:200]})
            continue
        cu = ctt._to_utc(info.get("updated"))
        # ① 정기 export
        prev = [r for r in scan if str(r["task_id"]) == tid]
        prev.sort(key=lambda r: (ctt._to_utc(r["updated"]) or ctt._to_utc(r["mtime"]), r["mtime"]))
        if not prev:
            vs_ex = {"state": "정기 export 없음"}
        else:
            p = prev[-1]
            try:
                ps = stats_from_zip(p["zip"])
                diff = _diff_labels(ps["by_label"], s["by_label"])
            except Exception:
                ps, diff = {}, None
            same_t = (ctt._to_utc(p["updated"]) or 0) == (cu or 1)
            vs_ex = {"folder": p["folder"], "updated": str(p.get("updated", "")),
                     "state": ("같음" if same_t and not diff else "박스 바뀜" if diff else "시각만 바뀜" if diff == {} else "비교 못 함"),
                     "diff": diff or {}}
        # ② 백업
        b = backups.get(tid) or {}
        if not b.get("last_backup"):
            vs_bk = {"state": "백업 없음"}
        else:
            bu = ctt._to_utc(b.get("task_updated"))
            vs_bk = {"last": b.get("last_backup", ""), "file": b.get("last_file", ""),
                     "state": "같음" if (bu and cu and bu.replace(microsecond=0) >= cu.replace(microsecond=0)) else "백업 뒤 바뀜"}
        # ③ 마지막 학습
        lt = last.get(tid)
        if not lt:
            vs_tr = {"state": "학습 안 함"}
        else:
            lu = ctt._to_utc(lt.get("label_updated"))
            vs_tr = {"model": lt.get("model", ""), "role": lt.get("role", ""),
                     "state": "같음" if (lu and cu and lu.replace(microsecond=0) >= cu.replace(microsecond=0)) else "학습 뒤 바뀜"}
        rows.append({"task_id": tid, "task_name": info.get("name", ""), "file": z.name, "cvat_updated": str(info.get("updated", "")),
                     "images": bool(info.get("images")), "frames": s["frames"], "by_label": s["by_label"], "total": s["total"],
                     "total_mean": s["total_mean"], "vs_export": vs_ex, "vs_backup": vs_bk, "vs_train": vs_tr})
    summ = {k: dict(Counter((r.get(k) or {}).get("state", "오류") for r in rows)) for k in ("vs_export", "vs_backup", "vs_train")}
    man = {"folder": folder, "train_name": folder[len(SNAP_PREFIX):] if folder.startswith(SNAP_PREFIX) else folder,
           "created": _now(), "tasks": rows, "summary": summ,
           "by_label": dict(sum((Counter(r.get("by_label") or {}) for r in rows), Counter()))}
    (d / "_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(d / "_manifest.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "task_name", "frames", "boxes", "by_label", "cvat_updated", "정기 export와", "박스 변화", "백업과", "마지막 학습과"])
        for r in rows:
            w.writerow([r.get("task_id"), r.get("task_name"), r.get("frames", ""), r.get("total", ""),
                        json.dumps(r.get("by_label", {}), ensure_ascii=False), r.get("cvat_updated", ""),
                        (r.get("vs_export") or {}).get("state", r.get("error", "")),
                        json.dumps((r.get("vs_export") or {}).get("diff", {}), ensure_ascii=False),
                        (r.get("vs_backup") or {}).get("state", ""), (r.get("vs_train") or {}).get("state", "")])
    if log:
        log(f"스냅숏 매니페스트: {folder} · TASK {len(rows)}개 · 정기 export와 {summ['vs_export']} · 백업과 {summ['vs_backup']} · 학습과 {summ['vs_train']}")
    return man


def snapshots(base, refresh=True, log=None):
    """exports/_train_*/ 목록과 매니페스트 (매니페스트가 zip보다 오래됐으면 다시 만듦)"""
    out = []
    for d in sorted((Path(base) / "exports").glob(SNAP_PREFIX + "*")):
        if not d.is_dir():
            continue
        mp = d / "_manifest.json"
        newest = max([z.stat().st_mtime for z in d.glob("*.zip")] or [0])
        try:
            if refresh and (not mp.exists() or mp.stat().st_mtime < newest):
                man = write_snapshot_manifest(base, d.name, log=log)
            else:
                man = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
        except Exception as e:
            man = {"folder": d.name, "error": str(e)[:200], "tasks": []}
        if man:
            out.append(man)
    return out


# ======================= LC 작업자 (31번 셀) — v4.26.0 =======================
# web/worker.json: 31번 셀 LC 작업자의 심장 박동 (누가·어디서·지금 하는 일). 한 번에 한 작업자만 요청을 받음.
# 요청 확인(사람이 결과를 봤음)은 웹 화면이 requests/acks/ACK_<요청 id>__<시각>.json으로 남김 — 작업자는 읽지 않음.
WORKER_STALE_SEC = 180
LC_WORKER_FILE = "web/worker.json"


def _lc_worker_file(slot=""):
    """v4.31.7: slot = '' (Colab·Kaggle 30번 셀) · '_gpu' (Kaggle GPU 워커) — 작업자마다 따로 기록"""
    return LC_WORKER_FILE.replace(".json", f"{slot}.json") if slot else LC_WORKER_FILE


def lc_worker_read(base, slot=""):
    p = Path(base) / _lc_worker_file(slot)
    try:
        w = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        hb = datetime.datetime.fromisoformat(w["heartbeat"])
        w["age_sec"] = (datetime.datetime.now(datetime.timezone.utc) - hb).total_seconds()
    except Exception:
        w["age_sec"] = 1e9
    return w


def lc_worker_beat(base, who, session, host, busy=None, started=None, stopping=False, slot=""):
    p = Path(base) / _lc_worker_file(slot)
    p.parent.mkdir(parents=True, exist_ok=True)
    w = {"who": who, "session": session, "host": host, "heartbeat": _now(), "busy": busy, "started": started,
         "stopping": stopping, "version": __version__, "app": "LC"}
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading_ident()}.tmp")    # 심장 박동 스레드와 겹치지 않게
    tmp.write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return w


def threading_ident():
    import threading
    return threading.get_ident()


def lc_worker_acquire(base, who, session, takeover=False, stale_sec=WORKER_STALE_SEC, slot=""):
    """다른 세션의 LC 작업자가 살아 있으면 멈춤 (요청을 두 곳에서 처리하지 않게)"""
    w = lc_worker_read(base, slot)
    if w and w.get("session") != session and w["age_sec"] < stale_sec and not w.get("stopping") and not takeover:
        raise SystemExit(f"⛔ 다른 LC 작업자가 켜져 있습니다: {w.get('who')} · {w.get('host')} · {w['age_sec']:.0f}초 전 "
                         "→ 그 세션을 멈추거나 LC_TAKEOVER = True")
    return w


def ack_dir(base):
    return Path(base) / "requests" / "acks"


def list_acks(base):
    """요청 확인 기록 {요청 id: [{who, time, app, note}, …]} (웹 화면이 남김)"""
    out = defaultdict(list)
    d = ack_dir(base)
    for p in sorted(d.glob("ACK_*.json")) if d.exists() else []:
        try:
            a = json.loads(p.read_text(encoding="utf-8") or "{}")
        except Exception:
            continue
        rid = a.get("rid") or p.name[4:].split("__")[0]
        out[rid].append(a)
    return dict(out)


# ======================= 검토 수정량 (v4.27.0): 자동 라벨 업로드 직후 ↔ 검토 뒤 export =======================
# 자동 라벨을 올린 직후 CVAT 라벨(업로드 기록 after_file, 없으면 올린 track XML)과 검토가 끝난 뒤의 export를 프레임·라벨별로 맞춰,
# 검토자가 그대로 둔 박스 · 고친 박스(위치·크기) · 라벨을 바꾼 박스 · 지운 박스(오탐) · 추가한 박스(놓침)를 셈.
# 모델(학습 이름)별로 모아 웹 '학습' 탭에 보여 줌. 캐시: web/corrections.json (같은 두 파일이면 다시 세지 않음)
CORR_CACHE = "web/corrections.json"
CORR_KEYS = ("auto", "reviewed", "kept", "occl", "fixed", "relabeled", "deleted", "added")


def _local_utc(v):
    """ctt.now() 형식(Asia/Seoul, 시간대 표시 없음) → UTC. 시간대가 붙어 있으면 그대로"""
    d = ctt._to_utc(v)
    if d is None:
        return None
    s = str(v)
    if "+" in s[10:] or s.endswith("Z") or "-" in s[19:]:
        return d
    try:
        from zoneinfo import ZoneInfo
        return d.replace(tzinfo=ZoneInfo(getattr(ctt, "TZ", "Asia/Seoul"))).astimezone(datetime.timezone.utc)
    except Exception:
        return d


def _norm_frames(ann):
    """원본 영상 프레임 번호(start + k*step) → TASK 순번 k. 두 파일의 형식(video·images)이 달라도 같은 프레임끼리 맞추려고"""
    m = ann.get("meta") or {}
    s, st = int(m.get("start") or 0), int(m.get("step") or 1)
    fs = set(ann.get("boxes") or {})
    if (s or st > 1) and fs and all(f >= s and (f - s) % st == 0 for f in fs):
        return {**ann, "boxes": {(f - s) // st: v for f, v in ann["boxes"].items()}}
    return ann


def corr_rate(t):
    """수정률 = (고침 + 라벨 바꿈 + 지움 + 추가) / (그대로 + 고침 + 라벨 바꿈 + 지움 + 추가)"""
    ch = t.get("fixed", 0) + t.get("relabeled", 0) + t.get("deleted", 0) + t.get("added", 0)
    n = ch + t.get("kept", 0)
    return round(ch / n, 4) if n else None


def _match_corr(a, b, same_iou=0.95, near_iou=0.5):
    """프레임마다 자동 박스(a) ↔ 검토 뒤 박스(b) 맞추기 → 라벨별 수
    그대로 = 같은 라벨 IoU ≥ same_iou · 고침 = 같은 라벨 near_iou ≤ IoU < same_iou ·
    라벨 바꿈 = 다른 라벨 IoU ≥ near_iou (위치를 조금 고친 것도) · 지움 = 자동에만 · 추가 = 검토 뒤에만.
    라벨은 자동 박스 기준 (추가는 검토 뒤 라벨)"""
    per = defaultdict(lambda: {k: 0 for k in CORR_KEYS})
    for f in set(a["boxes"]) | set(b["boxes"]):
        A, Bx = list(a["boxes"].get(f, [])), list(b["boxes"].get(f, []))
        for x in A:
            per[x[1]]["auto"] += 1
        for y in Bx:
            per[y[1]]["reviewed"] += 1
        pairs = sorted(((ctt._iou(x[3], y[3]), x[1] == y[1], i, j) for i, x in enumerate(A) for j, y in enumerate(Bx)),
                       key=lambda p: (p[1], p[0]), reverse=True)     # 같은 라벨 먼저, 많이 겹치는 것 먼저
        ua, ub = set(), set()
        for v, same, i, j in pairs:
            if v < near_iou:
                continue
            if i in ua or j in ub:
                continue
            ua.add(i); ub.add(j)
            d = per[A[i][1]]
            if not same:
                d["relabeled"] += 1
            elif v >= same_iou:
                d["kept"] += 1
                if A[i][2] != Bx[j][2]:
                    d["occl"] += 1
            else:
                d["fixed"] += 1
        for i, x in enumerate(A):
            if i not in ua:
                per[x[1]]["deleted"] += 1
        for j, y in enumerate(Bx):
            if j not in ub:
                per[y[1]]["added"] += 1
    return dict(per)


def correction_counts(auto_path, reviewed_path):
    """자동 라벨(업로드 직후) 파일과 검토 뒤 파일 → {'total': {...}, 'by_label': {라벨: {...}}, 'auto_tracks', 'reviewed_tracks'}"""
    a = _norm_frames(ctt.load_annotations(auto_path))
    b = _norm_frames(ctt.load_annotations(reviewed_path))
    per = _match_corr(a, b)
    total = {k: sum(d[k] for d in per.values()) for k in CORR_KEYS}
    return {"total": {**total, "rate": corr_rate(total)}, "by_label": per,
            "auto_tracks": len(a.get("tracks") or {}), "reviewed_tracks": len(b.get("tracks") or {})}


def _upload_model(label, names):
    """업로드 기록의 모델 표시('<학습 이름>/best.pt (11-02 09:00)') → 학습 이름"""
    s = str(label or "").strip()
    m = re.match(r"^([^/\s]+)/(best|last)\.pt\b", s)
    if m:
        return m.group(1)
    for n in sorted(names, key=len, reverse=True):
        if re.search(r"(^|[^\w.-])" + re.escape(n) + r"([^\w.-]|$)", s):
            return n
    return s.split(" ")[0] if s else "(모델 기록 없음)"


def compute_corrections(base, cvat_tasks, model_names=(), reviewed_rule="vf", scan=None, fetch=None, log=print, max_new=200):
    """TASK마다 마지막 자동 라벨 업로드(logs/uploads.csv)와 그 뒤 검토가 끝난 export를 비교.
    TASK 상태: '셈'(수정량을 셈) · '검토 전'(이름이 검토 완료가 아님) · 'export 필요'(검토 완료인데 업로드 뒤의 최신 export가 없음) ·
    '파일 없음'(업로드 직후 기록 파일이 없음) · '오류'. fetch(상대 경로 목록) = Kaggle에서 Drive 파일을 받는 함수.
    반환 {'by_task': {task_id: {...}}, 'by_model': {학습 이름: {...}}}"""
    base = Path(base)
    cp = base / CORR_CACHE
    try:
        cache = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    except Exception:
        cache = {}
    live = {str(t["task_id"]): t for t in cvat_tasks}
    if scan is None:
        scan = ctt.scan_exports(base / "exports", names=[t["name"] for t in cvat_tasks], log=None) if (base / "exports").exists() else []
    last_up = {}
    for u in _read_csv(base / "logs" / "uploads.csv"):
        st = str(u.get("status") or "")
        src = u.get("after_file") or (u.get("result_file") if str(u.get("result_file") or "").endswith(".xml") else "")
        if not src or "오류" in st or "실패" in st or str(u.get("uploaded", "")).lower() in ("false", "0"):
            continue
        tid = str(u.get("task_id") or "")
        if tid and (tid not in last_up or str(u.get("start") or "") >= str(last_up[tid].get("start") or "")):
            last_up[tid] = {**u, "_src": src}
    plan = []
    for tid, u in last_up.items():
        t = live.get(tid)
        row = {"model": _upload_model(u.get("model"), model_names), "model_label": u.get("model", ""), "method": u.get("method", ""),
               "uploaded": u.get("end") or u.get("start", ""), "src": u["_src"], "name": (t or {}).get("name") or u.get("task_name", "")}
        if t is None:
            row["status"] = "CVAT에 없음"
        elif not ctt.is_reviewed(t["name"], reviewed_rule):
            row["status"] = "검토 전"
        else:
            ex, est = ctt.best_export(scan, tid, t.get("updated_utc"))
            up_t, ex_t = _local_utc(row["uploaded"]), ctt._to_utc((ex or {}).get("updated")) or ctt._to_utc((ex or {}).get("mtime"))
            if not ex or est != "최신" or (up_t and ex_t and ex_t <= up_t):
                row["status"] = "export 필요"
            else:
                row.update(status="셈", export=f"{Path(ex['zip']).parent.name}/{Path(ex['zip']).name}", _zip=ex["zip"])
        plan.append((tid, row))
    if fetch:                                              # Kaggle: 셀 파일만 Drive에서
        need = []
        for tid, r in plan:
            if r["status"] == "셈":
                key = f"{r['src']}|{r['export']}"
                if (cache.get(tid) or {}).get("key") != key:
                    need += [r["src"], os.path.relpath(r["_zip"], base)]
        if need:
            try:
                fetch(sorted(set(need)))
            except Exception as e:
                log and log(f"(수정량: Drive에서 받기 실패 {e})")
    by_task, n_new, n_hit = {}, 0, 0
    for tid, r in plan:
        if r["status"] == "셈":
            key = f"{r['src']}|{r['export']}"
            c = cache.get(tid)
            if c and c.get("key") == key:
                r.update(total=c["total"], by_label=c["by_label"], tracks=c.get("tracks")); n_hit += 1
            elif n_new >= max_new:
                r["status"] = "다음에 셈"
            else:
                sp = base / r["src"]
                if not sp.exists() or not Path(r["_zip"]).exists():
                    r["status"] = "파일 없음"
                else:
                    try:
                        c = correction_counts(sp, r["_zip"])
                        r.update(total=c["total"], by_label=c["by_label"], tracks=[c["auto_tracks"], c["reviewed_tracks"]])
                        cache[tid] = {"key": key, "total": c["total"], "by_label": c["by_label"], "tracks": r["tracks"]}
                        n_new += 1
                    except Exception as e:
                        r.update(status="오류", error=f"{type(e).__name__}: {e}"[:200])
        r.pop("_zip", None)
        by_task[tid] = r
    by_model = {}
    for tid, r in by_task.items():
        m = by_model.setdefault(r["model"], {"tasks": 0, "measured": 0, "status": Counter(), "need_export": [],
                                             "total": {k: 0 for k in CORR_KEYS}, "by_label": {}, "by_method": {}, "list": []})
        m["tasks"] += 1
        m["status"][r["status"]] += 1
        if r["status"] == "export 필요":
            m["need_export"].append(int(tid) if tid.isdigit() else tid)
        if r["status"] != "셈":
            continue
        m["measured"] += 1
        for k in CORR_KEYS:
            m["total"][k] += r["total"].get(k, 0)
        mm = m["by_method"].setdefault(r["method"] or "?", {k: 0 for k in CORR_KEYS})
        for k in CORR_KEYS:
            mm[k] += r["total"].get(k, 0)
        for lab, v in r["by_label"].items():
            d = m["by_label"].setdefault(lab, {k: 0 for k in CORR_KEYS})
            for k in CORR_KEYS:
                d[k] += v.get(k, 0)
        m["list"].append({"id": int(tid) if tid.isdigit() else tid, "name": r["name"], "method": r["method"], "uploaded": r["uploaded"],
                          "export": r.get("export", ""), **{k: r["total"].get(k, 0) for k in CORR_KEYS}, "rate": r["total"].get("rate")})
    for m in by_model.values():
        m["status"] = dict(m["status"])
        m["rate"] = corr_rate(m["total"])
        for d in list(m["by_label"].values()) + list(m["by_method"].values()):
            d["rate"] = corr_rate(d)
        m["list"].sort(key=lambda x: (x["rate"] is None, -(x["rate"] or 0)))
        m["list"] = m["list"][:300]
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, cp)
    if log:
        cnt = Counter(r["status"] for r in by_task.values())
        log(f"검토 수정량: 자동 라벨을 올린 TASK {len(by_task)}개 · " + " · ".join(f"{k} {v}" for k, v in cnt.most_common())
            + f" (새로 셈 {n_new} · 저장된 것 {n_hit})" + (" → 28번 셀을 한 번 더 실행하면 나머지를 셈" if cnt.get("다음에 셈") else ""))
    return {"by_task": by_task, "by_model": by_model}


# ======================= TASK별 백업 기록 (v4.27.0) =======================
def backup_history(base, n=10):
    """backup_index.csv의 성공한 백업 → {task_id: [{time, kind, mb, name, task_updated, file}, …]} (오래된 것부터, TASK마다 최근 n개)"""
    out = defaultdict(list)
    for r in _read_csv(Path(base) / "backup_index.csv"):
        if r.get("result") != "성공":
            continue
        out[str(r.get("task_id"))].append({"time": r.get("run_time", ""), "kind": r.get("kind", ""), "mb": r.get("size_mb", ""),
                                           "name": r.get("task_name", ""), "task_updated": r.get("task_updated", ""),
                                           "file": r.get("file", ""), "server": r.get("server", "")})
    return {k: sorted(v, key=lambda x: x["time"])[-n:] for k, v in out.items()}


# ======================= 모델 비교 (v4.28.0) — 같은 TASK를 여러 모델로 탐지해 기준 라벨과 비교 (CVAT에 올리지 않음) =======================
# 기준 = 지금 CVAT 라벨 (검토 완료면 '검토 뒤 라벨' = 정답, 아니면 '검토 전 CVAT 라벨' = 일치도만).
# 비교 대상 = 고른 모델들(프레임마다 새로 탐지) + 이 TASK에 마지막으로 올린 자동 라벨(업로드 직후 기록, 검토 완료일 때).
# 기록: tasks/<ID>/compare_<시각>.json(전체) · logs/model_compare.csv(TASK × 대상 한 줄씩) → 웹 TASK 상세·재처리 앱 이력.
COMPARE_LOG = "logs/model_compare.csv"
COMPARE_COLUMNS = ["time", "task_id", "task_name", "ref_kind", "ref_file", "frames", "source", "kind", "model_label", "conf",
                   "auto", "ref_boxes", "tp", "fixed", "relabeled", "fp", "fn", "precision", "recall", "f1",
                   "who", "request", "detail"]


def last_upload(base, tid):
    """이 TASK의 마지막 자동 라벨 업로드(성공) 기록 + 업로드 직후 라벨 파일(after_file, 없으면 track XML) — 없으면 None"""
    best = None
    for u in _read_csv(Path(base) / "logs" / "uploads.csv"):
        if str(u.get("task_id")) != str(tid):
            continue
        st = str(u.get("status") or "")
        src = u.get("after_file") or (u.get("result_file") if str(u.get("result_file") or "").endswith(".xml") else "")
        if not src or "오류" in st or "실패" in st:
            continue
        if best is None or str(u.get("start") or "") >= str(best.get("start") or ""):
            best = {**u, "_src": src}
    return best


def _scores(per, labels=None):
    """_match_corr 결과(자동=a, 기준=b) → 평가 수치. 맞힘(tp) = 같은 라벨 IoU ≥ 0.5 (그대로 + 고침)"""
    keep = [k for k in per if labels is None or k in labels]
    t = {k: sum(per[l][k] for l in keep) for k in CORR_KEYS}
    tp = t["kept"] + t["fixed"]
    p = tp / t["auto"] if t["auto"] else None
    r = tp / t["reviewed"] if t["reviewed"] else None
    f1 = (2 * p * r / (p + r)) if p and r else (0.0 if (t["auto"] or t["reviewed"]) else None)
    return {"auto": t["auto"], "ref_boxes": t["reviewed"], "tp": tp, "fixed": t["fixed"], "relabeled": t["relabeled"],
            "fp": t["deleted"], "fn": t["added"], "precision": None if p is None else round(p, 3),
            "recall": None if r is None else round(r, 3), "f1": None if f1 is None else round(f1, 3)}


def yolo_predictor(model_path, imgsz=1920, conf=0.25, device=None):
    """ultralytics 모델 → fn(PIL 이미지, 원본 W, H) = [(라벨, 가림, (x1, y1, x2, y2))] (원본 좌표). '_occluded' 클래스는 가림으로"""
    from ultralytics import YOLO
    m = YOLO(str(model_path))
    names = {i: (n[:-9] if n.endswith("_occluded") else n) for i, n in m.names.items()}
    occl = {i: n.endswith("_occluded") for i, n in m.names.items()}

    def fn(img, W, H):
        img = img.convert("RGB")
        sx, sy = (W or img.width) / img.width, (H or img.height) / img.height
        kw = {"device": device} if device is not None else {}
        rr = m.predict(img, imgsz=int(imgsz), conf=float(conf), verbose=False, agnostic_nms=any(occl.values()), **kw)[0]
        return [(names[int(c)], occl[int(c)], (x1 * sx, y1 * sy, x2 * sx, y2 * sy))
                for (x1, y1, x2, y2), c in zip(rr.boxes.xyxy.tolist(), rr.boxes.cls.tolist())]
    return fn


def compare_models(ref_file, sources, frame_getter, max_frames=40, labels=None, reviewed=True, log=print):
    """기준 라벨 파일(CVAT export) ↔ 여러 대상.
    sources: [{'name', 'kind': 'model', 'predict': fn(img, W, H), 'model_label', 'conf'} 또는 {'name', 'kind': 'uploaded', 'file'}]
    frame_getter(f) = 그 프레임 이미지 (모델 대상만 씀). 프레임은 TASK 전체에서 고르게 max_frames장 (박스 없는 프레임도 — 잘못 그림을 셈).
    반환 {'ref_kind', 'frames', 'labels', 'sources': [{name, kind, model_label, conf, total: 수치, by_label: {라벨: 수치}}], 'best'}"""
    ref = ctt.load_annotations(ref_file)
    fr = list(ref.get("frames") or sorted(ref["boxes"]))
    if max_frames and len(fr) > max_frames:
        step = (len(fr) - 1) / (max_frames - 1)
        fr = sorted({fr[round(i * step)] for i in range(max_frames)})
    W, H = (ref.get("meta") or {}).get("W"), (ref.get("meta") or {}).get("H")
    imgs = {}
    if any(s["kind"] == "model" for s in sources):
        for k, f in enumerate(fr, 1):
            imgs[f] = frame_getter(f)
            if log and k % 10 == 0:
                log(f"  프레임 받기 {k}/{len(fr)}")
        miss = [f for f, im in imgs.items() if im is None]
        if miss:
            log and log(f"  (프레임 {len(miss)}장을 받지 못해 뺌)")
            fr = [f for f in fr if imgs.get(f) is not None]
    sub = lambda ann: {"boxes": {f: [b for b in ann["boxes"].get(f, [])] for f in fr}}
    R = sub(ref)
    all_labels = {b[1] for v in R["boxes"].values() for b in v}
    out = []
    for s in sources:
        if s["kind"] == "uploaded":
            A = sub(ctt.load_annotations(s["file"]))
        else:
            A = {"boxes": {}}
            for f in fr:
                A["boxes"][f] = [(f"p{j}", lab, oc, xy, True) for j, (lab, oc, xy) in enumerate(s["predict"](imgs[f], W, H))]
        known = set(labels) if labels else ({b[1] for v in A["boxes"].values() for b in v} | (set(s.get("labels") or [])) or all_labels)
        Rk = {"boxes": {f: [b for b in v if b[1] in known] for f, v in R["boxes"].items()}}
        Ak = {"boxes": {f: [b for b in v if b[1] in known] for f, v in A["boxes"].items()}}
        per = _match_corr(Ak, Rk)
        out.append({"name": s["name"], "kind": s["kind"], "model_label": s.get("model_label", ""), "conf": s.get("conf", ""),
                    "file": s.get("file", ""), "labels": sorted(known), "total": _scores(per),
                    "by_label": {l: _scores(per, [l]) for l in sorted(per)}})
    best = max((x for x in out if x["total"]["f1"]), key=lambda x: x["total"]["f1"], default=None)
    return {"ref_kind": "검토 뒤 라벨" if reviewed else "검토 전 CVAT 라벨 (일치도)", "frames": len(fr),
            "frame_list": fr[:200], "sources": out, "best": best["name"] if best else ""}


def write_compare(base, task_id, task_name, res, ref_file, who="", request="", detail=""):
    """비교 결과를 logs/model_compare.csv에 대상마다 한 줄씩"""
    path = Path(base) / COMPARE_LOG
    path = ctt.shard_path(path) if hasattr(ctt, "shard_path") else path   # v4.30.1: 이 세션 파일에
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    t = _now()
    with open(path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COMPARE_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for s in res["sources"]:
            w.writerow({"time": t, "task_id": task_id, "task_name": task_name, "ref_kind": res["ref_kind"],
                        "ref_file": os.path.relpath(ref_file, base) if os.path.isabs(str(ref_file)) else ref_file,
                        "frames": res["frames"], "source": s["name"], "kind": s["kind"], "model_label": s["model_label"],
                        "conf": s["conf"], **s["total"], "who": who, "request": request, "detail": detail})
    return t


def compare_summary(res):
    """한 줄 요약: 'ftB F1 0.91 (P 0.93 · R 0.89) · 올린 자동(ftA) F1 0.85 … — 검토 뒤 라벨 기준 40프레임'"""
    f = lambda v: "–" if v is None else f"{v:.2f}"
    return " · ".join(f"{s['name']} F1 {f(s['total']['f1'])} (P {f(s['total']['precision'])} · R {f(s['total']['recall'])})"
                      for s in res["sources"]) + f" — {res['ref_kind']} 기준 {res['frames']}프레임"


def read_compares(base, n=3):
    """logs/model_compare.csv → {task_id: [비교 한 번 {time, ref_kind, frames, rows: [...]}, …]} (최근 n번)"""
    by = defaultdict(lambda: defaultdict(list))
    for r in _read_csv(Path(base) / COMPARE_LOG):
        by[str(r.get("task_id"))][r.get("time", "")].append(r)
    num = lambda v: (float(v) if v not in (None, "") else None)
    out = {}
    for tid, runs in by.items():
        lst = []
        for t in sorted(runs)[-n:]:
            rows = runs[t]
            lst.append({"time": t, "ref_kind": rows[0].get("ref_kind", ""), "frames": rows[0].get("frames", ""), "who": rows[0].get("who", ""),
                        "rows": [{"source": x.get("source", ""), "kind": x.get("kind", ""), "model_label": x.get("model_label", ""),
                                  **{k: num(x.get(k)) for k in ("auto", "ref_boxes", "tp", "fixed", "relabeled", "fp", "fn", "precision", "recall", "f1")}}
                                 for x in rows]})
        out[tid] = lst
    return out


# ======================= TASK별 자동 라벨 기록 (v4.29.0) — 모델로 라벨링한 기록 (shape·track 올림 · track 만듦) =======================
def _lab_model(label):
    """'runs/<학습>/weights/best.pt' · '<학습>/best.pt (시각)' → 학습 이름"""
    m = re.match(r"^runs/([^/]+)/weights/", str(label or "").strip())
    return m.group(1) if m else _upload_model(label, ())


def labeling_history(base, n=12):
    """logs/uploads.csv(CVAT에 올린 자동 라벨: shape·track) + task_registry.csv('track 생성' = 만들고 아직 안 올렸을 수 있음)
    → {task_id: [{time, kind, model, model_label, status, ok, boxes, before, by_label, app, request}, …]} (오래된 것부터, TASK마다 최근 n개)"""
    base = Path(base)
    out = defaultdict(list)
    for u in _read_csv(base / "logs" / "uploads.csv"):
        tid = str(u.get("task_id") or "")
        if not tid:
            continue
        st = str(u.get("status") or "")
        try:
            sett = json.loads(u.get("settings") or "{}") if str(u.get("settings") or "").startswith("{") else {}
        except Exception:
            sett = {}
        try:
            bl = json.loads(u.get("after_by_label") or "{}") if str(u.get("after_by_label") or "").startswith("{") else {}
        except Exception:
            bl = {}
        method = "track" if u.get("method") == "track" else "shape"
        out[tid].append({"time": u.get("end") or u.get("start", ""), "kind": method + " 올림", "method": method,
                         "model": _lab_model(u.get("model")), "model_label": u.get("model", ""), "status": st,
                         "ok": bool(st) and not any(x in st for x in ("오류", "실패", "진행 중")),
                         "boxes": u.get("after_total", ""), "before": u.get("before_total", ""), "by_label": bl,
                         "app": "재처리 앱" if sett.get("app") == "relabel" else "노트북·LC앱",
                         "request": sett.get("request", ""), "who": u.get("operator", "")})
    for r in _read_csv(base / "task_registry.csv"):
        if r.get("action") != ctt.ACTIONS.get("track", "track 생성"):
            continue
        tid = str(r.get("task_id") or "")
        st = str(r.get("status") or "")
        if not tid or not st.startswith("완료"):
            continue
        out[tid].append({"time": r.get("run_time", ""), "kind": "track 만듦", "method": "track",
                         "model": _lab_model(r.get("model")), "model_label": r.get("model", ""), "status": st, "ok": True,
                         "tracks": r.get("tracks", ""), "app": "재처리 앱" if "재처리 앱" in str(r.get("note", "")) else "노트북·LC앱"})
    return {k: sorted(v, key=lambda x: str(x["time"]))[-n:] for k, v in out.items()}
