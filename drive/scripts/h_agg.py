"""v4.33 2b-4 취합 일 — hide·unhide·refresh (한 단계 `run`).

설계(DESIGN '취합 일'):
- 취합은 `arb/locks/aggregate.json`을 받은 실행 하나. 읽기 사본으로 계산하고 **자기 상태 파일만** 게시합니다.
  · `relabel/tracked.json` — 대상 TASK 목록(숨김 포함). 작성자는 취합 하나
  · `relabel/state.json`   — 폰 화면용 요약(TASK 이력 요약·열린 요청)
  · `web/pending_status.json` — 받는 중 백업·export 요약 (요청·TASK별 기록 `*/pending/*.json`에서, J1)
- 게시하기 전에 최신본을 다시 받고, 게시 파일에 `_pub = {epoch, gen, run, rid, at}`를 적습니다. 앱은 가장 높은
  (epoch, gen)을 씁니다. 이미 더 높은 것이 있으면 쓰지 않고 멈춤 보고(옛 실행).
- 쓰기마다 권한 확인(`ctx.auth('publish').call`). 잃으면 게시하지 않고 멈춤 보고 → 심판이 '확인 필요'.
- 다른 곳이 맡을 쓰기는 하지 않음: 요청 완료 처리(실행기 `_finalize`), 사라진 TASK 이력(TASK 잠금 경로),
  기록 압축(청소 관리 일). 그래서 '사라짐'은 tracked에 표시만 합니다.
- CVAT 목록이 끝까지 읽히지 않으면(개수 한도에 닿음) 보이지 않은 TASK를 '사라짐'으로 보지 않습니다.
- 시험 실행(`env.test`)은 `test/` 아래에만 게시 — 운영 상태 파일을 바꾸지 않음.
- `web/state.json`·`label_stats`·`corrections`·`snapshots`(옛 `wb.build_state` 전체)는 2b-6에서 실행 호스트의
  읽기 사본 위에 연결합니다(로그 샤드·영상 목록 등이 필요). 여기서는 위 세 파일만.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

import access
import arbiter as A
import handlers as H
from arb_io import StoreError

P_TRACKED = "relabel/tracked.json"
P_RSTATE = "relabel/state.json"
P_PENDING = "web/pending_status.json"
WEB_FILES = ("web/state.json", "web/label_stats.json", "web/corrections.json")   # 웹 상태 계산이 내도 되는 파일만
TASK_DIR = "relabel/tasks/"
PENDING_DIRS = {"backup": "backups/pending/", "export": "exports/pending/"}
REQ_DIRS = ("requests/", "relabel/requests/")
LIST_LIMIT = 5000
KEEP_DONE = 50                       # 요약에 남길 최근 '받음' 수
CARRY = ("source", "uld", "replaced_by")   # 영상·ULD 출처는 아직 이전 상태에서 이어 받음 (2b-6에서 계산)


class Unreadable(RuntimeError):
    """게시 대상의 지금 파일을 읽지 못함 → 덮어쓰지 않음."""


def _path(env, p: str) -> str:
    return ("test/" + p) if getattr(env, "test", False) else p


def _now(env) -> float:
    c = getattr(env, "clock", None)
    return c() if c else time.time()


def _read(store, path: str, missing=None):
    """없으면 missing. 있는데 못 읽거나 객체가 아니면 Unreadable (덮어쓰지 않으려고)."""
    if not store.exists(path):
        return missing
    try:
        o = store.read_json(path)
    except StoreError as e:
        raise Unreadable(f"{path}: {e}")
    if not isinstance(o, dict):
        raise Unreadable(f"{path}: 객체가 아님")
    return o


def stamp(ctx) -> dict:
    """지금 취합 잠금에서 epoch·회차(gen). 내 실행이 아니면 멈춤."""
    lk = ctx.env.store.read_json(A.P_LOCK_AGG)
    if not isinstance(lk, dict) or lk.get("run") != ctx.run:
        raise access.AuthorityLost("취합 잠금이 내 실행이 아님")
    return {"epoch": int(lk.get("epoch", -1)), "gen": int(lk.get("gen", 0)), "run": ctx.run, "rid": ctx.rid,
            "at": _now(ctx.env)}


def _key(pub) -> Tuple[int, int]:
    pub = pub if isinstance(pub, dict) else {}
    try:
        return int(pub.get("epoch", -1)), int(pub.get("gen", -1))
    except (TypeError, ValueError):
        return -1, -1


def publish(ctx, rel: str, obj: dict, pub: dict):
    """최신본의 (epoch, gen)이 내 것보다 높으면 쓰지 않음. 권한 확인 뒤 씀."""
    store, path = ctx.env.store, _path(ctx.env, rel)

    def put():
        cur = _read(store, path)
        if cur and _key(cur.get("_pub")) > _key(pub):
            raise access.AuthorityLost(f"{rel}: 더 새 취합이 이미 게시함")
        store.write_json(path, dict(obj, _pub=pub))
    ctx.auth("publish").call("publish:" + rel, put)


def tasks_of(tracked: dict) -> Dict[str, dict]:
    return {k: v for k, v in tracked.items() if not str(k).startswith("_") and isinstance(v, dict)}


# ---------------------------------------------------------------- hide · unhide
def run_hide(ctx) -> dict:
    env = ctx.env
    pub = stamp(ctx)
    tracked = _read(env.store, _path(env, P_TRACKED), {})        # 최신본에 고침
    tr = tasks_of(tracked)
    want = ctx.kind == "hide"
    ids = [str(t) for t in ctx.intake.get("tasks") or []]
    changed = [t for t in ids if t in tr and tr[t].get("hidden", False) != want]
    for t in changed:
        tr[t]["hidden"] = want
        tr[t]["hidden_at" if want else "unhidden_at"] = pub["at"]
    if changed:
        publish(ctx, P_TRACKED, tr, pub)
    missing = [t for t in ids if t not in tr]
    ctx.progress(f"{ctx.kind} {len(changed)}건" + (f" · 대상 아님 {len(missing)}건" if missing else ""))
    return {"report": "done_job", "result": "failed:not_tracked" if ids and len(missing) == len(ids) else "done"}


# ---------------------------------------------------------------- refresh
def update_tracked(tr: Dict[str, dict], rows: List[dict], complete: bool, now: float) -> Dict[str, dict]:
    """옛 rb.update_tracked와 같은 규칙(이름 꼬리가 대상이면 더함, 이름·진척 갱신)을 순수 함수로.
    목록이 끝까지 읽히지 않았으면 보이지 않은 TASK의 in_cvat·진척을 바꾸지 않음."""
    import h_task as HT
    tr = {k: dict(v) for k, v in tr.items()}
    by_id = {str(r["task_id"]): r for r in rows}
    for tid, t in by_id.items():
        if HT.is_target(t.get("name")) and tid not in tr:
            tr[tid] = {"first_name": t["name"], "first_seen": now, "hidden": False}
    for tid, r in tr.items():
        t = by_id.get(tid)
        if t is None and not complete:
            continue
        r["name"] = t["name"] if t else r.get("name") or r.get("first_name")
        r["in_cvat"] = t is not None
        if t is None and not r.get("gone_at"):
            r["gone_at"] = now                           # 이력은 TASK 잠금 경로가 씀 — 여기서는 표시만
        elif t is not None:
            r.pop("gone_at", None)
        was = r.get("progressed", False)
        r["progressed"] = t is None or not HT.is_target(t.get("name"))
        if r["progressed"] and not was:
            r["progressed_at"] = now
        if t:
            for k in ("frames", "media", "status", "org", "project_id"):
                if k in t:
                    r[k] = t[k]
            r["updated"] = t.get("updated_iso") or t.get("updated") or r.get("updated")
    return tr


def open_requests(store) -> Dict[str, list]:
    """열린 요청(이름의 상태가 최종이 아님) → {TASK: [{id, kind, status}]}. 못 읽는 요청은 건너뜀."""
    out: Dict[str, list] = {}
    for d in REQ_DIRS:
        for e in store.list(d, False):
            p = A.parse_req_name(e.path)
            if not p or p[2] in A.FINAL_STATUS:
                continue
            try:
                r = store.read_json(e.path)
            except StoreError:
                continue
            if not isinstance(r, dict):
                continue
            for t in r.get("tasks") or r.get("task_ids") or []:
                out.setdefault(str(t), []).append({"id": p[0], "kind": p[1], "status": p[2]})
    return out


def pending_summary(store, now: float) -> dict:
    """요청·TASK별 받는 중 기록(J1) → 요약. 기록 파일은 바꾸지 않음."""
    active, done, bad = [], [], 0
    for kind, d in PENDING_DIRS.items():
        for e in store.list(d, False):
            try:
                r = store.read_json(e.path)
            except StoreError:
                bad += 1
                continue
            if not isinstance(r, dict):
                bad += 1
                continue
            row = {"kind": kind, "rid": r.get("rid"), "task": r.get("task"), "task_name": r.get("task_name"),
                   "status": r.get("status"), "requested_at": r.get("requested_at"),
                   "task_updated": r.get("task_updated"), "result_file": r.get("result_file")}
            at = r.get("requested_at")
            if isinstance(at, (int, float)):
                row["age_min"] = int((now - at) // 60)
            (done if r.get("status") == "받음" else active).append(row)
    done.sort(key=lambda x: x.get("requested_at") if isinstance(x.get("requested_at"), (int, float)) else 0, reverse=True)
    counts: Dict[str, int] = {}
    for r in active + done:
        k = f"{r['kind']}:{r.get('status')}"
        counts[k] = counts.get(k, 0) + 1
    return {"generated": now, "counts": counts, "unreadable": bad, "active": active, "recent_done": done[:KEEP_DONE]}


# ---------------------------------------------------------------- 채택된 모델 (b24 T5)
def _valid_entry(v) -> bool:
    return isinstance(v, dict) and isinstance(v.get("sha256"), str) and len(v["sha256"]) == 64 \
        and isinstance(v.get("size"), int) and v["size"] > 0


def adopted_models(store, skipped: Optional[list] = None) -> List[dict]:
    """`runs/<모델>/CURRENT.json`이 가리키는 확인된 버전. 웹 상태·relabel 상태·모델 선택이 함께 씀.
    못 읽거나 형태가 틀리거나 확인 안 된 버전은 **그 모델만** 빼고 넘어감 (b25 F2). skipped에 [이름, 이유]."""
    out = []
    skip = skipped if skipped is not None else []
    for e in store.list("runs/", True, include=("CURRENT.json",)):
        parts = e.path.split("/")
        if len(parts) != 3:
            continue
        name = parts[1]
        try:
            cur = store.read_json(e.path)
            ver = cur.get("version") if isinstance(cur, dict) else None
            if not isinstance(ver, str) or not ver:
                continue                                       # 빈 시작(초기화) 또는 형태 오류
            base = H.version_dir("model", name, ver)
            man = store.read_json(base + "_files.json")
        except StoreError:
            skip.append([name, "unreadable"])
            continue
        files = man.get("files") if isinstance(man, dict) else None
        if not isinstance(man, dict) or man.get("verified") is not True or not isinstance(files, dict) \
                or not _valid_entry(files.get("best.pt")) or not all(isinstance(k, str) and _valid_entry(v) for k, v in files.items()):
            skip.append([name, "manifest_invalid"])
            continue
        paths = man.get("paths") if man.get("legacy") and isinstance(man.get("paths"), dict) else {}
        if any(not isinstance(v, str) or not v or ".." in v.split("/") for v in paths.values()):
            skip.append([name, "legacy_paths_invalid"])        # 경로가 틀리면 그 모델만 뺌 (b26 U3)
            continue
        meta = {}
        if "train.json" in files:
            try:
                meta = clean_meta(store.read_json(base + "train.json"))
            except StoreError:
                meta = {}
        out.append({"name": name, "version": str(ver), "adopted_at": cur.get("at"),
                    "files": {rel: paths.get(rel) or base + rel for rel in files},
                    "sizes": {rel: int(v["size"]) for rel, v in files.items()},
                    "meta": meta if isinstance(meta, dict) else {}})
    return sorted(out, key=lambda m: m["name"])


def clean_meta(m) -> dict:
    """train.json에서 쓰는 칸만, 자료형이 맞을 때만 (부가 정보가 깨져도 모델은 목록에 남음, b26 U3)."""
    if not isinstance(m, dict):
        return {}
    num = (int, float)
    mt = m.get("metrics") if isinstance(m.get("metrics"), dict) else {}
    ar = m.get("args") if isinstance(m.get("args"), dict) else {}
    cls = m.get("classes")
    out = {"metrics": {k: v for k, v in mt.items() if isinstance(k, str) and isinstance(v, num) and not isinstance(v, bool)},
           "args": {k: v for k, v in ar.items() if isinstance(k, str) and isinstance(v, (str, int, float, bool))},
           "classes": cls if isinstance(cls, list) and all(isinstance(c, str) for c in cls) else None}
    if isinstance(m.get("made_at"), num) and not isinstance(m.get("made_at"), bool):
        out["made_at"] = m["made_at"]
    return out


def model_rows(models: List[dict]) -> List[dict]:
    """relabel 상태(폰 화면)의 모델 선택 행 — 옛 rb.model_rows와 같은 칸."""
    rows = []
    for m in models:
        try:
            meta = clean_meta(m.get("meta"))
            mt, args = meta["metrics"], meta["args"]
            rows.append({"name": m["name"], "version": m["version"],
                         "map5095": mt.get("metrics/mAP50-95(B)"), "map50": mt.get("metrics/mAP50(B)"),
                         "classes": meta.get("classes"), "imgsz": args.get("imgsz"),
                         "time": _iso_kst(meta.get("made_at") or m.get("adopted_at"))[:16]})
        except Exception:
            continue                                       # 한 모델의 변환 실패가 다른 모델을 막지 않음
    rows.sort(key=lambda r: r["time"] or "", reverse=True)
    return rows


# ---------------------------------------------------------------- 새 처리기의 작업 이력 (b24 T6)
WRITE_KINDS = ("track", "shape", "auto", "upload_submission", "recovery")


def _iso_kst(ts) -> str:
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(float(ts), _dt.timezone(_dt.timedelta(hours=9))).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def result_history(store) -> Dict[str, list]:
    """심판이 확정한 TASK 결과(`arb/results`) → {TASK: [이력 행]} (읽기만). 요청 종류·모델은 접수 기록에서.
    같은 (요청, TASK, 작업 번호)는 한 번만."""
    intakes: Dict[str, dict] = {}
    out: Dict[str, list] = {}
    seen = set()
    for e in store.list(A.P_RESULTS, False):
        try:
            r = store.read_json(e.path)
        except StoreError:
            continue
        if not isinstance(r, dict) or r.get("task") in (None, "run", "create"):
            continue
        rid, t = str(r.get("rid") or ""), str(r.get("task"))
        key = (rid, t, r.get("job"))
        if key in seen:
            continue
        seen.add(key)
        if rid not in intakes:
            try:
                it = store.read_json(A.P_INTAKE + f"{rid}.json")
            except StoreError:
                it = {}
            intakes[rid] = it if isinstance(it, dict) else {}
        it = intakes[rid]
        kind = it.get("kind") or ""
        if kind not in WRITE_KINDS:
            continue
        prm = it.get("params") if isinstance(it.get("params"), dict) else {}
        out.setdefault(t, []).append({"kind": kind, "status": str(r.get("result")), "time": _iso_kst(r.get("at")),
                                      "request": rid, "job": r.get("job"), "model": prm.get("model"),
                                      "mode": it.get("mode"), "by": it.get("requester"), "source": "v4.33"})
    for t in out:
        out[t].sort(key=lambda h: h["time"])
    return out


def _worked_new(hist: list) -> Optional[dict]:
    """모델 라벨을 CVAT에 올린 마지막 일 (새 처리기). 보류·실패·되돌리기는 올린 것이 아님."""
    for h in reversed(hist):
        if h.get("source") == "v4.33" and h.get("status") == "done" and not (h["kind"] == "recovery" and h.get("mode") == "revert"):
            return {"kind": "shape" if h["kind"] in ("shape", "auto") else "track", "time": h["time"], "model": h.get("model"),
                    "boxes": None, "by": h.get("by") or "v4.33"}
    return None


def task_summary(tid: str, r: dict, rec: Optional[dict], prev: dict, open_by: Dict[str, list],
                 new_hist: Optional[list] = None) -> dict:
    import relabel_bridge as rb
    old = (rec or {}).get("history") or []
    hist = sorted(old + list(new_hist or []), key=lambda h: str(h.get("time") or ""))
    worked = [w_ for w_ in (rb._worked_from_history(old), _worked_new(hist)) if w_]
    pend = (rec or {}).get("track_pending")
    f = rb._parse(r.get("name") or r.get("first_name"))
    row = {"id": int(tid) if str(tid).isdigit() else tid, "name": r.get("name"), "first_name": r.get("first_name"),
           "rule_ok": bool(f), "first_seen": r.get("first_seen"), "progressed": r.get("progressed", False),
           "progressed_at": r.get("progressed_at"), "in_cvat": r.get("in_cvat", True), "hidden": r.get("hidden", False),
           "frames": r.get("frames"), "media": r.get("media"), "updated": r.get("updated"),
           "gone_at": r.get("gone_at") or None, "last": hist[-1] if hist else None, "runs": len(hist),
           "track_pending": ({k: pend.get(k) for k in ("made", "model", "conf", "tracks", "boxes", "by_label",
                                                         "frames_with_boxes", "preview", "xml", "video")}
                             if isinstance(pend, dict) else None),
           "open": open_by.get(str(tid), []), "worked": max(worked, key=lambda w_: str(w_.get("time") or "")) if worked else None,
           "record": "ok" if rec is not None else "unreadable"}
    if f:
        row.update({k: str(f.get(k) or "") for k in ("project", "gh", "date", "row", "plant", "state", "tag")})
    for k in CARRY:
        if k in prev:
            row[k] = prev[k]
    return row


def run_refresh(ctx) -> dict:
    env = ctx.env
    store, cv = env.store, env.cvat
    pub = stamp(ctx)
    now = pub["at"]
    with H.ticking(ctx.progress, "CVAT 목록 읽는 중"):
        if hasattr(cv, "list_tasks_full"):
            rows, complete = cv.list_tasks_full(limit=LIST_LIMIT)
        else:
            rows = cv.list_tasks(limit=LIST_LIMIT)
            complete = len(rows) < LIST_LIMIT
    ctx.progress(f"CVAT TASK {len(rows)}개" + ("" if complete else " (한도에 닿음 — 사라짐 판단 안 함)"))
    tracked = _read(store, _path(env, P_TRACKED), {})
    tr = update_tracked(tasks_of(tracked), rows, complete, now)
    publish(ctx, P_TRACKED, tr, pub)

    prev_state = _read(store, _path(env, P_RSTATE), {}) or {}
    prev_rows = {str(t.get("id")): t for t in prev_state.get("tasks") or [] if isinstance(t, dict)}
    open_by = open_requests(store)
    new_hist = result_history(store)
    tasks, unreadable = [], 0
    for i, (tid, r) in enumerate(sorted(tr.items())):
        p = TASK_DIR + f"{tid}.json"
        try:
            rec = _read(store, p, {"history": [], "track_pending": None})
        except Unreadable:
            rec, unreadable = None, unreadable + 1
        tasks.append(task_summary(tid, r, rec, prev_rows.get(tid, {}), open_by, new_hist.get(tid)))
        if i % 50 == 49:
            ctx.progress(f"TASK 요약 {i + 1}/{len(tr)}")
    tasks.sort(key=lambda t: (t["progressed"], t["name"] or ""))
    st = {k: prev_state[k] for k in ("server", "scope", "ends", "kinds", "defaults") if k in prev_state}
    skipped_models: list = []
    st["models"] = model_rows(adopted_models(store, skipped_models))   # 채택된 모델 버전에서 매번 계산 (b24 T5)
    st["models_skipped"] = skipped_models                 # 목록에서 뺀 모델과 이유 (b25 F2)
    st.update(generated=now, tasks=tasks, list_complete=complete, unreadable_records=unreadable,
              summary={"targets": sum(1 for t in tasks if not t["progressed"]),
                       "progressed": sum(1 for t in tasks if t["progressed"]),
                       "hidden": sum(1 for t in tasks if t["hidden"]),
                       "pending_track": sum(1 for t in tasks if t["track_pending"]),
                       "worked": sum(1 for t in tasks if t["worked"] and not t["progressed"])})
    publish(ctx, P_RSTATE, st, pub)
    publish(ctx, P_PENDING, pending_summary(store, now), pub)
    web = getattr(env, "web_state", None)              # 2b-6: 옛 web/state.json 등 (읽기 사본 위에서 계산)
    if web is not None:
        outs = web.build(ctx.progress)
        for rel in sorted(outs):
            if rel in WEB_FILES and isinstance(outs[rel], dict):
                publish(ctx, rel, outs[rel], pub)
    return {"report": "done_job", "result": "done"}


H.register("hide", run=run_hide)
H.register("unhide", run=run_hide)
H.register("refresh", run=run_refresh)
