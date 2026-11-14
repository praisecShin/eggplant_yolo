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
import subprocess
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
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
        now = self.clock()
        self._created.setdefault(path, now)
        self._mod[path] = now
        if owner is not None:
            self.owners.setdefault(path, owner)        # 소유자는 처음 만든 계정 (덮어써도 유지)
        return True

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
        res = []
        for it in items:
            if it.get("IsDir"):
                continue
            md = it.get("Metadata") or {}
            mod = _iso(it.get("ModTime", ""))
            res.append(Entry(target + it.get("Path", ""), md.get("owner", "") or "", _iso(md.get("btime", "")) or mod,
                             mod, int(it.get("Size", 0) or 0)))
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
    for kind, prefix, recursive, include in spec:
        try:
            for e in store.list(prefix, recursive, include):
                seen[e.path] = e
        except StoreError:
            unknown.add(kind)
            if prefix == "arb/":
                unknown.add("asks")                   # 신청·보고도 arb/ 아래
    for path, e in seen.items():
        c = cache.items.get(path) if cache is not None else None
        if c and c[0] == e.modified and c[1] == e.size:
            obj = c[2]
        else:
            try:
                obj = store.read_json(path)
            except StoreError:
                unknown.add("file:" + path)
                if path == "jobs/ARBITER_GRANT.json":
                    unknown.add("grant")
                continue
            if cache is not None:
                cache.items[path] = (e.modified, e.size, obj)
        files[path] = FileRec(obj, e.owner, e.created, e.modified)
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
