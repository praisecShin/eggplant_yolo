"""v4.33 2b-5b — 복구 일 · 학습 · 새 TASK 만들기(16·17) · 23번 복원.

복구 일 (`recovery`, TASK 줄: prepare → commit)
- '확인 필요' TASK에서 사람이 ② 되돌리기(`revert`) 또는 ③ 다시 하기(`redo`)를 고르면 심판이 만드는 요청.
  intake: `mode`, `origin_rid`, `origin_job`. 원래 확정의 복구 자료 `recovery/<TASK>/<origin_job>/`를 씀.
- revert: `before_upload.zip`(기록된 해시와 대조) → 지금 라벨을 지우고 가져옴 → 라벨 수가 원래와 같아야 끝 →
  이름은 원래 이름으로. 쓰기 절차(업로드 전 백업·복구 자료·권한 확인·분명한 실패만 되돌림)는 h_task.commit 그대로.
- redo: 원요청의 종류·설정(복구 자료의 `params`, 없으면 원요청 intake)으로 다시 계산 → 같은 확정 절차.
- 결과는 그 TASK의 결과로 기록되고(심판), 원요청은 이미 '확인 필요 n건'으로 끝나 있음.

학습 (`train`, 학습 줄: run)
- 학습 잠금의 고정값(시작 데이터셋 버전·시작 모델 버전)만 씀. 데이터셋은 목록 해시와 대조해 받음.
- 시작 가중치: `params.train_from = 'current'`이면 시작 때 채택된 모델 버전의 best.pt(해시 대조), 아니면 기본 모델.
- 에폭마다 진행 알림과 권한 확인 → 잃으면 학습을 멈추고 게시하지 않음.
- `runs/<모델>/v/<실행ID>/`에 best.pt·results.csv·args.yaml·train.json → `_files.json`(train_keys = 데이터셋 출처 키)
  → `done_run` → 심판이 채택(시작 뒤 채택 바뀜·호환 모름·오염이면 채택 대기).

새 TASK 만들기 (`create16` 백업에서 · `create17` 영상에서, 만들기 줄: run) — DESIGN '새 TASK 만들기'
- 의도 기록 `recovery/create/<요청ID>/<실행ID>/intent.json`을 먼저 씀.
- 17: 빈 TASK 먼저 → 번호를 바로 기록 → 영상 올리기. 16: 백업 복원은 한 번 호출 → 번호 기록 → 이름·프로젝트.
- 응답을 잃으면 다시 만들지 않고 멈춤 보고('확인 필요'). 같은 요청의 앞선 의도가 '모름'이면 시작하지 않음
  (사람이 CVAT를 보고 `params.retry_confirmed = true`로 다시 요청).

23번 복원 (`restore23`, 관리 일, Colab 실행기)
- Drive 버전 기록에서 고른 사용자의 마지막 파일 → 새 모델 이름 `<이름>_<A|B…>`의 버전 경로 → 채택 바꾸기 보고.
  원본은 그대로.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import access
import arbiter as A
import handlers as H
import h_task as HT
from arb_io import StoreError
from h_mgmt import MgmtFailed, _wrap, params, run_lock as mgmt_lock


def _now(env) -> float:
    c = getattr(env, "clock", None)
    return c() if c else time.time()


# ================================================================ 복구 일
class RecoveryFailed(RuntimeError):
    pass


def _origin(ctx) -> dict:
    it = ctx.intake
    oj, orid = it.get("origin_job"), it.get("origin_rid")
    if not oj or not orid:
        raise RecoveryFailed("원래 확정을 모름 (origin_job·origin_rid 없음)")
    rdir = f"recovery/{ctx.task}/{oj}/"
    store = ctx.env.store
    try:
        plan = store.read_json(rdir + "result_plan.json")
    except StoreError:
        raise RecoveryFailed("원래 확정의 복구 자료(result_plan)를 못 읽음")
    if not isinstance(plan, dict) or str(plan.get("task")) != str(ctx.task):
        raise RecoveryFailed("복구 자료가 이 TASK 것이 아님")
    return {"dir": rdir, "plan": plan, "rid": orid, "job": oj}


def recovery_prepare(ctx) -> dict:
    env, tid = ctx.env, int(ctx.task)
    cv = env.cvat
    o = _origin(ctx)
    info = cv.get_task(tid)
    if hasattr(cv, "check_write"):
        cv.check_write(tid, "prepare")
    wd = HT._work(ctx)
    mode = ctx.intake.get("mode")
    plan = o["plan"]
    allow = (plan.get("params") or {}).get("allow_replace") is True
    if mode == "revert":
        before = str(wd / "origin_before.zip")
        env.store.get_file(o["dir"] + "before_upload.zip", before)
        sha = plan.get("before_sha256")
        if not sha or H.sha256_file(before) != sha:
            raise RecoveryFailed("업로드 전 백업이 기록과 다르거나 해시 기록이 없음 — 되돌리지 않음")
        return {"info": info, "params": {}, "file": before, "fmt": HT.IMPORT_FMT, "count": int(plan.get("existing") or 0),
                "exact_count": True, "mode": "replace", "rename_to": plan.get("name") or info.get("name"),
                "archive": False, "allow_replace": True, "summary": {"recovery": "revert", "origin_job": o["job"]}}
    if mode == "redo":
        kind = plan.get("kind")
        if kind not in ("track", "shape", "auto", "upload_submission"):
            raise RecoveryFailed(f"다시 할 수 없는 종류: {kind}")
        sub = access_copy(ctx, kind, plan.get("params") or {})
        out = HT.prepare(sub)
        out["allow_replace"] = allow
        out["summary"] = dict(out.get("summary") or {}, recovery="redo", origin_job=o["job"])
        out["origin_kind"] = kind
        return out
    raise RecoveryFailed(f"모르는 복구 방식: {mode}")


def access_copy(ctx, kind: str, prm: dict):
    """원요청 종류·설정으로 계산하는 ctx 사본 (권한·진행·작업 번호는 그대로)."""
    import executor as X
    c = X.Ctx(**{**ctx.__dict__})
    c.kind = kind
    c.intake = dict(ctx.intake, kind=kind, params=prm)
    return c


def recovery_commit(ctx) -> str:
    p = ctx.prepared or {}
    if p.get("origin_kind"):
        sub = access_copy(ctx, p["origin_kind"], {})
        sub.prepared = p
        return HT.commit(sub)
    return HT.commit(ctx)


def _recovery(fn):
    def run(ctx):
        try:
            return fn(ctx)
        except RecoveryFailed as e:
            raise H.NoHandler(f"recovery: {e}") from e     # 실패로 보고 (거짓 완료 없음)
    return run


# ================================================================ 학습
class Trainer:
    """학습 엔진. train(데이터셋 폴더, 시작 가중치, 설정, 작업 폴더, 에폭마다 부를 함수) →
    {'best': 경로, 'results': 경로?, 'args': 경로?, 'metrics': {...}}"""

    def train(self, ds_dir: str, start: str, args: dict, workdir: str, on_epoch) -> dict:
        raise NotImplementedError


class CleanupUnknown(access.NeedsCheck):
    """학습 프로세스를 모두 끝냈는지 확인하지 못함 → '확인 필요'(사람 확인 전까지 같은 학습을 다시 시작하지 않음)."""

    def __init__(self, detail: str = ""):
        super().__init__("cleanup_unknown", detail)


# ---------------------------------------------------------------- 프로세스 추적 (b26 U1·U5, Linux /proc)
def _stat(pid: int):
    """(ppid, pgid, 상태, 시작 시각) 또는 None. /proc/<pid>/stat의 이름 칸 뒤를 읽음."""
    try:
        raw = open(f"/proc/{pid}/stat", "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    rest = raw[raw.rfind(")") + 2:].split()
    try:
        return int(rest[1]), int(rest[2]), rest[0], int(rest[19])
    except (IndexError, ValueError):
        return None


def _all_pids():
    try:
        return [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return []


class ProcTree:
    """감독과 그 아래 모든 프로세스를 (pid, 시작 시각)으로 기억 — 감독이 끝난 뒤 남은 것이 없는지 확인용.
    감독이 고아 프로세스의 새 부모이므로 학습 동안 아래 프로세스는 늘 감독 사슬에 붙어 있음."""

    def __init__(self, leader: int):
        self.leader = leader
        self.known: Dict[int, int] = {}
        st = _stat(leader)
        if st:
            self.known[leader] = st[3]

    def scan(self):
        procs = {}
        for pid in _all_pids():
            st = _stat(pid)
            if st:
                procs[pid] = st
        roots = {p for p, t in self.known.items() if p in procs and procs[p][3] == t}
        changed = True
        while changed:
            changed = False
            for pid, st in procs.items():
                if pid not in roots and st[0] in roots:
                    roots.add(pid)
                    self.known.setdefault(pid, st[3])
                    changed = True
        return procs

    def alive(self) -> Dict[int, tuple]:
        """살아 있는(좀비 아닌) 추적 프로세스 {pid: stat}."""
        procs = self.scan()
        return {p: procs[p] for p, t in self.known.items() if p in procs and procs[p][3] == t and procs[p][2] != "Z"}

    def reap(self):
        """이쪽의 자식이 된 좀비를 회수 (추적한 것만 — 다른 subprocess의 자식은 건드리지 않음)."""
        me = os.getpid()
        for p, t in list(self.known.items()):
            st = _stat(p)
            if st and st[3] == t and st[2] == "Z" and st[0] == me and p != self.leader:
                try:
                    os.waitpid(p, os.WNOHANG)
                except ChildProcessError:
                    pass


class RealTrainer(Trainer):
    """Ultralytics 학습을 **별도 프로세스**(`train_child.py`)로 띄우고 부모(실행기)가 지켜봄 (b24 T4, 11/17 결정).
    - 자식에게 콜백을 넘기지 않음 → GPU 여럿(DDP)에서도 됨. 진행은 자식 폴더의 results.csv 줄 수(에폭)로 읽음
    - 부모는 poll마다 on_tick(권한 확인)을 부르고, 에폭이 늘면 on_epoch, 출력이 늘면 on_alive(진행 알림)
    - 학습은 **학습만 소유하는 감독**(`train_supervisor.py`, 고아 프로세스의 새 부모) 아래에서 돎 (b27 F1). 학습 자식이나
      DDP launcher가 먼저 끝나도 그 아래 프로세스(새 세션으로 나간 작업자 포함)는 감독 아래로 넘어옴. 감독은 아래에
      살아 있는 것이 하나도 없을 때까지 끝나지 않고, 끝날 때 '깨끗함'을 남김. 실행기의 다른 subprocess와 섞이지 않음
    - 끝날 때(정상·실패·권한 상실 모두) 감독에게 TERM → 감독이 자기 아래를 TERM → 60초 → KILL → 모두 없어진 뒤 끝남.
      감독이 안 끝나거나 '깨끗함'이 없거나 추적한 것이 남으면 KILL 뒤 `CleanupUnknown` → '확인 필요' (b26 U2).
      좀비는 살아 있는 것으로 보지 않음 (U5)
    - 자식은 실행별 설정·캐시·임시 폴더만 씀, 외부 기록 연동 끔 (b26 U4, 11/17 결정)
    - /proc가 없는 곳(Linux 아님)에서는 GPU 여럿 학습을 거절"""
    POLL = 10
    GRACE = 60                       # 감독이 TERM 뒤 KILL까지 기다리는 시간 (PyTorch 자체 정리 30초보다 길게)
    KILL_WAIT = 90                   # 실행기가 감독의 정리를 기다리는 시간 (GRACE + 여유)
    # 자식에게 넘기지 않는 환경 변수 (외부 기록 연동·추적 서버) — 앞부분이 같으면 뺌
    DROP_ENV = ("MLFLOW_", "WANDB_", "COMET_", "CLEARML_", "NEPTUNE_", "DVC_", "RAY_", "TENSORBOARD", "HF_TOKEN",
                "YOLO_", "ULTRALYTICS_")

    def __init__(self, imgsz: int = 1920, child: Optional[str] = None, python: Optional[str] = None,
                 sleep=time.sleep):
        self.imgsz, self.sleep = imgsz, sleep
        here = Path(__file__).resolve().parent
        self.child = child or str(here / "train_child.py")
        self.supervisor = str(Path(self.child).resolve().parent / "train_supervisor.py") \
            if (Path(self.child).resolve().parent / "train_supervisor.py").exists() else str(here / "train_supervisor.py")
        self.python = python or sys.executable

    @staticmethod
    def has_proc() -> bool:
        return os.path.isdir(f"/proc/{os.getpid()}")

    def child_env(self, wd: Path) -> dict:
        """실행별 설정·캐시·임시 폴더 (작업 폴더 안). 사람 작업자·다른 실행과 같은 파일을 쓰지 않게."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(self.DROP_ENV)}
        own = {"YOLO_CONFIG_DIR": wd / "cfg" / "ultralytics", "XDG_CONFIG_HOME": wd / "cfg" / "xdg",
               "XDG_CACHE_HOME": wd / "cfg" / "cache", "MPLCONFIGDIR": wd / "cfg" / "mpl", "TMPDIR": wd / "tmp",
               "TORCH_HOME": wd / "cfg" / "torch", "HOME": wd / "home"}
        for k, p in own.items():
            p.mkdir(parents=True, exist_ok=True)
            env[k] = str(p)
        env["YOLO_OFFLINE"] = "1"                      # 연동·업데이트 확인 끔 (설정은 실행별 폴더에서 자식이 다시 끔)
        return env

    def train(self, ds_dir, start, args, workdir, on_epoch, on_tick=None, on_alive=None):
        import re
        import signal
        import subprocess
        args = dict(args)
        linux = self.has_proc()
        if "," in str(args.get("device", "")) and not linux:
            raise RuntimeError("GPU 여럿 학습은 Linux(/proc)에서만 — 하위 프로세스를 모두 추적할 수 없음")
        y = Path(ds_dir) / "data.yaml"
        if y.exists():
            y.write_text(re.sub(r"^path:.*$", f"path: {ds_dir}", y.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
        wd = Path(workdir)
        wd.mkdir(parents=True, exist_ok=True)
        args.setdefault("imgsz", self.imgsz)
        spec = {"data": str(y), "start": str(start), "args": args, "project": str(wd), "name": "r",
                "done": str(wd / "done.json")}
        (wd / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        status = wd / "supervisor.json"
        if linux:   # 학습만 소유하는 감독 아래에서 (b27 F1): 고아가 된 하위 프로세스도 언제나 감독 아래로
            cmd = [self.python, self.supervisor, self.child, str(wd / "spec.json"), str(status), str(self.GRACE)]
        else:
            cmd = [self.python, self.child, str(wd / "spec.json")]
        log = open(wd / "train.log", "wb")
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(wd), start_new_session=True,
                                env=self.child_env(wd))
        tree = ProcTree(proc.pid) if linux else None
        res = wd / "r" / "results.csv"
        epochs, size, rc = 0, 0, None
        try:
            while True:
                rc = proc.poll()
                if tree:
                    tree.scan()
                n = max(0, len(res.read_text(encoding="utf-8").splitlines()) - 1) if res.exists() else 0
                if n > epochs:
                    epochs = n
                    on_epoch(n)
                cur = (wd / "train.log").stat().st_size
                if cur != size and on_alive:
                    size = cur
                    on_alive()
                if rc is not None:
                    break
                if on_tick:
                    on_tick()
                self.sleep(self.POLL)
        finally:
            log.close()
            first = sys.exc_info()[1]
            try:
                if linux:
                    self._stop(proc, tree, status, signal)
                else:
                    self._kill_group(proc, signal)
            except CleanupUnknown as cu:
                if first is not None:
                    raise CleanupUnknown(f"{cu} (원래: {type(first).__name__})") from first
                raise
        if linux:
            st_ = json.loads(status.read_text(encoding="utf-8"))
            if st_.get("setup_failed"):                  # 감독이 소유 경계를 못 만들어 학습을 띄우지 않음 (b28 V4)
                raise RuntimeError(f"학습 감독 준비 실패 — 학습을 시작하지 않음: {st_['setup_failed']}")
            child_rc = st_.get("child_rc")
        else:
            child_rc = rc
        if child_rc != 0 or not (wd / "done.json").exists():
            raise RuntimeError(f"학습 프로세스 실패 (종료 코드 {child_rc})")
        d = wd / "r"
        return {"best": str(d / "weights/best.pt"),
                "results": str(d / "results.csv") if (d / "results.csv").exists() else None,
                "args": str(d / "args.yaml") if (d / "args.yaml").exists() else None,
                "metrics": json.loads((wd / "done.json").read_text(encoding="utf-8")).get("metrics") or {}}

    def _stop(self, proc, tree, status: Path, signal):
        """감독에게 TERM → 감독이 자기 아래 전부를 정리하고 '깨끗함'을 남기며 끝나기를 기다림 (유예 + 여유).
        감독이 안 끝나거나, 상태 파일이 없거나 깨끗하지 않거나, 추적한 것이 남으면 KILL 뒤 CleanupUnknown."""
        if proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as e:
                raise CleanupUnknown("감독에게 신호 권한 없음") from e
            t0 = time.monotonic()
            while proc.poll() is None and time.monotonic() - t0 < self.KILL_WAIT:
                tree.scan()
                time.sleep(0.2)
        problem = None
        if proc.poll() is None:
            problem = "감독이 끝나지 않음"
        else:
            try:
                st = json.loads(status.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                st = None
            if not isinstance(st, dict) or st.get("clean") is not True:
                problem = "감독의 정리 결과가 없거나 깨끗하지 않음"
        tree.reap()
        left = {p_: v for p_, v in tree.alive().items() if p_ != proc.pid}
        if left and not problem:
            problem = f"추적한 프로세스 {len(left)}개가 남음"
        if problem:
            for pid in list(left) + ([proc.pid] if proc.poll() is None else []):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            raise CleanupUnknown(problem)

    def _kill_group(self, proc, signal):
        pgid = proc.pid
        def gone():
            proc.poll()
            try:
                os.killpg(pgid, 0)
                return False
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
        if not gone():
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as e:
                raise CleanupUnknown("신호 권한 없음") from e
            t0 = time.monotonic()
            while not gone() and time.monotonic() - t0 < self.KILL_WAIT:
                time.sleep(0.2)
            if not gone():
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                time.sleep(1)
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
        if not gone():
            raise CleanupUnknown("학습 프로세스 묶음이 남음")


TRAIN_ARG_KEYS = ("epochs", "lr0", "optimizer", "patience", "batch", "imgsz", "device", "lrf", "warmup_epochs", "freeze")


def train_lock(ctx) -> tuple:
    store = ctx.env.store
    for e in store.list(A.P_LOCK_TRAIN, False):
        lk = store.read_json(e.path)
        if isinstance(lk, dict) and lk.get("run") == ctx.run:
            return e.path, lk
    raise access.AuthorityLost("학습 잠금에 내 실행이 없음")


def get_verified(store, typ: str, name: str, ver: str, rel: str, dest: str) -> dict:
    """버전 목록의 해시와 대조해 받음. 다르거나 목록이 확인 전이면 MgmtFailed."""
    base = H.version_dir(typ, name, ver)
    try:
        man = store.read_json(base + "_files.json")
    except StoreError:
        raise MgmtFailed(f"{typ}_manifest_unreadable")
    if not isinstance(man, dict) or not man.get("verified") or rel not in (man.get("files") or {}):
        raise MgmtFailed(f"{typ}_unverified")
    src = (man.get("paths") or {}).get(rel) if man.get("legacy") else None   # v/legacy 등록은 옛 위치를 가리킬 수 있음 (2f)
    store.get_file(src or base + rel, dest)
    if H.sha256_file(dest) != man["files"][rel].get("sha256"):
        raise MgmtFailed(f"{typ}_hash_mismatch")
    return man


def run_train(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    _, lk = train_lock(ctx)
    model = lk.get("model") or "default"
    p = params(ctx)
    dname = ctx.intake.get("dataset") or "default"
    dver = lk.get("start_dataset_version")
    if not dver:
        raise MgmtFailed("no_dataset_version")
    wd = Path(env.tmp) / f"train_{ctx.run}"
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    with H.ticking(ctx.progress, "데이터셋 받는 중"):
        dman = get_verified(store, "dataset", dname, dver, "dataset.zip", str(wd / "dataset.zip"))
    with zipfile.ZipFile(wd / "dataset.zip") as z:
        z.extractall(wd / "ds")
    start_txt = "base"
    if p.get("train_from") == "current":
        sver = lk.get("start_version")
        if not sver:
            raise MgmtFailed("no_current_model")
        get_verified(store, "model", model, sver, "best.pt", str(wd / "start.pt"))
        start, start_txt = str(wd / "start.pt"), f"{model}@{sver}"
    else:
        start = getattr(env, "base_model", "yolo11s.pt")
    args = {k: p[k] for k in TRAIN_ARG_KEYS if k in p}
    w = ctx.auth("publish")

    def on_epoch(n):
        ctx.progress(f"학습 에폭 {n}")
        w.ensure()                                     # 잃으면 AuthorityLost → 학습 프로세스 묶음을 끝냄, 게시 없음
    out = env.trainer.train(str(wd / "ds"), start, dict(args), str(wd / "out"), on_epoch,
                            on_tick=w.ensure, on_alive=lambda: ctx.progress("학습 중"))
    files = {"best.pt": out["best"]}
    for k, rel in (("results", "results.csv"), ("args", "args.yaml")):
        if out.get(k):
            files[rel] = out[k]
    keys = dman.get("task_keys")
    try:
        dmeta = store.read_json(H.version_dir("dataset", dname, dver) + "dataset.json")
        classes = ((dmeta or {}).get("convert") or {}).get("KEEP_CLASSES")
    except StoreError:
        classes = None
    meta = {"model": model, "run": ctx.run, "rid": ctx.rid, "dataset": dname, "dataset_version": dver, "classes": classes,
            "start": start_txt, "start_version": lk.get("start_version"), "test_version": lk.get("start_test_version"),
            "args": args, "metrics": out.get("metrics") or {}, "made_at": _now(env)}
    (wd / "train.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    files["train.json"] = str(wd / "train.json")
    extra = {"run": ctx.run, "decision": ctx.decision, "gen": lk.get("gen"), "dataset": dname, "dataset_version": dver}
    if keys is not None:
        extra["train_keys"] = list(keys)               # 출처 모름이면 적지 않음 (시작 때 이미 '호환 모름'으로 채택 대기)
    H.publish_version(store, "model", model, ctx.run, files, extra=extra, progress=ctx.progress, auth=w.ensure)
    shutil.rmtree(wd, ignore_errors=True)
    return {"report": "done_run", "type_": "model", "name": model, "train_keys": list(keys or [])}


# ================================================================ 새 TASK 만들기
P_CREATE = "recovery/create/"


def create_lock(ctx) -> dict:
    p = A.P_LOCK_CREATE + f"{ctx.assign_obj.get('key')}.json"
    lk = ctx.env.store.read_json(p)
    if not isinstance(lk, dict) or lk.get("run") != ctx.run:
        raise access.AuthorityLost("만들기 잠금이 내 실행이 아님")
    return lk


def _intents(store, rid: str) -> List[dict]:
    out = []
    for e in store.list(P_CREATE + f"{rid}/", True, include=("intent.json",)):
        try:
            r = store.read_json(e.path)
        except StoreError:
            raise MgmtFailed("intent_unreadable")
        if isinstance(r, dict):
            out.append(dict(r, _path=e.path))
    return out


def run_create(ctx) -> dict:
    env, store, cv = ctx.env, ctx.env.store, ctx.env.cvat
    create_lock(ctx)
    p = params(ctx)
    name = ctx.intake.get("name")
    if not name:
        raise MgmtFailed("no_name")
    prev = [i for i in _intents(store, ctx.rid) if i.get("state") != "created"]
    if prev and p.get("retry_confirmed") is not True:
        return {"report": "stop_run", "reason": "earlier_create_unknown"}     # 앞선 만들기 결과를 모름 → 사람이 확인
    project = p.get("project_id")
    src = p.get("backup") if ctx.kind == "create16" else p.get("video")
    if not isinstance(src, str) or not src or ".." in src.split("/") or \
            not src.startswith("backups/" if ctx.kind == "create16" else "videos/"):
        raise MgmtFailed("bad_source")
    wd = Path(env.tmp) / f"create_{ctx.run}"
    wd.mkdir(parents=True, exist_ok=True)
    local = str(wd / Path(src).name)
    with H.ticking(ctx.progress, "원본 받는 중"):
        try:
            store.get_file(src, local)
        except StoreError:
            raise MgmtFailed("source_missing")
    ipath = P_CREATE + f"{ctx.rid}/{ctx.run}/intent.json"
    intent = {"rid": ctx.rid, "run": ctx.run, "kind": ctx.kind, "name": name, "source": src,
              "sha256": H.sha256_file(local), "size": os.path.getsize(local), "project_id": project,
              "frame_step": p.get("frame_step"), "decision": ctx.decision, "session": ctx.assign_obj.get("session"),
              "at": _now(env), "state": "intent"}
    w = ctx.auth("publish")
    w.call("intent", lambda: store.write_json(ipath, intent))

    def note(**kw):
        intent.update(kw)
        w.call("intent_update", lambda: store.write_json(ipath, intent))
    try:
        if ctx.kind == "create17":
            tid = w.call("create", lambda: cv.create_task(name, project_id=project, labels=p.get("labels")))
            note(state="empty_created", task_id=int(tid))
            with H.ticking(ctx.progress, "영상 올리는 중"):
                w.call("upload", lambda: cv.upload_video(int(tid), local, int(p.get("frame_step") or 10),
                                                         int(p.get("image_quality") or 70)))
        else:
            tid = w.call("create", lambda: cv.create_from_backup(local, name, project_id=project))
            try:
                note(state="restored", task_id=int(tid))
                info = cv.get_task(int(tid))
                if info.get("name") != name:
                    w.call("rename", lambda: cv.rename_task(int(tid), name))
                if project is not None and info.get("project_id") != project:
                    w.call("move", lambda: cv.move_task(int(tid), project))
            finally:
                if hasattr(cv, "release_new"):
                    cv.release_new(int(tid))           # 만든 직후 예외는 여기까지만 (b24 T3)
    except (access.AuthorityLost, access.AccessError, H.ScopeError):
        raise
    except Exception as e:
        try:
            note(state="unknown", error=type(e).__name__)
        except Exception:
            pass
        return {"report": "stop_run", "reason": "create_unknown"}           # 다시 만들지 않음 → '확인 필요'
    note(state="created")
    shutil.rmtree(wd, ignore_errors=True)
    return {"report": "done_job", "result": "done", "task_id": int(tid)}


# ================================================================ 23번 복원
class RevisionSource:
    """Drive 버전 기록. rows(name, until) → [{'sub','kind','user','t','file_id','rev_id'}] (파일마다 사용자별 마지막)."""

    def rows(self, name: str, until=None) -> List[dict]:
        raise NotImplementedError

    def download(self, file_id: str, rev_id: str, dest: str):
        raise NotImplementedError


class RealRevisions(RevisionSource):
    def __init__(self, base: str):
        import drive_revisions as dr
        self.dr, self.base, self.svc = dr, base, dr.drive_service()

    def rows(self, name, until=None):
        items = self.dr.collect(self.svc, self.base, name, extra=(), log=lambda *a: None)
        out = []
        for r in self.dr.pick(items, until=until):
            v, it = r.get("_rev"), r.get("_it")
            if v is None or it.get("kind") != "run":
                continue
            out.append({"sub": it["sub"], "kind": "run", "user": r["사용자"], "t": v["t"], "file_id": it["id"],
                        "rev_id": v["id"]})
        return out

    def download(self, file_id, rev_id, dest):
        self.dr.download_rev(self.svc, file_id, rev_id, dest)


def run_restore23(ctx) -> dict:
    env, store = ctx.env, ctx.env.store
    mgmt_lock(ctx)
    p = params(ctx)
    name, who = p.get("name"), p.get("user")
    if not isinstance(name, str) or not name or ".." in name or "/" in name or not who:
        raise MgmtFailed("bad_params")
    rows = env.revisions.rows(name, p.get("until"))
    users = sorted({r["user"] for r in rows}, key=lambda u: min(r["t"] for r in rows if r["user"] == u))
    suffix = {u: chr(ord("A") + i) for i, u in enumerate(users)}
    user = who if who in suffix else next((u for u, s in suffix.items() if s == who), None)
    if not user:
        raise MgmtFailed("no_such_user")
    mine = [r for r in rows if r["user"] == user]
    if not any(r["sub"] == "weights/best.pt" for r in mine):
        raise MgmtFailed("no_best_pt")
    # 모델 버전 계약: 가중치는 버전 바로 아래 best.pt (추론·이어 학습·웹 목록이 이 이름을 읽음, b24 T2)
    rename = {"weights/best.pt": "best.pt", "weights/last.pt": "last.pt"}
    new = f"{name}_{suffix[user]}"
    wd = Path(env.tmp) / f"rv_{ctx.run}"
    files = {}
    for r in mine:
        if ".." in r["sub"].split("/"):
            continue
        rel = rename.get(r["sub"], r["sub"])
        dst = wd / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with H.ticking(ctx.progress, f"버전 받는 중 {r['sub']}"):
            env.revisions.download(r["file_id"], r["rev_id"], str(dst))
        files[rel] = str(dst)
    (wd / "RESTORED_FROM.json").write_text(json.dumps({"from": f"runs/{name}", "user": user, "suffix": suffix[user],
                                                       "until": p.get("until"), "run": ctx.run, "at": _now(env),
                                                       "files": sorted(files)}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    files["RESTORED_FROM.json"] = str(wd / "RESTORED_FROM.json")
    w = ctx.auth("publish")
    H.publish_version(store, "model", new, ctx.run, files, extra={"run": ctx.run, "decision": ctx.decision,
                                                                   "restored_from": name, "user_suffix": suffix[user]},
                      progress=ctx.progress, auth=w.ensure)
    shutil.rmtree(wd, ignore_errors=True)
    return {"report": "done_job", "result": "done", "current_change": {"type": "model", "name": new, "version": ctx.run}}


H.register("recovery", prepare=_recovery(recovery_prepare), commit=_recovery(recovery_commit))
H.register("train", run=_wrap(run_train))
H.register("create16", run=_wrap(run_create))
H.register("create17", run=_wrap(run_create))
H.register("restore23", run=_wrap(run_restore23))
