"""v4.33 2a — CPU 마스터 본체 (설계 8판 '심판: CPU 마스터', '실행 코드의 신뢰 경계').

마스터 노트북(뿌리)이 배포 목록을 고정 해시로 검증하고, 목록의 파일을 하나씩 검증한 **바로 그 바이트**로
이 모듈을 불러 `main(boot)`을 부릅니다. 이 모듈이 하는 일:

1. 최소 버전 확인 (`config/min_version.json`, 관리자 폴더) — 낮거나 못 읽으면 시작하지 않음
2. 심판 자격 신청 → 판정 루프(`MasterLoop`) + 생존 신호 스레드(`Beat`)
3. 바깥 조회(`Probes`): Kaggle 커널 상태, CVAT 가져오기 작업 — 판정 루프를 막지 않게 따로 도는 스레드가 채움
4. CPU 작업 프로세스(`worker_cpu`)를 검증한 파일로 띄우고 지켜봄
5. GPU 작업자가 필요하면(`wake.gpu_needed`) 배포 목록에 든 GPU 노트북·실행 설정만 Kaggle로 올림
6. 끝낼 때: 밤에 할 일이 없음 / 자격을 못 받음 / 실행 한도 → 작업 프로세스를 멈추고 '끝남'을 남김

비밀 값은 다루지 않습니다. rclone·kaggle 설정 파일은 노트북이 세션 임시 폴더(0600)에 만들어 환경 변수로 넘깁니다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import access
import arbiter as A
from arb_io import Beat, RcloneStore, StoreError
from arb_master import MasterLoop, Probes, RoundSummary

VERSION = "4.33.0i"

GPU_META = "kernel-metadata-gpu-worker.json"     # 배포 목록 안의 GPU 작업자 실행 설정
GPU_GAP = 600                                     # GPU 작업자 올린 뒤 10분은 다시 올리지 않음 (Kaggle이 띄우는 데 몇 분)
GRANT_WAIT = 600                                  # 자격을 10분 안에 못 받으면 끝냄 (다른 마스터가 심판)
NIGHT_GRACE = 900                                 # 밤: 다음 깨울 시각이 15분 안이면 끝내지 않음
MAX_RUN_H = 11.2                                  # Kaggle 세션 12시간 안에서 스스로 끝냄
CLEAN_MAX_AGE = 90                                # 밤 끝내기 판단에 쓰는 '빠짐없이 읽은 회차'의 최대 나이
WORKER_RESTARTS = 5                               # 작업 프로세스가 한 시간에 이만큼 넘게 죽으면 더 띄우지 않고 알림


class BootError(RuntimeError):
    pass


# ---------------------------------------------------------------- 버전·설정
def version_tuple(v) -> Tuple[int, ...]:
    import re
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def check_min_version(admin_json: Callable[[str], Any], version: str = VERSION) -> str:
    """관리자 폴더의 최소 버전. 못 읽거나 이 판이 낮으면 BootError (공유 쓰기를 하지 않음)."""
    try:
        mv = admin_json("config/min_version.json")
    except Exception as e:
        raise BootError(f"최소 버전 파일을 읽지 못했습니다 — 시작하지 않습니다 ({type(e).__name__})")
    want = (mv or {}).get("master") or (mv or {}).get("all")
    if not want:
        raise BootError("최소 버전 파일에 master 값이 없습니다")
    if version_tuple(version) < version_tuple(want):
        raise BootError(f"이 판({version})이 최소 버전({want})보다 낮습니다 — 시작하지 않습니다")
    return str(want)


def load_config(admin_json: Callable[[str], Any]) -> dict:
    """MasterLoop.config: 사람 목록·계정 지도. 못 읽으면 예외 (루프가 '모름'으로 다룸)."""
    people = admin_json("config/people.json")
    accounts = admin_json("config/accounts.json")
    if isinstance(people, dict):
        people = people.get("people")
    return {"people": people, "accounts": accounts}


# ---------------------------------------------------------------- 바깥 조회 (판정 루프와 따로 돎)
KERNEL_RUNNING = {"running", "queued", "cancelrequested"}      # 끝나는 중(cancelRequested)도 아직 끝난 것이 아님
KERNEL_ENDED = {"complete", "error", "cancelacknowledged"}
PROBE_MAX_AGE = 180                                              # 이보다 오래된 조회 값은 '모름' (U4)


def parse_kernel_status(out: str, rc: int = 0, err: str = "") -> str:
    """`<주소> has status "<값>"`의 값만 보고 정확히 맞춰 봄 (U3). 주소·설명의 낱말은 보지 않음.
    running | ended | unknown. 실패 응답은 모두 unknown — 오류 문구로 '노트북 없음'을 판단하지 않음 (V5).
    GPU 작업자 노트북은 배포 때 관리자가 처음 한 번 올림 (배포 계획 6절 10번)."""
    import re
    if rc != 0:
        return "unknown"
    m = re.findall(r'has status "([^"]+)"', out or "")
    if len(m) != 1:
        return "unknown"
    v = m[0].strip().lower()
    if v.startswith("kernelworkerstatus."):
        v = v[len("kernelworkerstatus."):]
    if v in KERNEL_RUNNING:
        return "running"
    if v in KERNEL_ENDED:
        return "ended"
    return "unknown"


class ProbeCache:
    """60초마다 채움. 판정 루프는 채워 둔 값만 읽음 (바깥 호출이 느려도 회차가 밀리지 않음).
    - 커널 상태: 생존 신호에 `kernel`(Kaggle 주소)을 적은 실행기만. {세션: running|ended|unknown}
    - 가져오기 작업: 확정 승인·'확인 필요' 잠금의 TASK만. {TASK: True(진행 중)|False(없음)|None(모름)}
    """

    def __init__(self, store, kaggle: Callable[[List[str]], Tuple[int, str, str]],
                 cvat_imports: Callable[[List[str]], Dict[str, Optional[bool]]], clock=time.time, every: float = 60):
        self.store, self.kaggle, self.cvat_imports, self.clock, self.every = store, kaggle, cvat_imports, clock, every
        self.kernels: Dict[str, str] = {}
        self.imports: Dict[str, Optional[bool]] = {}
        self.kernels_at = self.imports_at = 0.0          # 마지막으로 **성공한** 조회 시각 (U4)
        self.errors = 0
        self._lock = threading.Lock()

    def _kernels(self) -> Dict[str, str]:
        out = {}
        for e in self.store.list("workers/", False):
            try:
                w = self.store.read_json(e.path)
            except StoreError:
                continue
            if not isinstance(w, dict) or not isinstance(w.get("kernel"), str) or not isinstance(w.get("session"), str):
                continue
            rc, o, err = self.kaggle(["kernels", "status", w["kernel"]])
            st = parse_kernel_status(o, rc, err)
            out[w["session"]] = st if st in ("running", "ended") else "unknown"
        return out

    def _tasks(self) -> List[str]:
        ts = []
        for e in self.store.list(A.P_LOCK_TASK, False):
            try:
                lk = self.store.read_json(e.path)
            except StoreError:
                continue
            if isinstance(lk, dict) and lk.get("state") in ("confirm_approved", "quarantine"):
                ts.append(A._name(e.path))
        return sorted(ts)

    def refresh(self):
        t0 = self.clock()                               # 묶음 **시작** 시각을 붙임 — 오래 걸린 조회의 앞쪽 값이 새것처럼 보이지 않게 (V4)
        try:
            k = self._kernels()
        except Exception:
            k, self.errors = None, self.errors + 1
        try:
            ts = self._tasks()
            im = self.cvat_imports(ts) if ts else {}
        except Exception:
            im, self.errors = None, self.errors + 1
        with self._lock:
            if k is not None:
                self.kernels, self.kernels_at = k, t0
            else:                                       # 실패한 조회는 옛 값을 확정값으로 남기지 않음 (U4)
                self.kernels = {s_: "unknown" for s_ in self.kernels}
            if im is not None:
                self.imports, self.imports_at = im, t0
            else:
                self.imports = {t: None for t in self.imports}

    def probes(self) -> Probes:
        def ks():
            with self._lock:
                if self.clock() - self.kernels_at > PROBE_MAX_AGE:
                    return {s_: "unknown" for s_ in self.kernels}
                return dict(self.kernels)

        def ims():
            with self._lock:
                if self.clock() - self.imports_at > PROBE_MAX_AGE:
                    return {t: None for t in self.imports}
                return dict(self.imports)
        return Probes(kernel_status=ks, import_pending=ims)

    def start(self, stop: threading.Event):
        def loop():
            while not stop.is_set():
                self.refresh()
                stop.wait(self.every)
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t


def cvat_import_query(host: str, token: Optional[str], get=None) -> Callable[[List[str]], Dict[str, Optional[bool]]]:
    """CVAT 서버의 진행 중 가져오기 작업 (읽기 호출만). 응답 형식은 실제 서버로 확인 필요 (배포 계획 T10).
    알 수 없으면 None — 심판은 '모름'을 '없음'으로 보지 않음."""
    def _get(url):
        import urllib.request
        req = urllib.request.Request(url, headers={"Authorization": f"Token {token}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    get = get or _get

    def one(t: str) -> Optional[bool]:
        """모든 페이지의 모든 행이 알려진 상태일 때만 True/False. 하나라도 모르면 None (U5)."""
        url, pages, seen_active = f"{host.rstrip('/')}/api/requests?action=import&target=task&task_id={t}&page_size=50", 0, False
        while url:
            pages += 1
            if pages > CVAT_MAX_PAGES:
                return None                              # 다 보지 못함 → 모름
            d = get(url)
            rows = d.get("results") if isinstance(d, dict) else None
            if not isinstance(rows, list):
                return None
            for x in rows:
                st = str(x.get("status", "")).lower() if isinstance(x, dict) and isinstance(x.get("status"), str) else None
                if st not in CVAT_ACTIVE | CVAT_DONE:
                    return None
                seen_active |= st in CVAT_ACTIVE
            nxt = d.get("next")
            if nxt is not None and not isinstance(nxt, str):
                return None
            url = nxt
        return seen_active

    def q(tasks: List[str]) -> Dict[str, Optional[bool]]:
        out: Dict[str, Optional[bool]] = {}
        for t in tasks:
            if not token:
                out[t] = None
                continue
            try:
                out[t] = one(t)
            except Exception:
                out[t] = None
        return out
    return q


CVAT_ACTIVE = {"queued", "started"}
CVAT_DONE = {"finished", "failed"}
CVAT_MAX_PAGES = 5


# ---------------------------------------------------------------- GPU 작업자 올리기
class GpuLauncher:
    """심판이 'GPU 필요'(맞는 GPU 실행기가 살아 있지 않은 실행 가능한 일)를 적었을 때만.
    배포 목록에 든 실행 설정·노트북의 검증된 바이트만 씀 — 경로·주소를 신호·요청에서 받지 않음."""

    def __init__(self, files: Dict[str, bytes], kaggle: Callable[[List[str]], Tuple[int, str, str]],
                 test: bool, clock=time.time, gap: float = GPU_GAP):
        self.files, self.kaggle, self.test, self.clock, self.gap = files, kaggle, test, clock, gap
        self.last = 0.0
        self.log: List[str] = []
        self.unknown_since: Optional[float] = None       # GPU 상태를 계속 모르는 동안 — 생존 신호로 CTRL앱에 보임

    def meta(self) -> dict:
        b = self.files.get(GPU_META)
        if b is None:
            raise BootError("배포 목록에 GPU 작업자 실행 설정이 없습니다")
        m = json.loads(b.decode("utf-8"))
        slug = str(m.get("id", ""))
        if "/" not in slug or not m.get("code_file"):
            raise BootError("GPU 작업자 실행 설정의 id·code_file이 비었습니다")
        if self.test != slug.endswith("-test"):        # 시험은 시험 노트북만, 운영은 운영 노트북만 (예행 연습 혼입 방지)
            raise BootError(f"GPU 작업자 주소({slug})가 {'시험' if self.test else '운영'} 환경과 맞지 않습니다")
        if m["code_file"] not in self.files:
            raise BootError("GPU 작업자 노트북이 배포 목록에 없습니다")
        return m

    def maybe_start(self, wake: Optional[dict]) -> str:
        if not wake:
            return "no_summary"
        if wake.get("holds"):
            return "hold"                              # 정지 보류 중에는 켜지 않음
        if int(wake.get("gpu_needed") or 0) <= 0:
            return "not_needed"
        if self.clock() - self.last < self.gap:
            return "recent"
        try:
            m = self.meta()
        except BootError as e:
            self.log.append(str(e))
            return "bad_deploy"
        rc, out, err = self.kaggle(["kernels", "status", m["id"]])
        st = parse_kernel_status(out, rc, err)
        if st == "running":
            self.last, self.unknown_since = self.clock(), None
            return "already_running"
        if st != "ended":                              # 상태를 모르면 올리지 않고 다음 회차에 다시 조회 (U7·V5)
            if self.unknown_since is None:
                self.unknown_since = self.clock()
            return "status_unknown"
        self.unknown_since = None
        with tempfile.TemporaryDirectory(prefix="egg_gpu_") as d:
            Path(d, m["code_file"]).write_bytes(self.files[m["code_file"]])
            Path(d, "kernel-metadata.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
            rc, out, err = self.kaggle(["kernels", "push", "-p", d])
        self.last = self.clock()
        if rc != 0:
            self.log.append(f"push 실패 (코드 {rc})")    # 응답 원문은 남기지 않음
            return "push_failed"
        return "pushed"


# ---------------------------------------------------------------- CPU 작업 프로세스
class WorkerSupervisor:
    """검증한 파일로 CPU 작업 프로세스를 띄우고 지켜봄. 끝낼 때는 멈춤 파일 → 지금 단계를 마치고 끝남."""

    def __init__(self, code_dir: Path, base_remote: str, accounts_file: Path, caps: str, fp: str,
                 spawn: Callable[[List[str], Dict[str, str]], Any] = None, clock=time.time, env: str = "kgw"):
        self.code_dir, self.base, self.accounts_file, self.caps, self.fp = code_dir, base_remote, accounts_file, caps, fp
        self.spawn = spawn or (lambda cmd, envv: subprocess.Popen(cmd, env=envv))
        self.clock, self.env = clock, env
        self.proc, self.session = None, None
        self.starts: List[float] = []
        self.stop_file = Path(tempfile.mkdtemp(prefix="egg_stop_")) / "STOP"
        self.gave_up = False

    def _cmd(self) -> List[str]:
        boot = ("import sys; sys.path.insert(0, sys.argv[1]); import worker_cpu; "
                "sys.exit(worker_cpu.main(sys.argv[2:]))")
        return [sys.executable, "-I", "-c", boot, str(self.code_dir), "--base", self.base,
                "--accounts", str(self.accounts_file), "--caps", self.caps, "--session", self.session,
                "--stop-file", str(self.stop_file)]

    def tick(self) -> str:
        if self.proc is not None and self.proc.poll() is None:
            return "running"
        if self.gave_up:
            return "gave_up"
        now = self.clock()
        self.starts = [t for t in self.starts if now - t < 3600]
        if len(self.starts) >= WORKER_RESTARTS:
            self.gave_up = True
            return "gave_up"
        self.session = access.new_session_id(self.env, self.fp, now)     # 다시 띄울 때마다 새 세션 (옛 일은 심판이 정리)
        envv = dict(os.environ, **{access.MODE_VAR: "exec"})
        self.proc = self.spawn(self._cmd(), envv)
        self.starts.append(now)
        return "started" if len(self.starts) == 1 else "restarted"

    def stop(self, wait: float = 120, sleep=time.sleep):
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.write_text("stop")
        if self.proc is None:
            return
        t0 = self.clock()
        while self.proc.poll() is None and self.clock() - t0 < wait:
            sleep(1)
        if self.proc.poll() is None:
            self.proc.terminate()                     # 한도 안에 못 끝냄 → 끊김. 진행 중이던 일은 심판이 '확인 필요'로


# ---------------------------------------------------------------- 끝낼지
def exit_reason(now: float, started: float, loop: MasterLoop, tz_h: int = 9) -> Optional[str]:
    if now - started >= MAX_RUN_H * 3600:
        return "max_hours"
    if loop.last_acting_at == 0 and now - started >= GRANT_WAIT:
        return "not_granted"
    if loop.last_acting_at and now - loop.last_acting_at >= GRANT_WAIT:
        return "grant_lost"                           # 다른 마스터가 자격을 받음 (Keeper가 바꿈)
    arb = loop.last_arbiter or {}
    wk = arb.get("wake") or {}
    if A.is_day(now, tz_h) or not loop.last_acting_at or now - started < 300:
        return None
    if not loop.last_clean_at or loop.last_clean_at < loop.last_run_at or now - loop.last_clean_at > CLEAN_MAX_AGE:
        return None                                   # 바로 직전 회차가 빠짐없이 읽고 쓰지 못했으면 '할 일 없음'으로 보지 않음 (U6)
    nxt = wk.get("next_wake_at")
    if int(wk.get("runnable") or 0) == 0 and int(wk.get("busy") or 0) == 0 and int(wk.get("gpu_needed") or 0) == 0 \
            and (nxt is None or float(nxt) > now + NIGHT_GRACE):
        return "night_idle"                           # Keeper가 next_wake_at·신호로 다시 깨움
    return None


# ---------------------------------------------------------------- 본체
@dataclass
class Boot:
    """노트북(뿌리)이 넘겨주는 것. files: 배포 목록으로 검증한 {상대 경로: 바이트} (scripts/는 'scripts/x.py')."""
    files: Dict[str, bytes]
    remote: str                      # 공유 폴더 rclone 연결 (예: 'gdrive:' / 'gdrive_test:')
    admin_remote: str                # 관리자 폴더 연결 (예: 'gadmin:' / 'gadmin_test:')
    test: bool = False
    env: str = "kgl"
    cvat_host: str = "https://app.cvat.ai"
    interval: float = 25
    secret_dir: Optional[Path] = None


def check_remotes(boot: Boot):
    names = (boot.remote, boot.admin_remote)
    if boot.test and not all("test" in n for n in names):
        raise BootError("시험 실행인데 rclone 연결 이름에 test가 없습니다 — 운영 폴더에 쓰지 않으려고 멈춥니다")
    if not boot.test and any("test" in n for n in names):
        raise BootError("운영 실행인데 시험 연결을 가리킵니다")


def write_code_dir(files: Dict[str, bytes]) -> Path:
    """작업 프로세스용: 검증한 scripts 바이트를 본인 전용 폴더(0700)에 씀."""
    d = Path(tempfile.mkdtemp(prefix="egg_code_"))
    for rel, b in files.items():
        if rel.startswith("scripts/") and rel.endswith(".py"):
            p = d / rel[len("scripts/"):]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
    return d


def main(boot: Boot, store=None, admin=None, kaggle=None, spawn=None, cvat_imports=None,
         clock=time.time, sleep=time.sleep, stop: Callable[[], bool] = lambda: False,
         log: Callable[[str], None] = print, max_rounds: Optional[int] = None) -> str:
    """끝난 이유를 돌려줌. 시험에서는 store·admin·kaggle·spawn·clock을 바꿔 넣음."""
    check_remotes(boot)
    store = store or RcloneStore(boot.remote)
    admin = admin or RcloneStore(boot.admin_remote)
    kaggle = kaggle or default_kaggle
    check_min_version(admin.read_json)
    fp = access.machine_fingerprint()
    me = access.new_session_id(boot.env, fp, clock())
    loop = MasterLoop(store, me, fp, lambda: load_config(admin.read_json), clock=clock)
    accounts_file = Path(tempfile.mkdtemp(prefix="egg_cfg_")) / "accounts.json"
    accounts_file.write_text(json.dumps(load_config(admin.read_json)["accounts"]), encoding="utf-8")
    os.chmod(accounts_file, 0o600)

    halt = threading.Event()
    pc = ProbeCache(store, kaggle, cvat_imports or cvat_import_query(boot.cvat_host, os.environ.get("CVAT_TOKEN")),
                    clock=clock)
    loop.probes = pc.probes()
    pc.start(halt)
    beat = Beat(loop.heartbeat, 60, final=lambda: loop.heartbeat(stopping=True))
    beat.start()
    loop.ask_grant()
    gpu = GpuLauncher(boot.files, kaggle, boot.test, clock=clock)
    sup = WorkerSupervisor(write_code_dir(boot.files), boot.remote, accounts_file, "cpu,agg", fp, spawn=spawn,
                           clock=clock)
    started = clock()
    log(f"[마스터 {VERSION}] 세션 {me} · {'시험' if boot.test else '운영'} · 자격 신청함")
    reason, n = None, 0
    try:
        while not stop():
            try:
                r = loop.run_once()
            except StoreError:
                r = RoundSummary(False, 0, 0, None, ["store"], ["store_error"])
            except Exception as e:
                r = RoundSummary(False, 0, 0, None, ["error"], ["round_error:" + type(e).__name__])
            loop.status_extra = {"gpu_status_unknown_since": gpu.unknown_since, "worker": sup.session,
                                 "worker_gave_up": sup.gave_up, "config": loop.config_status()}
            if r.acting:
                st = sup.tick()
                if st in ("started", "restarted", "gave_up"):
                    log(f"작업 프로세스: {st} ({sup.session})")
                g = gpu.maybe_start((loop.last_arbiter or {}).get("wake"))
                if g in ("pushed", "push_failed", "bad_deploy"):
                    log(f"GPU 작업자: {g}")
            reason = exit_reason(clock(), started, loop)
            n += 1
            if reason or (max_rounds is not None and n >= max_rounds):
                break
            sleep(boot.interval)
        reason = reason or ("stopped" if stop() else "max_rounds")
    finally:
        sup.stop(sleep=sleep)
        halt.set()
        beat.stop()
        beat.join(timeout=90)
        log(f"[마스터] 끝냄: {reason}")
    return reason


def default_kaggle(args: List[str]) -> Tuple[int, str, str]:
    """kaggle CLI (KAGGLE_CONFIG_DIR은 노트북이 세션 임시 폴더로 정함). 출력 원문은 기록하지 않음."""
    try:
        r = subprocess.run(["kaggle", *args], capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "no kaggle cli"
