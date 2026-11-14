"""v4.33 심판(판정) 함수 — 설계 8판 `docs/DESIGN_v4.33.md` (v4.33.0b: 1a 검토 M1~M12 반영).

**입출력이 없는 순수 함수**입니다. 마스터 판정 루프가 Drive 목록·파일을 읽어 `files` 사전
(경로 → FileRec)으로 넘기면 `decide_round()`가 이번 회차에 쓸 파일 목록(Write)을 차례대로 돌려줍니다.
- 입력 `files`는 바꾸지 않습니다. 회차 안에서는 사본 위에서 판단합니다 (M7).
- 심판은 회차 사이에 기억이 없습니다. 쓰기 목록 어디에서 끊겨도 다음 회차가 파일만 보고 이어 갑니다.

주요 규칙:
  - 자격: G 소유 `jobs/ARBITER_GRANT.json`만 믿음. 소유자를 못 읽으면 판정하지 않음 (M8)
  - 세션 지문: 심판이 쓰는 모든 파일에 by_session·by_epoch. 읽을 때는 공통 `trusted()`를 거침 (M9).
    증명이 아니라 실수 방지 장치 (L2)
  - 인계: 새 epoch의 다시 발급을 마치면 `arb/handover/<epoch>.json`. 이 기록이 없으면 다른 판정을 하지 않음 (M8)
  - 보고: 종류별 필수 식별 묶음이 모두 맞아야 반영 (M3). 결과 기록을 잠금보다 먼저 씀 (M6)
  - 배정·잠금 재조정: 배정은 있는데 잠금이 빠졌으면 매 회차 채움 (M5)
  - 작업 종류: TASK 일·관리 일·학습·취합·새 TASK 만들기마다 잠금과 완료 보고 (M10)
  - '모름': 목록이나 파일을 못 읽으면 그 대상에 대한 승인·회수·해제를 하지 않음 (M8)
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

VERSION = "4.33.0d"

# ---------------------------------------------------------------- 경로
ARB = "arb/"
P_GRANT = "jobs/ARBITER_GRANT.json"
P_ARBITER = ARB + "ARBITER.json"
P_HANDOVER = ARB + "handover/"
P_INTAKE = ARB + "intake/"
P_RESULTS = ARB + "results/"
P_ASSIGN = ARB + "assign/"
P_LOCK_TASK = ARB + "locks/task/"
P_LOCK_MGMT = ARB + "locks/mgmt.json"
P_LOCK_AGG = ARB + "locks/aggregate.json"
P_LOCK_TRAIN = ARB + "locks/train/"
P_LOCK_CREATE = ARB + "locks/create/"
P_ASK = ARB + "ask/"
P_PLAN = ARB + "signal_plan/"
P_DONE = ARB + "signal_done/"
P_HOLD = ARB + "holds/"
P_FLAGS = ARB + "flags/"
P_RECOVERY = ARB + "recovery/"
P_ALERT = ARB + "alerts/"
P_SIGNALS = "jobs/signals/"
P_WORKERS = "workers/"
REQ_DIRS = ("requests/", "relabel/requests/")
CURRENT_OF = {"model": "runs/{n}/CURRENT.json", "dataset": "datasets/{n}/CURRENT.json",
              "test_tasks": "sets/test_tasks/CURRENT.json"}
VERSION_FILES_OF = {"model": "runs/{n}/v/{run}/_files.json", "dataset": "datasets/{n}/v/{run}/_files.json",
                    "test_tasks": "sets/test_tasks/v/{run}/_files.json"}

# ---------------------------------------------------------------- 설정
HB_STALE = 180
CHOICE_WAIT = 900
CHUNK_TASKS = 5
DAY_START, DAY_END = 8, 19
CRITICAL = {"grant", "requests", "workers", "asks", "state", "artifacts"}
BLIND = {"state", "artifacts"}      # 판정 정본(arb/)·버전 파일 목록을 못 읽음 → 보고·신호도 반영하지 않음

READ_KINDS = {"backup", "export"}
AGG_KINDS = {"hide", "unhide", "refresh"}
MGMT_KINDS = {"dataset", "force_new", "restore23", "cleanup29", "test_tasks33", "cleanup34"}
TRAIN_KINDS = {"train"}
CREATE_KINDS = {"create16", "create17"}
TASKLESS_KINDS = MGMT_KINDS | TRAIN_KINDS | CREATE_KINDS | AGG_KINDS
AUTO_KINDS = {"track", "shape", "auto", "backup", "export", "refresh"}   # 수집기(G)가 만들 수 있는 요청
DEFAULT_ROUTE = {
    "track": {"gpu"}, "shape": {"gpu"}, "auto": {"gpu"}, "upload_submission": {"gpu", "cpu"},
    "backup": {"cpu"}, "export": {"cpu"},
    "hide": {"agg"}, "unhide": {"agg"}, "refresh": {"agg"},
    "dataset": {"cpu"}, "force_new": {"cpu"}, "restore23": {"colab_oauth"}, "cleanup29": {"cpu"},
    "test_tasks33": {"cpu"}, "cleanup34": {"cpu"},
    "train": {"gpu"}, "create16": {"cpu"}, "create17": {"cpu"}, "recovery": {"gpu", "cpu"},
}
GPU_STARTABLE = {"gpu"}          # 마스터가 스스로 켤 수 있는 실행기 능력 (Kaggle GPU)
FINAL_STATUS = {"done", "failed", "canceled", "needs_check"}
PERM_OF_SIGNAL = {"cancel": "request", "confirm_choice": "request", "approve_night": "request",
                  "stop": "release", "release": "release", "adopt_choice": "release", "run_choice": "release"}

# 보고 종류별 필수 식별 (M3)
IDENT_TASK = ("rid", "chunk", "job", "epoch", "gen", "decision", "session", "task")
REPORT_KEYS = {
    "confirm": IDENT_TASK,
    "end": IDENT_TASK + ("result",),
    "stop": ("rid", "chunk", "epoch", "decision", "session", "task"),
    "result": ("rid", "chunk", "epoch", "gen", "decision", "session", "task", "result"),
    "release": ("assign", "rid", "chunk", "epoch", "decision", "session"),
    "publish_lock": ("rid", "chunk", "epoch", "decision", "session", "task"),
    "done_run": ("lane", "type_", "name", "run", "rid", "epoch", "gen", "decision", "session"),
    "done_job": ("lane", "run", "rid", "epoch", "gen", "decision", "session", "result"),
}


# ---------------------------------------------------------------- 자료형
@dataclass
class FileRec:
    obj: Any
    owner: str = ""
    created: float = 0.0
    modified: float = 0.0


@dataclass
class Write:
    path: str
    obj: Any
    mode: str = "put"        # put | create (없을 때만)
    why: str = ""


@dataclass
class Cfg:
    me: str
    accounts: Dict[str, str]
    people: List[dict]
    route: Dict[str, set] = field(default_factory=lambda: dict(DEFAULT_ROUTE))
    tz_offset_h: int = 9


@dataclass
class Inputs:
    now: float
    files: Dict[str, FileRec]
    list_started_at: float
    unknown: set = field(default_factory=set)     # {'grant','requests','workers','asks','signals','file:<경로>'}
    kernel_status: Dict[str, str] = field(default_factory=dict)
    import_pending: Dict[str, Optional[bool]] = field(default_factory=dict)
    waiting: Dict[str, float] = field(default_factory=dict)


@dataclass
class Result:
    writes: List[Write] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    acting: bool = True


# ---------------------------------------------------------------- 도우미
def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".json", 1)[0]


def parse_req_name(path: str) -> Optional[Tuple[str, str, str]]:
    n = _name(path)
    if not n.startswith("REQ_"):
        return None
    parts = n[4:].split("__")
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def is_day(now: float, tz_h: int = 9) -> bool:
    h = int(((now + tz_h * 3600) % 86400) // 3600)
    return DAY_START <= h < DAY_END


def next_morning(now: float, tz_h: int = 9) -> float:
    local = now + tz_h * 3600
    t = local - (local % 86400) + DAY_START * 3600
    if t <= local:
        t += 86400
    return t - tz_h * 3600


def short_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def create_key(server: str, name: str) -> str:
    """같은 이름 만들기 잠금 키: 서버·정규화한 이름 (CVAT 계정은 하나)."""
    return short_hash(f"{server}|{(name or '').strip().lower()}")


def result_path(rid: str, task: str, job: str) -> str:
    return P_RESULTS + f"{rid}__{task}__{job}.json"


# ---------------------------------------------------------------- 보기
class View:
    def __init__(self, cfg: Cfg, inp: Inputs, res: Result):
        self.cfg, self.inp, self.res = cfg, inp, res
        self.now, self.me = inp.now, cfg.me
        self.f: Dict[str, FileRec] = {p: FileRec(copy.deepcopy(r.obj), r.owner, r.created, r.modified)
                                      for p, r in inp.files.items()}          # 입력은 바꾸지 않음 (M7)
        self.unknown_files: Set[str] = {u[5:] for u in inp.unknown if u.startswith("file:")}
        self.g_account = cfg.accounts.get("G", "")
        self.alerts: List[dict] = []
        g = self.f.get(P_GRANT)
        self.grant = None
        if g is not None and P_GRANT not in self.unknown_files:
            if self.g_account and g.owner == self.g_account:
                self.grant = g.obj or {}
            else:
                self.alerts.append({"kind": "grant_untrusted", "owner": g.owner or "(모름)"})
        self.ep = int((self.grant or {}).get("epoch", 0))
        self.people_by_acct = {p.get("account"): p for p in cfg.people if p.get("account")}
        self.people_by_id = {p.get("id"): p for p in cfg.people}
        self._load()

    # ---- 믿을 수 있는 읽기 (세션 지문, M9)
    def trusted(self, path: str, quiet: bool = False) -> Optional[dict]:
        r = self.f.get(path)
        if r is None or path in self.unknown_files:
            return None
        o = r.obj if isinstance(r.obj, dict) else None
        if o is None:
            return None
        bs, be = o.get("by_session"), o.get("by_epoch")
        why = ""
        if bs is None or be is None:
            why = "unstamped"
        elif int(be) > self.ep:
            why = "future_epoch"
        elif int(be) == self.ep and bs != self.me:
            why = "other_session_same_epoch"
        if why:
            if not quiet:
                self.alerts.append({"kind": "foreign_judgement", "path": path, "why": why, "by_session": bs})
            return None
        return o

    def _trusted_under(self, prefix: str) -> Dict[str, dict]:
        out = {}
        for p in sorted(self.f):
            if p.startswith(prefix) and p.endswith(".json"):
                o = self.trusted(p)
                if o is not None:
                    out[_name(p)] = o
        return out

    def _load(self):
        self.arbiter = self.trusted(P_ARBITER, quiet=True) or {}
        self.handover = self.trusted(P_HANDOVER + f"{self.ep}.json", quiet=True)
        # 요청 (사람·수집기·심판이 만든 파일: 소유 계정으로 접수)
        self.requests: Dict[str, dict] = {}
        for d in REQ_DIRS:
            for p in sorted(self.f):
                if not (p.startswith(d) and p.endswith(".json")) or "/" in p[len(d):] or p in self.unknown_files:
                    continue
                pr = parse_req_name(p)
                if not pr:
                    continue
                r = self.f[p]
                rid, kind, status = pr
                obj = dict(r.obj or {})
                obj.update(rid=rid, kind=kind, status=status, path=p, owner=r.owner,
                           created=obj.get("created", r.created), app="aa" if d.startswith("relabel") else "lc",
                           _mod=r.modified)
                prev = self.requests.get(rid)
                if prev is None or r.modified >= prev.get("_mod", 0):
                    self.requests[rid] = obj
        self.intake = self._trusted_under(P_INTAKE)
        self.results = self._trusted_under(P_RESULTS)
        self.assigns = self._trusted_under(P_ASSIGN)
        self.locks = self._trusted_under(P_LOCK_TASK)
        self.mgmt = self.trusted(P_LOCK_MGMT)
        self.agg = self.trusted(P_LOCK_AGG)
        self.train_locks = self._trusted_under(P_LOCK_TRAIN)
        self.create_locks = self._trusted_under(P_LOCK_CREATE)
        self.plans = self._trusted_under(P_PLAN)
        self.done = self._trusted_under(P_DONE)
        self.holds = self._trusted_under(P_HOLD)
        self.asks = sorted(((p, r) for p, r in self.f.items()
                            if p.startswith(P_ASK) and p.endswith(".json") and p not in self.unknown_files),
                           key=lambda pr: (pr[1].created, pr[0]))
        self.workers, self.duplicates = {}, set()
        fps: Dict[str, set] = {}
        for p, r in self.f.items():
            if not (p.startswith(P_WORKERS) and p.endswith(".json")):
                continue
            o = dict(r.obj or {})
            o.setdefault("session", _name(p).split("__")[0])
            s_ = o["session"]
            if (self.now - float(o.get("hb", 0))) <= HB_STALE and not o.get("stopping"):
                fps.setdefault(s_, set()).add(o.get("fp", ""))
            prev = self.workers.get(s_)
            if prev is None or float(o.get("hb", 0)) >= float(prev.get("hb", 0)):
                self.workers[s_] = o
        for s_, fs in fps.items():
            if len(fs) > 1:
                self.duplicates.add(s_)
                self.alerts.append({"kind": "duplicate_session", "session": s_, "fps": sorted(fs)})
        self.signals = sorted(((_name(p), p, r) for p, r in self.f.items()
                               if p.startswith(P_SIGNALS) and p.endswith(".json") and p not in self.unknown_files),
                              key=lambda t: (t[2].created, t[0]))

    # ---- 쓰기 (사본에 반영 + 쓰기 목록)
    def put(self, path: str, obj: dict, why: str, mode: str = "put"):
        o = dict(obj, by_session=self.me, by_epoch=self.ep)
        if mode == "create" and path in self.f:
            return
        self.res.writes.append(Write(path, o, mode, why))
        prev = self.f.get(path)
        self.f[path] = FileRec(o, prev.owner if prev else "", prev.created if prev else self.now, self.now)
        n = _name(path)
        for prefix, d in ((P_INTAKE, self.intake), (P_RESULTS, self.results), (P_ASSIGN, self.assigns),
                          (P_LOCK_TASK, self.locks), (P_LOCK_TRAIN, self.train_locks),
                          (P_LOCK_CREATE, self.create_locks), (P_PLAN, self.plans), (P_DONE, self.done),
                          (P_HOLD, self.holds)):
            if path.startswith(prefix):
                d[n] = o
        if path == P_LOCK_MGMT:
            self.mgmt = o
        if path == P_LOCK_AGG:
            self.agg = o

    def alert(self, key: str, obj: dict):
        self.put(P_ALERT + key + ".json", dict(obj, at=self.now), "alert")

    # ---- 실행기
    def alive(self, s: Optional[str]) -> bool:
        if not s or s in self.duplicates:
            return False
        w = self.workers.get(s)
        return bool(w) and not w.get("stopping") and (self.now - float(w.get("hb", 0))) <= HB_STALE

    def hb_lost_at(self, s: str) -> float:
        return float((self.workers.get(s) or {}).get("hb", 0)) + HB_STALE

    def caps(self, s: str) -> set:
        return set((self.workers.get(s) or {}).get("caps") or [])

    # ---- 사람
    def person_ok(self, pid: str, perm: str) -> bool:
        p = self.people_by_id.get(pid)
        return bool(p) and p.get("status", "active") == "active" and (not perm or perm in (p.get("perms") or []))

    def requester_ok(self, account: str, perm: str) -> Tuple[Optional[str], str]:
        if not account:
            return None, "owner_unknown"
        if self.g_account and account == self.g_account:
            return "system:G", ""
        p = self.people_by_acct.get(account)
        if not p:
            return None, "not_registered"
        if p.get("status", "active") != "active":
            return None, "stopped"
        if perm and perm not in (p.get("perms") or []):
            return None, "no_perm:" + perm
        return p["id"], ""

    # ---- 진행 (결과 기록에서 계산, M6)
    def done_tasks(self, rid: str) -> Dict[str, dict]:
        out = {}
        for r in self.results.values():
            if r.get("rid") == rid:
                out[str(r.get("task"))] = r
        for rr, it in self.intake.items():           # 복구 결과는 원요청에도 연결
            if it.get("origin_rid") == rid:
                for r in self.results.values():
                    if r.get("rid") == rr and r.get("task") not in ("run", "create"):
                        out[str(r.get("task"))] = dict(r, via=rr)
        return out

    def task_unknown(self, t) -> bool:
        return (P_LOCK_TASK + f"{t}.json") in self.unknown_files


# ---------------------------------------------------------------- 신호 (K1)
class SignalKind:
    name = ""

    def effects(self, v: View, sid: str, sig: dict) -> List[str]:
        return []

    def evidence(self, v: View, sid: str, sig: dict, eff: str) -> bool:
        return False

    def judge(self, v: View, sid: str, sig: dict, eff: str) -> Tuple[str, str]:
        return "apply", ""

    def apply(self, v: View, sid: str, sig: dict, eff: str):
        pass


def _intake_with(v: View, rid: str, **kw) -> dict:
    d = {k: x for k, x in (v.intake.get(rid) or {"rid": rid}).items() if k not in ("by_session", "by_epoch")}
    d.update(kw)
    return d


class Cancel(SignalKind):
    name = "cancel"

    def effects(self, v, sid, sig):
        return ["mark"]

    def evidence(self, v, sid, sig, eff):
        return (v.intake.get(sig.get("rid")) or {}).get("cancel_signal") == sid

    def judge(self, v, sid, sig, eff):
        rid = sig.get("rid")
        if rid not in v.intake:
            return "invalid", "no_intake"
        if (v.requests.get(rid) or {}).get("status") in FINAL_STATUS:
            return "invalid", "already_" + v.requests[rid]["status"]
        return "apply", ""

    def apply(self, v, sid, sig, eff):
        rid = sig["rid"]
        v.put(P_INTAKE + rid + ".json", _intake_with(v, rid, cancel_signal=sid, cancel_at=v.now), "cancel")


class ApproveNight(SignalKind):
    name = "approve_night"

    def effects(self, v, sid, sig):
        return ["mark"]

    def evidence(self, v, sid, sig, eff):
        return (v.intake.get(sig.get("rid")) or {}).get("night_signal") == sid

    def judge(self, v, sid, sig, eff):
        return ("apply", "") if sig.get("rid") in v.intake else ("invalid", "no_intake")

    def apply(self, v, sid, sig, eff):
        rid = sig["rid"]
        v.put(P_INTAKE + rid + ".json", _intake_with(v, rid, night_signal=sid), "approve_night")


class Stop(SignalKind):
    name = "stop"

    def effects(self, v, sid, sig):
        return ["hold", "gpu"]

    def evidence(self, v, sid, sig, eff):
        if eff == "hold":
            return sid in v.holds
        return all(a.get("stop_signal") == sid for a in v.assigns.values()
                   if a.get("lane") == "gpu" and a.get("state") == "active")

    def apply(self, v, sid, sig, eff):
        if eff == "hold":
            v.put(P_HOLD + sid + ".json", {"stop_id": sid, "active": True, "until": sig.get("until"),
                                           "by": sig.get("_requester"), "at": v.now}, "stop")
        else:
            for k, a in sorted(v.assigns.items()):
                if a.get("lane") == "gpu" and a.get("state") == "active" and a.get("stop_signal") != sid:
                    v.put(P_ASSIGN + k + ".json", _strip(dict(a, stop_signal=sid)), "stop_gpu")


class Release(SignalKind):
    name = "release"

    def effects(self, v, sid, sig):
        return ["unhold"]

    def evidence(self, v, sid, sig, eff):
        return (v.holds.get(sig.get("stop_id")) or {}).get("released_by") == sid

    def judge(self, v, sid, sig, eff):
        h = v.holds.get(sig.get("stop_id"))
        if not h:
            return "invalid", "no_such_stop"
        if not h.get("active"):
            return "invalid", "already_released"
        return "apply", ""

    def apply(self, v, sid, sig, eff):
        st = sig["stop_id"]
        v.put(P_HOLD + st + ".json", _strip(dict(v.holds[st], active=False, released_by=sid, released_at=v.now)),
              "release")


def _strip(o: dict) -> dict:
    return {k: x for k, x in o.items() if k not in ("by_session", "by_epoch")}


def choice_open(v: View, lk: dict) -> bool:
    """'확인 필요'의 선택 버튼이 열리는가 (H1). 관리자 강제 해제는 따로."""
    s = lk.get("session")
    t = str(lk.get("task"))
    if v.inp.import_pending.get(t) is True:
        return False
    if lk.get("stop_reported") or v.inp.kernel_status.get(s) == "ended":
        return True
    since = float(lk.get("quarantine_since", v.hb_lost_at(s)))
    return v.now - since >= CHOICE_WAIT


class ConfirmChoice(SignalKind):
    name = "confirm_choice"

    def effects(self, v, sid, sig):
        return ["lock"] if sig.get("choice") == "ok" else ["recovery_request", "lock"]

    def rcv(self, sid):
        return "rcv" + short_hash(sid)

    def evidence(self, v, sid, sig, eff):
        if eff == "lock":
            return (v.locks.get(str(sig.get("task"))) or {}).get("by_signal") == sid
        return (v.intake.get(self.rcv(sid)) or {}).get("origin_signal") == sid

    def judge(self, v, sid, sig, eff):
        t = str(sig.get("task"))
        if v.task_unknown(t):
            return "defer", "lock_unknown"
        lk = v.locks.get(t) or {}
        if lk.get("state") != "quarantine" or lk.get("decision") != sig.get("decision"):
            return "invalid", "not_quarantined_for_decision"
        if not choice_open(v, lk) and not (sig.get("force") and sig.get("_admin")):
            return "invalid", "choice_not_open"
        return "apply", ""

    def apply(self, v, sid, sig, eff):
        t = str(sig["task"])
        lk = v.locks.get(t) or {}
        if eff == "recovery_request":
            rr = self.rcv(sid)
            req = {"rid": rr, "kind": "recovery", "tasks": [t], "mode": sig["choice"],
                   "origin_rid": lk.get("rid"), "origin_job": lk.get("job"), "by_signal": sid, "created": v.now}
            v.put(REQ_DIRS[0] + f"REQ_{rr}__recovery__pending.json", req, "recovery_request", mode="create")
            v.requests[rr] = dict(req, status="pending", path="", owner="")
            v.put(P_INTAKE + rr + ".json", make_intake(v, v.requests[rr], "system:arbiter", "", ""), "recovery_intake")
        else:
            g = int(lk.get("gen", 0)) + 1
            prev = {k: lk.get(k) for k in ("rid", "job", "session", "decision")}
            if sig.get("choice") == "ok":
                new = {"task": t, "state": "free", "gen": g, "epoch": v.ep, "decision": "sig-" + short_hash(sid),
                       "by_signal": sid, "prev": prev}
            else:
                new = {"task": t, "state": "reserved", "gen": g, "epoch": v.ep, "decision": "sig-" + short_hash(sid),
                       "rid": self.rcv(sid), "session": None, "by_signal": sid, "prev": prev}
            v.put(P_LOCK_TASK + t + ".json", new, "choice")


class AdoptChoice(SignalKind):
    """'채택 대기' 버전에 대한 사람의 선택. 시험 설정이면 시험 키를 채택 표시에 넣고 오염 대조까지 (P1)."""
    name = "adopt_choice"

    def effects(self, v, sid, sig):
        if sig.get("choice") != "adopt":
            return ["flag"]
        return ["current", "contam", "flag"] if sig.get("type") == "test_tasks" else ["current", "flag"]

    def _fp(self, sig):
        return P_FLAGS + f"{sig.get('type')}__{sig.get('name')}__{sig.get('run')}.json"

    def _deps(self, v, sig):
        typ = sig.get("type")
        deps = [self._fp(sig), CURRENT_OF[typ].format(n=sig.get("name")),
                VERSION_FILES_OF[typ].format(n=sig.get("name"), run=sig.get("run"))]
        return deps + (_contam_deps(v) if typ == "test_tasks" else [])

    def evidence(self, v, sid, sig, eff):
        if sig.get("type") not in CURRENT_OF or any(d in v.unknown_files for d in self._deps(v, sig)):
            return False
        if eff == "current":
            return (v.trusted(CURRENT_OF[sig["type"]].format(n=sig.get("name"))) or {}).get("by_signal") == sid
        if eff == "contam":
            return False                                    # 매번 다시 맞춤 (이미 된 것은 건너뜀)
        return (v.trusted(self._fp(sig)) or {}).get("by_signal") == sid

    def judge(self, v, sid, sig, eff):
        if sig.get("type") not in CURRENT_OF:
            return "invalid", "bad_type"
        if any(d in v.unknown_files for d in self._deps(v, sig)):
            return "defer", "deps_unknown"
        fl = v.trusted(self._fp(sig))
        if not fl or fl.get("state") != "adopt_wait":
            return "invalid", "not_waiting"
        return "apply", ""

    def apply(self, v, sid, sig, eff):
        typ, n, run = sig["type"], sig["name"], sig["run"]
        cp = CURRENT_OF[typ].format(n=n)
        if eff == "current":
            cur = v.trusted(cp) or {}
            new = {"type": typ, "name": n, "version": run, "adopted_gen": int(cur.get("adopted_gen", 0)) + 1,
                   "at": v.now, "by_signal": sid}
            if typ == "test_tasks":
                vf = v.f.get(VERSION_FILES_OF[typ].format(n=n, run=run))
                new["keys"] = list(((vf.obj if vf else None) or {}).get("keys") or [])
            v.put(cp, new, "adopt_choice")
        elif eff == "contam":
            cur = v.trusted(cp) or {}
            if cur.get("version") == run:
                flag_contamination(v, cur)
        else:
            fl = _strip(v.trusted(self._fp(sig)) or {})
            fl.update(state="adopted" if sig.get("choice") == "adopt" else "discarded", by_signal=sid)
            v.put(self._fp(sig), fl, "adopt_choice_flag")


class RunChoice(SignalKind):
    """관리 일·학습·만들기 실행이 '확인 필요'일 때 사람의 선택: done(끝난 것으로) | redo(다시 하기).
    '끝난 것으로'는 정상 완료와 같은 complete_run을 거침 — 산출물은 채택 판정까지, 만들기는 확인한 TASK 번호로 (N2)."""
    name = "run_choice"

    def _lock_path(self, sig):
        lane = sig.get("lane")
        if lane == "mgmt":
            return P_LOCK_MGMT
        if lane == "train":
            return P_LOCK_TRAIN + f"{sig.get('model')}.json"
        if lane == "create":
            return P_LOCK_CREATE + f"{sig.get('key')}.json"
        return ""

    def effects(self, v, sid, sig):
        return ["complete"] if sig.get("choice") == "done" else ["redo"]

    def evidence(self, v, sid, sig, eff):
        lp = self._lock_path(sig)
        lk = v.trusted(lp) if lp else None
        if not lk or lk.get("by_signal") != sid:
            return False
        if eff == "redo":
            return True
        rp, rec = _result_of_run(v, lk)
        return bool(rec) and lk.get("state") == "done"

    def judge(self, v, sid, sig, eff):
        lp = self._lock_path(sig)
        lk = v.trusted(lp) if lp else None
        if lp and lp in v.unknown_files:
            return "defer", "lock_unknown"
        if not lk or lk.get("run") != sig.get("run"):
            return "invalid", "no_such_run"
        if any(d in v.unknown_files for d in _complete_deps(v, lk, lp)):
            return "defer", "deps_unknown"                      # 완료가 읽는 파일을 모름 → 미룸 (P2)
        if lk.get("by_signal") == sid or (eff == "complete" and (_result_of_run(v, lk)[1] or {}).get("by_signal") == sid):
            return "apply", ""                                  # 이어서 마저 함
        if lk.get("state") != "needs_check":
            return "invalid", "not_needs_check"
        s_ = lk.get("session")
        open_ = v.inp.kernel_status.get(s_) == "ended" or v.now - float(lk.get("since", v.hb_lost_at(s_))) >= CHOICE_WAIT
        if not open_ and not (sig.get("force") and sig.get("_admin")):
            return "invalid", "choice_not_open"
        if eff == "complete":
            art = lk.get("artifact")
            if art:
                vf = v.f.get(VERSION_FILES_OF[art["type"]].format(n=art["name"], run=lk["run"]))
                if not vf or not (vf.obj or {}).get("files") or not (vf.obj or {}).get("verified"):
                    return "invalid", "version_files_not_verified"
            if sig.get("lane") == "create" and sig.get("task_id") is None:
                return "invalid", "create_needs_task_id"
        return "apply", ""

    def apply(self, v, sid, sig, eff):
        lp = self._lock_path(sig)
        lk = v.trusted(lp)
        if eff == "complete":
            art = lk.get("artifact")
            vf = v.f.get(VERSION_FILES_OF[art["type"]].format(n=art["name"], run=lk["run"])) if art else None
            complete_run(v, lp, lk, result="done_by_choice", session=lk.get("session"), by_signal=sid,
                         task_id=sig.get("task_id"), train_keys=(vf.obj or {}).get("train_keys") if vf else None,
                         keys=(vf.obj or {}).get("keys") if vf else None)
        else:
            v.put(lp, dict(_strip(lk), state="free", gen=int(lk.get("gen", 0)) + 1, by_signal=sid), "run_choice_redo")
            for k, a in sorted(v.assigns.items()):
                if a.get("run") == lk.get("run") and a.get("state") == "active":
                    v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="revoked", revoked_at=v.now)), "redo_revoke")


SIGNAL_KINDS = {k.name: k for k in (Cancel(), ApproveNight(), Stop(), Release(), ConfirmChoice(),
                                    AdoptChoice(), RunChoice())}


def _signal_requester(v: View, rec: FileRec, kind_name: str, sig: dict) -> Tuple[Optional[str], str, bool]:
    """신호의 신원 (K3). G가 만든 신호는 Keeper의 해제(원래 관리자 신호 연결)만 받음."""
    perm = PERM_OF_SIGNAL.get(kind_name, "request")
    if v.g_account and rec.owner == v.g_account:
        if kind_name != "release" or not sig.get("origin_signal"):
            return None, "g_not_allowed:" + kind_name, False
        orig = v.f.get(P_SIGNALS + sig["origin_signal"] + ".json")
        if not orig:
            return None, "origin_missing", False
        who, why = v.requester_ok(orig.owner, "release")
        if not who or who.startswith("system:"):
            return None, "origin_" + (why or "not_person"), False
        return who, "", (v.people_by_id.get(who) or {}).get("role") == "admin"
    who, why = v.requester_ok(rec.owner, perm)
    if who and who.startswith("system:"):
        return None, "system_signal", False
    return who, why, bool(who) and (v.people_by_id.get(who) or {}).get("role") == "admin"


def process_signals(v: View):
    seq = max([int(p.get("seq", 0)) for p in v.plans.values()] or [0])
    for sid, path, rec in v.signals:
        if sid in v.done:
            continue
        sig = dict(rec.obj or {})
        kind_name = sid.split("__", 1)[0]
        if kind_name == "wake":
            continue
        kind = SIGNAL_KINDS.get(kind_name)
        plan = v.plans.get(sid)
        if plan is None:
            if not rec.owner:
                continue                              # 소유 계정 모름 → 다음 회에
            who, why, admin = _signal_requester(v, rec, kind_name, sig)
            if kind is None:
                who, why = None, "unknown_kind"
            if who is None:
                v.put(P_DONE + sid + ".json", {"sid": sid, "result": "rejected", "reason": why, "at": v.now},
                      "reject_signal")
                continue
            seq += 1
            plan = {"sid": sid, "seq": seq, "kind": kind_name, "requester": who, "admin": admin,
                    "target": sig.get("rid") or sig.get("task") or sig.get("stop_id") or sig.get("run"),
                    "effects": kind.effects(v, sid, sig), "at": v.now}
            v.put(P_PLAN + sid + ".json", plan, "plan")
        if kind is None:
            continue
        sig["_requester"], sig["_admin"] = plan.get("requester"), plan.get("admin")
        results, deferred = {}, False
        for eff in plan.get("effects", []):
            if kind.evidence(v, sid, sig, eff):
                results[eff] = "reflected"
                continue
            verdict, why = kind.judge(v, sid, sig, eff)
            if verdict == "defer":
                deferred = True
                break
            if verdict == "invalid":
                results[eff] = "invalid:" + why
                continue
            kind.apply(v, sid, sig, eff)
            results[eff] = "applied"
        if deferred:
            continue
        v.put(P_DONE + sid + ".json", {"sid": sid, "seq": plan["seq"], "result": "done", "effects": results,
                                       "at": v.now}, "done")


# ---------------------------------------------------------------- 접수 (K3)
def make_intake(v: View, req: dict, who, account, why) -> dict:
    d = {"rid": req["rid"], "requester": who, "account": account, "at": v.now,
         "ok": who is not None, "reason": why, "kind": req.get("kind"), "created": req.get("created", 0),
         "tasks": [str(t) for t in (req.get("tasks") or [])]}
    for k in ("model", "dataset", "name", "server"):
        if req.get(k) is not None:
            d[k] = req.get(k)
    if req.get("kind") == "recovery":
        d.update(origin_rid=req.get("origin_rid"), origin_signal=req.get("by_signal"), mode=req.get("mode"))
    return d


def intake_new(v: View):
    for rid, req in sorted(v.requests.items(), key=lambda kv: (kv[1].get("created", 0), kv[0])):
        if rid in v.intake or (P_INTAKE + rid + ".json") in v.unknown_files:
            continue
        if req.get("status") in FINAL_STATUS:
            continue
        if req.get("kind") == "recovery":
            sid = req.get("by_signal")
            ok_r = (bool(sid) and sid in v.plans and req.get("by_session") is not None
                    and req.get("by_epoch") is not None and int(req["by_epoch"]) <= v.ep
                    and not (int(req["by_epoch"]) == v.ep and req["by_session"] != v.me))
            who, why = ("system:arbiter", "") if ok_r else (None, "recovery_not_by_arbiter")
            v.put(P_INTAKE + rid + ".json", make_intake(v, req, who, req.get("owner", ""), why), "intake")
            continue
        if not req.get("owner"):
            continue
        who, why = v.requester_ok(req["owner"], "request")
        if who == "system:G" and req.get("kind") not in AUTO_KINDS:
            who, why = None, "g_kind_not_allowed"
        v.put(P_INTAKE + rid + ".json", make_intake(v, req, who, req["owner"], why), "intake")


# ---------------------------------------------------------------- 보고 (M3·M6)
def _ask(rec: FileRec) -> dict:
    return dict(rec.obj or {})


def _missing(a: dict) -> List[str]:
    keys = REPORT_KEYS.get(a.get("type"), ())
    return [k for k in keys if a.get(k) is None]


def _task_lock_match(v: View, a: dict, states: Tuple[str, ...], need_gen=True, need_job=False) -> bool:
    lk = v.locks.get(str(a.get("task"))) or {}
    ok = (lk.get("state") in states and lk.get("session") == a.get("session")
          and lk.get("decision") == a.get("decision") and lk.get("rid") == a.get("rid")
          and str(lk.get("chunk")) == str(a.get("chunk"))
          and int(lk.get("epoch", -1)) == v.ep and int(a.get("epoch", -2)) == v.ep)
    if ok and need_gen:
        ok = int(lk.get("gen", -1)) == int(a.get("gen", -2))
    if ok and need_job:
        ok = lk.get("job") == a.get("job")
    return ok


def _free_task(v: View, t: str, why: str, extra: dict = None):
    lk = v.locks.get(t) or {}
    new = {"task": t, "state": "free", "gen": int(lk.get("gen", 0)) + 1, "epoch": v.ep, "decision": lk.get("decision")}
    if extra:
        new.update(extra)
    v.put(P_LOCK_TASK + t + ".json", new, why)


def apply_reports(v: View) -> Tuple[List[str], List[str]]:
    """반영한 보고(handled)와 승인 대기(confirm)를 돌려줌."""
    prev = set(v.arbiter.get("asks_handled") or [])
    handled: List[str] = []
    confirms: List[Tuple[str, dict]] = []
    # 같은 회차의 시험 설정 채택을 모델 완료보다 먼저 (도착 순서와 무관하게 같은 결과)
    ordered = sorted(v.asks, key=lambda pr: 0 if (_ask(pr[1]).get("type") == "done_run"
                                                  and _ask(pr[1]).get("type_") == "test_tasks") else 1)
    for path, rec in ordered:
        key = _name(path)
        if key in prev:
            handled.append(key)
            continue
        a = _ask(rec)
        typ = a.get("type")
        miss = _missing(a)
        if typ not in REPORT_KEYS or miss:
            v.alert("incomplete_" + key, {"kind": "incomplete_report", "ask": key, "missing": miss, "type": typ})
            handled.append(key)
            continue
        t = str(a.get("task", ""))
        deps = []
        if a.get("task") is not None:
            deps.append(P_LOCK_TASK + t + ".json")
            if typ in ("end", "result"):
                deps.append(result_path(a["rid"], t, a.get("job") or ("nojob-" + a["decision"])))
        if typ in ("release", "publish_lock") and a.get("assign"):
            deps.append(P_ASSIGN + a["assign"] + ".json")
        if typ in ("done_run", "done_job"):
            deps += _deps_run(v, a, _lane_lock(v, a)[0])
        if any(d in v.unknown_files for d in deps):
            continue                                       # 기대는 파일을 모름 → 처리됨으로 두지 않고 다음 회에 (M8·N3)
        verdict = "stale"
        if typ == "confirm":
            confirms.append((key, a))
            continue
        if typ == "end":
            rp = result_path(a["rid"], t, a["job"])
            if _task_lock_match(v, a, ("confirm_approved",), need_job=True):
                v.put(rp, {"rid": a["rid"], "task": t, "job": a["job"], "result": a["result"],
                           "decision": a["decision"], "session": a["session"], "at": v.now}, "result", mode="create")
                _free_task(v, t, "end", {"last": {"rid": a["rid"], "job": a["job"], "result": a["result"]}})
                verdict = "applied"
            elif (v.results.get(_name(rp)) or {}).get("decision") == a["decision"]:
                lk = v.locks.get(t) or {}                  # 결과는 남았는데 잠금 해제 전에 끊김 → 마저 품
                if lk.get("state") == "confirm_approved" and lk.get("decision") == a["decision"] \
                        and lk.get("job") == a["job"] and lk.get("session") == a["session"]:
                    _free_task(v, t, "end_resume", {"last": {"rid": a["rid"], "job": a["job"], "result": a["result"]}})
                verdict = "applied"
        elif typ == "result":
            rp = result_path(a["rid"], t, "nojob-" + a["decision"])
            if _task_lock_match(v, a, ("held",)):
                v.put(rp, {"rid": a["rid"], "task": t, "job": "nojob-" + a["decision"], "result": a["result"],
                           "decision": a["decision"], "session": a["session"], "at": v.now}, "result", mode="create")
                _free_task(v, t, "result")
                verdict = "applied"
            elif _name(rp) in v.results:
                lk = v.locks.get(t) or {}
                if lk.get("state") == "held" and lk.get("decision") == a["decision"] and lk.get("session") == a["session"]:
                    _free_task(v, t, "result_resume")
                verdict = "applied"
        elif typ == "stop":
            if _task_lock_match(v, a, ("held", "confirm_approved"), need_gen=False):
                lk = _strip(v.locks[t])
                new = dict(lk, stop_reported=True, stop_reason=a.get("reason"), gen=int(lk.get("gen", 0)) + 1)
                if lk.get("state") == "confirm_approved":
                    new.update(state="quarantine", quarantine_since=v.now)
                v.put(P_LOCK_TASK + t + ".json", new, "stop_report")
                verdict = "applied"
        elif typ == "release":
            asg = v.assigns.get(a["assign"]) or {}
            if (asg.get("session") == a["session"] and asg.get("decision") == a["decision"]
                    and asg.get("state") == "active" and asg.get("rid") == a["rid"]
                    and str(asg.get("chunk")) == str(a["chunk"]) and int(asg.get("epoch", -1)) == v.ep == int(a["epoch"])):
                for t2 in asg.get("tasks", []):
                    l2 = v.locks.get(str(t2)) or {}
                    if l2.get("session") == a["session"] and l2.get("state") == "held" \
                            and l2.get("decision") == asg.get("decision"):
                        _free_task(v, str(t2), "release_task")
                v.put(P_ASSIGN + a["assign"] + ".json", _strip(dict(asg, state="returned", returned_at=v.now)), "release")
                verdict = "applied"
        elif typ == "publish_lock":
            rid = a["rid"]
            asg = next((x for x in v.assigns.values() if x.get("rid") == rid and x.get("state") == "active"
                        and x.get("session") == a["session"] and x.get("decision") == a["decision"]
                        and str(x.get("chunk")) == str(a["chunk"]) and x.get("lane") == "read"
                        and int(x.get("epoch", -1)) == v.ep and t in [str(y) for y in x.get("tasks", [])]), None)
            if asg is None:                                # 배정 밖 TASK·다른 줄의 게시 잠금 → 거절 (N4)
                v.alert("publish_denied_" + key, {"kind": "publish_lock_denied", "ask": key, "task": t})
                handled.append(key)
                continue
            lk = v.locks.get(t) or {}
            if asg and int(a["epoch"]) == v.ep and lk.get("state") in (None, "free") \
                    and not (v.intake.get(rid) or {}).get("cancel_signal"):
                v.put(P_LOCK_TASK + t + ".json", {"task": t, "state": "held", "session": a["session"], "rid": rid,
                                                  "decision": a["decision"], "epoch": v.ep,
                                                  "gen": int(lk.get("gen", 0)) + 1, "chunk": a["chunk"],
                                                  "at": v.now, "publish": True}, "publish_lock")
                verdict = "applied"
            elif asg and lk.get("state") not in (None, "free"):
                continue                                   # 잠겨 있음 → 다음 회에
        elif typ in ("done_run", "done_job"):
            verdict = run_report(v, a)
        if verdict == "stale":
            v.alert("stale_" + key, {"kind": "stale_report", "ask": key})
        handled.append(key)
    return handled, confirms


def approve_confirms(v: View, confirms: List[Tuple[str, dict]], handled: List[str]):
    for key, a in confirms:
        t = str(a["task"])
        canceled = bool((v.intake.get(a["rid"]) or {}).get("cancel_signal"))
        if _task_lock_match(v, a, ("held",)) and not canceled:
            lk = _strip(v.locks[t])
            v.put(P_LOCK_TASK + t + ".json", dict(lk, state="confirm_approved", gen=int(lk["gen"]) + 1, job=a["job"],
                                                  approved_at=v.now, recovery_dir=a.get("recovery_dir")), "approve")
        else:
            v.alert("deny_" + key, {"kind": "confirm_denied", "ask": key, "canceled": canceled})
        handled.append(key)


# ---------------------------------------------------------------- 관리 일·학습·취합·만들기 완료 (M10, J5·K5)
def _lane_lock(v: View, a: dict) -> Tuple[str, Optional[dict]]:
    lane = a.get("lane")
    if lane == "train":
        return P_LOCK_TRAIN + f"{a.get('name')}.json", v.train_locks.get(a.get("name"))
    if lane == "mgmt":
        return P_LOCK_MGMT, v.mgmt
    if lane == "agg":
        return P_LOCK_AGG, v.agg
    if lane == "create":
        k = a.get("key", "")
        return P_LOCK_CREATE + f"{k}.json", v.create_locks.get(k)
    return "", None


def _run_lock_match(v: View, lk: Optional[dict], a: dict) -> bool:
    return bool(lk) and (lk.get("run") == a.get("run") and lk.get("decision") == a.get("decision")
                         and int(lk.get("gen", -1)) == int(a.get("gen", -2)) and lk.get("state") == "running"
                         and lk.get("session") == a.get("session") and lk.get("rid") == a.get("rid")
                         and int(lk.get("epoch", -1)) == v.ep == int(a.get("epoch", -2)))


def _end_run_lock(v: View, lp: str, lk: dict, why: str, by_signal: Optional[str] = None):
    new = dict(_strip(lk), state="done", gen=int(lk.get("gen", 0)) + 1, ended_at=v.now)
    if by_signal:
        new["by_signal"] = by_signal
    v.put(lp, new, why)
    for k, a in sorted(v.assigns.items()):                 # 그 실행의 배정도 닫음
        if a.get("run") == lk.get("run") and a.get("state") == "active":
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="done", done_at=v.now)), why + "_assign")


def _result_of_run(v: View, lk: dict) -> Tuple[str, Optional[dict]]:
    tag = "create" if str(lk.get("run", "")).startswith("create_") else "run"
    rp = result_path(lk.get("rid"), tag, lk.get("run"))
    return rp, v.results.get(_name(rp))


def _premise(v: View, typ: str, n: str) -> dict:
    cur = v.trusted(CURRENT_OF[typ].format(n=n)) or {}
    tcur = v.trusted(CURRENT_OF["test_tasks"]) or {}
    return {"cur_gen": int(cur.get("adopted_gen", 0)), "test_version": tcur.get("version")}


def _artifact_judgement(v: View, lk: dict, typ: str, n: str, train_keys) -> Optional[str]:
    """처음 판정: None(채택) 또는 채택 대기 이유."""
    if typ != "model" or not str(lk.get("run", "")).startswith("train_"):
        return None
    cur = v.trusted(CURRENT_OF[typ].format(n=n)) or {}
    if int(cur.get("adopted_gen", 0)) != int(lk.get("start_adopted_gen", 0)):
        return "current_changed"
    if lk.get("compat") == "unknown":
        return "compat_unknown"
    tcur = v.trusted(CURRENT_OF["test_tasks"]) or {}
    if tcur.get("version") != lk.get("start_test_version") and contaminated(train_keys, tcur):
        return "contaminated"
    return None


RESOLVED_FLAG = ("adopt_wait", "adopted", "discarded")


def _flag(v: View, typ: str, n: str, run: str, reason: str):
    """채택 대기 표시. 이미 있거나 사람이 채택·버림으로 해소했으면 되살리지 않음 (P3)."""
    fp = P_FLAGS + f"{typ}__{n}__{run}.json"
    fl = v.trusted(fp) or {}
    if fl.get("state") in RESOLVED_FLAG:
        return
    v.put(fp, dict(_strip(fl), type=typ, name=n, run=run, state="adopt_wait", reason=reason, at=v.now), "adopt_wait")


def _contam_deps(v: View) -> List[str]:
    """시험 설정 채택의 오염 대조가 읽는 파일 가운데 지금 못 읽은 것."""
    return sorted(u for u in v.unknown_files if u.startswith(P_FLAGS) or u.startswith("runs/"))


def _settle_artifact(v: View, rec: dict):
    """결과 기록의 판정을 채택 표시에 반영. 판정 뒤 다른 채택·시험 설정 변경이 있었으면 덮지 않고 채택 대기 (N1).
    채택 표시가 이미 이 버전이어도 시험 설정의 오염 대조는 마저 함 (P1)."""
    art = rec["artifact"]
    typ, n, run = art["type"], art["name"], rec["job"]
    cp = CURRENT_OF[typ].format(n=n)
    cur = v.trusted(cp) or {}
    if cur.get("version") == run:                                # 이미 반영 (정상 채택이든 사람의 채택이든)
        if typ == "test_tasks":
            flag_contamination(v, cur)
        return
    if rec.get("result") == "adopt_wait":
        _flag(v, typ, n, run, rec.get("reason") or "wait")
        return
    prem = rec.get("premise") or {}
    if int(cur.get("adopted_gen", 0)) != int(prem.get("cur_gen", 0)):
        _flag(v, typ, n, run, "superseded")                      # 그사이 다른 채택(FORCE_NEW 등)
        return
    tcur = v.trusted(CURRENT_OF["test_tasks"]) or {}
    if typ == "model" and tcur.get("version") != prem.get("test_version") and contaminated(rec.get("train_keys"), tcur):
        _flag(v, typ, n, run, "contaminated")
        return
    new = {"type": typ, "name": n, "version": run, "adopted_gen": int(cur.get("adopted_gen", 0)) + 1,
           "at": v.now, "decision": rec["decision"]}
    if typ == "test_tasks":
        new["keys"] = list(rec.get("keys") or [])
    v.put(cp, new, "adopt")
    if typ == "test_tasks":
        flag_contamination(v, new)


def _settle_change(v: View, rec: dict):
    """FORCE_NEW: 채택 표시만 바꿈. 판정 뒤 다른 채택이 있었으면 덮지 않음."""
    cc = rec["current_change"]
    cp = CURRENT_OF[cc["type"]].format(n=cc.get("name"))
    cur = v.trusted(cp) or {}
    if cur.get("decision") == rec["decision"]:
        return
    if int(cur.get("adopted_gen", 0)) != int((rec.get("premise") or {}).get("cur_gen", 0)):
        v.alert("superseded_" + short_hash(rec["job"]), {"kind": "current_change_superseded", "run": rec["job"]})
        return
    v.put(cp, {"type": cc["type"], "name": cc.get("name"), "version": cc.get("version"),
               "adopted_gen": int(cur.get("adopted_gen", 0)) + 1, "at": v.now, "decision": rec["decision"]},
          "force_new")


def complete_run(v: View, lp: str, lk: dict, *, result: str, session: str, by_signal: Optional[str] = None,
                 task_id=None, train_keys=None, current_change: Optional[dict] = None, keys=None,
                 with_artifact: bool = True) -> dict:
    """실행형 일(관리·학습·취합·만들기)의 완료 — 정상 보고와 사람의 선택이 같은 함수를 씀 (N2).
    1) 결과 기록(판정과 전제) 2) 가변 효과(채택 표시·플래그) 3) 잠금·배정 닫기. 어디서 끊겨도 다시 부르면 이어 감."""
    rp, rec = _result_of_run(v, lk)
    if rec is None:
        tag = "create" if rp.split("__")[-2] == "create" else "run"
        rec = {"rid": lk.get("rid"), "task": tag, "job": lk.get("run"), "result": result,
               "decision": lk.get("decision"), "session": session, "at": v.now}
        if by_signal:
            rec["by_signal"] = by_signal
        if task_id is not None:
            rec["task_id"] = task_id
        art = lk.get("artifact") if with_artifact else None      # 실패 보고(done_job)는 산출물을 채택하지 않음
        if art:
            reason = _artifact_judgement(v, lk, art["type"], art["name"], train_keys)
            rec.update(result="adopt_wait" if reason else "adopt", reason=reason, artifact=art,
                       premise=_premise(v, art["type"], art["name"]), train_keys=list(train_keys or []),
                       keys=list(keys or []))
        if current_change and current_change.get("type") in CURRENT_OF:
            rec.update(current_change=current_change,
                       premise=_premise(v, current_change["type"], current_change.get("name")))
        v.put(rp, rec, "result", mode="create")
    if rec.get("artifact"):
        _settle_artifact(v, rec)
    if rec.get("current_change"):
        _settle_change(v, rec)
    if lk.get("state") in ("running", "needs_check"):
        _end_run_lock(v, lp, lk, "run_done", by_signal)
    return rec


def _complete_deps(v: View, lk: Optional[dict], lp: str, current_change: Optional[dict] = None) -> List[str]:
    """complete_run이 읽는 파일 전체 — 정상 보고와 사람의 선택이 같은 목록으로 '모름'을 확인 (P2)."""
    deps = [lp] if lp else []
    if lk:
        deps.append(_result_of_run(v, lk)[0])
        art = lk.get("artifact")
        if art:
            deps.append(CURRENT_OF[art["type"]].format(n=art["name"]))
            deps.append(VERSION_FILES_OF[art["type"]].format(n=art["name"], run=lk.get("run")))
            deps.append(P_FLAGS + f"{art['type']}__{art['name']}__{lk.get('run')}.json")
            if art["type"] == "model":
                deps.append(CURRENT_OF["test_tasks"])            # 오염 판정이 읽음
            if art["type"] == "test_tasks":
                deps += _contam_deps(v)
    if current_change and current_change.get("type") in CURRENT_OF:
        deps.append(CURRENT_OF[current_change["type"]].format(n=current_change.get("name")))
    return deps


def _deps_run(v: View, a: dict, lp: str) -> List[str]:
    lk = next((d for d in (v.mgmt, v.agg) + tuple(v.train_locks.values()) + tuple(v.create_locks.values())
               if d and d.get("run") == a.get("run")), None)
    return _complete_deps(v, lk, lp, a.get("current_change"))


def run_report(v: View, a: dict) -> str:
    """done_run(산출물)·done_job(산출물 없음) 보고."""
    lp, lk = _lane_lock(v, a)
    if not lk:
        return "stale"
    rp, rec = _result_of_run(v, lk)
    resume = bool(rec) and rec.get("decision") == a["decision"] and lk.get("run") == a.get("run") \
        and lk.get("state") in ("running", "needs_check")
    if not _run_lock_match(v, lk, a) and not resume:
        return "applied" if rec and rec.get("decision") == a["decision"] else "stale"
    if a["type"] == "done_run":
        art = lk.get("artifact") or {}
        if a.get("type_") != art.get("type"):
            return "stale"
        vf = v.f.get(VERSION_FILES_OF[art["type"]].format(n=art["name"], run=lk["run"]))
        if not rec and (not vf or not (vf.obj or {}).get("files")):
            return "stale"
        complete_run(v, lp, lk, result="done", session=a["session"], train_keys=a.get("train_keys")
                     or ((vf.obj or {}).get("train_keys") if vf else None), keys=(vf.obj or {}).get("keys") if vf else None)
    else:
        complete_run(v, lp, lk, result=a["result"], session=a["session"], task_id=a.get("task_id"),
                     current_change=a.get("current_change"), with_artifact=False)
    return "applied"


def contaminated(train_keys, tcur: dict) -> bool:
    return bool(set(train_keys or []) & set(tcur.get("keys") or []))


def flag_contamination(v: View, tcur: dict):
    """새 시험 설정 채택 때 모델 버전 출처와 대조 — 모델 버전·시험 버전 짝으로 표시 (K5)."""
    for p in sorted(v.f):
        if not (p.startswith("runs/") and p.endswith("/_files.json")):
            continue
        keys = (v.f[p].obj or {}).get("train_keys") or []
        if not contaminated(keys, tcur):
            continue
        parts = p.split("/")
        m, run = parts[1], parts[3]
        fp = P_FLAGS + f"model__{m}__{run}.json"
        prev = v.trusted(fp) or {}
        if prev.get("contaminated_for") == tcur.get("version"):
            continue
        fl = dict(_strip(prev), type="model", name=m, run=run, contaminated_for=tcur.get("version"), at=v.now)
        if (v.trusted(CURRENT_OF["model"].format(n=m)) or {}).get("version") == run:
            fl["state"] = prev.get("state") or "adopted_contaminated"
        v.put(fp, fl, "contaminated")


def train_start_compat(dataset_files: Optional[dict], tcur: dict) -> str:
    if not dataset_files or dataset_files.get("task_keys") is None:
        return "unknown"
    return "overlap" if set(dataset_files.get("task_keys") or []) & set(tcur.get("keys") or []) else "ok"


# ---------------------------------------------------------------- 만료·보류 기한
def expire(v: View):
    for t, lk in sorted(v.locks.items()):
        s = lk.get("session")
        if not s or lk.get("state") not in ("held", "confirm_approved") or v.task_unknown(t) or v.alive(s):
            continue
        if lk.get("state") == "held":
            _free_task(v, t, "expire", {"expired": {"session": s, "rid": lk.get("rid")}})
        else:
            v.put(P_LOCK_TASK + t + ".json", dict(_strip(lk), state="quarantine", gen=int(lk.get("gen", 0)) + 1,
                                                  quarantine_since=v.hb_lost_at(s)), "expire")
    for k, a in sorted(v.assigns.items()):
        if a.get("state") == "active" and not v.alive(a.get("session")):
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="revoked", revoked_at=v.now)), "revoke")
    run_locks = [(P_LOCK_TRAIN + f"{n}.json", lk) for n, lk in v.train_locks.items()]
    run_locks += [(P_LOCK_MGMT, v.mgmt), (P_LOCK_AGG, v.agg)]
    run_locks += [(P_LOCK_CREATE + f"{k}.json", lk) for k, lk in v.create_locks.items()]
    for lp, lk in run_locks:
        if lk and lk.get("state") == "running" and not v.alive(lk.get("session")):
            st = "free" if lp == P_LOCK_AGG else "needs_check"        # 취합은 다시 계산하면 되므로 풀어 줌
            v.put(lp, dict(_strip(lk), state=st, gen=int(lk.get("gen", 0)) + 1,
                           since=v.hb_lost_at(lk.get("session"))), "run_lost")


def expire_holds(v: View):
    for st, h in sorted(v.holds.items()):
        if h.get("active") and h.get("until") is not None and float(h["until"]) <= v.now:
            v.put(P_HOLD + st + ".json", _strip(dict(h, active=False, expired_at=v.now)), "hold_expired")


# ---------------------------------------------------------------- 재시작 인계 (E4·M8)
def reissue(v: View, only: Optional[set] = None) -> dict:
    """새 epoch 인계. only가 있으면 그 경로만 (앞서 못 읽어 미뤄 둔 자원, N3)."""
    ep = v.ep
    rep = {"epoch": ep, "at": v.now, "reissued": [], "freed": [], "quarantined": [], "needs_check": []}

    def want(path):
        return only is None or path in only
    for k, a in sorted(v.assigns.items()):                    # assign 먼저
        if a.get("state") != "active" or int(a.get("epoch", ep)) >= ep or not want(P_ASSIGN + k + ".json"):
            continue
        if v.alive(a.get("session")):
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, epoch=ep, reissued=True)), "reissue_assign")
        else:
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="revoked", revoked_at=v.now)), "reissue_assign")
    for t, lk in sorted(v.locks.items()):
        if int(lk.get("epoch", ep)) >= ep or lk.get("state") == "free" or v.task_unknown(t) \
                or not want(P_LOCK_TASK + t + ".json"):
            continue
        s = lk.get("session")
        g = int(lk.get("gen", 0)) + 1
        if lk.get("state") in ("held", "confirm_approved") and v.alive(s):
            new = dict(_strip(lk), epoch=ep, gen=g, reissued=True)
            rep["reissued"].append(t)
        elif lk.get("state") == "held":
            new = {"task": t, "state": "free", "gen": g, "epoch": ep, "decision": lk.get("decision")}
            rep["freed"].append(t)
        elif lk.get("state") == "confirm_approved":
            new = dict(_strip(lk), state="quarantine", gen=g, epoch=ep, quarantine_since=v.hb_lost_at(s))
            rep["quarantined"].append(t)
        else:
            new = dict(_strip(lk), epoch=ep, gen=g)
        v.put(P_LOCK_TASK + t + ".json", new, "reissue")
    run_locks = [(P_LOCK_TRAIN + f"{n}.json", lk) for n, lk in v.train_locks.items()]
    run_locks += [(P_LOCK_MGMT, v.mgmt), (P_LOCK_AGG, v.agg)]
    run_locks += [(P_LOCK_CREATE + f"{k}.json", lk) for k, lk in v.create_locks.items()]
    for lp, lk in run_locks:
        if not lk or lk.get("state") != "running" or int(lk.get("epoch", ep)) >= ep or not want(lp):
            continue
        if v.alive(lk.get("session")):
            v.put(lp, dict(_strip(lk), epoch=ep, gen=int(lk.get("gen", 0)) + 1), "reissue_run")
        else:
            st = "free" if lp == P_LOCK_AGG else "needs_check"
            v.put(lp, dict(_strip(lk), state=st, gen=int(lk.get("gen", 0)) + 1,
                           since=v.hb_lost_at(lk.get("session"))), "reissue_run")
            rep["needs_check"].append(lp)
    return rep


# ---------------------------------------------------------------- 배정·잠금 재조정 (M5)
def _run_lock_of_assign(v: View, a: dict) -> Optional[dict]:
    lane = a.get("lane")
    if lane == "mgmt":
        return v.mgmt
    if lane == "agg":
        return v.agg
    if lane == "create":
        return v.create_locks.get(a.get("key"))
    if lane == "train":
        return next((lk for lk in v.train_locks.values() if lk.get("run") == a.get("run")), None)
    return None


def reconcile(v: View):
    # 실행형 배정(관리·학습·취합·만들기): 잠금 쓰기 전에 끊겨 잠금이 없으면 배정을 거두고 다시 차례로 (M5)
    for k, a in sorted(v.assigns.items()):
        if a.get("state") != "active" or a.get("lane") not in ("mgmt", "train", "agg", "create") \
                or int(a.get("epoch", -1)) != v.ep:
            continue
        lane = a.get("lane")
        lp = {"mgmt": P_LOCK_MGMT, "agg": P_LOCK_AGG}.get(lane) or (
            P_LOCK_CREATE + f"{a.get('key')}.json" if lane == "create" else "")
        if (lp and lp in v.unknown_files) or (lane == "train" and any(u.startswith(P_LOCK_TRAIN) for u in v.unknown_files)):
            continue                                       # 실행 잠금을 모름 → 거두지 않음 (N3)
        lk = _run_lock_of_assign(v, a)
        if not lk or lk.get("run") != a.get("run"):
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="revoked", revoked_at=v.now, reason="no_run_lock")),
                  "reconcile_revoke_run")
        elif lk.get("state") in ("done", "free"):            # 잠금은 끝났는데 배정 닫기 전에 끊김
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="done", done_at=v.now)), "reconcile_close_run")
    for k, a in sorted(v.assigns.items()):
        if a.get("state") != "active" or a.get("lane") in ("read", "mgmt", "train", "agg", "create") \
                or int(a.get("epoch", -1)) != v.ep:
            continue
        done = v.done_tasks(a.get("rid"))
        conflict = False
        for t in [str(x) for x in a.get("tasks", [])]:
            if t in done or v.task_unknown(t):
                continue
            lk = v.locks.get(t) or {}
            if lk.get("decision") == a.get("decision") and lk.get("state") in ("held", "confirm_approved", "quarantine"):
                continue
            if lk.get("state") in (None, "free") or (lk.get("state") == "reserved" and lk.get("rid") == a.get("rid")):
                v.put(P_LOCK_TASK + t + ".json", {"task": t, "state": "held", "session": a["session"], "rid": a["rid"],
                                                  "decision": a["decision"], "epoch": v.ep,
                                                  "gen": int(lk.get("gen", 0)) + 1, "chunk": a.get("chunk"),
                                                  "at": v.now, "reconciled": True}, "reconcile_lock")
            else:
                conflict = True
        if conflict:
            for t in [str(x) for x in a.get("tasks", [])]:
                lk = v.locks.get(t) or {}
                if lk.get("decision") == a.get("decision") and lk.get("state") == "held":
                    _free_task(v, t, "reconcile_free")
            v.put(P_ASSIGN + k + ".json", _strip(dict(a, state="revoked", revoked_at=v.now, reason="lock_conflict")),
                  "reconcile_revoke")


# ---------------------------------------------------------------- 차례·배정
def _lane(kind: str) -> str:
    if kind in MGMT_KINDS:
        return "mgmt"
    if kind in TRAIN_KINDS:
        return "train"
    if kind in AGG_KINDS:
        return "agg"
    if kind in READ_KINDS:
        return "read"
    if kind in CREATE_KINDS:
        return "create"
    return "gpu" if "gpu" in DEFAULT_ROUTE.get(kind, set()) else "cpu"


def _active_assign(v: View, rid: str) -> Optional[dict]:
    return next((a for a in v.assigns.values() if a.get("rid") == rid and a.get("state") == "active"), None)


def _completed(v: View, rid: str, kind: str) -> bool:
    if kind in TASKLESS_KINDS:
        tag = "create" if kind in CREATE_KINDS else "run"
        return any(r.get("rid") == rid and r.get("task") == tag for r in v.results.values())
    return False


def runnable_requests(v: View) -> List[dict]:
    day = is_day(v.now, v.cfg.tz_offset_h)
    out = []
    for rid, it in v.intake.items():
        req = v.requests.get(rid)
        if not req or not it.get("ok") or it.get("cancel_signal") or req.get("status") in FINAL_STATUS:
            continue
        who = it.get("requester") or ""
        if not who.startswith("system:") and not v.person_ok(who, "request"):
            continue                                       # 지금 people 기준 (b7)
        if not day and not it.get("night_signal") and req.get("kind") != "recovery":
            continue
        if _active_assign(v, rid) or _completed(v, rid, req.get("kind")):
            continue
        done = v.done_tasks(rid)
        rest = [t for t in it.get("tasks") or [] if t not in done]
        if req.get("kind") in TASKLESS_KINDS or rest:
            if req.get("kind") in TASKLESS_KINDS and req.get("kind") not in AGG_KINDS and not rest and it.get("tasks"):
                continue
            out.append(dict(req, _rest=rest, _requester=who, _intake=it))
    return sorted(out, key=lambda r: (r.get("created", 0), r["rid"]))


def _blocked_tasks(v: View, req: dict) -> set:
    if req.get("kind") in READ_KINDS:
        return {t for t in req["_rest"] if v.task_unknown(t)}
    blocked = {t for t in req["_rest"] if v.task_unknown(t)}
    reserved_mine = set()
    for t in req["_rest"]:
        lk = v.locks.get(str(t)) or {}
        if lk.get("state") == "reserved" and lk.get("rid") == req["rid"]:
            reserved_mine.add(t)
        elif lk.get("state") in ("held", "confirm_approved", "quarantine"):
            blocked.add(t)                 # 같은 요청의 TASK라도 잠겨 있거나 '확인 필요'면 다시 배정하지 않음
        elif lk.get("state") == "reserved" and lk.get("rid") != req["rid"]:
            blocked.add(t)
    for rid2, it2 in v.intake.items():
        if rid2 == req["rid"] or not it2.get("ok") or it2.get("cancel_signal"):
            continue
        r2 = v.requests.get(rid2) or {}
        if r2.get("status") in FINAL_STATUS or r2.get("kind") in READ_KINDS:
            continue
        if (r2.get("created", 0), rid2) >= (req.get("created", 0), req["rid"]):
            continue
        done2 = v.done_tasks(rid2)
        for t in it2.get("tasks") or []:
            if t in req["_rest"] and t not in done2:
                blocked.add(t)
    return blocked - reserved_mine


def _assign(v: View, r: dict, pick: str, lane: str, tasks: List[str], extra: dict = None) -> dict:
    n_chunk = 1 + sum(1 for a in v.assigns.values() if a.get("rid") == r["rid"])
    dec = "d" + short_hash(f"{r['rid']}|{n_chunk}|{v.ep}|{v.now}|{pick}")
    asg = {"rid": r["rid"], "session": pick, "decision": dec, "epoch": v.ep, "lane": lane, "state": "active",
           "tasks": tasks, "chunk": n_chunk, "at": v.now}
    if extra:
        asg.update(extra)
    v.put(P_ASSIGN + f"{r['rid']}__{n_chunk}.json", asg, "assign_" + lane)
    return asg


def schedule(v: View):
    if any(h.get("active") for h in v.holds.values()):
        v.res.notes.append("hold")
        return
    busy = {a.get("session") for a in v.assigns.values() if a.get("state") == "active"}
    idle = [s for s in sorted(v.workers) if v.alive(s) and s not in busy and s != v.me]
    reqs = runnable_requests(v)

    def take(need):
        s = next((x for x in idle if v.caps(x) & need), None)
        if s:
            idle.remove(s)
        return s

    # 관리 일: 실행 중 하나, 맞는 실행기 없으면 비켜 둠 (잠금 파일을 모르면 배정하지 않음)
    if P_LOCK_MGMT not in v.unknown_files and not (v.mgmt and v.mgmt.get("state") in ("running", "needs_check")):
        for r in [x for x in reqs if x["kind"] in MGMT_KINDS]:
            pick = take(v.cfg.route.get(r["kind"], {"cpu"}))
            if not pick:
                continue
            run = "mgmt_" + short_hash(f"{r['rid']}{v.now}")
            asg = _assign(v, r, pick, "mgmt", [], {"run": run})
            art = {"type": "dataset", "name": r.get("name") or "default"} if r["kind"] == "dataset" else (
                {"type": "test_tasks", "name": ""} if r["kind"] == "test_tasks33" else None)
            v.put(P_LOCK_MGMT, {"run": run, "rid": r["rid"], "kind": r["kind"], "session": pick,
                                "decision": asg["decision"], "epoch": v.ep, "gen": int((v.mgmt or {}).get("gen", 0)) + 1,
                                "state": "running", "at": v.now, "artifact": art}, "lock_mgmt")
            break
    # 학습 줄: 모델별 하나
    for r in [x for x in reqs if x["kind"] in TRAIN_KINDS]:
        model = r.get("model") or "default"
        tl = v.train_locks.get(model) or {}
        if tl.get("state") in ("running", "needs_check") or (P_LOCK_TRAIN + f"{model}.json") in v.unknown_files:
            continue
        cur = v.trusted(CURRENT_OF["model"].format(n=model)) or {}
        tcur = v.trusted(CURRENT_OF["test_tasks"]) or {}
        dname = r.get("dataset") or "default"
        dcur = v.trusted(CURRENT_OF["dataset"].format(n=dname)) or {}
        dvf = (v.f.get(VERSION_FILES_OF["dataset"].format(n=dname, run=dcur.get("version"))) or FileRec(None)).obj
        compat = train_start_compat(dvf, tcur)
        if compat == "overlap":
            v.alert("train_overlap_" + r["rid"], {"kind": "train_dataset_overlaps_test", "rid": r["rid"],
                                                  "dataset": dcur.get("version"), "test": tcur.get("version")})
            continue
        pick = take({"gpu"})
        if not pick:
            continue
        run = "train_" + short_hash(f"{r['rid']}{v.now}")
        pins = {"start_version": cur.get("version"), "start_test_version": tcur.get("version"),
                "start_dataset_version": dcur.get("version")}
        asg = _assign(v, r, pick, "train", [], {"run": run, "pins": pins})
        v.put(P_LOCK_TRAIN + model + ".json", dict(pins, run=run, rid=r["rid"], model=model, session=pick,
                                                   decision=asg["decision"], epoch=v.ep,
                                                   gen=int(tl.get("gen", 0)) + 1, state="running", at=v.now,
                                                   start_adopted_gen=int(cur.get("adopted_gen", 0)), compat=compat,
                                                   artifact={"type": "model", "name": model}), "lock_train")
    # 취합: 하나
    if P_LOCK_AGG not in v.unknown_files and not (v.agg and v.agg.get("state") == "running"):
        for r in [x for x in reqs if x["kind"] in AGG_KINDS]:
            pick = take(v.cfg.route.get(r["kind"], {"agg"}))
            if not pick:
                break
            run = "agg_" + short_hash(f"{r['rid']}{v.now}")
            asg = _assign(v, r, pick, "agg", r["_rest"], {"run": run})
            v.put(P_LOCK_AGG, {"run": run, "rid": r["rid"], "session": pick, "decision": asg["decision"],
                               "epoch": v.ep, "gen": int((v.agg or {}).get("gen", 0)) + 1, "state": "running",
                               "at": v.now}, "lock_agg")
            break
    # 새 TASK 만들기: 같은 서버·이름은 하나씩 (K6)
    for r in [x for x in reqs if x["kind"] in CREATE_KINDS]:
        key = create_key(r.get("server") or "", r.get("name") or r["rid"])
        cl = v.create_locks.get(key) or {}
        if cl.get("state") in ("running", "needs_check") or (P_LOCK_CREATE + f"{key}.json") in v.unknown_files:
            continue
        pick = take(v.cfg.route.get(r["kind"], {"cpu"}))
        if not pick:
            continue
        run = "create_" + short_hash(f"{r['rid']}{v.now}")
        asg = _assign(v, r, pick, "create", [], {"run": run, "key": key})
        v.put(P_LOCK_CREATE + key + ".json", {"run": run, "rid": r["rid"], "key": key, "name": r.get("name"),
                                              "session": pick, "decision": asg["decision"], "epoch": v.ep,
                                              "gen": int(cl.get("gen", 0)) + 1, "state": "running", "at": v.now},
              "lock_create")
    # TASK 일: 사람별 차례·묶음 5개
    last, held_people = {}, set()
    for a in v.assigns.values():
        who = (v.intake.get(a.get("rid")) or {}).get("requester")
        last[who] = max(last.get(who, 0), float(a.get("at", 0)))
        if a.get("state") == "active":
            held_people.add(who)
    task_reqs = [x for x in reqs if x["kind"] not in TASKLESS_KINDS]
    seen = set()
    for r in sorted(task_reqs, key=lambda x: (last.get(x["_requester"], 0), x.get("created", 0), x["rid"])):
        who = r["_requester"]
        if who in held_people or who in seen:
            continue
        blocked = _blocked_tasks(v, r)
        chunk = [t for t in r["_rest"] if t not in blocked][:CHUNK_TASKS]
        if not chunk:
            continue
        pick = take(v.cfg.route.get(r["kind"], {"gpu"}))
        if not pick:
            continue
        lane = _lane(r["kind"])
        asg = _assign(v, r, pick, lane, chunk)
        if r["kind"] not in READ_KINDS:
            for t in chunk:                                   # assign 먼저, 잠금은 그다음
                lk0 = v.locks.get(str(t)) or {}
                v.put(P_LOCK_TASK + f"{t}.json", {"task": str(t), "state": "held", "session": pick, "rid": r["rid"],
                                                  "decision": asg["decision"], "epoch": v.ep,
                                                  "gen": int(lk0.get("gen", 0)) + 1, "chunk": asg["chunk"],
                                                  "at": v.now}, "lock")
        seen.add(who)


# ---------------------------------------------------------------- 점검·깨우기
def periodic_check(v: View) -> dict:
    out = {"orphans": [], "needs_check": [], "executor_wait": [], "stalled": "1b"}
    for rid, req in v.requests.items():
        if req.get("status") in ("taken", "running") and not _active_assign(v, rid):
            out["orphans"].append(rid)
    out["needs_check"] = sorted(t for t, lk in v.locks.items() if lk.get("state") == "quarantine")
    runs = [("mgmt", v.mgmt), ("agg", v.agg)] + [("train:" + n, lk) for n, lk in v.train_locks.items()] \
        + [("create:" + k, lk) for k, lk in v.create_locks.items()]
    out["needs_check"] += [n for n, lk in runs if lk and lk.get("state") == "needs_check"]
    for r in runnable_requests(v):
        need = v.cfg.route.get(r["kind"], {"cpu"})
        if not (need & GPU_STARTABLE) and not any(v.alive(s) and v.caps(s) & need for s in v.workers):
            out["executor_wait"].append(r["rid"])
    return out


def wake_info(v: View, check: dict) -> dict:
    holds_active = sorted(k for k, h in v.holds.items() if h.get("active"))
    cands = []
    runnable = 0
    if not holds_active:
        for r in runnable_requests(v):
            if r["rid"] in check["executor_wait"]:
                continue
            if r["kind"] not in TASKLESS_KINDS and not [t for t in r["_rest"] if t not in _blocked_tasks(v, r)]:
                continue
            runnable += 1
    if runnable:
        cands.append(v.now)
    cands += [float(t) for t in v.inp.waiting.values()]
    cands += [float(v.holds[k]["until"]) for k in holds_active if v.holds[k].get("until") is not None]
    if not is_day(v.now, v.cfg.tz_offset_h):
        for rid, it in v.intake.items():
            req = v.requests.get(rid) or {}
            if it.get("ok") and not it.get("cancel_signal") and req.get("status") not in FINAL_STATUS \
                    and not it.get("night_signal") and not _completed(v, rid, req.get("kind")):
                cands.append(next_morning(v.now, v.cfg.tz_offset_h))
                break
    return {"runnable": runnable, "next_wake_at": min(cands) if cands else None,
            "observed_from": v.inp.list_started_at, "observed_requests": sorted(v.requests.keys()),
            "holds": holds_active}


# ---------------------------------------------------------------- 한 회
def decide_round(cfg: Cfg, inp: Inputs) -> Result:
    res = Result()
    v = View(cfg, inp, res)
    if v.grant is None or v.grant.get("session") != cfg.me:
        res.acting = False
        res.notes.append("not_arbiter")
        return res
    unknown = set(inp.unknown)
    if "state" in unknown:                        # arb/ 목록을 못 읽음 → 회차 기록도 쓰지 않음 (옛 기록을 덮지 않게)
        res.notes.append("state_unknown")
        return res
    for al in v.alerts:
        v.alert(short_hash(json.dumps(al, sort_keys=True, default=str)), al)
    critical = bool(CRITICAL & unknown)
    handled: List[str] = []
    report = None
    if v.handover is None:                       # 이 epoch의 인계를 아직 마치지 않음
        if not critical:
            report = reissue(v)
            report["check"] = periodic_check(v)
            pending = sorted(p for p in v.unknown_files if p.startswith(ARB + "locks/") or p.startswith(P_ASSIGN))
            v.put(P_RECOVERY + f"{v.ep}.json", report, "restart_report")
            v.put(P_HANDOVER + f"{v.ep}.json", {"epoch": v.ep, "at": v.now, "pending": pending}, "handover")
        else:
            res.notes.append("handover_waits_unknown")
    elif v.handover.get("pending") and not critical:   # 못 읽어 미뤄 둔 자원을 읽히는 회차에 마저 인계 (N3)
        ready = {p for p in v.handover["pending"] if p not in v.unknown_files}
        if ready:
            reissue(v, only=ready)
            v.put(P_HANDOVER + f"{v.ep}.json", dict(_strip(v.handover), pending=sorted(set(v.handover["pending"]) - ready)),
                  "handover_pending")
    if v.trusted(P_HANDOVER + f"{v.ep}.json", quiet=True) is not None:
        expire_holds(v)
        if "requests" not in unknown:
            intake_new(v)
        if not critical:
            reconcile(v)
        confirms: List[Tuple[str, dict]] = []
        if "asks" not in unknown and not (BLIND & unknown):
            handled, confirms = apply_reports(v)
        if not critical:
            expire(v)
            if "signals" not in unknown:
                process_signals(v)
            schedule(v)
            approve_confirms(v, confirms, handled)
    check = periodic_check(v)
    prev = set(v.arbiter.get("asks_handled") or [])
    if "asks" in unknown or (BLIND & unknown):
        keep = prev | set(handled)                   # 목록을 다 읽지 못했으면 줄이지 않음
    else:
        keep = (prev | set(handled)) & {_name(p) for p, _ in v.asks}
    same_epoch = int(v.arbiter.get("by_epoch", -1)) == v.ep
    rnd = int(v.arbiter.get("round", 0)) + 1 if same_epoch else 1
    v.put(P_ARBITER, {"epoch": v.ep, "round": rnd, "session": cfg.me, "at": v.now, "version": VERSION,
                      "unknown": sorted(unknown), "critical_unknown": critical, "check": check,
                      "wake": wake_info(v, check), "asks_handled": sorted(keep)}, "round")
    return res


# ---------------------------------------------------------------- 실행기 쪽 권한 확인 (M1)
PHASES = ("prepare", "recovery_publish", "cvat_write", "publish")


def executor_may_follow(files: Dict[str, FileRec], accounts: Dict[str, str], session: str, task: str,
                        decision: str, phase: str = "cvat_write", job: Optional[str] = None) -> Tuple[bool, str]:
    """실행기가 CVAT 쓰기·게시 직전에 확인.
    - prepare: 받기·추론·확정 신청 (held 또는 confirm_approved)
    - recovery_publish·cvat_write: 확정 승인(confirm_approved)이고 작업번호(job)가 맞아야 함
    - publish: 받는 중 일의 게시 잠금(held, publish)
    격리(quarantine)·해제(free)·복구 예약(reserved)은 모두 거절."""
    if phase not in PHASES:
        return False, "bad_phase"
    g = files.get(P_GRANT)
    if not g or not accounts.get("G") or g.owner != accounts["G"]:
        return False, "grant_untrusted"
    gr = g.obj or {}
    gep = int(gr.get("epoch", -1))
    lk = files.get(P_LOCK_TASK + f"{task}.json")
    if not lk:
        return False, "lost"
    o = lk.obj or {}
    if o.get("by_session") is None or o.get("by_epoch") is None or int(o["by_epoch"]) > gep \
            or (int(o["by_epoch"]) == gep and o["by_session"] != gr.get("session")):
        return False, "lock_untrusted"
    if o.get("session") != session or o.get("decision") != decision:
        return False, "lost"
    if int(o.get("epoch", -1)) != gep or int(o["by_epoch"]) != gep:
        return False, "wait_reissue"
    st = o.get("state")
    if st == "quarantine":
        return False, "quarantined"
    if phase == "prepare":
        return (True, "") if st in ("held", "confirm_approved") else (False, "lost")
    if phase == "publish":
        return (True, "") if st == "held" and o.get("publish") else (False, "not_publish_lock")
    if st != "confirm_approved":
        return False, "not_approved"
    if job is None or o.get("job") != job:
        return False, "job_mismatch"
    return True, ""


def stamp_ok(obj: Optional[dict], grant: dict) -> bool:
    """실행기가 판정 파일을 따를 수 있는가: 지금 자격의 세션·epoch가 쓴 것."""
    return bool(obj) and obj.get("by_session") == grant.get("session") \
        and obj.get("by_epoch") is not None and int(obj["by_epoch"]) == int(grant.get("epoch", -1))


def run_may_follow(files: Dict[str, FileRec], accounts: Dict[str, str], session: str, lock_path: str,
                   run: str, decision: str) -> Tuple[bool, str]:
    """실행형 일(관리·학습·취합·만들기)이 게시 직전에 확인 — 실행 잠금이 running이고 내 실행·decision."""
    g = files.get(P_GRANT)
    if not g or not accounts.get("G") or g.owner != accounts["G"]:
        return False, "grant_untrusted"
    gr = g.obj or {}
    lk = files.get(lock_path)
    if not lk:
        return False, "lost"
    o = lk.obj or {}
    if o.get("by_session") is None or o.get("by_epoch") is None or int(o["by_epoch"]) > int(gr.get("epoch", -1)):
        return False, "lock_untrusted"
    if o.get("session") != session or o.get("run") != run or o.get("decision") != decision:
        return False, "lost"
    if not stamp_ok(o, gr) or int(o.get("epoch", -1)) != int(gr.get("epoch", -2)):
        return False, "wait_reissue"
    return (True, "") if o.get("state") == "running" else (False, "not_running")


# ---------------------------------------------------------------- 새 TASK 만들기 후보 판정 (K6·L3)
def judge_create_candidates(intent: dict, candidates: List[dict], server_done: Optional[bool]) -> Tuple[str, Any]:
    c = [x for x in candidates if float(x.get("created", 0)) >= float(intent.get("created_at", 0))]
    if not c:
        return ("retry_ok", None) if server_done else ("needs_check", "no_candidate_server_unknown")
    if len(c) > 1:
        return "needs_check", "multiple_candidates"
    x = c[0]
    if intent.get("server_job") and x.get("server_job") == intent.get("server_job"):
        return "adopt", x["id"]
    if not x.get("has_media"):
        return "needs_check", "empty_candidate_without_evidence"
    if x.get("source_sha") and x.get("source_sha") == intent.get("source_sha") \
            and int(x.get("frames", -1)) == int(intent.get("frames", -2)):
        return "adopt", x["id"]
    return "needs_check", "candidate_not_verified"
