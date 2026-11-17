"""v4.33 2b-5a 관리 일 — dataset · test_tasks33 · force_new · cleanup29 · cleanup34 (한 단계 `run`).

설계(DESIGN '관리 일'·'버전과 채택'·'지움 표시와 청소'):
- 관리 일은 `arb/locks/mgmt.json`을 받은 실행 하나. 쓰기마다 권한 확인(`ctx.auth('publish')`), 잃으면 멈춤 보고.
- 산출물(데이터셋·시험 TASK 설정)은 버전 경로 `…/v/<실행ID>/`에 다 쓰고 다시 받아 확인한 뒤 마지막에 `_files.json`.
  채택(`CURRENT.json`)은 심판이 함 — 여기서는 `done_run`만 보고.
- FORCE_NEW는 파일을 옮기지 않고 채택 바꾸기(`current_change`)만 보고 → 심판이 반영.
- 29번 정리는 지우지 않고 '정리 대상' 표시만: `arb/mgmt/<실행ID>/marks.json` (그 실행이 쓰는 곳).
- 34번 청소만 실제로 지움. 미리 보기(`plan.json`)를 늘 쓰고, `params.apply = true`일 때만 지움.
  · 정리 표시 뒤 30일이 지났고, 채택되지 않았고, 진행 중 학습·실행이 참조하지 않고, 채택 대기가 아닌 버전 (`v/legacy`는 지우지 않음)
  · 끝난 요청 30일 (복구가 참조하는 원요청은 남김)
  · 완료 기록이 있는 신호 7일. 완료 기록·계획은 원래 신호가 없어진 뒤 30일
  · 확정 신청(`arb/ask`)·생존 신호(`workers/`) 7일
  · 끝난 확정의 `recovery/`는 복구 일과 함께 2b-5b
  못 지운 것(소유자 다름 등)은 계정별 목록으로 남김.
- 23번 복원(Colab Drive 인증)·학습·만들기는 2b-5b.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import access
import arbiter as A
import handlers as H
from arb_io import StoreError

DAY = 86400
MARK_DAYS, REQ_DAYS, SIG_DAYS, DONE_DAYS, ASK_DAYS, HB_DAYS, RECOV_DAYS = 30, 30, 7, 30, 7, 7, 30
KEEP_LOCK_STATES = ("held", "confirm_approved", "quarantine", "reserved", "needs_check")
P_MGMT = A.ARB + "mgmt/"
EXPORT_PENDING = "exports/pending/"
IMPORT_FORMATS_OK = ("CVAT for video 1.1", "CVAT for images 1.1")


class MgmtFailed(RuntimeError):
    """요청대로 할 수 없음 → 결과 'failed:<이유>' (거짓 완료 없음)."""


def _now(env) -> float:
    c = getattr(env, "clock", None)
    return c() if c else time.time()


def params(ctx) -> dict:
    p = ctx.intake.get("params")
    return p if isinstance(p, dict) else {}


def run_lock(ctx) -> dict:
    lk = ctx.env.store.read_json(A.P_LOCK_MGMT)
    if not isinstance(lk, dict) or lk.get("run") != ctx.run:
        raise access.AuthorityLost("관리 잠금이 내 실행이 아님")
    return lk


def task_key(name: str) -> Optional[str]:
    """TASK 이름 → '온실|촬영일|줄|그루' (시험 TASK와 같은 그루·촬영일을 학습에서 빼는 기준, 옛 ctt.test_key)."""
    import cvat_task_tools as ctt
    k = ctt.test_key(name or "")
    return "|".join(k) if k else None


def _write(ctx, path: str, obj: dict):
    ctx.auth("publish").call("write:" + path, lambda: ctx.env.store.write_json(path, obj))


def _read_obj(store, path: str):
    """없으면 None. 있는데 못 읽거나 객체가 아니면 MgmtFailed."""
    if not store.exists(path):
        return None
    try:
        o = store.read_json(path)
    except StoreError:
        raise MgmtFailed("unreadable:" + path)
    if not isinstance(o, dict):
        raise MgmtFailed("unreadable:" + path)
    return o


def current_test(store) -> dict:
    """채택된 시험 TASK 설정 {version, ids, keys}. 채택이 없으면 빈 것. 채택은 있는데 목록을 못 읽으면 실패
    (시험 TASK를 빼지 못한 채 데이터셋을 만들지 않음)."""
    cur = _read_obj(store, A.CURRENT_OF["test_tasks"])
    if not cur or not cur.get("version"):
        return {"version": None, "ids": [], "keys": []}
    vf = _read_obj(store, A.VERSION_FILES_OF["test_tasks"].format(n="", run=cur["version"]))
    if not vf or not vf.get("verified"):
        raise MgmtFailed("test_tasks_unverified")
    return {"version": cur["version"], "ids": [str(x) for x in vf.get("ids") or []], "keys": list(vf.get("keys") or [])}


# ---------------------------------------------------------------- dataset
def export_inputs(store, tasks: List[str], export_rid: Optional[str]) -> Dict[str, dict]:
    """TASK마다 받은 export 기록(J1). export_rid가 있으면 그 요청의 것, 없으면 가장 나중에 받은 것."""
    best: Dict[str, dict] = {}
    for e in store.list(EXPORT_PENDING, False):
        try:
            r = store.read_json(e.path)
        except StoreError:
            continue
        if not isinstance(r, dict) or r.get("status") != "받음" or not r.get("result_file") or not r.get("sha256"):
            continue
        t = str(r.get("task"))
        if t not in tasks or (export_rid and r.get("rid") != export_rid):
            continue
        if r.get("format") not in IMPORT_FORMATS_OK:
            continue
        if t not in best or float(r.get("published_at") or 0) > float(best[t].get("published_at") or 0):
            best[t] = r
    return best


class DatasetBuilder:
    """데이터셋 만들기 엔진. build(zip 목록, 출력 폴더, 설정, val TASK) → {'train': n, 'val': n}."""

    def build(self, zips: List[str], out_dir: str, settings: dict, val_tasks: Optional[dict], progress) -> dict:
        raise NotImplementedError


class RealBuilder(DatasetBuilder):
    """cvat_to_yolo.py를 15번 셀과 같은 설정으로 부름. 영상·원본 이미지 폴더는 실행 호스트가 준비(2b-6)."""
    DEFAULTS = {"MERGE_HEALTH": True, "KEEP_CLASSES": ["healthy_fruit"], "OCCLUDED_POLICY": "keep", "VAL_RATIO": 0.2}

    def __init__(self, scripts_dir, videos_dir, backups_dir, images_dir, frames_dir, imgsz: int = 1920):
        self.scripts, self.dirs, self.imgsz = Path(scripts_dir), (videos_dir, backups_dir, images_dir, frames_dir), imgsz

    def build(self, zips, out_dir, settings, val_tasks, progress):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cvat_to_yolo_run", self.scripts / "cvat_to_yolo.py")
        conv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conv)
        in_dir = Path(out_dir).parent / "in"
        shutil.rmtree(in_dir, ignore_errors=True)
        in_dir.mkdir(parents=True)
        for z in zips:
            shutil.copy2(z, in_dir / Path(z).name)
        v, b, i, f = self.dirs
        conv.INPUT_DIR, conv.OUT_DIR = in_dir, Path(out_dir)
        conv.VIDEOS_DIR, conv.BACKUPS_DIR = Path(v), (Path(b) if b else None)
        conv.IMAGES_DIR, conv.CVAT_FRAMES_DIR = Path(i), Path(f)
        conv.DECODER, conv.TRAIN_IMGSZ = "auto", self.imgsz
        conv.PROGRESS_HOOK = lambda: progress("데이터셋 만드는 중")
        for k, val in dict(self.DEFAULTS, **settings).items():
            setattr(conv, k, val)
        conv.VAL_TASKS = val_tasks
        conv.main()
        return {"train": len(os.listdir(Path(out_dir) / "train/images")),
                "val": len(os.listdir(Path(out_dir) / "val/images"))}


def run_dataset(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    lk = run_lock(ctx)
    art = lk.get("artifact") or {}
    name = art.get("name") or "default"
    p = params(ctx)
    tasks = [str(t) for t in ctx.intake.get("tasks") or []]
    if not tasks:
        raise MgmtFailed("no_tasks")
    test = current_test(store)
    inputs = export_inputs(store, tasks, p.get("export_rid"))
    missing = sorted(set(tasks) - set(inputs))
    if missing:
        raise MgmtFailed("no_export:" + ",".join(missing[:10]))
    use, excluded = {}, []
    for t, r in sorted(inputs.items()):
        k = task_key(r.get("task_name"))
        if t in test["ids"]:
            excluded.append({"task": t, "why": "시험 TASK"})
        elif k and k in test["keys"]:
            excluded.append({"task": t, "why": "같은 그루·촬영일"})
        else:
            use[t] = dict(r, key=k)
    if not use:
        raise MgmtFailed("all_excluded")
    work = Path(env.tmp) / f"ds_{ctx.run}"
    shutil.rmtree(work, ignore_errors=True)
    (work / "zips").mkdir(parents=True)
    zips = []
    for t, r in sorted(use.items()):
        dst = str(work / "zips" / f"{t}.zip")
        with H.ticking(ctx.progress, f"export 받는 중 {t}"):
            store.get_file(r["result_file"], dst)
        if H.sha256_file(dst) != r["sha256"]:
            raise MgmtFailed("export_changed:" + t)       # 받은 export가 기록과 다름 → 만들지 않음
        zips.append(dst)
    val_ids = [str(x) for x in p.get("val_ids") or []]
    val_tasks = {t: t in val_ids for t in use} if val_ids else None
    settings = p.get("convert") if isinstance(p.get("convert"), dict) else {}
    with H.ticking(ctx.progress, "데이터셋 만드는 중"):
        stats = env.builder.build(zips, str(work / "out"), settings, val_tasks, ctx.progress)
    zbase = str(work / "dataset")
    shutil.make_archive(zbase, "zip", str(work / "out"))
    meta = {"name": name, "run": ctx.run, "rid": ctx.rid, "convert": settings, "val_ids": val_ids, "stats": stats,
            "test_version": test["version"], "excluded": excluded,
            "sources": [{"task": t, "task_name": r.get("task_name"), "file": r["result_file"], "sha256": r["sha256"],
                         "task_updated": r.get("task_updated"), "export_rid": r.get("rid")} for t, r in sorted(use.items())],
            "made_at": _now(env)}
    (work / "dataset.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    keys = sorted({r["key"] for r in use.values() if r.get("key")})
    unkeyed = sorted(t for t, r in use.items() if not r.get("key"))
    H.publish_version(store, "dataset", name, ctx.run, {"dataset.zip": zbase + ".zip", "dataset.json": str(work / "dataset.json")},
                      extra={"run": ctx.run, "decision": ctx.decision, "gen": lk.get("gen"), "tasks": sorted(use),
                             # 출처 키를 모르는 TASK가 있으면 task_keys를 적지 않음 → 학습 시작 때 '호환 확인 불가'(b7)
                             **({} if unkeyed else {"task_keys": keys}), "unkeyed_tasks": unkeyed},
                      progress=ctx.progress, auth=lambda: ctx.auth("publish").ensure())
    shutil.rmtree(work, ignore_errors=True)
    return {"report": "done_run", "type_": "dataset", "name": name}


# ---------------------------------------------------------------- test_tasks33
def run_test_tasks(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    lk = run_lock(ctx)
    p = params(ctx)
    ids = [str(x) for x in (p.get("ids") or ctx.intake.get("tasks") or [])]
    if not ids:
        raise MgmtFailed("no_tasks")
    names = {}
    for t in ids:
        try:
            names[t] = env.cvat.get_task(int(t)).get("name", "")
        except Exception:
            raise MgmtFailed("task_unreadable:" + t)       # 이름을 모르면 같은 그루·촬영일을 뺄 수 없음
    keys = sorted({k for k in (task_key(n) for n in names.values()) if k})
    doc = {"ids": ids, "names": names, "keys": keys, "note": str(p.get("note") or ""), "by": ctx.intake.get("requester"),
           "run": ctx.run, "made_at": _now(env)}
    work = Path(env.tmp) / f"tt_{ctx.run}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "test_tasks.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    H.publish_version(store, "test_tasks", "", ctx.run, {"test_tasks.json": str(work / "test_tasks.json")},
                      extra={"run": ctx.run, "decision": ctx.decision, "gen": lk.get("gen"), "ids": ids, "keys": keys},
                      progress=ctx.progress, auth=lambda: ctx.auth("publish").ensure())
    shutil.rmtree(work, ignore_errors=True)
    return {"report": "done_run", "type_": "test_tasks", "name": ""}


# ---------------------------------------------------------------- force_new
def run_force_new(ctx) -> dict:
    p = params(ctx)
    typ, name, ver = p.get("type"), p.get("name"), p.get("version") or None
    if typ not in ("model", "dataset") or not isinstance(name, str) or not name:
        raise MgmtFailed("bad_params")
    if ver is not None and not H.verify_version(ctx.env.store, typ, name, str(ver)):
        raise MgmtFailed("version_unverified")             # 없거나 목록·파일이 맞지 않는 버전은 채택하지 않음
    run_lock(ctx)
    return {"report": "done_job", "result": "done",
            "current_change": {"type": typ, "name": name, "version": None if ver is None else str(ver)}}


# ---------------------------------------------------------------- 버전 목록
def versions(store) -> List[dict]:
    """모든 버전 [{type, name, version, path}] (v/<실행ID>/_files.json 기준)."""
    out = []
    for typ, root in (("model", "runs/"), ("dataset", "datasets/"), ("test_tasks", "sets/test_tasks/")):
        for e in store.list(root, True, include=("_files.json",)):
            parts = e.path[len(root):].split("/")
            if typ == "test_tasks" and len(parts) == 3 and parts[0] == "v":
                out.append({"type": typ, "name": "", "version": parts[1], "path": e.path})
            elif typ != "test_tasks" and len(parts) == 4 and parts[1] == "v":
                out.append({"type": typ, "name": parts[0], "version": parts[2], "path": e.path})
    return out


def protected(store) -> Dict[str, str]:
    """지우면 안 되는 버전 {'type|name|version': 이유}. 하나라도 못 읽으면 MgmtFailed (모르면 지우지 않음)."""
    keep: Dict[str, str] = {}
    adopted = {}
    for v in versions(store):
        k = (v["type"], v["name"])
        if k not in adopted:
            cur = _read_obj(store, A.CURRENT_OF[v["type"]].format(n=v["name"]))
            adopted[k] = (cur or {}).get("version")
        if adopted[k] == v["version"]:
            keep[f"{v['type']}|{v['name']}|{v['version']}"] = "채택됨"
    pins = set()
    for e in store.list(A.P_LOCK_TRAIN, False) + store.list(A.P_LOCK_MGMT, False) + store.list(A.P_LOCK_CREATE, False):
        lk = _read_obj(store, e.path) or {}
        if lk.get("state") in ("running", "needs_check"):
            pins |= {str(lk.get(x)) for x in ("run", "start_version", "start_dataset_version", "start_test_version") if lk.get(x)}
    for e in store.list(A.P_FLAGS, False):
        fl = _read_obj(store, e.path) or {}
        if fl.get("state") == "adopt_wait" and fl.get("run"):
            pins.add(str(fl["run"]))
    for k in list({f"{v['type']}|{v['name']}|{v['version']}" for v in versions(store)}):
        if k.rsplit("|", 1)[1] in pins:
            keep.setdefault(k, "진행 중 실행이 참조 또는 채택 대기")
    return keep


# ---------------------------------------------------------------- cleanup29 (표시만)
def run_cleanup29(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    run_lock(ctx)
    p = params(ctx)
    typ, name = p.get("type") or "model", p.get("name")
    want = {str(x) for x in p.get("versions") or []}
    if typ not in A.CURRENT_OF or (typ != "test_tasks" and not name):
        raise MgmtFailed("bad_params")
    keep = protected(store)
    marks, skipped = [], []
    for v in versions(store):
        if v["type"] != typ or (typ != "test_tasks" and v["name"] != name) or (want and v["version"] not in want):
            continue
        k = f"{v['type']}|{v['name']}|{v['version']}"
        if v["version"] == "legacy":
            skipped.append({"version": v["version"], "why": "legacy 등록 (원본을 지우지 않음)"})
        elif k in keep:
            skipped.append({"version": v["version"], "why": keep[k]})
        else:
            marks.append({"type": typ, "name": v["name"], "version": v["version"], "at": _now(env)})
    if want - {m["version"] for m in marks} - {s["version"] for s in skipped}:
        raise MgmtFailed("unknown_version:" + ",".join(sorted(want - {m["version"] for m in marks} - {s["version"] for s in skipped})))
    _write(ctx, P_MGMT + f"{ctx.run}/marks.json", {"run": ctx.run, "rid": ctx.rid, "marks": marks, "skipped": skipped,
                                                    "at": _now(env)})
    ctx.progress(f"정리 대상 표시 {len(marks)}개 · 건너뜀 {len(skipped)}개")
    return {"report": "done_job", "result": "done"}


# ---------------------------------------------------------------- cleanup34 (청소)
def _done_runs(store) -> set:
    out = set()
    for e in store.list(A.P_RESULTS, False):
        try:
            r = store.read_json(e.path)
        except StoreError:
            continue
        if isinstance(r, dict) and r.get("task") == "run" and r.get("result") == "done":
            out.add(r.get("job"))
    return out


def cleanup_plan(store, now: float) -> dict:
    """지울 것 목록 (지우지 않음). 못 읽는 판단 재료가 있으면 MgmtFailed."""
    plan: Dict[str, list] = {"versions": [], "requests": [], "signals": [], "signal_records": [], "asks": [], "workers": [],
                             "recovery": []}
    keep = protected(store)
    done_runs = _done_runs(store)
    marked: Dict[str, float] = {}
    for e in store.list(P_MGMT, True, include=("marks.json",)):
        run = e.path[len(P_MGMT):].split("/")[0]
        if run not in done_runs:
            continue                                   # 끝나지 않은(권한을 잃은 등) 정리 실행의 표시는 쓰지 않음
        m = _read_obj(store, e.path) or {}
        for x in m.get("marks") or []:
            if not isinstance(x, dict):
                continue
            k = f"{x.get('type')}|{x.get('name')}|{x.get('version')}"
            at = max(float(x.get("at") or 0), e.created)      # 늦은 쪽(보수적)
            marked[k] = min(marked.get(k, at), at)
    for v in versions(store):
        k = f"{v['type']}|{v['name']}|{v['version']}"
        if v["version"] == "legacy" or k in keep or k not in marked or now - marked[k] < MARK_DAYS * DAY:
            continue
        man = _read_obj(store, v["path"]) or {}
        base = v["path"].rsplit("/", 1)[0] + "/"
        plan["versions"].append({"key": k, "manifest": v["path"],
                                 "files": [base + f for f in sorted((man.get("files") or {}))]})
    recov_rids = set()
    for e in store.list(A.P_RECOVERY, True):
        r = _read_obj(store, e.path) or {}
        recov_rids |= {str(r.get(x)) for x in ("rid", "origin_rid") if r.get(x)}
    for d in A.REQ_DIRS:
        for e in store.list(d, False):
            pr = A.parse_req_name(e.path)
            if pr and pr[2] in A.FINAL_STATUS and now - e.modified >= REQ_DAYS * DAY and pr[0] not in recov_rids:
                plan["requests"].append({"path": e.path, "owner": e.owner})
    sig = {A._name(e.path): e for e in store.list(A.P_SIGNALS, False)}
    done = {A._name(e.path): e for e in store.list(A.P_DONE, False)}
    for sid, e in sorted(sig.items()):
        if sid in done and now - e.modified >= SIG_DAYS * DAY:
            plan["signals"].append({"path": e.path, "owner": e.owner})
    for sid, e in sorted(done.items()):
        if sid not in sig and now - e.modified >= DONE_DAYS * DAY:
            # 계획 먼저, 완료 기록은 마지막 (완료 기록이 계획보다 먼저 없어지면 다시 처리될 수 있음)
            plan["signal_records"] += [{"path": A.P_PLAN + sid + ".json", "owner": ""}, {"path": e.path, "owner": e.owner}]
    for e in store.list(A.P_ASK, False):
        if now - e.modified >= ASK_DAYS * DAY:
            plan["asks"].append({"path": e.path, "owner": e.owner})
    for e in store.list(A.P_WORKERS, False):
        if now - e.modified >= HB_DAYS * DAY:
            plan["workers"].append({"path": e.path, "owner": e.owner})
    plan["recovery"] = recovery_plan(store, now)
    return plan


def recovery_plan(store, now: float) -> List[dict]:
    """끝난 확정의 복구 자료 `recovery/<TASK>/<작업번호>/` 중 30일 지난 것 (2b-6).
    남기는 것: 아직 끝나지 않은 TASK 잠금(확정 중·'확인 필요'·복구 예약)이 가리키는 작업, 끝나지 않은 복구 요청의 원래 작업,
    결과를 모르는 만들기 의도(`recovery/create/…`, 사람 확인 전). 판단 재료를 못 읽으면 MgmtFailed."""
    keep_jobs = set()
    for e in store.list(A.P_LOCK_TASK, False):
        lk = _read_obj(store, e.path) or {}
        if lk.get("state") in KEEP_LOCK_STATES:
            keep_jobs |= {str(x) for x in (lk.get("job"), (lk.get("prev") or {}).get("job")) if x}
    for e in store.list(A.P_INTAKE, False):
        it = _read_obj(store, e.path) or {}
        if it.get("kind") == "recovery" and it.get("origin_job"):
            req = [x for d in A.REQ_DIRS for x in store.list(d, False)
                   if (A.parse_req_name(x.path) or ("",))[0] == it.get("rid")]
            if not req or any((A.parse_req_name(x.path) or ("", "", ""))[2] not in A.FINAL_STATUS for x in req):
                keep_jobs.add(str(it["origin_job"]))
    groups: Dict[str, list] = {}
    for e in store.list_any("recovery/", True):
        parts = e.path.split("/")
        if len(parts) < 4:
            continue
        key = "/".join(parts[:4 if parts[1] == "create" else 3]) + "/"
        groups.setdefault(key, []).append(e)
    out = []
    for key, es in sorted(groups.items()):
        parts = key.strip("/").split("/")
        if parts[1] == "create":
            it = next((x for x in es if x.path.endswith("/intent.json")), None)
            st_ = (_read_obj(store, it.path) or {}).get("state") if it else None
            if st_ != "created":
                continue                                   # 결과를 모르는 만들기는 사람이 확인할 때까지 남김
        elif parts[2] in keep_jobs:
            continue
        if now - max(x.modified for x in es) < RECOV_DAYS * DAY:
            continue
        # 결과 계획(result_plan·intent)을 먼저 지워 반쯤 지운 자료가 온전한 복구 자료로 보이지 않게
        files = sorted((x.path for x in es), key=lambda p: (not p.endswith(("result_plan.json", "intent.json")), p))
        out.append({"dir": key, "files": files, "owner": es[0].owner})
    return out


def run_cleanup34(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    run_lock(ctx)
    apply = params(ctx).get("apply") is True
    now = _now(env)
    plan = cleanup_plan(store, now)
    counts = {k: len(v) for k, v in plan.items()}
    _write(ctx, P_MGMT + f"{ctx.run}/plan.json", {"run": ctx.run, "rid": ctx.rid, "apply": apply, "at": now,
                                                   "counts": counts, "plan": plan})
    if not apply:
        return {"report": "done_job", "result": "done"}
    w = ctx.auth("publish")
    deleted, failed = [], {}

    def rm(path, owner=""):
        try:
            w.call("delete:" + path, lambda: store.delete(path))
            deleted.append(path)
            return True
        except StoreError:
            failed.setdefault(owner or "(모름)", []).append(path)
            return False
    for v in plan["versions"]:
        if rm(v["manifest"]):                          # 목록을 먼저 지움 → 반쯤 지운 버전이 완전한 버전으로 보이지 않음
            for f in v["files"]:
                rm(f)
        ctx.progress(f"버전 정리 {v['key']}")
    for k in ("requests", "signals", "asks", "workers"):
        for x in plan[k]:
            rm(x["path"], x.get("owner", ""))
    for r in plan.get("recovery", []):
        if rm(r["files"][0], r.get("owner", "")):
            for f in r["files"][1:]:
                rm(f, r.get("owner", ""))
    recs = plan["signal_records"]
    for i in range(0, len(recs), 2):
        if rm(recs[i]["path"], recs[i].get("owner", "")):
            rm(recs[i + 1]["path"], recs[i + 1].get("owner", ""))
    _write(ctx, P_MGMT + f"{ctx.run}/report.json", {"run": ctx.run, "at": _now(env), "deleted": len(deleted),
                                                     "failed_by_owner": failed})
    ctx.progress(f"청소: 지움 {len(deleted)} · 못 지움 {sum(len(x) for x in failed.values())}")
    return {"report": "done_job", "result": "done"}


def _wrap(fn):
    def run(ctx):
        try:
            return fn(ctx)
        except MgmtFailed as e:
            return {"report": "done_job", "result": "failed:" + str(e)[:120]}
    return run


H.register("dataset", run=_wrap(run_dataset))
H.register("test_tasks33", run=_wrap(run_test_tasks))
H.register("force_new", run=_wrap(run_force_new))
H.register("cleanup29", run=_wrap(run_cleanup29))
H.register("cleanup34", run=_wrap(run_cleanup34))
