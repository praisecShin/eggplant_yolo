"""v4.33 1b — 판정·실행기가 쓰는 저장소 어댑터 (설계 8판 '심판: CPU 마스터' 2·3단계).

- `LocalStore`: 폴더 (시험, Drive가 마운트된 환경)
- `RcloneStore`: rclone 원격 (Kaggle). 명령마다 timeout, 제어 파일 전용
- `snapshot()`: 목록·파일을 읽어 `arbiter.Inputs`에 넣을 `files`와 `unknown`을 만듦.
  **못 읽은 것은 '없음'이 아니라 '모름'**으로 전달합니다 — 목록 실패는 종류 이름, 파일 실패는 `file:<경로>`.
- `apply_writes()`: 쓰기 목록을 차례대로 씀. 하나라도 실패하면 거기서 멈춤 (다음 회차가 이어 감).
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from arbiter import FileRec, Write


class StoreError(RuntimeError):
    pass


@dataclass
class Entry:
    path: str
    owner: str = ""
    created: float = 0.0
    modified: float = 0.0
    size: int = 0
    created_known: bool = True        # False: 저장소가 만든 시각을 주지 않아 수정 시각으로 대신함 (순서에만 씀)


class Beat(threading.Thread):
    """일하는 줄과 따로 도는 생존 신호. 긴 처리 중에도 계속 보냄 (Q1).
    final이 있으면 멈출 때 이 스레드가 마지막으로 씀 — 생존 신호 파일은 이 스레드 하나만 씀 (R7)."""

    def __init__(self, fn: Callable[[], None], interval: float = 60, final: Optional[Callable[[], None]] = None):
        super().__init__(daemon=True)
        self.fn, self.interval, self.final, self._stop_ev = fn, interval, final, threading.Event()
        self.errors, self.final_done = 0, False

    def run(self):
        while not self._stop_ev.is_set():
            try:
                self.fn()
            except Exception:
                self.errors += 1
            self._stop_ev.wait(self.interval)
        if self.final is not None:                       # 진행 중이던 쓰기가 끝난 뒤에만 '끝남'을 씀
            try:
                self.final()
                self.final_done = True
            except Exception:
                self.errors += 1

    def stop(self):
        self._stop_ev.set()


# (종류, 접두사, 하위 폴더까지, 파일 이름 거르기)
ARBITER_SPEC: List[Tuple[str, str, bool, Optional[Tuple[str, ...]]]] = [
    ("grant", "jobs/ARBITER_GRANT.json", False, None),
    ("requests", "requests/", False, None),
    ("requests", "relabel/requests/", False, None),
    ("workers", "workers/", False, None),
    ("signals", "jobs/signals/", False, None),
    ("state", "arb/", True, None),
    ("artifacts", "runs/", True, ("CURRENT.json", "_files.json")),
    ("artifacts", "datasets/", True, ("CURRENT.json", "_files.json")),
    ("artifacts", "sets/", True, ("CURRENT.json", "_files.json")),
]
EXECUTOR_SPEC = [
    ("grant", "jobs/ARBITER_GRANT.json", False, None),
    ("state", "arb/assign/", False, None),
    ("state", "arb/locks/", True, None),
    ("state", "arb/intake/", False, None),
    ("state", "arb/results/", False, None),
]


# ---------------------------------------------------------------- 폴더 저장소
class LocalStore:
    """폴더를 저장소로 씀. 소유 계정은 `owners`(경로 → 계정) 또는 `default_owner`.
    `fail`: 시험용 — (동작, 경로)를 받아 True면 그 동작을 실패시킴."""

    def __init__(self, root, default_owner: str = "", owners: Optional[Dict[str, str]] = None,
                 fail: Optional[Callable[[str, str], bool]] = None, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.default_owner, self.owners = default_owner, owners if owners is not None else {}
        self.fail, self.clock = fail, clock
        self._created: Dict[str, float] = {}
        self._mod: Dict[str, float] = {}

    def _chk(self, op, path):
        if self.fail and self.fail(op, path):
            raise StoreError(f"{op} 실패: {path}")

    def list(self, prefix: str, recursive: bool, include: Optional[Tuple[str, ...]] = None) -> List[Entry]:
        self._chk("list", prefix)
        base = self.root / prefix
        out = []
        if prefix.endswith(".json"):
            cands = [base] if base.exists() else []
        elif not base.exists():
            cands = []
        else:
            cands = base.rglob("*.json") if recursive else base.glob("*.json")
        for f in cands:
            if not f.is_file() or (include and f.name not in include):
                continue
            rel = f.relative_to(self.root).as_posix()
            st = f.stat()
            mod = self._mod.get(rel, st.st_mtime)
            out.append(Entry(rel, self.owners.get(rel, self.default_owner), self._created.get(rel, mod), mod, st.st_size))
        return out

    def read_json(self, path: str) -> Any:
        self._chk("read", path)
        try:
            return json.loads((self.root / path).read_text(encoding="utf-8"))
        except Exception as e:
            raise StoreError(f"읽기 실패: {path} ({type(e).__name__})")

    def exists(self, path: str) -> bool:
        self._chk("list", path)
        return (self.root / path).exists()

    def write_json(self, path: str, obj: Any, create_only: bool = False, owner: Optional[str] = None) -> bool:
        self._chk("write", path)
        f = self.root / path
        if create_only and f.exists():
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")   # 같은 파일 동시 쓰기에도 겹치지 않게
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
        now = self.clock()
        self._created.setdefault(path, now)
        self._mod[path] = now
        if owner is not None:
            self.owners.setdefault(path, owner)        # 소유자는 처음 만든 계정 (덮어써도 유지)
        return True

    def put_file(self, local: str, path: str):
        """큰 파일 올리기 (산출물). 실패하면 StoreError (2b)."""
        self._chk("write", path)
        f = self.root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        shutil.copyfile(local, tmp)
        os.replace(tmp, f)
        now = self.clock()
        self._created.setdefault(path, now)
        self._mod[path] = now

    def get_file(self, path: str, local: str):
        """큰 파일 받기. 없거나 실패하면 StoreError (2b)."""
        self._chk("read", path)
        src = self.root / path
        if not src.is_file():
            raise StoreError(f"받기 실패: {path}")
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, local)

    def list_any(self, prefix: str, recursive: bool = True) -> List[Entry]:
        """JSON이 아닌 파일까지 (영상·백업·모델 찾기, 2b-6)."""
        self._chk("list", prefix)
        base = self.root / prefix
        if not base.exists():
            return []
        out = []
        for f in (base.rglob("*") if recursive else base.glob("*")):
            if f.is_file() and not f.name.endswith(".tmp"):
                rel = f.relative_to(self.root).as_posix()
                st = f.stat()
                out.append(Entry(rel, self.owners.get(rel, self.default_owner), st.st_mtime, st.st_mtime, st.st_size))
        return out

    def pull(self, prefix: str, local: str, include: Tuple[str, ...] = ()):
        """prefix 아래를 local로 받음 (읽기 사본, 취합의 웹 상태 계산용). include는 rclone 무늬(prefix 기준)."""
        import fnmatch
        self._chk("read", prefix)
        base = self.root / prefix
        if not base.exists():
            return
        for f in base.rglob("*"):
            rel = f.relative_to(base).as_posix()
            if f.is_file() and (not include or any(fnmatch.fnmatch(rel, pat.lstrip("/")) for pat in include)):
                dst = Path(local) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst)

    def delete(self, path: str):
        """파일 하나 지우기 (청소 관리 일만 씀, 2b-5). 없으면 그대로, 실패하면 StoreError."""
        self._chk("delete", path)
        f = self.root / path
        if f.is_file():
            f.unlink()
        for d in (self._created, self._mod, self.owners):
            d.pop(path, None)

    def rename(self, src: str, dst: str):
        self._chk("write", dst)
        (self.root / dst).parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.root / src, self.root / dst)
        for d in (self._created, self._mod, self.owners):
            if src in d:
                d[dst] = d.pop(src)


# ---------------------------------------------------------------- rclone 저장소
def _iso(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        t = ts.replace("Z", "+00:00")
        if "." in t:                                   # 나노초 → 마이크로초
            head, rest = t.split(".", 1)
            frac, tz = rest, ""
            for sep in ("+", "-"):
                if sep in rest:
                    frac, tz = rest.split(sep, 1)
                    tz = sep + tz
                    break
            t = f"{head}.{frac[:6]}{tz}"
        return datetime.datetime.fromisoformat(t).timestamp()
    except Exception:
        return 0.0


def default_runner(args: List[str], input: Optional[str] = None, timeout: float = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(["rclone", *args], input=input, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


class RcloneStore:
    """rclone 원격(예: 'gdrive:eggplant_yolo'). 제어 파일만 다룹니다 — 큰 전송과 함께 쓰지 않습니다."""

    def __init__(self, remote: str, runner: Callable = default_runner, timeout: float = 60):
        self.remote = remote if remote.endswith(":") else remote.rstrip("/") + "/"
        self.runner, self.timeout = runner, timeout

    def _r(self, rel: str) -> str:
        return self.remote + rel

    def list(self, prefix: str, recursive: bool, include: Optional[Tuple[str, ...]] = None) -> List[Entry]:
        is_file = prefix.endswith(".json")
        target = prefix.rsplit("/", 1)[0] + "/" if is_file else prefix
        args = ["lsjson", self._r(target), "--files-only", "--metadata"]
        if recursive:
            args.append("-R")
        if is_file:
            args += ["--include", prefix.rsplit("/", 1)[1]]
        elif include:
            for n in include:
                args += ["--include", n]            # 앞에 /가 없는 무늬는 어느 깊이의 파일 이름에도 맞음
        else:
            args += ["--include", "*.json"]
        rc, out, err = self.runner(args, None, self.timeout)
        if rc != 0:
            if "directory not found" in (err or "").lower():
                return []                               # 폴더가 아직 없음 = 빈 목록 (읽기 실패가 아님)
            raise StoreError(f"목록 실패: {prefix}")
        try:
            items = json.loads(out or "[]")
        except Exception:
            raise StoreError(f"목록 해석 실패: {prefix}")
        if not isinstance(items, list) or not all(isinstance(it, dict) and isinstance(it.get("Path"), str) for it in items):
            raise StoreError(f"목록 형태가 다름: {prefix}")
        res = []
        for it in items:
            if it.get("IsDir"):
                continue
            md = it.get("Metadata") if isinstance(it.get("Metadata"), dict) else {}
            mod = _iso(str(it.get("ModTime", "")))
            bt = _iso(str(md.get("btime", "")))
            try:
                size = int(it.get("Size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            res.append(Entry(target + it["Path"], str(md.get("owner", "") or ""), bt or mod, mod, size, created_known=bool(bt)))
        return res

    def read_json(self, path: str) -> Any:
        rc, out, err = self.runner(["cat", self._r(path)], None, self.timeout)
        if rc != 0:
            raise StoreError(f"읽기 실패: {path}")
        try:
            return json.loads(out)
        except Exception:
            raise StoreError(f"해석 실패: {path}")

    def exists(self, path: str) -> bool:
        return any(e.path == path for e in self.list(path, False))

    def write_json(self, path: str, obj: Any, create_only: bool = False, owner: Optional[str] = None) -> bool:
        if create_only and self.exists(path):
            return False
        rc, out, err = self.runner(["rcat", self._r(path)], json.dumps(obj, ensure_ascii=False), self.timeout)
        if rc != 0:
            raise StoreError(f"쓰기 실패: {path}")
        return True

    def rename(self, src: str, dst: str):
        rc, out, err = self.runner(["moveto", self._r(src), self._r(dst)], None, self.timeout)
        if rc != 0:
            raise StoreError(f"이름 바꾸기 실패: {src}")

    def list_any(self, prefix: str, recursive: bool = True) -> List[Entry]:
        """JSON이 아닌 파일까지 (영상·백업·모델 찾기, 2b-6). 소유자 정보는 쓰지 않음."""
        args = ["lsjson", self._r(prefix), "--files-only"] + (["-R"] if recursive else [])
        rc, out, err = self.runner(args, None, max(self.timeout, 300))
        if rc != 0:
            if "directory not found" in (err or "").lower():
                return []
            raise StoreError(f"목록 실패: {prefix}")
        try:
            items = json.loads(out or "[]")
        except Exception:
            raise StoreError(f"목록 해석 실패: {prefix}")
        pre = prefix if prefix.endswith("/") or not prefix else prefix + "/"
        return [Entry(pre + it["Path"], "", _iso(str(it.get("ModTime", ""))), _iso(str(it.get("ModTime", ""))),
                      int(it.get("Size", 0) or 0), created_known=False)
                for it in items if isinstance(it, dict) and isinstance(it.get("Path"), str) and not it.get("IsDir")]

    def pull(self, prefix: str, local: str, include: Tuple[str, ...] = ()):
        """prefix 아래를 local로 받음 (읽기 사본). 바뀐 것만 (rclone copy --update)."""
        args = ["copy", self._r(prefix), local, "--update"]
        for pat in include:
            args += ["--include", pat]
        rc, out, err = self.runner(args, None, 1800)
        if rc != 0 and "directory not found" not in (err or "").lower():
            raise StoreError(f"받기 실패: {prefix}")

    def delete(self, path: str):
        """파일 하나 지우기 (청소 관리 일만, 2b-5). Drive 휴지통으로 감 (rclone 기본)."""
        rc, out, err = self.runner(["deletefile", self._r(path)], None, self.timeout)
        if rc != 0 and "not found" not in (err or "").lower():
            raise StoreError(f"지우기 실패: {path}")

    def put_file(self, local: str, path: str, timeout: float = 3600):
        """큰 파일 올리기 (산출물, 2b). 제어 파일과 달리 시간 한도를 길게."""
        rc, out, err = self.runner(["copyto", local, self._r(path)], None, timeout)
        if rc != 0:
            raise StoreError(f"올리기 실패: {path}")

    def get_file(self, path: str, local: str, timeout: float = 3600):
        rc, out, err = self.runner(["copyto", self._r(path), local], None, timeout)
        if rc != 0 or not Path(local).is_file():
            raise StoreError(f"받기 실패: {path}")


# ---------------------------------------------------------------- 읽기·쓰기
class Cache:
    """바뀐 파일만 다시 읽기 위한 기억 (수정 시각·크기). full_every초마다 전부 다시 읽음."""

    def __init__(self, full_every: float = 600):
        self.items: Dict[str, Tuple[float, int, Any]] = {}
        self.full_every, self.last_full = full_every, 0.0


def snapshot(store, spec=ARBITER_SPEC, cache: Optional[Cache] = None, clock=time.time
             ) -> Tuple[Dict[str, FileRec], Set[str], float]:
    """(files, unknown, 목록 읽기 시작 시각). 목록 실패 → 종류 이름, 파일 읽기 실패 → 'file:<경로>'."""
    started = clock()
    files: Dict[str, FileRec] = {}
    unknown: Set[str] = set()
    if cache is not None and started - cache.last_full >= cache.full_every:
        cache.items.clear()
        cache.last_full = started
    seen: Dict[str, Entry] = {}
    no_btime = 0
    dup: Set[str] = set()
    for kind, prefix, recursive, include in spec:
        try:
            here: Set[str] = set()
            for e in store.list(prefix, recursive, include):
                if e.path in here:                    # 한 목록에 같은 경로가 둘 = 같은 이름 파일 여럿 (b19 Z4)
                    dup.add(e.path)
                here.add(e.path)
                seen[e.path] = e
        except StoreError:
            unknown.add(kind)
            if prefix == "arb/":
                unknown.add("asks")                   # 신청·보고도 arb/ 아래
    for path in dup:                                  # 어느 것을 읽고 쓰는지 보장되지 않음 → 그 파일은 '모름' + 알림 (관리자가 하나를 지울 때까지)
        unknown.add("file:" + path)
        unknown.add("dup:" + path)
    for path, e in seen.items():
        if path in dup:
            continue
        no_btime += 0 if e.created_known else 1
        c = cache.items.get(path) if cache is not None else None
        if c and c[0] == e.modified and c[1] == e.size:
            obj = c[2]
        else:
            try:
                obj = store.read_json(path)
                # 문법은 맞는데 객체가 아니면 '모름'이 아니라 그대로 넘김 — 심판이 형태 검사로 거절(바깥 입력)·보호 모드(판정 파일).
                # '모름'은 판정 보류(0o)라서, 고쳐지지 않는 잘못된 바깥 파일 하나가 전체를 멈추게 하면 안 됨 (Q7 → 0o)
            except StoreError:
                unknown.add("file:" + path)
                if path == "jobs/ARBITER_GRANT.json":
                    unknown.add("grant")
                continue
            if cache is not None:
                cache.items[path] = (e.modified, e.size, obj)
        files[path] = FileRec(obj, e.owner, e.created, e.modified)
    try:
        store.no_btime = no_btime                     # 만든 시각이 빠진 파일 수 (마스터가 알림에 씀)
    except Exception:
        pass
    return files, unknown, started


def apply_writes(store, writes: Iterable[Write], owner: Optional[str] = None) -> Tuple[int, Optional[str]]:
    """차례대로 씀. 실패하면 그 자리에서 멈추고 (쓴 수, 실패한 경로)를 돌려줌."""
    n = 0
    for w in writes:
        try:
            store.write_json(w.path, w.obj, create_only=(w.mode == "create"), owner=owner)
        except StoreError:
            return n, w.path
        n += 1
    return n, None
