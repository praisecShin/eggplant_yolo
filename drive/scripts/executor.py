"""v4.33 1b — 실행기 쪽 규칙 (설계 8판 '실행기 규칙', '보고·결과·인계 계약').

30번 셀·GPU 작업자·CPU 작업 프로세스가 함께 쓰는 뼈대입니다. 실제 일(추론·CVAT 올리기·백업·학습)은
`Handlers`에 넣고, 이 모듈은 **심판과의 약속**만 지킵니다.

- 지금 자격(G 소유)의 세션·epoch가 쓴 배정·잠금만 따름 (세션 지문)
- 보고는 종류별 필수 식별 묶음을 모두 채워서 냄. 재시작 다시 발급으로 잠금 gen이 바뀌면 새 gen으로 다시 냄
- CVAT를 바꾸는 호출·게시는 `Authority`로 감싸 호출 직전에 권한을 확인 (단계별: 승인 뒤에만 쓰기)
- 권한을 잃으면 복원하지 않고 멈춤 보고. 확정 중 예기치 못한 오류도 멈춤 보고 → '확인 필요'
- 취소(요청 접수 기록의 표시)는 매 TASK 시작 전에 확인. 확정 신청 뒤의 TASK는 마침
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import access
import arbiter as A
from arb_io import StoreError, snapshot

SPEC = [
    ("grant", A.P_GRANT, False, None),
    ("state", "arb/assign/", False, None),
    ("state", "arb/locks/", True, None),
    ("state", "arb/intake/", False, None),
    ("state", "arb/results/", False, None),
    ("requests", "requests/", False, None),
    ("requests", "relabel/requests/", False, None),
]
RUN_LANES = ("mgmt", "train", "agg", "create")



def _non_object_unknown(files, unknown):
    """실행기 쪽: 객체가 아닌 파일은 '모름'으로 하고 읽는 목록에서 뺌 — 다른 코드가 그 값을 건드리지 못하게 (b22 R1).
    (심판은 0o부터 그대로 받아 형태 검사, 실행기는 기다림으로)"""
    unknown = set(unknown)
    for p in [p for p, r in files.items() if not isinstance(r.obj, dict)]:
        del files[p]
        if p == A.P_GRANT or A.judgement_kind(p):     # 판정 파일·자격 → 모름(기다림). 심판은 보호 모드
            unknown.add("file:" + p)
            if p == A.P_GRANT:
                unknown.add("grant")
        # 바깥 입력(요청 등)이 객체가 아니면 그냥 뺌 — 심판이 거절하므로 실행기가 멈출 이유가 아님
    return unknown


@dataclass

class Ctx:
    """핸들러가 받는 일의 정보."""
    rid: str
    kind: str
    lane: str
    assign: str
    chunk: Any
    decision: str
    task: Optional[str] = None
    job: Optional[str] = None
    run: Optional[str] = None
    intake: dict = field(default_factory=dict)
    assign_obj: dict = field(default_factory=dict)
    prepared: Any = None
    auth: Callable[[str], access.Authority] = None       # auth('recovery_publish'|'cvat_write'|'publish'|'run')
    step_log: Optional[access.StepLog] = None
    progress: Callable[..., None] = lambda *a, **k: None  # 처리기가 오래 걸리는 일 중간에 부름 → 생존 신호의 진행 시각 (2b-1)
    env: Any = None                                      # 처리기 환경 (저장소·CVAT·임시 폴더) — handlers.Dispatch가 넣음 (2b-2)


class Handlers:
    """실제 일. 필요한 것만 구현합니다."""

    def prepare(self, ctx: Ctx) -> Any:
        """TASK 일: 받기·추론·결과 만들기 (로컬에서 끝까지). 돌려준 값은 ctx.prepared로 commit에 넘어감."""
        return None

    def commit(self, ctx: Ctx) -> str:
        """확정: 복구 자료 게시(ctx.auth('recovery_publish')) → CVAT 쓰기(ctx.auth('cvat_write')). 결과 문자열."""
        return "done"

    def fetch(self, ctx: Ctx) -> bool:
        """받는 중 일: 받을 준비가 됐으면 True (아직이면 False — 다음에 다시 물음)."""
        return True

    def publish(self, ctx: Ctx) -> str:
        """받는 중 일의 게시 (ctx.auth('publish'))."""
        return "done"

    def run(self, ctx: Ctx) -> dict:
        """실행형 일(관리·학습·취합·만들기). 게시 전 ctx.auth('run').
        산출물이면 {'report': 'done_run', 'type_': 'model'|'dataset'|'test_tasks', 'name': …, 'train_keys': […]},
        아니면 {'report': 'done_job', 'result': 'done', 'task_id': …, 'current_change': …}."""
        return {"report": "done_job", "result": "done"}


class Executor:
    def __init__(self, store, session: str, fp: str, caps: List[str], accounts: Dict[str, str], handlers: Handlers,
                 clock=time.time, mono=time.monotonic, sleep=time.sleep, owner: Optional[str] = None):
        self.store, self.me, self.fp, self.caps = store, session, fp, list(caps)
        self.accounts, self.h, self.clock, self.mono, self.sleep, self.owner = accounts, handlers, clock, mono, sleep, owner
        self.seq = 0
        self.sent: set = set()
        self.mem: Dict[Tuple, dict] = {}
        self.touched: set = set()          # 이 세션이 맡았던 요청 (최종 상태 쓰기)
        self.notes: List[str] = []
        self.kernel: Optional[str] = None  # Kaggle 작업자면 노트북 주소 — 마스터가 커널 종료를 확인 (2b-6)
        self.busy: Optional[dict] = None   # 지금 처리기가 하는 일 — 생존 신호에 실어 보냄 (진행이 멈추면 심판이 '멈춘 것 같음')
        self._busy_lock = threading.Lock()

    # ---- 진행 (2b-1)
    def _working(self, c: "Ctx", phase: str):
        ex = self

        class _W:
            def __enter__(self_):
                now = ex.clock()
                with ex._busy_lock:
                    ex.busy = {"lane": c.lane or "task", "rid": c.rid, "kind": c.kind, "task": c.task, "run": c.run,
                               "phase": phase, "since": now, "progress_at": now, "note": ""}
                return self_

            def __exit__(self_, *a):
                with ex._busy_lock:
                    ex.busy = None
                return False
        return _W()

    def _progress(self, note: str = ""):
        with self._busy_lock:
            if self.busy is not None:
                self.busy = dict(self.busy, progress_at=self.clock(), note=str(note)[:120])

    # ---- 쓰기
    def heartbeat(self, stopping: bool = False):
        with self._busy_lock:
            busy = dict(self.busy) if self.busy else None
        rec = {"session": self.me, "fp": self.fp, "caps": self.caps, "hb": self.clock(), "stopping": stopping}
        if self.kernel:
            rec["kernel"] = self.kernel
        if busy and not stopping:
            rec["busy"] = busy
        self.store.write_json(access.worker_record_name(self.me, self.fp), rec, owner=self.owner)

    def _ask(self, typ: str, res: str, **kw):
        self.seq += 1
        self.store.write_json(f"{A.P_ASK}{self.me}__{res}__{self.seq:06d}.json",
                              dict(kw, type=typ, session=self.me, at=self.clock()), owner=self.owner)

    def _once(self, key: Tuple, fn: Callable[[], None]):
        if key not in self.sent:
            fn()
            self.sent.add(key)

    # ---- 권한 확인
    def _fresh(self, lock_path: str):
        files, unknown, _ = snapshot(self.store, [("grant", A.P_GRANT, False, None), ("state", lock_path, False, None)],
                                     None, self.clock)
        return files, _non_object_unknown(files, unknown)

    def _authority(self, check: Callable[[], Tuple[bool, str]], log: Optional[access.StepLog]) -> access.Authority:
        return access.Authority(check, clock=self.mono, sleep=self.sleep, step_log=log)

    def _task_auth(self, ctx: Ctx, phase: str) -> access.Authority:
        lp = A.P_LOCK_TASK + f"{ctx.task}.json"

        def check():
            try:
                files, unknown = self._fresh(lp)
            except StoreError:
                return False, "wait_reissue"
            if unknown:
                return False, "wait_reissue"                 # 못 읽음 → 잠시 기다림 (한도 안에서)
            return A.executor_may_follow(files, self.accounts, self.me, ctx.task, ctx.decision, phase, ctx.job)
        return self._authority(check, ctx.step_log)

    def _run_auth(self, ctx: Ctx, lock_path: str) -> access.Authority:
        def check():
            try:
                files, unknown = self._fresh(lock_path)
            except StoreError:
                return False, "wait_reissue"
            if unknown:
                return False, "wait_reissue"
            return A.run_may_follow(files, self.accounts, self.me, lock_path, ctx.run, ctx.decision)
        return self._authority(check, ctx.step_log)

    def _step_log(self, task: str, job: str) -> access.StepLog:
        return access.StepLog(lambda path, d: self.store.write_json(path, d, owner=self.owner), task, job, clock=self.clock)

    # ---- 한 걸음
    def step(self) -> str:
        """파일을 읽고 할 수 있는 일을 하나씩 진행. 'wait'(읽지 못함·자격 없음) | 'idle' | 'work'."""
        try:
            files, unknown, _ = snapshot(self.store, SPEC, None, self.clock)
            unknown = _non_object_unknown(files, unknown)
        except StoreError:
            return "wait"
        if unknown:
            return "wait"                   # 읽지 못한 것이 하나라도 있으면 이 차례는 일하지 않고 기다림 — 심판의 판정 보류와 같은 규칙 (b22 R1)
        g = files.get(A.P_GRANT)
        if not g or not self.accounts.get("G") or g.owner != self.accounts["G"]:
            return "wait"
        grant = g.obj or {}
        ep = int(grant.get("epoch", -1))

        def obj(path):
            r = files.get(path)
            return r.obj if r and ("file:" + path) not in unknown else None

        worked = False
        for path in sorted(files):
            if not path.startswith(A.P_ASSIGN):
                continue
            a = files[path].obj or {}
            if a.get("session") != self.me or a.get("state") != "active" or not A.stamp_ok(a, grant) \
                    or int(a.get("epoch", -1)) != ep:
                continue
            key = A._name(path)
            intake = obj(A.P_INTAKE + f"{a['rid']}.json")
            if intake is None:
                continue                                       # 접수 기록을 못 읽음 → 이번에는 건너뜀
            self.touched.add(a["rid"])
            lane = a.get("lane")
            base = Ctx(rid=a["rid"], kind=intake.get("kind"), lane=lane, assign=key, chunk=a.get("chunk"),
                       decision=a["decision"], run=a.get("run"), intake=intake, assign_obj=a)
            if lane in RUN_LANES:
                worked |= self._step_run(base, files, grant, ep)
            elif lane == "read":
                worked |= self._step_read(base, files, grant, ep, unknown)
            else:
                worked |= self._step_tasks(base, files, grant, ep, unknown)
        if "requests" not in unknown:
            self._finalize(files, grant)
        return "work" if worked else "idle"

    def _results_for(self, files, rid: str) -> Dict[str, dict]:
        out = {}
        for p, r in files.items():
            if p.startswith(A.P_RESULTS) and (r.obj or {}).get("rid") == rid and (r.obj or {}).get("by_session"):
                out[str(r.obj.get("task"))] = r.obj
        return out

    def _lock(self, files, grant, t: str) -> Optional[dict]:
        r = files.get(A.P_LOCK_TASK + f"{t}.json")
        return r.obj if r and A.stamp_ok(r.obj, grant) else None

    # ---- TASK 일
    def _step_tasks(self, c: Ctx, files, grant, ep, unknown) -> bool:
        a, worked = c.assign_obj, False
        done = self._results_for(files, c.rid)
        stopping = bool(a.get("stop_signal"))
        canceled = bool(c.intake.get("cancel_signal"))
        remaining = []
        for t in [str(x) for x in a.get("tasks", [])]:
            if t in done:
                continue
            remaining.append(t)
            lk = self._lock(files, grant, t)
            if not lk or lk.get("session") != self.me or lk.get("decision") != c.decision or int(lk.get("epoch", -1)) != ep:
                continue                                       # 아직 잠금이 안 왔거나 다시 발급을 기다림
            m = self.mem.setdefault((c.assign, t), {"job": f"{self.me}-{t}-{c.chunk}-{A.short_hash(c.assign)[:6]}"})
            ctx = Ctx(**{**c.__dict__, "task": t, "job": m["job"], "prepared": m.get("prepared")})
            ctx.step_log = m.setdefault("log", self._step_log(t, m["job"]))
            ctx.auth = lambda phase, ctx=ctx: self._task_auth(ctx, phase)
            ctx.progress = self._progress
            st = lk.get("state")
            if st == "held":
                if m.get("failed"):
                    self._once(("result", t, lk["gen"], ep), lambda: self._ask(
                        "result", t, rid=c.rid, chunk=c.chunk, epoch=ep, gen=lk["gen"], decision=c.decision,
                        task=t, result=m["failed"]))
                    continue
                if canceled or stopping:
                    if canceled:                               # 준비 단계의 취소 → 바로 멈춤
                        self._once(("result", t, lk["gen"], ep), lambda: self._ask(
                            "result", t, rid=c.rid, chunk=c.chunk, epoch=ep, gen=lk["gen"], decision=c.decision,
                            task=t, result="canceled"))
                    continue
                if "prepared_ok" not in m:
                    try:
                        with self._working(ctx, "prepare"):
                            m["prepared"] = self.h.prepare(ctx)
                        m["prepared_ok"] = True
                    except Exception as e:
                        m["failed"] = "failed:" + type(e).__name__
                    worked = True
                    continue
                # 확정 신청은 TASK 하나씩 (11/17 결정, b24 E15): 같은 배정의 앞 TASK가 확정 중이면 끝날 때까지 기다림
                # → 취소·정지 뒤에 쓰이는 것은 지금 확정 중인 TASK 하나뿐
                if any(self._confirming(c, files, grant, o, done) for o in a.get("tasks", []) if str(o) != t):
                    continue
                m["asked"] = True
                self._once(("confirm", t, lk["gen"], ep), lambda: self._ask(
                    "confirm", t, rid=c.rid, chunk=c.chunk, job=m["job"], epoch=ep, gen=lk["gen"],
                    decision=c.decision, task=t, recovery_dir=ctx.step_log.dir()))
            elif st == "confirm_approved" and lk.get("job") == m["job"]:
                if "committed" not in m and "stopped" not in m:
                    try:
                        with self._working(ctx, "commit"):
                            m["committed"] = self.h.commit(ctx) or "done"
                    except access.AuthorityLost as e:
                        m["stopped"] = "lost"                  # 복원하지 않고 멈춤
                        self.notes.append(f"lost {t}: {e}")
                    except Exception as e:
                        m["stopped"] = "commit_error:" + type(e).__name__   # 어디까지 썼는지 모름 → 확인 필요
                    worked = True
                if "stopped" in m:
                    self._once(("stop", t, ep), lambda: self._ask(
                        "stop", t, rid=c.rid, chunk=c.chunk, epoch=ep, decision=c.decision, task=t, reason=m["stopped"]))
                elif "committed" in m:
                    self._once(("end", t, lk["gen"], ep), lambda: self._ask(
                        "end", t, rid=c.rid, chunk=c.chunk, job=m["job"], epoch=ep, gen=lk["gen"],
                        decision=c.decision, task=t, result=m["committed"]))
        approved = any((self._lock(files, grant, t) or {}).get("state") == "confirm_approved" for t in remaining)
        if not remaining or (stopping and not approved):       # 멈춤 표시: 확정 중인 TASK만 마치고 반납
            self._once(("release", c.assign, ep), lambda: self._ask(
                "release", "assign", assign=c.assign, rid=c.rid, chunk=c.chunk, epoch=ep, decision=c.decision))
        return worked

    def _confirming(self, c: Ctx, files, grant, t, done) -> bool:
        """이 배정의 TASK t가 확정 신청했거나 확정 중이고 아직 결과가 없는가."""
        t = str(t)
        if t in done:
            return False
        m = self.mem.get((c.assign, t)) or {}
        if "stopped" in m:
            return False                                   # 멈춤 보고한 TASK는 심판이 '확인 필요'로 넘김 — 다음을 막지 않음
        lk = self._lock(files, grant, t) or {}
        if lk.get("session") != self.me or lk.get("decision") != c.decision:
            return False
        return lk.get("state") == "confirm_approved" or (lk.get("state") == "held" and bool(m.get("asked")))

    # ---- 받는 중 일 (백업·export)
    def _step_read(self, c: Ctx, files, grant, ep, unknown) -> bool:
        a, worked = c.assign_obj, False
        done = self._results_for(files, c.rid)
        remaining = [str(x) for x in a.get("tasks", []) if str(x) not in done]
        canceled = bool(c.intake.get("cancel_signal"))
        for t in remaining:
            m = self.mem.setdefault((c.assign, t), {"job": f"{self.me}-{t}-{c.chunk}-{A.short_hash(c.assign)[:6]}"})
            ctx = Ctx(**{**c.__dict__, "task": t, "job": m["job"]})
            ctx.step_log = m.setdefault("log", self._step_log(t, m["job"]))
            ctx.auth = lambda phase, ctx=ctx: self._task_auth(ctx, "publish")
            ctx.progress = self._progress
            lk = self._lock(files, grant, t)
            mine = bool(lk) and lk.get("session") == self.me and lk.get("decision") == c.decision \
                and lk.get("publish") and lk.get("state") == "held" and int(lk.get("epoch", -1)) == ep
            if mine:
                if "published" not in m:
                    try:
                        with self._working(ctx, "publish"):
                            m["published"] = self.h.publish(ctx) or "done"
                    except Exception as e:
                        m["published"] = "failed:" + type(e).__name__
                    worked = True
                self._once(("result", t, lk["gen"], ep), lambda: self._ask(
                    "result", t, rid=c.rid, chunk=c.chunk, epoch=ep, gen=lk["gen"], decision=c.decision,
                    task=t, result=m["published"]))
                continue
            if canceled:
                continue
            if not m.get("ready"):
                try:
                    with self._working(ctx, "fetch"):
                        m["ready"] = bool(self.h.fetch(ctx))
                except Exception as e:
                    m["ready"], m["published"] = True, "failed:" + type(e).__name__
                worked = True
            if m.get("ready"):
                self._once(("publish_lock", t, ep, self.mono() // 60), lambda: self._ask(
                    "publish_lock", t, rid=c.rid, chunk=c.chunk, epoch=ep, decision=c.decision, task=t))
        if not remaining or canceled:
            self._once(("release", c.assign, ep), lambda: self._ask(
                "release", "assign", assign=c.assign, rid=c.rid, chunk=c.chunk, epoch=ep, decision=c.decision))
        return worked

    # ---- 실행형 일
    def _run_lock_path(self, c: Ctx, files) -> str:
        if c.lane == "mgmt":
            return A.P_LOCK_MGMT
        if c.lane == "agg":
            return A.P_LOCK_AGG
        if c.lane == "create":
            return A.P_LOCK_CREATE + f"{c.assign_obj.get('key')}.json"
        for p, r in files.items():
            if p.startswith(A.P_LOCK_TRAIN) and (r.obj or {}).get("run") == c.run:
                return p
        return ""

    def _step_run(self, c: Ctx, files, grant, ep) -> bool:
        lp = self._run_lock_path(c, files)
        r = files.get(lp)
        lk = r.obj if r and A.stamp_ok(r.obj, grant) else None
        if not lk or lk.get("run") != c.run or lk.get("session") != self.me or lk.get("state") != "running" \
                or int(lk.get("epoch", -1)) != ep:
            return False
        m = self.mem.setdefault(("run", c.run), {})
        worked = False
        if "out" not in m:
            ctx = Ctx(**{**c.__dict__})
            ctx.step_log = self._step_log("run", c.run)
            ctx.auth = lambda phase, ctx=ctx: self._run_auth(ctx, lp)
            ctx.progress = self._progress
            try:
                with self._working(ctx, "run"):
                    m["out"] = dict(self.h.run(ctx) or {"report": "done_job", "result": "done"})
            except access.AuthorityLost as e:
                m["out"] = {"report": "stop_run", "reason": "lost"}     # 게시하지 않고 멈춤 보고 → 심판이 '확인 필요'로 (Q2)
                self.notes.append(f"lost run {c.run}: {e}")
            except access.NeedsCheck as e:
                m["out"] = {"report": "stop_run", "reason": e.reason}   # 결과를 확정할 수 없음 → '확인 필요' (b26 U2)
                self.notes.append(f"needs_check run {c.run}: {e}")
            except Exception as e:
                m["out"] = {"report": "done_job", "result": "failed:" + type(e).__name__}
            worked = True
        out = m["out"]
        if out:
            common = dict(lane=c.lane, run=c.run, rid=c.rid, epoch=ep, gen=lk["gen"], decision=c.decision)
            if c.lane == "create":
                common["key"] = c.assign_obj.get("key")
            if c.lane == "train":
                common["name"] = lk.get("model")
            if out.get("report") == "stop_run":
                self._once(("stop_run", c.run, ep), lambda: self._ask(
                    "stop_run", "run", lane=c.lane, run=c.run, rid=c.rid, epoch=ep, decision=c.decision,
                    name=common.get("name"), key=common.get("key"), reason=out.get("reason")))
            elif out.get("report") == "done_run":
                art = lk.get("artifact") or {}
                self._once(("done", c.run, lk["gen"], ep), lambda: self._ask(
                    "done_run", "run", **{**common, "type_": out.get("type_", art.get("type")),
                                          "name": out.get("name", art.get("name")),
                                          "train_keys": out.get("train_keys")}))
            else:
                self._once(("done", c.run, lk["gen"], ep), lambda: self._ask(
                    "done_job", "run", **{**common, "result": out.get("result", "done"), "task_id": out.get("task_id"),
                                          "current_change": out.get("current_change")}))
        return worked

    # ---- 요청의 최종 상태 (마지막 묶음 뒤 이름 바꾸기)
    def _finalize(self, files, grant):
        for rid in sorted(self.touched):
            r = files.get(A.P_INTAKE + f"{rid}.json")
            it = r.obj if r else None
            if not it:
                continue
            req_path = next((p for p in files if (p.startswith("requests/") or p.startswith("relabel/requests/"))
                             and (A.parse_req_name(p) or ("",))[0] == rid), None)
            if not req_path:
                continue
            _, kind, status = A.parse_req_name(req_path)
            if status in A.FINAL_STATUS:
                self.touched.discard(rid)
                continue
            if any((x.obj or {}).get("rid") == rid and (x.obj or {}).get("state") == "active"
                   for p, x in files.items() if p.startswith(A.P_ASSIGN)):
                continue
            res = self._results_for(files, rid)
            tasks = [str(t) for t in it.get("tasks") or []]
            if tasks and it.get("kind") not in A.TASKLESS_KINDS:      # 숨김처럼 TASK를 적어도 실행 하나로 끝나는 일 (2b-4)
                if any(t not in res for t in tasks):
                    if not it.get("cancel_signal"):
                        continue
                    final = "canceled"
                else:
                    rs = [str(res[t].get("result")) for t in tasks]
                    final = "canceled" if it.get("cancel_signal") and any(x == "canceled" for x in rs) else (
                        "failed" if any(x.startswith("failed") for x in rs) else "done")
            else:
                rr = res.get("run") or res.get("create")
                if not rr:
                    continue
                final = "failed" if str(rr.get("result")).startswith("failed") else "done"
            dst = req_path.rsplit("__", 1)[0] + f"__{final}.json"
            try:
                self.store.rename(req_path, dst)
                self.touched.discard(rid)
            except StoreError:
                pass
