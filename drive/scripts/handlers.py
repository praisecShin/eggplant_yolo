"""v4.33 처리기 기반 (2b-1).

실행기(`executor.Executor`)가 부르는 실제 일을 요청 종류별로 등록하고 나눠 부릅니다. CPU 작업 프로세스·GPU 작업자·
Colab 30번 셀이 모두 같은 등록부를 씁니다.

- `register(kind, prepare=…, commit=…, fetch=…, publish=…, run=…)`: 종류마다 필요한 함수만
- `Dispatch`: 실행기에 넘기는 `Handlers` — 등록되지 않은 종류·단계는 `NoHandler`(실패 보고, 거짓 완료 없음)
- `CvatOps`: 처리기가 쓰는 CVAT 동작 묶음(읽기·백업/export 준비·받기·가져오기·이름 바꾸기). 실제 구현은
  `cvat_task_tools`·`cvat_backup`을 감싸고(2b-2·2b-3), 시험은 `tests/fake_cvat.py`
- `ScopedCvat`: 시험 실행(`_test`)은 정해진 프로젝트의 `REH_` TASK에만 쓰기 (2b-6 시험 범위 강제의 바탕)
- `publish_version` / `verify_version`: 산출물(모델·데이터셋·시험 설정)을 버전 경로에 올리고, 다시 받아 해시·크기를
  확인한 뒤에만 `_files.json`에 `verified: true` (필수: 산출물 목록 최종 검증)
- 진행: 처리기는 오래 걸리는 일 중간에 `ctx.progress("메모")`를 부름. 멈추면 심판이 `STALL_SEC` 뒤 '멈춘 것 같음'
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import arbiter as A
import executor as X
from arb_io import StoreError

# ---------------------------------------------------------------- 등록부
REGISTRY: Dict[str, Dict[str, Callable]] = {}
PHASE_NAMES = ("prepare", "commit", "fetch", "publish", "run")

# v4.32 앱이 쓰던 요청 종류 → v4.33 종류 (2f 전환 도구가 씀). None은 v4.33에 대응 없음(전환 대장에서 사람이 정리)
LEGACY_KIND = {"aa": "auto", "track": "track", "shape": "shape", "backup": "backup", "export": "export",
               "hide": "hide", "unhide": "unhide", "refresh": "refresh", "discard": None}


def register(kind: str, **fns: Callable):
    bad = [k for k in fns if k not in PHASE_NAMES]
    if bad:
        raise ValueError(f"모르는 단계: {bad}")
    REGISTRY.setdefault(kind, {}).update(fns)


def registered(kind: str, phase: str) -> bool:
    return phase in REGISTRY.get(kind, {})


class NoHandler(RuntimeError):
    pass


class Env:
    """처리기 환경. 실행 호스트(CPU 작업 프로세스·GPU 작업자·Colab 30번 셀)가 만들어 Dispatch에 넘김.
    cvat는 ScopedCvat로 감싼 것 (시험 범위). tmp는 세션 전용 임시 폴더."""

    def __init__(self, store, cvat=None, tmp: Optional[str] = None, test: bool = False, log: Callable[..., None] = print,
                 clock: Callable[[], float] = time.time):
        self.store, self.cvat, self.test, self.log, self.clock = store, cvat, test, log, clock
        self.tmp = tmp or tempfile.mkdtemp(prefix="egg_h_")
        os.makedirs(self.tmp, mode=0o700, exist_ok=True)


HANDLER_MODULES = ("h_read", "h_task", "h_agg", "h_mgmt", "h_run")


def load_all():
    """처리기 모듈을 불러 등록부를 채움 (실행 호스트가 시작할 때 한 번)."""
    import importlib
    for m in HANDLER_MODULES:
        importlib.import_module(m)


class Dispatch(X.Handlers):
    """요청 종류에 따라 등록된 처리기를 부름. env가 있으면 ctx.env로 넘김."""

    def __init__(self, registry: Optional[Dict[str, Dict[str, Callable]]] = None, env: Optional[Env] = None):
        self.registry = REGISTRY if registry is None else registry
        self.env = env

    def _fn(self, ctx: X.Ctx, name: str) -> Callable:
        fn = (self.registry.get(ctx.kind) or {}).get(name)
        if fn is None:
            raise NoHandler(f"{ctx.kind}.{name}")
        if self.env is not None:
            ctx.env = self.env
        return fn

    def prepare(self, ctx):
        return self._fn(ctx, "prepare")(ctx)

    def commit(self, ctx):
        return self._fn(ctx, "commit")(ctx)

    def fetch(self, ctx):
        return self._fn(ctx, "fetch")(ctx)

    def publish(self, ctx):
        return self._fn(ctx, "publish")(ctx)

    def run(self, ctx):
        return self._fn(ctx, "run")(ctx)


# ---------------------------------------------------------------- CVAT 동작 묶음
class CvatOps:
    """처리기가 쓰는 CVAT 동작. 실제 구현은 2b-2·2b-3에서 cvat_task_tools·cvat_backup을 감쌉니다."""
    WRITES = ("import_annotations", "remove_annotations", "rename_task", "create_task", "upload_video",
              "create_from_backup", "move_task")

    def get_task(self, tid: int) -> dict:                       # {id, name, project_id, size, labels, updated}
        raise NotImplementedError

    def list_tasks(self, limit: int = 5000) -> list:             # [{task_id, name, project_id, frames, media, status, updated_iso}]
        raise NotImplementedError

    def get_annotations(self, tid: int) -> dict:                # {shapes, tracks, tags, version}
        raise NotImplementedError

    def request_backup(self, tid: int) -> str:                  # 준비 작업 번호
        raise NotImplementedError

    def request_export(self, tid: int, fmt: str, images: bool = False) -> str:
        raise NotImplementedError

    def job_status(self, job: str) -> str:                      # queued | started | finished | failed
        raise NotImplementedError

    def download(self, job: str, dest: str) -> str:
        raise NotImplementedError

    def import_annotations(self, tid: int, path: str, fmt: str) -> str:   # 가져오기 작업 번호
        raise NotImplementedError

    def import_status(self, job: str) -> str:
        raise NotImplementedError

    def remove_annotations(self, tid: int):
        raise NotImplementedError

    def rename_task(self, tid: int, name: str):
        raise NotImplementedError

    def create_task(self, name: str, **kw) -> int:              # 빈 TASK (project_id·labels)
        raise NotImplementedError

    def upload_video(self, tid: int, path: str, frame_step: int, quality: int):   # 빈 TASK에 영상 (끝날 때까지 기다림)
        raise NotImplementedError

    def create_from_backup(self, path: str, name: str, **kw) -> int:   # 백업 zip → 새 TASK (한 번 호출)
        raise NotImplementedError

    def move_task(self, tid: int, project_id: int):
        raise NotImplementedError


class ScopeError(PermissionError):
    pass


class ImportRejected(RuntimeError):
    """가져오기를 서버가 분명히 받지 않음 (예: 4xx 거절) — 이때만 처리기가 되돌림 (b23 S2). 그 밖의 예외는 '모름'."""


class ticking:
    """오래 걸리는 호출(큰 파일 전송·SDK 가져오기) 동안 every초마다 progress를 부름 — 정상 전송을 '멈춤'으로 보지 않게 (b23 보충).
    호출이 실제로 끝나지 않으면 저장소·SDK의 시간 한도가 끝냄."""

    def __init__(self, progress: Callable[..., None], note: str, every: float = 60):
        import threading
        self.progress, self.note, self.every = progress, note, every
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self.every):
            try:
                self.progress(self.note)
            except Exception:
                pass

    def __enter__(self):
        self._th.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._th.join(timeout=5)
        return False


class ScopedCvat:
    """시험 실행은 `project_id` 프로젝트의 `prefix`로 시작하는 TASK에만 쓰기. 운영 실행은 시험 TASK(`prefix`)에 쓰지 않음.
    읽기는 그대로 통과. TASK 정보를 못 읽으면 쓰지 않음."""

    READS = ("get_task", "get_annotations", "request_backup", "request_export", "job_status", "download", "import_status")

    def list_tasks(self, limit: int = 5000) -> list:
        """TASK 목록. 시험 실행은 정해진 프로젝트의 REH_ TASK만 보임 (시험 취합이 운영 TASK를 다루지 않게)."""
        return self.list_tasks_full(limit)[0]

    def list_tasks_full(self, limit: int = 5000):
        """(행, 끝까지 읽었는가). '끝까지'는 **거르기 전** 원래 목록이 한도에 닿지 않았는가로 판단 (b24 T7)."""
        raw = self._ops.list_tasks(limit=limit)
        rows = raw
        if self.test:
            rows = [r for r in raw if r.get("project_id") == self.project_id and str(r.get("name", "")).startswith(self.prefix)]
        return rows, len(raw) < limit

    def __init__(self, ops: CvatOps, test: bool, project_id: Optional[int], prefix: str = "REH_"):
        self._ops, self.test, self.project_id, self.prefix = ops, test, project_id, prefix
        self._made = set()                             # 방금 백업에서 만든 TASK — 그 직후의 이름·프로젝트 맞춤에만 (b24 T3)

    def _new_ok(self, op: str, name, project_id):
        if self.test and (not str(name).startswith(self.prefix) or project_id != self.project_id):
            raise ScopeError(f"{op}: 시험 실행은 프로젝트 {self.project_id}에 {self.prefix} 이름으로만 만듦")
        if not self.test and str(name).startswith(self.prefix):
            raise ScopeError(f"{op}: 운영 실행은 시험 이름으로 만들지 않음")

    NEW_TASK_OPS = ("rename_task", "move_task")       # 만든 직후 범위를 맞추는 쓰기만 예외

    def release_new(self, tid):
        """만들기 처리기가 이름·프로젝트 맞춤을 마치면(성공이든 실패든) 예외를 거둠."""
        self._made.discard(int(tid))

    def _check(self, tid: int, op: str):
        if int(tid) in self._made and op in self.NEW_TASK_OPS:
            return
        try:
            t = self._ops.get_task(tid)
        except Exception as e:
            raise ScopeError(f"{op}: TASK {tid} 정보를 못 읽어 쓰지 않음 ({type(e).__name__})")
        name = str(t.get("name") or "")
        if self.test:
            if self.project_id is None or t.get("project_id") != self.project_id or not name.startswith(self.prefix):
                raise ScopeError(f"{op}: 시험 실행은 프로젝트 {self.project_id}의 {self.prefix} TASK에만 씀 (TASK {tid} {name})")
        elif name.startswith(self.prefix):
            raise ScopeError(f"{op}: 운영 실행은 시험 TASK({self.prefix})에 쓰지 않음 (TASK {tid})")

    def check_write(self, tid, what="prepare"):
        """쓰기 전에 미리 범위 확인 (준비 단계에서 무거운 계산 전에)."""
        self._check(tid, what)

    def import_annotations(self, tid, path, fmt, **kw):
        self._check(tid, "import_annotations")
        return self._ops.import_annotations(tid, path, fmt, **kw)

    def remove_annotations(self, tid):
        self._check(tid, "remove_annotations")
        return self._ops.remove_annotations(tid)

    def rename_task(self, tid, name):
        self._check(tid, "rename_task")
        if self.test and not str(name).startswith(self.prefix):
            raise ScopeError(f"rename_task: 시험 TASK 이름은 {self.prefix}로 시작해야 함")
        return self._ops.rename_task(tid, name)

    def create_task(self, name, **kw):
        self._new_ok("create_task", name, kw.get("project_id"))
        return self._ops.create_task(name, **kw)       # 빈 TASK는 처음부터 범위 안의 이름·프로젝트 → 예외 필요 없음

    def create_from_backup(self, path, name, **kw):
        self._new_ok("create_from_backup", name, kw.get("project_id"))
        tid = self._ops.create_from_backup(path, name, **kw)
        self._made.add(int(tid))
        return tid

    def upload_video(self, tid, path, frame_step, quality):
        self._check(tid, "upload_video")
        return self._ops.upload_video(tid, path, frame_step, quality)

    def move_task(self, tid, project_id):
        self._check(tid, "move_task")
        if self.test and project_id != self.project_id:
            raise ScopeError("move_task: 시험 실행은 정해진 프로젝트로만")
        return self._ops.move_task(tid, project_id)

    def __getattr__(self, name):
        """정해 둔 읽기·준비·받기만 넘김. 원래 연결(client·session)이나 새 함수는 넘기지 않음 — 범위 검사를 우회하지 못하게 (b23 S7)."""
        if name in self.READS:
            return getattr(self._ops, name)
        raise ScopeError(f"범위가 걸린 CVAT 묶음에는 '{name}'이 없음 (읽기·준비·받기와 감싼 쓰기만)")


# ---------------------------------------------------------------- 산출물 게시와 최종 검증
class VerifyError(RuntimeError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def version_dir(typ: str, name: str, run: str) -> str:
    return A.VERSION_FILES_OF[typ].format(n=name, run=run).rsplit("/", 1)[0] + "/"


def publish_version(store, typ: str, name: str, run: str, files: Dict[str, str], extra: Optional[dict] = None,
                    progress: Callable[..., None] = lambda *a, **k: None, auth: Optional[Callable[[], Any]] = None) -> dict:
    """files: {버전 안의 이름: 로컬 경로}. 올린 뒤 다시 받아 해시·크기를 확인하고, 모두 맞을 때만
    `_files.json`({files: {이름: {sha256, size}}, verified: true, …extra})을 씀. 하나라도 다르면 VerifyError (목록을 쓰지 않음).
    auth: 게시 직전 권한 확인(ctx.auth('run'))을 부르는 함수 — 목록을 쓰기 바로 앞에서 한 번 더 부름."""
    base = version_dir(typ, name, run)
    if store.exists(base + "_files.json"):            # 확인을 마친 버전은 바꾸지 않음 — 다시 하려면 새 실행 번호 (11/17 결정, b23 S4)
        raise VerifyError(f"이미 게시된 버전 ({base}) — 새 실행 번호로 다시 게시하세요")
    want = {}
    for rel, local in sorted(files.items()):
        if rel.startswith("/") or ".." in rel.split("/") or not rel:
            raise VerifyError(f"이름이 버전 밖을 가리킴: {rel}")
        want[rel] = {"sha256": sha256_file(local), "size": os.path.getsize(local)}
        with ticking(progress, f"올리는 중 {rel}"):
            store.put_file(local, base + rel)
        progress(f"올림 {rel}")
    got = check_files(store, base, want, progress)
    if got:
        raise VerifyError("다시 받아 보니 다름: " + ", ".join(got[:5]))
    if auth is not None:
        auth()
    man = dict(extra or {}, files=want, verified=True)
    store.write_json(base + "_files.json", man)
    return man


def check_files(store, base: str, want: Dict[str, dict], progress: Callable[..., None] = lambda *a, **k: None) -> list:
    """버전 경로의 파일을 다시 받아 목록과 맞는지. 다른 이름 목록을 돌려줌 (빈 목록 = 모두 맞음)."""
    bad = []
    with tempfile.TemporaryDirectory(prefix="egg_verify_") as td:
        for rel, w in sorted(want.items()):
            dst = str(Path(td) / "f")
            try:
                with ticking(progress, f"확인하려고 받는 중 {rel}"):
                    store.get_file(base + rel, dst)
            except StoreError:
                bad.append(rel + "(받기 실패)")
                continue
            if os.path.getsize(dst) != int(w.get("size", -1)) or sha256_file(dst) != w.get("sha256"):
                bad.append(rel)
            os.remove(dst)
            progress(f"확인 {rel}")
    return bad


def verify_version(store, typ: str, name: str, run: str) -> bool:
    """이미 게시된 버전의 목록과 실제 파일이 맞는가 (채택·학습 전에 다시 확인할 때)."""
    base = version_dir(typ, name, run)
    try:
        man = store.read_json(base + "_files.json")
    except StoreError:
        return False
    if not isinstance(man, dict) or not man.get("verified") or not isinstance(man.get("files"), dict):
        return False
    return not check_files(store, base, man["files"])
