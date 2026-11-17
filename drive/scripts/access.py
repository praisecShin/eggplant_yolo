"""v4.33 실행 권한·쓰기 제한 — 설계 7판 '셀 분류', '실행기 규칙', '이 결과 올리기', '실행 코드의 신뢰 경계'.

신뢰 모델: 이 모듈의 분석 모드 장치는 **실수 방지 장치**입니다. CVAT·Drive 자격을 가진 등록 사용자의
고의를 막는 보안 경계가 아닙니다. 보안 장치는 배포 목록 해시 검증(verify_*)뿐입니다.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

MODE_VAR = "EGG_ACCESS"
MODES = ("analysis", "exec")
CHECK_GAP_SEC = 5.0        # 권한 확인과 호출 사이 최대 틈 (H1)
CVAT_CALL_MAX = 600        # CVAT 호출 하나 10분


class AccessError(RuntimeError):
    """허용되지 않은 쓰기·호출. 메시지에 비밀 값을 넣지 않습니다."""


# ---------------------------------------------------------------- 모드·실행 컨텍스트
def mode() -> str:
    m = os.environ.get(MODE_VAR, "analysis")
    return m if m in MODES else "invalid"


@dataclass
class ExecContext:
    rid: str
    session: str
    decision: str
    resources: Tuple[str, ...] = ()      # 쓰기 허가 경로 접두사 (BASE 기준)
    tasks: Tuple[str, ...] = ()
    run: str = ""


_CTX: contextvars.ContextVar[Optional[ExecContext]] = contextvars.ContextVar("egg_exec_ctx", default=None)


def current() -> Optional[ExecContext]:
    return _CTX.get()


@contextlib.contextmanager
def executing(ctx: ExecContext):
    """배정받은 일을 처리하는 동안만 실행 권한. 끝나면(finally) 거둠."""
    if mode() != "exec":
        raise AccessError("실행 권한은 실행기(EGG_ACCESS=exec)에서만 받을 수 있습니다")
    tok = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(tok)


_EXEC_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar("egg_exec_scope", default=False)


@contextlib.contextmanager
def exec_scope():
    """실행기가 한 걸음을 처리하는 동안만 (2c-1). 같은 Colab 커널에서 30번 셀(실행기)이 돌 때 분석 셀의 가드가
    실행기의 쓰기를 막지 않게 함. 실행기가 멈추면(이 블록을 벗어나면) 다른 셀의 쓰기는 다시 막힘."""
    if mode() != "exec":
        raise AccessError("실행 범위는 실행기(EGG_ACCESS=exec)에서만")
    tok = _EXEC_SCOPE.set(True)
    try:
        yield
    finally:
        _EXEC_SCOPE.reset(tok)


def in_exec_scope() -> bool:
    return mode() == "exec" and _EXEC_SCOPE.get()


def can_write_cvat() -> bool:
    return mode() == "exec" and current() is not None


# ---------------------------------------------------------------- CVAT 접속 (허용 목록)
CVAT_READ_ALLOWED = {
    # client / repo
    "tasks", "projects", "jobs", "organizations", "retrieve", "list", "get", "api_client", "config",
    "organization_slug",
    # 접속 확인·조직 (v4.32.0 ctt: whoami·조직 조회)
    "users_api", "retrieve_self", "organizations_api", "slug", "username", "email",
    # task 읽기
    "id", "name", "size", "status", "labels", "get_labels", "get_annotations", "get_meta",
    "get_frames_info", "get_frame", "get_preview", "updated_date", "created_date", "segment_size",
    "project_id", "subset", "owner", "data_chunk_size", "to_dict",
    # 참조용 export (서버 작업을 만들지만 라벨을 바꾸지 않음)
    "export_dataset", "tasks_api", "create_dataset_export", "retrieve_dataset",
    "requests_api", "retrieve_request", "list_requests",
}
# 범용 호출(call_api·rest_client·HTTP 메서드)은 허용하지 않음 — 경로·메서드로 무엇이든 바꿀 수 있음 (M2)
CVAT_LOCAL_SETTABLE = {"organization_slug"}     # 서버를 바꾸지 않는 client 로컬 설정


class ReadOnlyProxy:
    """분석 모드에서 쓰는 CVAT 감싼 객체. 허용 목록 밖 속성은 거절합니다."""

    def __init__(self, target: Any, path: str = "client"):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_p", path)

    def __getattr__(self, item):
        if item not in CVAT_READ_ALLOWED and not item.startswith("_repr"):
            raise AccessError(f"분석 모드에서는 CVAT의 '{item}'를 쓸 수 없습니다 — 바꾸는 일은 '요청으로 보내기'나 '이 결과 올리기'를 쓰세요")
        val = getattr(object.__getattribute__(self, "_t"), item)
        return _wrap(val, f"{object.__getattribute__(self, '_p')}.{item}")

    def __setattr__(self, k, v):
        if k in CVAT_LOCAL_SETTABLE:
            setattr(object.__getattribute__(self, "_t"), k, v)
            return
        raise AccessError("분석 모드에서는 CVAT 객체를 바꿀 수 없습니다")

    def __call__(self, *a, **k):
        return _wrap(object.__getattribute__(self, "_t")(*a, **k), object.__getattribute__(self, "_p") + "()")

    def __iter__(self):
        for x in object.__getattribute__(self, "_t"):
            yield _wrap(x, object.__getattribute__(self, "_p") + "[]")

    def __len__(self):
        return len(object.__getattribute__(self, "_t"))

    def __getitem__(self, i):
        return _wrap(object.__getattribute__(self, "_t")[i], object.__getattribute__(self, "_p") + "[]")

    def __repr__(self):
        return f"<읽기 전용 {object.__getattribute__(self, '_p')}>"


_SCALAR = (str, bytes, int, float, bool, type(None), Path)


def _wrap(val, path):
    """목록·사전 안의 객체까지 감쌈 (M2)."""
    if isinstance(val, _SCALAR):
        return val
    if isinstance(val, (list, tuple, set)):
        return type(val)(_wrap(x, path + "[]") for x in val)
    if isinstance(val, dict):
        return {k: _wrap(x, f"{path}[{k!r}]") for k, x in val.items()}
    return ReadOnlyProxy(val, path)


class CvatFactory:
    """모든 CVAT 접속을 여기서 만듭니다. 원시 client는 실행 컨텍스트 안에서만 돌려줍니다."""

    def __init__(self, make_raw: Callable[[], Any]):
        self._make_raw = make_raw
        self._raw = None

    def client(self):
        m = mode()
        if m == "invalid":
            raise AccessError(f"{MODE_VAR} 값이 올바르지 않습니다 — 쓰기를 거절합니다")
        if self._raw is None:
            self._raw = self._make_raw()
        if can_write_cvat():
            return self._raw
        return ReadOnlyProxy(self._raw)

    def raw_session_allowed(self) -> bool:
        """백업 스크립트의 자체 세션(requests) 같은 원시 접속 허용 여부."""
        return can_write_cvat()


# ---------------------------------------------------------------- 세션 지문 (8판)
def machine_fingerprint(hostname: Optional[str] = None, boot_id: Optional[str] = None) -> str:
    """세션이 도는 기계의 지문 8자. 호스트 이름 + 부팅 ID의 해시 — Kaggle·Colab은 실행마다 바뀜.
    파일 안에 적는 값이라 '증명'이 아니라 실수(노트북 사본 동시 실행 등)를 걸러내는 표시입니다."""
    import socket
    h = hostname if hostname is not None else socket.gethostname()
    if boot_id is None:
        try:
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception:
            boot_id = ""
    return hashlib.sha256(f"{h}|{boot_id}".encode()).hexdigest()[:8]


def new_session_id(env: str, fp: Optional[str] = None, now: Optional[float] = None) -> str:
    """<환경>-<기계 지문>-<시작 시각 MMDDHHMM>-<난수 4자>. 예: kgl-3fa91c2e-11140408-7k2q"""
    import secrets
    import string
    fp = fp or machine_fingerprint()
    t = time.strftime("%m%d%H%M", time.gmtime(now if now is not None else time.time()))
    rnd = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{env}-{fp}-{t}-{rnd}"


def worker_record_name(session: str, fp: str) -> str:
    """생존 신호 파일 이름: workers/<세션>__<지문>.json — 같은 세션이 두 기계에서 돌면 파일이 둘이 됨."""
    return f"workers/{session}__{fp}.json"


# ---------------------------------------------------------------- 저장 도우미 (입력/출력 분리)
@dataclass
class Paths:
    base: Path                 # 공유 입력 (읽기)
    output_root: Path          # 분석 출력 analysis/<M>/<날짜>_<세션>/
    session_tmp: Path          # 세션 임시 폴더
    narrow: Tuple[str, ...] = ("requests/", "relabel/requests/", "jobs/signals/", "workers/", "submissions/")


class Saver:
    def __init__(self, paths: Paths, person: str = "M1"):
        self.p = paths
        self.person = person

    def _rel(self, path: Path) -> Optional[str]:
        try:
            return Path(path).resolve().relative_to(self.p.base.resolve()).as_posix()
        except ValueError:
            return None

    def allowed(self, path, narrow: bool = False) -> Tuple[bool, str]:
        m = mode()
        if m == "invalid":
            return False, "invalid_mode"
        rp = Path(path).resolve()
        for root in (self.p.output_root, self.p.session_tmp):
            try:
                rp.relative_to(Path(root).resolve())
                return True, ""
            except ValueError:
                pass
        rel = self._rel(rp)
        if rel is None:
            return False, "outside_base"
        if narrow and any(rel.startswith(n) for n in self.p.narrow):
            if rel.startswith("submissions/") and not rel.startswith(f"submissions/{self.person}/"):
                return False, "other_person_submission"
            return True, ""
        ctx = current()
        if m == "exec" and ctx and any(rel.startswith(r) for r in ctx.resources):
            return True, ""
        return False, "not_permitted:" + rel

    def out(self, rel: str) -> Path:
        """분석 결과 경로. 분석 모드에서는 항상 output_root 아래."""
        p = self.p.output_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def open_write(self, path, mode_="w", narrow=False, **kw):
        ok, why = self.allowed(path, narrow)
        if not ok:
            raise AccessError(f"이 위치에는 쓸 수 없습니다 ({why})")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return open(path, mode_, **kw)

    def write_json(self, path, obj, narrow=False):
        with self.open_write(path, "w", narrow=narrow, encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return Path(path)


# ---------------------------------------------------------------- 권한 확인 (G1·H1)
class AuthorityLost(AccessError):
    pass


class NeedsCheck(RuntimeError):
    """처리기가 결과를 확정할 수 없음 → 실행기는 '멈춤 보고'(stop_run), 심판은 '확인 필요'로 둠 (b26 U2).
    reason은 짧은 영문 표식 (예: cleanup_unknown)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class WaitReissue(AccessError):
    pass


class Authority:
    """CVAT를 바꾸는 호출·공유 게시 직전마다 확인. check()는 (ok, 이유)를 돌려주는 함수.

    - 확인과 호출 사이 틈이 CHECK_GAP_SEC를 넘으면 다시 확인
    - 권한을 잃으면 AuthorityLost (복원도 하지 않음)
    - 자격이 바뀌고 다시 발급 전이면 최대 wait_max 기다림
    """

    def __init__(self, check: Callable[[], Tuple[bool, str]], clock=time.monotonic, sleep=time.sleep,
                 wait_max: float = 600, step_log: Optional["StepLog"] = None):
        self.check, self.clock, self.sleep, self.wait_max = check, clock, sleep, wait_max
        self.step_log = step_log
        self._ok_at: Optional[float] = None

    def ensure(self):
        t0 = self.clock()
        while True:
            ok, why = self.check()
            if ok:
                self._ok_at = self.clock()
                return
            if why == "wait_reissue" and self.clock() - t0 < self.wait_max:
                self.sleep(5)
                continue
            if self.step_log:
                self.step_log.write("lost", {"reason": why})
            raise AuthorityLost(f"권한을 잃었습니다 ({why}) — 복원하지 않고 멈춥니다")

    def call(self, what: str, fn: Callable, *a, **k):
        """매 호출마다 새로 확인 → 의도 기록 → 호출 직전 틈 확인 → 호출. 성공·실패와 상관없이 확인 결과를 버림 (M4)."""
        try:
            self._ok_at = None
            self.ensure()
            if self.step_log:
                self.step_log.write("intent", {"call": what})
            if self.clock() - self._ok_at > CHECK_GAP_SEC:     # 의도 기록이 느렸거나 멈췄다 깸
                self.ensure()
            if self.clock() - self._ok_at > CHECK_GAP_SEC:
                self.ensure()
            try:
                out = fn(*a, **k)
            except Exception as e:
                if self.step_log:
                    self.step_log.write("result", {"call": what, "ok": False, "error": type(e).__name__})
                raise
            if self.step_log:
                self.step_log.write("result", {"call": what, "ok": True})
            return out
        finally:
            self._ok_at = None


# ---------------------------------------------------------------- 단계 기록
class StepLog:
    """recovery/<TASK>/<작업번호>/steps/NNN_<종류>.json — 새 파일만 씀."""

    def __init__(self, writer: Callable[[str, dict], None], task: str, job: str, clock=time.time):
        self.writer, self.task, self.job, self.clock = writer, str(task), str(job), clock
        self.n = 0

    def dir(self) -> str:
        return f"recovery/{self.task}/{self.job}"

    def write(self, kind: str, data: dict):
        self.n += 1
        self.writer(f"{self.dir()}/steps/{self.n:03d}_{kind}.json", dict(data, kind=kind, at=self.clock()))


# ---------------------------------------------------------------- 해시
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 제출본 (G7)
def freeze_submission(saver: Saver, sub_root: Path, sub_id: str, files: Iterable[Path], meta: dict) -> Path:
    """분석 결과를 submissions/<M>/<제출ID>/에 복사해 고정. 같은 ID가 있으면 거절."""
    d = Path(sub_root) / saver.person / sub_id
    if d.exists():
        raise AccessError("같은 제출 ID가 이미 있습니다 — 새 ID로 보내세요")
    entries = []
    for f in files:
        f = Path(f)
        dst = d / f.name
        ok, why = saver.allowed(dst, narrow=True)
        if not ok:
            raise AccessError(f"제출본 위치에 쓸 수 없습니다 ({why})")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst)
        entries.append({"name": f.name, "sha256": sha256_file(dst), "size": dst.stat().st_size})
    need = {"task_id", "server", "frames", "labels", "mode", "frame_range", "frame_map_sha"}
    miss = need - set(meta)
    if miss:
        raise AccessError("제출 정보가 빠졌습니다: " + ",".join(sorted(miss)))
    man = dict(meta, files=entries, sub_id=sub_id, person=saver.person)
    saver.write_json(d / "_submission.json", man, narrow=True)
    return d


def verify_submission(local_dir: Path, task_info: dict) -> Tuple[bool, str]:
    """실행기가 자기 임시 폴더로 받은 제출본을 검증.
    task_info: {'task_id','server','frames','labels','frame_range','frame_map_sha'} — 지금 CVAT TASK에서 읽은 값"""
    d = Path(local_dir)
    try:
        man = json.loads((d / "_submission.json").read_text(encoding="utf-8"))
    except Exception:
        return False, "no_manifest"
    for e in man.get("files", []):
        f = d / e["name"]
        if not f.exists() or sha256_file(f) != e["sha256"]:
            return False, "hash_mismatch:" + e["name"]
    if str(man.get("task_id")) != str(task_info.get("task_id")):
        return False, "task_mismatch"
    if man.get("server") != task_info.get("server"):
        return False, "server_mismatch"
    if int(man.get("frames", -1)) != int(task_info.get("frames", -2)):
        return False, "frames_mismatch"
    if sorted(man.get("labels") or []) != sorted(task_info.get("labels") or []):
        return False, "labels_mismatch"
    if man.get("mode") not in ("replace", "append"):
        return False, "mode_missing"
    if list(man.get("frame_range") or []) != list(task_info.get("frame_range") or [None]):
        return False, "frame_range_mismatch"
    if man.get("frame_map_sha") != task_info.get("frame_map_sha"):
        return False, "frame_map_mismatch"        # 장수는 같아도 프레임 대응이 바뀐 TASK (M12)
    return True, ""


def frame_map_sha(frame_map) -> str:
    """프레임 대응(ULD 프레임맵 등)의 지문. 대응이 없으면 None을 넣고 그 사실도 비교합니다."""
    return sha256_bytes(json.dumps(frame_map, ensure_ascii=False, sort_keys=True).encode())


# ---------------------------------------------------------------- 배포 목록 검증 (K2)
class DeployError(AccessError):
    pass


def make_manifest(files: Dict[str, bytes], exclude: Iterable[str] = ()) -> bytes:
    """배포 목록. 마스터 노트북·목록 자신은 넣지 않음 (한 방향 사슬)."""
    ex = set(exclude) | {"manifest.json"}
    items = {k: sha256_bytes(v) for k, v in sorted(files.items()) if k not in ex}
    return json.dumps({"files": items}, ensure_ascii=False, sort_keys=True, indent=1).encode()


def verify_manifest(manifest_bytes: bytes, pinned_sha: str) -> dict:
    if sha256_bytes(manifest_bytes) != pinned_sha:
        raise DeployError("배포 목록 해시가 고정값과 다릅니다 — 실행하지 않습니다")
    return json.loads(manifest_bytes.decode())


def verified_bytes(manifest: dict, rel: str, data: bytes) -> bytes:
    """파일 해시를 목록과 대조하고, 검증한 바로 그 바이트를 돌려줌 (그대로 실행)."""
    want = (manifest.get("files") or {}).get(rel)
    if not want:
        raise DeployError(f"배포 목록에 없는 파일입니다: {rel}")
    if sha256_bytes(data) != want:
        raise DeployError(f"배포 목록과 다른 파일입니다: {rel}")
    return data


def exec_verified(manifest: dict, rel: str, data: bytes, glb: dict):
    code = verified_bytes(manifest, rel, data)
    exec(compile(code.decode("utf-8"), rel, "exec"), glb)


def import_verified(manifest: dict, rel: str, data: bytes, modname: str):
    import importlib.util
    import sys
    code = verified_bytes(manifest, rel, data)
    spec = importlib.util.spec_from_loader(modname, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = rel
    exec(compile(code.decode("utf-8"), rel, "exec"), mod.__dict__)
    sys.modules[modname] = mod
    return mod
