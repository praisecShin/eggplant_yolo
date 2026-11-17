"""받는 중 일: 백업·export 처리기 (2b-2).

v4.32의 `run_cpu_backup_and_export`·`run_cpu_export`·`poll_waiting_backups`·30번 셀 `_rl_backup`·`_rl_bk_poll`을
'준비 요청·상태 확인'(fetch)과 '받기·게시'(publish)로 나눴습니다.

- fetch: 처음에는 TASK 정보를 읽고 서버에 준비를 요청 → 받는 중 기록 `backups|exports/pending/<요청ID>__<TASK>.json`
  (요청·TASK마다 파일 하나, J1). 기록에 요청 시각의 CVAT 라벨 버전(`task_updated`)을 남김(G9).
  다음 차례부터는 같은 작업 번호의 상태만 물음 — 실행기가 바뀌어도 다시 요청하지 않음.
- publish: 게시 잠금을 받은 뒤 받기 → `backups|exports/<요청ID>/<TASK 이름>__<TASK ID>.zip`에 올림 →
  다시 받아 해시·크기 확인 → 받는 중 기록을 '받음'으로. 확인이 안 되면 실패(거짓 완료 없음).
- 요청의 params: export는 format(기본 'CVAT for images 1.1')·images(기본 False).
- 바뀐 점: 백업 뒤 검토 TASK export를 이어 붙이던 v4.32 동작은 없앴습니다 — 수집기가 검토 단계로 바뀔 때 export
  요청을 따로 만듭니다(11/12 결정). 백업 현황판(backup_status.csv)·export 목록 요약은 취합 일(2b-4)이 받는 중 기록에서 만듭니다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import handlers as H
from arb_io import StoreError

PENDING_DIR = {"backup": "backups/pending/", "export": "exports/pending/"}
OUT_DIR = {"backup": "backups/", "export": "exports/"}
DEFAULT_FORMAT = "CVAT for images 1.1"


class JobFailed(RuntimeError):
    pass


class TaskMissing(RuntimeError):
    pass


def file_stem(name: str) -> str:
    """cvat_task_tools.export_file_stem과 같은 규칙 (그 모듈을 부르지 않고 — cvat-sdk 없이 시험 가능)."""
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", name or "")


def pending_path(ctx) -> str:
    return f"{PENDING_DIR[ctx.kind]}{ctx.rid}__{ctx.task}.json"


def _read(store, path):
    if not store.exists(path):
        return None
    rec = store.read_json(path)                        # 있는데 못 읽으면 StoreError → 이번 차례는 실패로 보지 않고 다시
    return rec if isinstance(rec, dict) else None


def fetch(ctx) -> bool:
    env = ctx.env
    store, cv, pp = env.store, env.cvat, pending_path(ctx)
    try:
        rec = _read(store, pp)
    except StoreError:
        ctx.progress("받는 중 기록을 못 읽음 — 다음에 다시")
        return False
    if rec and rec.get("job") and rec.get("status") in ("requested", "started"):
        st = cv.job_status(rec["job"])
        if st == "finished":
            rec.update(status="ready", ready_at=env_now(env))
            store.write_json(pp, rec)
            return True
        if st == "failed":
            rec.update(status="failed", failed_at=env_now(env))
            store.write_json(pp, rec)
            raise JobFailed(f"서버 준비 실패 ({rec['job']})")
        if st == "started" and rec.get("status") != "started":
            rec["status"] = "started"
            store.write_json(pp, rec)
        ctx.progress(f"{ctx.kind} 준비 중 ({st})")
        return False
    if rec and rec.get("status") in ("ready", "받음"):
        return True
    tid = int(ctx.task)
    try:
        info = cv.get_task(tid)
    except Exception as e:
        raise TaskMissing(f"TASK {tid} 정보를 못 읽음 ({type(e).__name__})")
    params = ctx.intake.get("params") if isinstance(ctx.intake.get("params"), dict) else {}
    if ctx.kind == "backup":
        job, fmt, images = cv.request_backup(tid), None, None
    else:
        fmt, images = str(params.get("format") or DEFAULT_FORMAT), bool(params.get("images", False))
        job = cv.request_export(tid, fmt, images=images)
    rec = {"rid": ctx.rid, "task": str(tid), "kind": ctx.kind, "job": job, "status": "requested",
           "requested_at": env_now(env), "task_name": info.get("name", ""), "task_updated": info.get("updated", ""),
           "format": fmt, "images": images, "assign": ctx.assign}
    store.write_json(pp, rec)
    ctx.progress(f"{ctx.kind} 준비 요청 {job}")
    return False


def publish(ctx) -> str:
    env = ctx.env
    store, cv, pp = env.store, env.cvat, pending_path(ctx)
    rec = _read(store, pp)
    if not rec or rec.get("status") not in ("ready", "받음") or not rec.get("job"):
        raise JobFailed("받을 준비가 안 된 기록")
    tid = rec["task"]
    fname = f"{file_stem(rec.get('task_name')) or 'task'}__{tid}.zip"
    base = f"{OUT_DIR[ctx.kind]}{ctx.rid}/"
    local = str(Path(env.tmp) / f"{ctx.kind}_{ctx.rid}_{tid}.zip")
    with H.ticking(ctx.progress, "받는 중"):
        cv.download(rec["job"], local)
    ctx.progress("받음")
    want = {fname: {"sha256": H.sha256_file(local), "size": os.path.getsize(local)}}

    def put():
        with H.ticking(ctx.progress, "올리는 중"):
            store.put_file(local, base + fname)
        bad = H.check_files(store, base, want, ctx.progress)
        if bad:
            raise H.VerifyError("올린 파일이 다름: " + ", ".join(bad))
    ctx.auth("publish").call("publish", put)
    rec.update(status="받음", result_file=base + fname, sha256=want[fname]["sha256"], size=want[fname]["size"],
               published_at=env_now(env))
    store.write_json(pp, rec)
    try:
        os.remove(local)
    except OSError:
        pass
    return "done"


def env_now(env):
    clock = getattr(env, "clock", None)
    if clock:
        return clock()
    import time
    return time.time()


for _k in ("backup", "export"):
    H.register(_k, fetch=fetch, publish=publish)
