"""v4.33 2c-1 사람용 셀의 기반 (0번 셀이 부름). 설계 '셀 분류'·점검표 A·B·D.

사람이 셀을 실행하면 **분석 모드**입니다.
- 공유 폴더(BASE)는 읽기만. 결과는 자기 분석 폴더 `analysis/<사람>/<날짜>_<세션>/`에만 씀.
- 쓰기 가드(`WriteGuard`): open·os.replace·os.remove·shutil.rmtree·os.makedirs 등이 BASE 안의 허가 밖 경로에 쓰면 거절.
  BASE 밖(Colab 로컬 디스크)은 그대로. 실수 방지 장치입니다 (등록 사용자는 믿음, 설계 '신뢰 모델').
- CVAT 가드(`TransportGuard`): CVAT 서버로 가는 **HTTP 요청**에서 허용 목록만 통과 — 읽기(GET·HEAD·OPTIONS),
  로그인·로그아웃, 참조용 export 준비(`POST /api/tasks|jobs/<id>/dataset/export`). 그 밖의 POST·PUT·PATCH·DELETE는 거절.
  메서드 이름 추측이 아니라 전송 경계의 (방식, 경로) 허용 목록 — cvat-sdk·cvat_backup(requests)·ctt 함수 모두 같은 길을 지남.
  cvat-cli는 `run()`에서 허용 하위 명령만.
- 좁은 예외 API: 요청 만들기(`request`), 신호(`signal`) — 이 둘만 공유 폴더에 새 파일을 씀.
  (분석 세션의 생존 표시는 `workers/`가 아니라 자기 분석 폴더에 — workers/는 심판이 실행기로 읽음)
- 모델·데이터셋은 채택(`CURRENT.json`)된 버전을 목록 해시와 대조해 받음 (점검표 D).
- 같은 커널에서 30번 셀(실행기)이 도는 동안만 가드를 비켜 감(`access.in_exec_scope`). 실행기가 멈추면 다시 막힘.

옛 쓰기 함수(학습 잠금·업로드 기록·라벨 업로드 이름 바꾸기·Kaggle 동기화 등)는 `refused()`로 바꿔 부르면 이유를 알려 줌.
"""
from __future__ import annotations

import builtins
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import access
import arbiter as A

CELLS_VERSION = "4.33.0z10"
PERSON_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
REQUEST_KINDS = tuple(sorted(k for k in A.DEFAULT_ROUTE if k != "recovery"))   # 복구 일은 심판만 만듦
SIGNAL_KINDS = tuple(sorted(A.PERM_OF_SIGNAL))


class AnalysisRefused(access.AccessError):
    """분석 모드에서 할 수 없는 일. 메시지에 바꿔 쓸 길을 적음."""


def refused(what: str, hint: str = "") -> Callable:
    def f(*a, **k):
        raise AnalysisRefused(f"{what}: v4.33 사람용 셀은 분석 모드입니다 — "
                              + (hint or "바꾸는 일은 request(...)로 요청을 보내거나 '이 결과 올리기'를 쓰세요"))
    f.__name__ = what
    return f


# ---------------------------------------------------------------- 쓰기 가드
_ALLOW = threading.local()
KST = datetime.timezone(datetime.timedelta(hours=9))


def _orig(f):
    """가드가 감싼 함수의 진짜 원래 함수 (모듈을 다시 불러와도 가드가 겹치지 않게 — b28 V1)."""
    while getattr(f, "__egg_orig__", None) is not None:
        f = f.__egg_orig__
    return f


def _mark(wrapper, orig):
    wrapper.__egg_orig__ = _orig(orig)
    return wrapper


GUARD_GEN = 2          # 가드 방식의 세대. 다른 세대의 세션이 남은 커널에서는 바꾸지 않고 런타임 재시작을 안내 (b31 X2)


def _set_policy(writes, cvat, owner):
    """지금 적용할 규칙 묶음을 한 번의 대입으로 바꿈. 감싸기는 이 묶음을 한 번만 읽고 그대로 씀 (b31 X1)."""
    _state()["policy"] = (writes, cvat, owner)


def _policy():
    return _state().get("policy") or (None, None, None)


def _state() -> dict:
    """활성 세션 — 모듈 전역이 아니라 sys에 둠: 0번 셀의 importlib.reload(cb)에도 남음 (b28 V1)."""
    import sys
    st = getattr(sys, "_egg_cells_state", None)
    if st is None:
        st = {"active": None}
        sys._egg_cells_state = st
    return st


def _is_under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _dir_fd_path(p, dir_fd):
    """dir_fd 기준 상대 경로 → 절대 경로 (/proc/self/fd). 알 수 없으면 None."""
    if dir_fd is None or os.path.isabs(os.fspath(p)):
        return os.fspath(p)
    try:
        return os.path.join(os.readlink(f"/proc/self/fd/{int(dir_fd)}"), os.fspath(p))
    except (OSError, TypeError, ValueError):
        return None


@contextlib.contextmanager
def _narrow():
    """좁은 예외 API가 자기 파일을 쓰는 동안만."""
    prev = getattr(_ALLOW, "on", False)
    _ALLOW.on = True
    try:
        yield
    finally:
        _ALLOW.on = prev


class WriteGuard:
    """BASE 안의 허가 밖 경로에 쓰기·지우기·옮기기를 거절. BASE 밖은 그대로."""

    def __init__(self, saver: access.Saver):
        self.saver = saver
        self.base = Path(saver.p.base).resolve()
        self.refusals: List[str] = []

    def _under_base(self, p) -> bool:
        try:
            Path(os.path.abspath(os.fspath(p))).resolve().relative_to(self.base)
            return True
        except (ValueError, TypeError, OSError):
            return False

    def _entry(self, p) -> Path:
        """디렉터리 항목 자체 (지우기·옮기기·링크 만들기): 부모만 풀고 마지막 이름은 그대로 (b28 V5)."""
        ap = Path(os.path.abspath(os.fspath(p)))
        return ap.parent.resolve() / ap.name

    def _entry_ok(self, e: Path) -> bool:
        for root in (self.saver.p.output_root, self.saver.p.session_tmp):
            try:
                e.relative_to(Path(root).resolve())
                return True
            except ValueError:
                pass
        return False

    @staticmethod
    def _booting(p) -> bool:
        """새 세션이 자기 분석 폴더를 만드는 동안 (앞 세션의 가드가 아직 켜져 있을 때). 상태는 sys에 있어
        모듈을 다시 불러온 뒤에도 앞 가드가 알아봄 (b28 V1)."""
        b = _state().get("boot")
        if not b or b[0] != threading.get_ident():
            return False
        try:
            ap = Path(os.path.abspath(os.fspath(p)))
        except TypeError:
            return False
        out, ana = b[1], b[2]
        try:
            ap.relative_to(out)
            return True                                   # 새 분석 폴더와 그 안
        except ValueError:
            pass
        try:                                              # 새 분석 폴더까지 이어지는 부모 (analysis/·analysis/<사람>/)만 (b29 W5)
            out.relative_to(ap)
            return ap == ana or ap.relative_to(ana) is not None
        except ValueError:
            return False

    def check_entry(self, p, what: str):
        """항목을 바꾸는 일: 항목이 BASE 안이면 내 분석 폴더·임시 폴더 안일 때만 (링크가 가리키는 곳과 무관)."""
        if isinstance(p, int) or (p is not None and self._booting(p)):
            return
        if p is None:
            self.refusals.append(f"{what} (dir_fd 경로를 알 수 없음)")
            raise AnalysisRefused(f"공유 폴더 보호: {what}의 dir_fd 경로를 알 수 없어 거절합니다")
        e = self._entry(p)
        try:
            e.relative_to(self.base)
        except ValueError:
            return
        if access.in_exec_scope() or self._entry_ok(e):
            return
        if getattr(_ALLOW, "on", False):
            rel = e.relative_to(self.base).as_posix()
            if any((rel + "/").startswith(n) or n.startswith(rel + "/") for n in self.saver.p.narrow):
                return
        self.refusals.append(f"{what} {p}")
        raise AnalysisRefused(f"공유 폴더에 쓸 수 없습니다 ({what}: not_permitted:{e.relative_to(self.base).as_posix()}) — "
                              "결과는 OUT(분석 폴더)에, 바꾸는 일은 request(...)로")

    def check(self, p, what: str):
        if p is None:
            self.refusals.append(f"{what} (dir_fd 경로를 알 수 없음)")
            raise AnalysisRefused(f"공유 폴더 보호: {what}의 dir_fd 경로를 알 수 없어 거절합니다")
        if isinstance(p, int) or not self._under_base(p) or self._booting(p):
            return
        if access.in_exec_scope():
            return                                        # 같은 커널의 30번 셀(실행기)이 배정받은 일을 하는 중
        narrow = getattr(_ALLOW, "on", False)
        if narrow:                                         # 좁은 API가 자기 폴더(requests/·jobs/signals/)를 처음 만들 때
            rel = Path(os.path.abspath(os.fspath(p))).resolve().relative_to(self.base).as_posix() + "/"
            if any(n.startswith(rel) for n in self.saver.p.narrow):
                return
        ok, why = self.saver.allowed(p, narrow=narrow)
        if not ok:
            self.refusals.append(f"{what} {p}")
            raise AnalysisRefused(f"공유 폴더에 쓸 수 없습니다 ({what}: {why}) — 결과는 OUT(분석 폴더)에, "
                                  "바꾸는 일은 request(...)로")

    # 함수별 경로 인자: (이름, 위치, 'entry'=항목 자체 | 'content'=가리키는 곳, dir_fd 키워드)
    OS_ARGS = {
        "replace": (("src", 0, "entry", "src_dir_fd"), ("dst", 1, "entry", "dst_dir_fd")),
        "rename": (("src", 0, "entry", "src_dir_fd"), ("dst", 1, "entry", "dst_dir_fd")),
        "remove": (("path", 0, "entry", "dir_fd"),),
        "unlink": (("path", 0, "entry", "dir_fd"),),
        "rmdir": (("path", 0, "entry", "dir_fd"),),
        "symlink": (("dst", 1, "entry", "dir_fd"),),
        "link": (("dst", 1, "entry", "dst_dir_fd"),),
        "truncate": (("path", 0, "content", None),),
    }
    SH_ARGS = {
        "rmtree": (("path", 0, "entry"),),
        "move": (("src", 0, "entry"), ("dst", 1, "entry")),
        "copy": (("dst", 1, "content"),),
        "copy2": (("dst", 1, "content"),),
        "copyfile": (("dst", 1, "content"),),
        "copytree": (("dst", 1, "entry"),),
    }

    # ---- 공용 감싸기가 부르는 검사 (이 가드가 활성 세션의 가드이고 켜져 있을 때만 불림)
    @staticmethod
    def _arg(a, k, name, pos):
        return a[pos] if len(a) > pos else k.get(name)

    def before_open(self, file, mode):
        if any(c in str(mode) for c in "wax+"):
            self.check(file, "열기(쓰기)")

    def before_os(self, name, a, k):
        for pname, pos, kind, fdk in self.OS_ARGS[name]:
            p = self._arg(a, k, pname, pos)
            if p is None:
                continue
            if not isinstance(p, int):
                p = _dir_fd_path(p, k.get(fdk) if fdk else None)
            (self.check_entry if kind == "entry" else self.check)(p, f"os.{name}")

    def before_mkdir(self, path, dir_fd):
        p = _dir_fd_path(path, dir_fd)
        if p is None or not os.path.isdir(p):               # 이미 있는 폴더(pathlib의 exist_ok)는 바꾸는 것이 아님
            self.check_entry(p, "os.mkdir")

    def before_makedirs(self, name):
        if not os.path.isdir(name):
            self.check_entry(name, "os.makedirs")

    def before_sh(self, name, a, k):
        for pname, pos, kind in self.SH_ARGS[name]:
            p = self._arg(a, k, pname, pos)
            if p is not None:
                (self.check_entry if kind == "entry" else self.check)(p, f"shutil.{name}")

    def install(self):
        """감싸기를 깔고, 이 가드가 지금 규칙의 주인 세션 것이면 규칙에 다시 넣음. 감싸기는 프로세스에 한 번 깔리고
        언제나 '지금 규칙'을 한 번 읽어 그대로 씀 — 읽은 규칙이 앞 세션 것이어도 그 규칙으로 검사함 (b29 W1·b31 X1)."""
        _install_write_wrappers()
        w, c, o = _policy()
        if o is not None and getattr(o, "writes", None) is self and w is not self:
            _set_policy(self, c, o)

    def uninstall(self):
        """이 가드를 지금 규칙에서 뺌 (시험·정리용)."""
        w, c, o = _policy()
        if w is self:
            _set_policy(None, c, o)


def _active_writes():
    return _policy()[0]                               # 한 번 읽음 — 따로 '켜짐'을 확인하지 않음 (b31 X1)


def _install_write_wrappers():
    """open·os·shutil 감싸기를 깖 (진짜 원래 함수를 감쌈). 다시 불러도 같은 동작의 새 감싸기로 한 번에 바꿀 뿐."""
    o_open, o_io = _orig(builtins.open), _orig(io.open)

    def _open(file, mode="r", *a, **k):
        w = _active_writes()
        if w is not None:
            w.before_open(file, mode)
        return o_open(file, mode, *a, **k)
    builtins.open = _mark(_open, o_open)

    def _io_open(file, mode="r", *a, **k):
        w = _active_writes()
        if w is not None:
            w.before_open(file, mode)
        return o_io(file, mode, *a, **k)
    io.open = _mark(_io_open, o_io)

    def wrap_os(name):
        orig = _orig(getattr(os, name))

        def f(*a, **k):
            w = _active_writes()
            if w is not None:
                w.before_os(name, a, k)
            return orig(*a, **k)
        setattr(os, name, _mark(f, orig))
    for name in WriteGuard.OS_ARGS:
        wrap_os(name)

    o_mkdir, o_makedirs = _orig(os.mkdir), _orig(os.makedirs)

    def _mkdir(path, mode=0o777, *, dir_fd=None):
        w = _active_writes()
        if w is not None:
            w.before_mkdir(path, dir_fd)
        return o_mkdir(path, mode, dir_fd=dir_fd)
    os.mkdir = _mark(_mkdir, o_mkdir)

    def _makedirs(name, mode=0o777, exist_ok=False):
        w = _active_writes()
        if w is not None:
            w.before_makedirs(name)
        return o_makedirs(name, mode, exist_ok)
    os.makedirs = _mark(_makedirs, o_makedirs)

    def wrap_sh(name):
        orig = _orig(getattr(shutil, name))

        def f(*a, **k):
            w = _active_writes()
            if w is not None:
                w.before_sh(name, a, k)
            return orig(*a, **k)
        setattr(shutil, name, _mark(f, orig))
    for name in WriteGuard.SH_ARGS:
        wrap_sh(name)


# ---------------------------------------------------------------- CVAT 가드 (전송 경계)
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
CVAT_POST_ALLOWED = (
    re.compile(r"^/api/auth/(login|logout)/?$"),
    re.compile(r"^/api/(tasks|jobs)/\d+/dataset/export/?$"),        # 참조용 export 준비 (라벨을 바꾸지 않음)
)
CLI_ALLOWED = {("task", "ls"), ("project", "ls"), ("task", "export-dataset"), ("task", "frames")}


class TransportGuard:
    """CVAT 서버(hosts)로 가는 HTTP 요청을 허용 목록으로 거름. 다른 서버로 가는 요청은 그대로."""

    def __init__(self, hosts: Sequence[str]):
        self.hosts = {urllib.parse.urlparse(h).hostname or h for h in hosts}
        self.refusals: List[str] = []

    def allowed(self, method: str, url: str) -> Tuple[bool, str]:
        u = urllib.parse.urlparse(str(url))
        if (u.hostname or "") not in self.hosts:
            return True, "other_host"
        if access.in_exec_scope():
            return True, "exec"
        m = str(method or "").upper()
        if m in SAFE_METHODS:
            return True, "read"
        if m == "POST" and any(r.match(u.path) for r in CVAT_POST_ALLOWED):
            return True, "allowed_post"
        return False, f"{m} {u.path}"

    def _guard(self, method, url):
        ok, why = self.allowed(method, url)
        if not ok:
            self.refusals.append(why)
            raise AnalysisRefused(f"분석 모드에서는 CVAT를 바꾸는 요청을 보낼 수 없습니다 ({why}) — "
                                  "request(...)로 요청하거나 '이 결과 올리기'를 쓰세요")

    def patch_class(self, cls, attr: str = "request", method_pos: int = 0, url_pos: int = 1):
        """cls.attr(self, method, url, ...) 형태의 전송 함수를 감쌈 (한 번). 감싼 함수는 언제나 지금 활성 세션의
        CVAT 가드를 따름 (b29 W1)."""
        _patch_transport(cls, attr, method_pos, url_pos)

    def install(self):
        for cls in _transport_classes():
            _patch_transport(cls)
        w, c, o = _policy()
        if o is not None and getattr(o, "cvat", None) is self and c is not self:
            _set_policy(w, self, o)

    def uninstall(self):
        w, c, o = _policy()
        if c is self:
            _set_policy(w, None, o)

    def check_cli(self, cmd: Sequence[str]):
        """cvat-cli 명령: 허용 하위 명령만 (분석 모드)."""
        toks = [str(c) for c in cmd]
        if not any(Path(t).name in ("cvat-cli", "cvat_cli") or t == "cvat_cli" for t in toks):
            return
        if access.in_exec_scope():
            return
        for i, t in enumerate(toks[:-1]):
            if t in ("task", "project") and (t, toks[i + 1]) in CLI_ALLOWED:
                return
        self.refusals.append(" ".join(toks[:6]))
        raise AnalysisRefused("분석 모드에서는 cvat-cli로 CVAT를 바꿀 수 없습니다 (허용: task ls·export-dataset·frames)")


def _active_cvat():
    return _policy()[1]


def _transport_classes():
    out = []
    try:
        from cvat_sdk.api_client.rest import RESTClientObject          # cvat-sdk의 모든 HTTP가 지나는 곳
        out.append(RESTClientObject)
    except ImportError:
        pass
    try:
        import requests                                                  # cvat_backup의 자체 세션
        out.append(requests.Session)
    except ImportError:
        pass
    return out


def _patch_transport(cls, attr: str = "request", method_pos: int = 0, url_pos: int = 1):
    orig = _orig(getattr(cls, attr))

    def wrapped(obj, *a, **k):
        c = _active_cvat()
        if c is not None:
            method = a[method_pos] if len(a) > method_pos else k.get("method")
            url = a[url_pos] if len(a) > url_pos else k.get("url")
            c._guard(method, url)
        return orig(obj, *a, **k)
    setattr(cls, attr, _mark(wrapped, orig))


# ---------------------------------------------------------------- 세션
@dataclass
class Session:
    base: Path
    person: str
    session: str
    out: Path
    saver: access.Saver
    writes: WriteGuard
    cvat: TransportGuard
    local: Path
    store: Any = None
    seq: int = 0
    log: List[dict] = field(default_factory=list)
    model_meta: Optional[dict] = None                # 마지막으로 고른 모델 (이름·버전·채택 시각)

    # ---- 좁은 예외 API
    def request(self, kind: str, tasks: Sequence = (), params: Optional[dict] = None, **fields) -> str:
        """요청 파일 하나를 만듦 → 심판이 접수·배정. 돌려주는 값은 요청 ID."""
        if kind not in REQUEST_KINDS:
            raise AnalysisRefused(f"모르는 요청 종류: {kind} (가능: {', '.join(REQUEST_KINDS)})")
        params = dict(params or {})
        bad = [k for k in fields if k not in ("name", "model", "dataset", "server", "mode")]
        if bad:
            raise AnalysisRefused(f"요청에 넣을 수 없는 칸: {bad}")
        tids = [str(int(t)) for t in tasks]
        body = {"tasks": tids, "created": time.time(), "params": params, "by_person": self.person,
                "by_analysis_session": self.session, **{k: v for k, v in fields.items() if v is not None}}
        try:
            text = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError):
            raise AnalysisRefused("요청 설정(params)은 JSON으로 적을 수 있는 값만")
        self.seq += 1
        rid = f"{datetime.datetime.now(KST).strftime('%y%m%d%H%M%S')}{self.person}{self.session[-4:]}{self.seq:02d}"
        rid = re.sub(r"[^A-Za-z0-9]", "", rid)
        p = self.base / "requests" / f"REQ_{rid}__{kind}__pending.json"
        with _narrow():
            if p.exists():
                raise AnalysisRefused("같은 요청 ID가 이미 있음 — 다시 실행하세요")
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, p)
        self._note("request", rid=rid, kind=kind, tasks=tids)
        return rid

    # ---- '이 결과 올리기' (2c-4)
    SUB_FORMATS = ("CVAT 1.1", "shapes-json")

    def submit(self, task_id, task_info: dict, data_file, fmt: str, mode: str, server: str, model: str = "",
               settings: Optional[dict] = None, count: int = 0, note: str = "", extra_files: Sequence = ()) -> str:
        """분석 결과 파일을 고정 제출본 `submissions/<사람>/<제출ID>/`로 복사하고 제출 정보(`_submission.json`)를 씀.
        task_info: 지금 CVAT TASK에서 읽은 {'frames': TASK 프레임 수, 'labels': [라벨 이름]} — 실행기가 올리기 전에
        같은지 다시 확인함(access.verify_submission). 돌려줌: 'submissions/<사람>/<제출ID>/'"""
        if fmt not in self.SUB_FORMATS:
            raise AnalysisRefused(f"올릴 수 있는 형식이 아님: {fmt} (가능: {', '.join(self.SUB_FORMATS)})")
        if mode not in ("replace", "append"):
            raise AnalysisRefused("mode는 'replace'(기존 라벨을 지우고 바꿈) 또는 'append'(덧붙임)")
        data = Path(data_file)
        if not data.is_file():
            raise AnalysisRefused(f"올릴 파일이 없습니다: {data_file}")
        for f in [data, *map(Path, extra_files)]:                # 제출본은 내 분석 결과만 (공유 폴더의 남의 파일을 내 이름으로 내지 않게)
            rp = f.resolve()
            if not any(_is_under(rp, Path(r).resolve()) for r in (self.out, self.local)):
                raise AnalysisRefused(f"내 분석 폴더(OUT)나 Colab 로컬의 파일만 올릴 수 있습니다: {f}")
        frames = int(task_info.get("frames") or 0)
        labels = sorted(str(x) for x in (task_info.get("labels") or []))
        if frames <= 0 or not labels:
            raise AnalysisRefused("TASK 프레임 수·라벨 정의를 읽지 못함 — 제출본에 넣을 수 없음")
        self.seq += 1
        sub_id = re.sub(r"[^A-Za-z0-9_]", "", f"{datetime.datetime.now(KST).strftime('%y%m%d%H%M%S')}_{task_id}_{self.session[-4:]}{self.seq:02d}")
        meta = {"task_id": str(int(task_id)), "server": str(server).rstrip("/"), "frames": frames, "labels": labels,
                "mode": mode, "frame_range": [0, frames - 1], "frame_map_sha": access.frame_map_sha(None),
                "format": fmt, "data": data.name, "count": int(count), "model": model, "settings": settings or {},
                "note": note, "made_at": time.time(), "analysis_session": self.session,
                "analysis_out": str(self.out.relative_to(self.base))}
        with _narrow():
            d = access.freeze_submission(self.saver, self.base / "submissions", sub_id, [data, *map(Path, extra_files)], meta)
        self._note("submit", sub=sub_id, task=str(task_id))
        return d.relative_to(self.base).as_posix() + "/"

    def request_upload(self, task_id, submission: str, allow_replace: bool = False) -> str:
        """제출본을 올리라는 요청 (upload_submission). 사람 라벨이 있는 TASK를 바꾸려면 allow_replace=True."""
        if not str(submission).startswith(f"submissions/{self.person}/"):
            raise AnalysisRefused("내 제출본(submissions/<내 ID>/…)만 올릴 수 있습니다")
        return self.request("upload_submission", [task_id], params={"submission": submission, "allow_replace": bool(allow_replace)})

    # ---- 요청 상태 (읽기만, 2c-3)
    def status(self, rid: str) -> dict:
        """요청 하나의 상태: 파일 이름의 상태(pending·…·done·failed·canceled·needs_check), 접수(받음·거절 이유),
        TASK별 결과(심판 기록). 읽기만 함."""
        rid = re.sub(r"[^A-Za-z0-9]", "", str(rid))
        out = {"rid": rid, "kind": "", "status": "없음", "intake": None, "results": {}}
        for d in A.REQ_DIRS:
            try:
                ents = self.store.list(d, False)
            except Exception:
                continue
            for e in ents:
                pr = A.parse_req_name(e.path)
                if pr and pr[0] == rid:
                    out["kind"], out["status"], out["file"] = pr[1], pr[2], e.path
        try:
            out["intake"] = self.store.read_json(A.P_INTAKE + rid + ".json")
        except Exception:
            pass
        try:
            for e in self.store.list(A.P_RESULTS, False):
                if not os.path.basename(e.path).startswith(rid + "__"):
                    continue
                try:
                    r = self.store.read_json(e.path)
                except Exception:
                    continue
                if isinstance(r, dict) and str(r.get("rid")) == rid:
                    out["results"][str(r.get("task"))] = str(r.get("result"))
        except Exception:
            pass
        return out

    def my_requests(self, all_sessions: bool = False) -> List[dict]:
        """내가 보낸 요청 [{rid, kind, status, tasks, created}] — 이 세션(또는 이 사람의 모든 세션). 읽기만 함."""
        out = []
        try:
            ents = self.store.list("requests/", False)
        except Exception:
            return out
        for e in ents:
            pr = A.parse_req_name(e.path)
            if not pr:
                continue
            try:
                b = self.store.read_json(e.path)
            except Exception:
                continue
            if not isinstance(b, dict) or b.get("by_person") != self.person:
                continue
            if not all_sessions and b.get("by_analysis_session") != self.session:
                continue
            out.append({"rid": pr[0], "kind": pr[1], "status": pr[2], "tasks": b.get("tasks") or [],
                        "created": b.get("created", 0), "params": b.get("params") or {}})
        return sorted(out, key=lambda r: r["created"])

    def signal(self, kind: str, **fields) -> str:
        """신호 파일 하나 (취소·확인 선택·야간 승인 등) → 심판이 처리."""
        if kind not in SIGNAL_KINDS:
            raise AnalysisRefused(f"모르는 신호 종류: {kind}")
        try:
            text = json.dumps(fields, ensure_ascii=False)
        except (TypeError, ValueError):
            raise AnalysisRefused("신호 내용은 JSON으로 적을 수 있는 값만")
        self.seq += 1
        sid = f"{kind}__{re.sub(r'[^A-Za-z0-9]', '', self.session)}__{int(time.time())}{self.seq:02d}"
        p = self.base / A.P_SIGNALS / f"{sid}.json"
        with _narrow():
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "x", encoding="utf-8") as f:
                f.write(text)
        self._note("signal", sid=sid, kind=kind)
        return sid

    # ---- 분석 폴더
    def out_path(self, rel: str) -> Path:
        rel = str(rel).lstrip("/")
        if ".." in Path(rel).parts:
            raise AnalysisRefused("분석 폴더 밖을 가리키는 이름")
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _note(self, what: str, **kw):
        self.log.append(dict(kw, what=what, at=time.time()))
        try:
            with open(self.out / "_session.json", "w", encoding="utf-8") as f:
                json.dump({"person": self.person, "session": self.session, "version": CELLS_VERSION,
                           "events": self.log[-500:]}, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ---- 명령 실행
    def run(self, cmd, log=None, env=None, echo=print) -> int:
        """명령 실행 (옛 0번 셀 run과 같음). cvat-cli는 허용 하위 명령만, 기록 파일은 분석 폴더(또는 BASE 밖)만."""
        import subprocess
        self.cvat.check_cli(cmd)
        if log is not None:
            self.writes.check(log, "명령 기록")
        echo("$ " + " ".join(map(str, cmd)))
        p = subprocess.Popen(list(map(str, cmd)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env={**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})})
        fh = open(log, "a", encoding="utf-8") if log else None
        for line in p.stdout:
            echo(line.rstrip("\n"))
            if fh:
                fh.write(line)
        p.wait()
        if fh:
            fh.close()
        return p.returncode

    # ---- 모델·데이터셋 (채택된 버전, 해시 대조)
    def models(self) -> List[dict]:
        import h_agg as HA
        return HA.adopted_models(self.store)

    LAST_ADOPTED = "last_adopted"

    def model(self, choice="last_adopted") -> Tuple[str, str, str]:
        """(이름, 버전, 로컬 best.pt). 'last_adopted'(최근 채택) = 채택 시각이 가장 늦은 모델 — '최근 학습 완료'가 아님.
        옛 'latest'(최근 학습 완료)와 섞이지 않게 'latest'는 받지 않음 (b28 D11)."""
        import h_run as HR
        if choice == "latest":
            raise AnalysisRefused("v4.33에서는 'latest'를 쓰지 않습니다 — 'last_adopted'(최근 채택된 모델) 또는 모델 이름을 쓰세요 "
                                  "(옛 'latest'는 '최근 학습 완료'라 뜻이 다름)")
        ms = self.models()
        if not ms:
            raise AnalysisRefused("채택된 모델이 없습니다")
        if choice == self.LAST_ADOPTED:
            timed = [x for x in ms if isinstance(x.get("adopted_at"), (int, float)) and x["adopted_at"] > 0]
            if not timed:                                    # 채택 시각이 하나도 없으면 고르지 않음 (이름순 첫 모델 금지)
                raise AnalysisRefused("채택 시각이 기록된 모델이 없어 '최근 채택'을 정할 수 없습니다 — 모델 이름을 적으세요 "
                                      f"(있는 것: {', '.join(x['name'] for x in ms)})")
            m = max(timed, key=lambda x: float(x["adopted_at"]))
        else:
            m = next((x for x in ms if x["name"] == str(choice)), None)
            if m is None:
                raise AnalysisRefused(f"채택된 버전이 없는 모델: {choice} (있는 것: {', '.join(x['name'] for x in ms)})")
        self.model_meta = dict(m)
        dst = self.local / "models" / m["name"] / m["version"] / "best.pt"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            HR.get_verified(self.store, "model", m["name"], m["version"], "best.pt", str(dst))
        return m["name"], m["version"], str(dst)

    def dataset(self, name: str, version: Optional[str] = None) -> Tuple[str, str]:
        """(버전, 로컬 폴더) — 채택된(또는 지정한) 데이터셋 버전을 해시 대조해 받아 풂."""
        import zipfile
        import h_run as HR
        ver = version
        if not ver:
            try:
                cur = self.store.read_json(A.CURRENT_OF["dataset"].format(n=name))
            except Exception:
                cur = None
            ver = cur.get("version") if isinstance(cur, dict) else None
        if not ver:
            raise AnalysisRefused(f"채택된 데이터셋이 없습니다: {name}")
        d = self.local / "datasets" / name / ver
        if not (d / "data.yaml").exists():
            z = self.local / "datasets" / name / f"{ver}.zip"
            z.parent.mkdir(parents=True, exist_ok=True)
            HR.get_verified(self.store, "dataset", name, ver, "dataset.zip", str(z))
            shutil.rmtree(d, ignore_errors=True)
            with zipfile.ZipFile(z) as zf:
                zf.extractall(d)
            y = d / "data.yaml"
            if y.exists():
                y.write_text(re.sub(r"^path:.*$", f"path: {d}", y.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
        return ver, str(d)

    def dataset_of_model(self, name: str, version: str) -> Tuple[str, str]:
        """모델 버전을 만든 데이터셋 버전 (train.json) → (버전, 로컬 폴더). 모르면 AnalysisRefused."""
        try:
            meta = self.store.read_json(f"runs/{name}/v/{version}/train.json")
        except Exception:
            meta = None
        if not isinstance(meta, dict) or not meta.get("dataset") or not meta.get("dataset_version"):
            raise AnalysisRefused(f"모델 {name}의 학습 데이터셋 기록이 없습니다")
        return self.dataset(str(meta["dataset"]), str(meta["dataset_version"]))

    def run_dir(self, name: str, version: str) -> str:
        """모델 버전의 기록 폴더(results.csv·args.yaml) — 버전 경로, legacy는 옛 runs/<이름>."""
        try:
            man = self.store.read_json(f"runs/{name}/v/{version}/_files.json")
        except Exception:
            man = {}
        if isinstance(man, dict) and man.get("legacy") and isinstance(man.get("paths"), dict):
            bp = man["paths"].get("best.pt")
            if isinstance(bp, str) and bp.endswith("/weights/best.pt"):
                return str(self.base / bp[: -len("/weights/best.pt")])
        return str(self.base / f"runs/{name}/v/{version}")

    # ---- 올린 결과 (2c-2: 옛 작업 대장 + v4.33 실행기 결과)
    def uploads(self, tid) -> List[dict]:
        """v4.33 실행기가 이 TASK에 올린 결과 (심판 결과 + 접수 + 복구 자료의 result_plan). 오래된 것부터.
        각 행: kind·status·time·request·job·model·result_file(BASE 기준)·before_file·source='v4.33'"""
        import h_agg as HA
        out = []
        for h in HA.result_history(self.store).get(str(tid), []):
            row = dict(h)
            plan_p = f"recovery/{tid}/{h.get('job')}/result_plan.json"
            try:
                plan = self.store.read_json(plan_p)
            except Exception:
                plan = None
            if isinstance(plan, dict):
                rf = plan.get("result_file")
                row["result_file"] = f"recovery/{tid}/{h.get('job')}/{rf}" if rf else ""
                row["before_file"] = f"recovery/{tid}/{h.get('job')}/before_upload.zip"
                row["model"] = row.get("model") or plan.get("model")
            out.append(row)
        return out

    def video(self, source: str, name: str) -> Optional[str]:
        """원본 영상: 공유 videos/(읽기) → 없으면 공유 backups/의 백업에서 Colab 로컬로 꺼냄."""
        import cvat_task_tools as ctt
        v = ctt.find_video(str(self.base / "videos"), source, name)
        if v:
            return str(v)
        lv = self.local / "videos"
        lv.mkdir(parents=True, exist_ok=True)
        got = ctt.video_from_backups(str(self.base / "backups"), name, str(lv))
        return str(got[0]) if got and got[0] else None

    GUARD_GEN = GUARD_GEN

    def close(self):
        """이 세션이 지금 규칙의 주인이면 규칙을 비움 (가드 없음). 주인이 아니면(이미 새 세션으로 바뀜) 아무것도 바꾸지 않음."""
        st = _state()
        if _policy()[2] is self:
            _set_policy(None, None, None)
        if st.get("active") is self:
            st["active"] = None


def redirect_records(S: "Session", ctt=None, wb=None):
    """옛 scripts가 공유 기록에 쓰던 것을 내 분석 폴더로 (2c-2). 옛 기록은 읽기 전용 (11/17 결정).
    - ctt의 세션별 기록(작업 대장·작업 기록·업로드 기록 등, shard_path)은 OUT/records/<원래 경로>로
    - web_bridge의 통계·검토 수정량 캐시는 OUT/cache/로 (처음에 공유 캐시를 복사해 시작)"""
    rec = S.out / "records"
    if ctt is not None and hasattr(ctt, "shard_path"):
        ctt.set_shard(re.sub(r"[^\w.-]+", "_", S.session))
        orig = getattr(ctt, "_egg_orig_shard_path", None) or ctt.shard_path
        ctt._egg_orig_shard_path = orig

        def shard_path(path):
            p = Path(orig(path))
            try:
                rel = p.resolve().relative_to(S.base)
            except ValueError:
                return p
            if rel.parts[:1] == ("analysis",):
                return p
            return rec / rel
        ctt.shard_path = shard_path
        orig_files = getattr(ctt, "_egg_orig_shard_files", None) or ctt.shard_files
        ctt._egg_orig_shard_files = orig_files

        def shard_files(path):
            """읽기: 옛 공용 기록(읽기만) + 내 분석 폴더의 이번 세션 기록"""
            out = list(orig_files(path))
            mine = shard_path(path)
            if Path(mine).exists() and Path(mine) not in out:
                out.append(Path(mine))
            return out
        ctt.shard_files = shard_files
    if wb is not None:
        cache = S.out / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        for attr, rel in (("STATS_CACHE", "web/label_stats.json"), ("CORR_CACHE", "web/corrections.json")):
            if hasattr(wb, attr):
                src = S.base / rel
                dst = cache / Path(rel).name
                if src.exists() and not dst.exists():
                    with open(src, "rb") as a, open(dst, "wb") as b:
                        b.write(a.read())
                setattr(wb, attr, str(dst))              # 절대 경로 → base / 절대 = 절대 (분석 폴더의 사본에 씀)


def _start_lock():
    import sys
    st = _state()
    lk = st.get("lock")
    if lk is None:
        lk = st.setdefault("lock", threading.RLock())
    return lk


def start(base: str, person: str, cvat_hosts: Sequence[str], local: str = "/content/egg_local",
          guard: bool = True) -> Session:
    """0번 셀이 부름. 다시 실행하면 새 세션을 다 준비한 뒤에야 규칙을 바꿈.
    - 설정이 틀려 시작이 실패하면 앞 세션의 가드는 그대로 남음 (b28 V2)
    - 0번 셀의 importlib.reload(cb)를 거쳐도 앞 세션을 찾음 — 활성 세션은 sys에 둠 (b28 V1)
    - 규칙(쓰기 가드·CVAT 가드·주인)은 한 묶음으로 한 번에 바꿈 — 감싸기는 묶음을 한 번만 읽음 (b29 W1·b31 X1)
    - 다른 세대 가드의 세션이 남은 커널이면 아무것도 바꾸지 않고 런타임 재시작을 안내 (b31 X2)
    - 시작끼리는 차례로 (잠금)"""
    with _start_lock():
        return _start(base, person, cvat_hosts, local, guard)


def _start(base, person, cvat_hosts, local, guard) -> Session:
    st = _state()
    prev = st.get("active")
    if prev is not None and getattr(prev, "GUARD_GEN", None) != GUARD_GEN:
        raise AnalysisRefused("이 커널에는 다른 판의 분석 세션이 남아 있습니다 — 런타임을 다시 시작한 뒤 0번 셀을 실행하세요 "
                              "(판이 다른 가드는 안전하게 바꿀 수 없음)")
    m = access.mode()
    if m != "analysis":
        raise access.AccessError(f"사람용 셀은 분석 모드에서만 ({access.MODE_VAR}={os.environ.get(access.MODE_VAR)!r}) — "
                                 "실행기는 30번 셀이 따로 띄웁니다")
    if not PERSON_RE.match(person or ""):
        raise AnalysisRefused("OPERATOR(사람 ID, 예 M1)를 0번 셀에 적으세요 — 분석 폴더 이름이 됩니다")
    base_p = Path(base).resolve()
    if not base_p.is_dir():
        raise AnalysisRefused(f"BASE 폴더가 없습니다: {base}")
    # 분석 트리가 링크로 다른 곳(예: CVAT_UpLoader)을 가리키면 거절 (b31 X3)
    ana, pdir = base_p / "analysis", base_p / "analysis" / person
    for d in (ana, pdir):
        if (d.exists() or d.is_symlink()) and (d.is_symlink() or d.resolve() != d):
            raise AnalysisRefused(f"분석 폴더 {d.relative_to(base_p).as_posix()}가 링크라 쓸 곳을 믿을 수 없습니다 — 링크를 지우고 다시")
    fp = access.machine_fingerprint()
    sess = access.new_session_id("ana", fp)
    stamp = datetime.datetime.now(KST).strftime("%y%m%d_%H%M")        # Colab 서버 시계(UTC)가 아니라 한국 시각
    out = pdir / f"{stamp}_{re.sub(r'[^A-Za-z0-9]', '', sess)[-8:]}"
    local_p = Path(local)
    local_p.mkdir(parents=True, exist_ok=True)
    paths = access.Paths(base=base_p, output_root=out, session_tmp=local_p,
                         narrow=("requests/", A.P_SIGNALS, f"submissions/{person}/"))   # workers/는 넣지 않음 (심판이 실행기로 읽음)
    saver = access.Saver(paths, person=person)
    st["boot"] = (threading.get_ident(), out, ana)   # 내 새 분석 폴더와 그 부모만 — 앞 세션의 가드는 아직 켜져 있음
    try:
        out.mkdir(parents=True, exist_ok=True)
    finally:
        st["boot"] = None
    if out.resolve() != out:                           # 만든 뒤에도 실제 위치 확인 (b31 X3)
        raise AnalysisRefused(f"새 분석 폴더가 다른 곳으로 이어집니다: {out.resolve()}")
    from arb_io import LocalStore
    S = Session(base=base_p, person=person, session=sess, out=out, saver=saver, writes=WriteGuard(saver),
                cvat=TransportGuard(cvat_hosts), local=local_p, store=LocalStore(base_p, default_owner=""))
    # 여기까지 실패하면 앞 세션 그대로. 감싸기를 깔고(아직 앞 규칙을 따름) 규칙 묶음을 한 번에 바꿈.
    # 앞 세션의 가드 객체는 바뀐 뒤에도 같은 규칙으로 검사하므로, 바꾸기 직전에 읽은 감싸기도 검사 없이 지나가지 않음
    _install_write_wrappers()
    for cls in _transport_classes():
        _patch_transport(cls)
    _set_policy(S.writes if guard else None, S.cvat if guard else None, S)
    st["active"] = S
    S._note("start")
    return S


def active() -> Optional[Session]:
    return _state().get("active")
