"""재처리 앱 연동 — 이름이 uld·AA로 끝나는 TASK를 골라 모델로 다시 라벨링 (안드로이드용 웹 페이지 '가지 재처리', v4.25.0)

Drive eggplant_yolo/relabel/ (작업자 셀 30번과 폰 페이지만 씀 — TASK 이름은 바꾸지 않음)
  state.json            작업자가 쓰는 화면 상태: 대상 TASK·진행·모델·작업자
  tracked.json          한 번이라도 대상이었던 TASK (처음 이름·처음 본 시각·숨김). 이름이 uld·AA가 아니게 바뀌면 '진척'(줄 긋기)
  tasks/<ID>.json       TASK별 재처리 이력 · 확인 대기 중인 track
  previews/<ID>_<시각>.jpg  track 확인용 그림 (폰에서 봄)
  requests/REQ_<id>__<kind>__<status>.json   폰이 만드는 요청 (web_bridge와 같은 형식)
  WORKER.json           작업자 셀의 심장 박동 (누가·어디서·지금 하는 일)
"""
__version__ = "4.31.8"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)

import datetime
import functools
import json
import os
import re
import threading
import time
from pathlib import Path

import web_bridge as wb

KINDS = {
    "shape": "shape 라벨링", "track": "track 만들기", "upload": "track 올리기", "discard": "track 버리기",
    "backup": "백업", "hide": "숨기기", "unhide": "다시 보이기", "refresh": "새로 고침",
}
WORK_KINDS = ("shape", "track", "upload", "backup")          # CVAT·GPU를 쓰는 일 (v4.29: shape·track은 GPU 줄 하나씩, upload·backup은 입출력 줄 동시)
TARGET_END = ("uld", "AA")                                    # 이름이 이것으로 끝나는 TASK가 대상
WORKER_STALE_SEC = 180
_LOCK = threading.RLock()        # v4.29: 작업자가 여러 일을 동시에 할 때 같은 파일(TASK 기록·tracked·state)을 겹쳐 쓰지 않게


def _locked(f):
    @functools.wraps(f)
    def g(*a, **k):
        with _LOCK:
            return f(*a, **k)
    return g


def root(base):
    return Path(base) / "relabel"


def is_target(name, ends=TARGET_END):
    n = re.sub(r"_AA_r\d+$", "_AA", (name or "").strip())      # v4.31.5: AA_r1·AA_r2 = AA
    return any(n.endswith(e) for e in ends)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    import threading
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")   # 작업자의 심장 박동 스레드와 겹치지 않게
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p


def ensure(base):
    for d in ("requests", "tasks", "previews"):
        (root(base) / d).mkdir(parents=True, exist_ok=True)
    return root(base)


# ---------- 대상 TASK ----------
def load_tracked(base):
    return _read_json(root(base) / "tracked.json", {})


@_locked
def update_tracked(base, cvat_tasks, ends=TARGET_END):
    """CVAT 목록에서 대상(이름이 uld·AA로 끝남)을 더하고, 이미 있는 것은 지금 이름·진척을 갱신 → tracked dict"""
    tr = load_tracked(base)
    by_id = {str(t["task_id"]): t for t in cvat_tasks}
    gone = wb.gone_tasks(base) if hasattr(wb, "gone_tasks") else {}
    now = _now()
    for tid, t in by_id.items():
        if is_target(t["name"], ends) and tid not in tr:
            tr[tid] = {"first_name": t["name"], "first_seen": now, "hidden": False}
    for tid, r in tr.items():
        t = by_id.get(tid)
        r["name"] = t["name"] if t else r.get("name") or r["first_name"]
        r["in_cvat"] = t is not None
        g = gone.get(tid)
        if t is None and g and not r.get("gone_at"):       # v4.31.8: 수집기가 'CVAT에서 사라짐'으로 본 TASK → 이력에 한 번
            r["gone_at"] = g.get("gone_at") or now
            add_history(base, tid, kind="gone", status="CVAT에서 사라짐", note=f"수집기 기록 {r['gone_at'][:16]}", who="수집기")
        elif t is not None and r.get("gone_at"):
            r.pop("gone_at", None)                         # 다시 나타남
        was = r.get("progressed", False)
        r["progressed"] = (t is None) or not is_target(t["name"], ends)
        if r["progressed"] and not was:
            r["progressed_at"] = now
        if t:
            for k in ("frames", "media", "updated", "status", "org", "project_id"):
                if k in t:
                    r[k] = t[k]
            if t.get("updated_iso"):
                r["updated"] = t["updated_iso"]          # v4.31.4: 시간대 붙인 시각
    _write_json(root(base) / "tracked.json", tr)
    return tr


@_locked
def set_hidden(base, ids, hidden):
    tr = load_tracked(base)
    n = 0
    for tid in ids:
        r = tr.get(str(tid))
        if r is not None and r.get("hidden") != hidden:
            r["hidden"] = hidden
            n += 1
    _write_json(root(base) / "tracked.json", tr)
    return n


# ---------- TASK별 이력 ----------
def task_record(base, tid):
    return _read_json(root(base) / "tasks" / f"{tid}.json", {"history": [], "track_pending": None})


def save_task_record(base, tid, rec):
    return _write_json(root(base) / "tasks" / f"{tid}.json", rec)


@_locked
def add_history(base, tid, **entry):
    rec = task_record(base, tid)
    rec["history"] = (rec.get("history") or []) + [{"time": _now(), **entry}]
    rec["history"] = rec["history"][-30:]
    save_task_record(base, tid, rec)
    return rec


@_locked
def set_pending_track(base, tid, pending):
    rec = task_record(base, tid)
    rec["track_pending"] = pending
    save_task_record(base, tid, rec)
    return rec


def stale_pending(base):
    """확인 대기 track을 만든 뒤 shape로 CVAT 라벨을 바꾼 TASK (그 track은 올리면 shape 라벨을 덮어씀) → TASK ID 목록 (v4.29)"""
    out = []
    for p in sorted((root(base) / "tasks").glob("*.json")):
        rec = _read_json(p, {})
        pend = rec.get("track_pending")
        if not pend:
            continue
        hist = rec.get("history") or []
        mine = [i for i, h in enumerate(hist) if h.get("kind") == "track" and h.get("request") == pend.get("request")
                and str(h.get("status", "")).startswith("완료")]
        start = mine[-1] if mine else None
        if start is None:
            continue
        if any(h.get("kind") == "shape" and str(h.get("status", "")).startswith("완료") for h in hist[start + 1:]):
            out.append(int(p.stem) if p.stem.isdigit() else p.stem)
    return out


# ---------- 작업자 ----------
def read_worker(base, slot=""):
    w = _read_json(root(base) / f"WORKER{slot}.json", None)       # v4.31.7: slot '_gpu' = Kaggle GPU 워커
    if not w:
        return None
    try:
        hb = datetime.datetime.fromisoformat(w["heartbeat"])
        w["age_sec"] = (datetime.datetime.now(datetime.timezone.utc) - hb).total_seconds()
    except Exception:
        w["age_sec"] = 1e9
    return w


def worker_beat(base, who, session, host, busy=None, started=None, stopping=False, slot=""):
    return _write_json(root(base) / f"WORKER{slot}.json", {
        "who": who, "session": session, "host": host, "heartbeat": _now(), "busy": busy, "started": started,
        "stopping": stopping, "version": __version__})


def acquire_worker(base, who, session, takeover=False, stale_sec=WORKER_STALE_SEC, slot=""):
    """다른 세션의 작업자가 살아 있으면 멈춤 (요청을 두 곳에서 처리하지 않게)"""
    w = read_worker(base, slot)
    if w and w.get("session") != session and w["age_sec"] < stale_sec and not w.get("stopping") and not takeover:
        raise SystemExit(f"⛔ 다른 작업자가 켜져 있습니다: {w.get('who')} · {w.get('host')} · {w['age_sec']:.0f}초 전 "
                         "→ 그 세션을 멈추거나 RL_TAKEOVER = True")
    return w


# ---------- 요청 ----------
@_locked
def list_requests(base):
    return wb.list_requests(root(base))     # v4.29.5: 상태 바꾸기(set_status)와 같은 잠금 — 이름을 바꾸는 중에 목록을 읽지 않게


def next_request(base, host=""):
    """가장 오래된 대기 요청 하나 (숨기기·새로 고침 같은 가벼운 일이 먼저) — 배정자(requests/assign/) 라우팅 준수"""
    reqs = [r for r in list_requests(base) if r["status"] == "pending" and r["kind"] in KINDS and wb._assigned_to_me(base, r["id"], host)]
    if not reqs:
        return None
    reqs.sort(key=lambda r: (r["kind"] in WORK_KINDS, str(r.get("created", ""))))
    return reqs[0]


@_locked
def set_status(base, req, status, **fields):
    return wb.set_status(root(base), req, status, **fields)


def waiting_requests(base):
    return [r for r in list_requests(base) if r["status"] == "waiting" and r["kind"] in ("track", "backup")]


# ---------- 화면 상태 ----------
def _worked_from_history(hist):
    """재처리 앱 이력에서 마지막으로 CVAT에 라벨을 올린 일 (shape 완료 · track 업로드 완료) — v4.29.1"""
    for h in reversed(hist or []):
        k, st = h.get("kind"), str(h.get("status") or "")
        if (k == "shape" and st.startswith("완료")) or (k == "upload" and st.startswith("업로드 완료")):
            return {"kind": "shape" if k == "shape" else "track", "time": h.get("time"), "model": h.get("model"),
                    "boxes": h.get("boxes"), "by": "재처리 앱"}
    return None


def _worked_from_uploads(base):
    """노트북·LC앱(6·10번 셀)으로 올린 자동 라벨 (logs/uploads.csv) → {task_id: {...}} — 마지막 것"""
    out = {}
    for u in wb._read_csv(Path(base) / "logs" / "uploads.csv"):
        st = str(u.get("status") or "")
        if not st or any(x in st for x in ("오류", "실패", "진행 중")):
            continue
        tid = str(u.get("task_id") or "")
        t = u.get("end") or u.get("start") or ""
        if tid and (tid not in out or str(t) >= str(out[tid]["time"])):
            out[tid] = {"kind": "track" if u.get("method") == "track" else "shape", "time": t,
                        "model": wb._lab_model(u.get("model", "")), "boxes": u.get("after_total") or None, "by": "노트북·LC앱"}
    return out



def model_rows(base, files=None):
    """라벨링에 쓸 수 있는 모델: 학습이 끝났고 best.pt가 있고 보관되지 않은 것 (최근 것 먼저)
    files = Drive 파일 목록 {경로: (크기, 수정 시각)} (v4.31.6 Kaggle: best.pt를 모두 받지 않으므로 Drive 목록으로 봄)"""
    base = Path(base)
    files = files or {}
    out = []
    jobs = wb._train_jobs(wb._read_csv(base / "logs" / "activity.csv"))
    for d in sorted((base / "runs").glob("*")):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        best = d / "weights" / "best.pt"
        remote = files.get(f"runs/{d.name}/weights/best.pt")
        if not (d / "TRAINING_DONE").exists() or not (best.exists() or remote):
            continue
        cl = _read_json(d / "CLEANUP.json", {})
        if cl.get("archived"):
            continue
        m = wb.model_info(base, d, (), jobs, ())
        conv = (m.get("settings") or {}).get("convert") or {}
        out.append({"name": d.name, "map5095": (m.get("best") or {}).get("map5095"), "map50": (m.get("best") or {}).get("map50"),
                    "classes": conv.get("KEEP_CLASSES"), "imgsz": (m.get("args") or {}).get("imgsz"),
                    "time": datetime.datetime.fromtimestamp(best.stat().st_mtime if best.exists() else float(remote[1])).isoformat(timespec="minutes")})
    out.sort(key=lambda r: r["time"], reverse=True)
    return out


@_locked
def build_state(base, tracked=None, models=None, media=None, defaults=None, server="", scope_text="", uld=None, replaced=None):
    """tracked.json + TASK별 이력 + 열린 요청 → state.json (폰 페이지가 읽음)"""
    base = Path(base)
    tracked = load_tracked(base) if tracked is None else tracked
    vids, bks = media or (set(), set())
    uld_ = {str(k): v for k, v in (uld or {}).items()}
    rep_ = {str(k): str(v) for k, v in (replaced or {}).items()}
    open_by = {}
    for r in list_requests(base):
        if r["status"] in ("pending", "taken", "waiting"):
            for t in r.get("task_ids") or []:
                open_by.setdefault(str(t), []).append({"id": r["id"], "kind": r["kind"], "status": r["status"]})
    tasks = []
    ups = _worked_from_uploads(base)
    for tid, r in tracked.items():
        rec = task_record(base, tid)
        hist = rec.get("history") or []
        bn = _base_name(r.get("name") or r.get("first_name"))
        pend = rec.get("track_pending")
        f = _parse(r.get("name") or r.get("first_name"))
        tasks.append({
            "id": int(tid) if str(tid).isdigit() else tid, "name": r.get("name"), "first_name": r.get("first_name"),
            "rule_ok": bool(f), **({k: str(f.get(k) or "") for k in ("project", "gh", "date", "row", "plant", "state", "tag")} if f else {}),
            "first_seen": r.get("first_seen"), "progressed": r.get("progressed", False), "progressed_at": r.get("progressed_at"),
            "in_cvat": r.get("in_cvat", True), "hidden": r.get("hidden", False), "frames": r.get("frames"),
            "media": r.get("media"), "updated": r.get("updated"),
            "source": "영상" if bn.lower() in vids else "ULD" if str(tid) in uld_ else "백업" if bn in bks else "",   # v4.31.6: ULD clip
            "uld": uld_.get(str(tid), ""),
            "gone_at": r.get("gone_at") or None,
            "replaced_by": rep_.get(str(tid)),
            "last": hist[-1] if hist else None, "runs": len(hist),
            "track_pending": ({k: pend.get(k) for k in ("made", "model", "conf", "tracks", "boxes", "by_label", "frames_with_boxes",
                                                         "preview", "xml", "video")} if pend else None),
            "open": open_by.get(str(tid), []),
            "worked": _worked_from_history(hist) or ups.get(str(tid)),     # v4.29.1: 모델 라벨을 CVAT에 올린 적 있음 → 폰에서 뒤로·흐리게
        })
    tasks.sort(key=lambda t: (t["progressed"], t["name"] or ""))
    st = {"version": __version__, "generated": _now(), "server": server, "scope": scope_text, "ends": list(TARGET_END),
          "kinds": KINDS, "defaults": defaults or {}, "models": models if models is not None else model_rows(base),
          "tasks": tasks,
          "summary": {"targets": sum(1 for t in tasks if not t["progressed"]), "progressed": sum(1 for t in tasks if t["progressed"]),
                      "hidden": sum(1 for t in tasks if t["hidden"]), "pending_track": sum(1 for t in tasks if t["track_pending"]),
                      "worked": sum(1 for t in tasks if t["worked"] and not t["progressed"])}}
    _write_json(root(base) / "state.json", st)
    return st


def _parse(name):
    try:
        import cvat_task_tools as ctt
        return ctt.parse_task_name(name or "")
    except Exception:
        return None


def _base_name(name):
    try:
        import cvat_task_tools as ctt
        return ctt.base_name(name or "")
    except Exception:
        return re.sub(r"_(uld|vf\w*)(_AA\w*)?$", "", name or "")


# ---------- track 확인용 그림 ----------
def preview_image(xml_path, frame_getter, out_path, n=4, width=1080, offset=0):
    """track XML에서 박스가 많은 프레임 n장을 골라 박스를 그린 2열 모음 그림(JPEG) → (경로, 고른 프레임)"""
    from PIL import Image, ImageDraw
    import cvat_task_tools as ctt
    ann = ctt.load_annotations(xml_path)
    frames = sorted(ann["boxes"], key=lambda f: -len(ann["boxes"][f]))[:max(1, n)]
    frames = sorted(frames)
    colors = {"healthy_fruit": (255, 221, 0), "disease_fruit": (255, 60, 60), "healthy_bud": (0, 230, 255), "disease_bud": (255, 0, 255)}
    tiles = []
    for f in frames:
        im = frame_getter(f - offset)
        if im is None:
            continue
        im = im.convert("RGB")
        W, H = ann["meta"].get("W") or im.width, ann["meta"].get("H") or im.height
        sx, sy = im.width / W, im.height / H
        d = ImageDraw.Draw(im)
        lw = max(2, im.width // 400)
        for _tid, label, occ, (x1, y1, x2, y2), _kf in ann["boxes"][f]:
            d.rectangle([x1 * sx, y1 * sy, x2 * sx, y2 * sy], outline=colors.get(label, (255, 255, 255)), width=lw)
        d.rectangle([0, 0, im.width // 5, im.height // 22 + 8], fill=(0, 0, 0))
        d.text((8, 4), f"frame {f} · {len(ann['boxes'][f])}", fill=(255, 255, 255))
        tiles.append(im)
    if not tiles:
        return None, []
    tw = width // 2 if len(tiles) > 1 else width
    tiles = [t.resize((tw, max(1, int(t.height * tw / t.width)))) for t in tiles]
    th = max(t.height for t in tiles)
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * rows), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=72)
    return out_path, frames


def track_summary(xml_path):
    """track XML → track 수 · 박스 수 · 라벨별 · 박스가 있는 프레임 수"""
    import cvat_task_tools as ctt
    from collections import Counter
    ann = ctt.load_annotations(xml_path)
    by = Counter(lab for bs in ann["boxes"].values() for _t, lab, _o, _c, _k in bs)
    return {"tracks": len(ann["tracks"]), "boxes": sum(by.values()), "by_label": dict(by),
            "frames_with_boxes": sum(1 for bs in ann["boxes"].values() if bs), "frames": len(ann["frames"])}
