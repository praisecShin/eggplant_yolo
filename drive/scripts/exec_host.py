"""v4.33 2b-6 실행 호스트 — CPU 작업 프로세스·Kaggle GPU 작업자·Colab 30번 셀이 실행기를 띄우는 공용 코드.

- `build_env(cfg, store, …)`: 처리기 환경(`handlers.Env`)을 능력에 맞게 꾸밈
  · CVAT는 언제나 `ScopedCvat`로 감쌈 → **시험 범위 강제**: 시험 실행(`test=True`)은 `config/exec.json`의
    `test_project_id` 프로젝트의 `REH_` TASK에만 쓰고, 운영 실행은 `REH_` TASK에 쓰지 않음. 시험인데 프로젝트 번호가
    없으면 시작하지 않음
  · gpu: track·shape 엔진(`RealEngine` + 채택된 모델·영상 받기), 학습 엔진(`RealTrainer`)
  · cpu: 데이터셋 만들기(`HostBuilder` — 쓸 export의 영상을 먼저 받음)
  · colab_oauth: Drive 버전 기록(`RealRevisions`)
- `run_loop(…)`: 실행기 한 걸음씩 + 생존 신호(일과 따로). 멈춤 파일·쉬는 시간 한도로 끝냄
- `main_gpu(…)`: Kaggle GPU 작업자 노트북(뿌리 노트북 ROLE='gpu')이 부름. 맡은 일이 없는 채로 한도(기본 15분)를
  넘기면 끝냄 (GPU 시간 아끼기). 생존 신호에 Kaggle 주소(`kernel`)를 실어 마스터가 커널 종료를 확인할 수 있게
- `main_colab(…)`: Colab 30번 셀. Colab 로그인 토큰으로 세션 전용 rclone 설정(0600)을 만들어 같은 저장소 규칙을 씀
  (Colab 보안 비밀에는 RCLONE_CONF가 없음 — 11/14 결정). 토큰은 만료 전에 다시 씀

비밀 값(CVAT 토큰 등)은 환경 변수에서만 읽고 파일·기록에 쓰지 않습니다 (Colab rclone 설정만 세션 전용 0600 파일).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import access
import arbiter as A
import executor as X
import handlers as H
from arb_io import Beat, LocalStore, RcloneStore, StoreError

HOST_VERSION = "4.33.0z10"
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv")
DEFAULT_EXEC = {"cvat_host": "https://app.cvat.ai", "cvat_org": None, "cvat_project": "", "test_project_id": None,
                "base_model": "yolo11s.pt", "imgsz": 1920, "track": {}, "idle_exit_min": 15, "uld_remote": None,
                "val_rule": "plant=3|plant=7"}


class HostError(RuntimeError):
    pass


# ---------------------------------------------------------------- 설정
def load_exec_config(admin) -> dict:
    """관리자 폴더 `config/exec.json` (비밀 아님: CVAT 주소·조직·시험 프로젝트·기본 모델). 없으면 기본값.
    있는데 못 읽으면 HostError (모르는 설정으로 쓰지 않음). admin = 관리자 폴더 저장소."""
    try:
        o = admin.read_json("config/exec.json") if admin.exists("config/exec.json") else {}
    except StoreError as e:
        raise HostError(f"실행 설정을 못 읽음: {e}")
    if not isinstance(o, dict):
        raise HostError("실행 설정(config/exec.json)이 객체가 아님")
    return dict(DEFAULT_EXEC, **o)


@dataclass
class HostConfig:
    test: bool
    caps: List[str]
    exec_cfg: dict = field(default_factory=lambda: dict(DEFAULT_EXEC))
    scripts_dir: Optional[str] = None
    work: Optional[str] = None
    device: str = "0"
    kernel: Optional[str] = None

    def project_scope(self) -> Optional[int]:
        pid = self.exec_cfg.get("test_project_id")
        if self.test and not isinstance(pid, int):
            raise HostError("시험 실행인데 config/exec.json에 test_project_id(eggplant_AA 프로젝트 번호)가 없음 — 시작하지 않음")
        return pid if self.test else None


# ---------------------------------------------------------------- 영상·모델 받기
class Media:
    """처리기가 쓸 원본 영상·채택 모델을 공유 폴더에서 받아 둠 (세션 작업 폴더 안)."""

    def __init__(self, store, root: str, log: Callable[..., None] = print):
        self.store, self.root, self.log = store, Path(root), log
        self._idx: Dict[str, list] = {}
        self._lock = threading.RLock()
        (self.root / "videos").mkdir(parents=True, exist_ok=True)
        (self.root / "backups").mkdir(parents=True, exist_ok=True)

    def _list(self, prefix: str):
        with self._lock:
            if prefix not in self._idx:
                self._idx[prefix] = self.store.list_any(prefix, True)
            return self._idx[prefix]

    def _get(self, rel: str) -> Path:
        dst = self.root / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.store.get_file(rel, str(dst))
        return dst

    def video(self, source: str, name: str) -> Optional[str]:
        """videos/(같은 이름) → 없으면 backups/<기본 이름>/의 가장 최근 백업에서 꺼냄. 못 찾으면 None."""
        import cvat_task_tools as ctt
        base = ctt.base_name(name) if name else ""
        want = {x.lower() for x in (base, Path(source or "").stem, name or "") if x}
        for e in self._list("videos/"):
            if e.path.lower().endswith(VIDEO_EXT) and Path(e.path).stem.lower() in want:
                self._get(e.path)
        v = ctt.find_video(str(self.root / "videos"), source, name)
        if v:
            return str(v)
        if base:
            bks = sorted((e for e in self._list("backups/") if e.path.startswith(f"backups/{base}/") and e.path.endswith(".zip")),
                         key=lambda e: e.modified)
            if bks:
                self._get(bks[-1].path)
                got = ctt.video_from_backups(str(self.root / "backups"), name, str(self.root / "videos"))
                if got and got[0]:
                    return str(got[0])
        return None

    def model(self, name: str) -> str:
        """채택된 모델 버전의 best.pt (목록 해시와 대조). 채택이 없으면 HostError."""
        import h_run as HR
        try:
            cur = self.store.read_json(A.CURRENT_OF["model"].format(n=name))
        except StoreError:
            raise HostError(f"모델 '{name}'의 채택 표시를 못 읽음")
        ver = (cur or {}).get("version") if isinstance(cur, dict) else None
        if not ver:
            raise HostError(f"모델 '{name}'에 채택된 버전이 없음")
        dst = self.root / "models" / name / str(ver) / "best.pt"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            HR.get_verified(self.store, "model", name, str(ver), "best.pt", str(dst))
        return str(dst)


def zip_task_meta(zpath: str) -> dict:
    """export zip의 annotations.xml에서 TASK 이름·원본 파일 이름 (영상 받기용)."""
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(zpath) as z:
            n = next((x for x in z.namelist() if x.replace("\\", "/").split("/")[-1] == "annotations.xml"), None)
            if not n:
                return {}
            root = ET.fromstring(z.read(n))
    except Exception:
        return {}
    t = root.find("meta/task") if root.find("meta/task") is not None else root.find("meta/job")
    if t is None:
        return {}
    return {"name": t.findtext("name") or "", "source": t.findtext("source") or "", "id": t.findtext("id") or "",
            "images": root.find("image") is not None}


# ---------------------------------------------------------------- 엔진
class LazyTrainer:
    def __init__(self, imgsz, scripts_dir=None):
        self.imgsz = imgsz
        self.child = str(Path(scripts_dir) / "train_child.py") if scripts_dir else None   # 검증된 코드 폴더의 것

    def train(self, *a, **k):
        import h_run as HR
        return HR.RealTrainer(imgsz=self.imgsz, child=self.child).train(*a, **k)


class LazyEngine:
    """RealEngine을 처음 쓸 때 만듦 (h_task를 불러오면 등록부가 채워지므로)."""

    def __init__(self, make):
        self._make, self._e = make, None

    def __getattr__(self, name):
        if self._e is None:
            self._e = self._make()
        return getattr(self._e, name)


def make_engine(cfg: HostConfig, raw_cvat, media: Media):
    return LazyEngine(lambda: _make_engine(cfg, raw_cvat, media))


def _make_engine(cfg: HostConfig, raw_cvat, media: Media):
    import h_task as HT

    def model_for(params):
        name = params.get("model") or cfg.exec_cfg.get("default_model")
        if not name:
            raise HostError("요청에 모델이 없음")
        return media.model(str(name))

    def video_for(info, ref_zip):
        meta = zip_task_meta(ref_zip)
        v = media.video(meta.get("source", ""), info.get("name", ""))
        if not v:
            raise HostError(f"TASK {info.get('id')}의 원본 영상을 찾지 못함 (videos/·backups/)")
        return v, None                                 # ULD 사진 TASK(프레임맵)는 2c에서
    return HT.RealEngine(cfg.scripts_dir, raw_cvat, model_for, video_for, device=cfg.device,
                         settings=dict(cfg.exec_cfg.get("track") or {}, imgsz=cfg.exec_cfg.get("imgsz", 1920)))


class HostBuilder:
    """데이터셋 만들기 전에 쓸 export의 영상을 받아 두고 RealBuilder를 부름."""

    def __init__(self, cfg: HostConfig, media: Media):
        self.cfg, self.media = cfg, media              # 처리기 모듈은 쓸 때 불러옴 (불러오면 등록부가 채워짐)

    def build(self, zips, out_dir, settings, val_tasks, progress):
        import h_mgmt as HM
        m_ = self.media
        self.inner = HM.RealBuilder(self.cfg.scripts_dir, str(m_.root / "videos"), str(m_.root / "backups"),
                                    str(m_.root / "raw_images"), str(m_.root / "cvat_frames"),
                                    imgsz=int(self.cfg.exec_cfg.get("imgsz", 1920)))
        for z in zips:
            m = zip_task_meta(z)
            if m and not m.get("images"):
                if not self.media.video(m.get("source", ""), m.get("name", "")):
                    progress(f"영상 없음: {m.get('name')} (zip 안 이미지로만)")
        return self.inner.build(zips, out_dir, settings, val_tasks, progress)


class WebState:
    """옛 취합(`aggregate_and_sync_state`)의 웹 상태 계산을 읽기 사본 위에서 (2b-4에서 미룬 것).
    공유 폴더를 바꾸지 않고 {경로: 객체}만 돌려줌 — 게시는 취합 처리기가 epoch·회차를 붙여 함.
    기록 압축(샤드 합치기)·요청 완료 처리·사라진 TASK 이력은 하지 않음 (각자 맡은 곳, DESIGN '취합 일')."""
    PULLS = (("logs/shards", ()), ("relabel/tasks", ()), ("exports", ("*.csv", "*/*.zip", "_train_*/**")),
             ("status", ("cvat_tasks.json",)), ("web", ("label_stats.json", "corrections.json")))

    def __init__(self, store, work: str, raw_cvat, exec_cfg: dict, uld_store=None):
        self.store, self.base, self.cvat, self.cfg, self.uld = store, Path(work) / "web_base", raw_cvat, exec_cfg, uld_store
        self.base.mkdir(parents=True, exist_ok=True)

    def build(self, progress) -> Dict[str, Any]:
        import cvat_task_tools as ctt
        import web_bridge as wb
        for prefix, inc in self.PULLS:
            with H.ticking(progress, f"읽기 사본 받는 중 {prefix}"):
                self.store.pull(prefix, str(self.base / prefix), inc)
        client = self.cvat.client()
        scope = ctt.set_scope(client, self.cfg.get("cvat_org"), self.cfg.get("cvat_project") or "")
        with H.ticking(progress, "CVAT 목록 읽는 중"):
            tasks, cat = ctt.list_tasks_all(client, limit=5000)
        vids = [e.path[len("videos/"):] for e in self.store.list_any("videos/", True)]
        bks = [e.path[len("backups/"):] for e in self.store.list_any("backups/", True)]
        vn, bn = wb.media_names(self.base, remote_videos=vids, remote_backups=bks)
        uld = {"index": {}, "lineage": {}}
        if self.uld is not None and hasattr(wb, "uld_scan"):
            try:
                d = self.base / "_uld"
                self.uld.pull("registry/tasks", str(d), ("*.json",))
                uld = wb.uld_scan(d)
            except Exception:
                pass                                       # ULD 표시만 빠짐 (옛 취합과 같음)
        server = f"{ctt.whoami(client)}@{self.cfg['cvat_host'].split('//')[-1]}"
        files = self._models(progress)
        with H.ticking(progress, "웹 상태 계산 중"):
            snaps = wb.snapshots(self.base, refresh=True, log=None)
            stats = wb.compute_stats(self.base, tasks, client=client, cvat_max=25, log=None)
            corr = wb.compute_corrections(self.base, tasks, reviewed_rule="vf", max_new=80, log=None)
            st = wb.build_state(self.base, tasks, operator="aggregate", app_version=HOST_VERSION, reviewed_rule="vf",
                                val_rule=self.cfg.get("val_rule", "plant=3|plant=7"), server=server, video_stems=vn,
                                backup_bases=bn, stats=stats, snaps=snaps, scope=scope, catalog=cat, corrections=corr,
                                uld=uld["index"], replaced=uld["lineage"], files=files)
        out = {"web/state.json": st}
        for rel in ("web/label_stats.json", "web/corrections.json"):
            p = self.base / rel
            if p.exists():
                try:
                    o = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(o, dict):
                        out[rel] = o
                except Exception:
                    pass
        return out


    def _models(self, progress) -> Dict[str, tuple]:
        """채택된 모델 버전을 옛 화면 계산이 읽는 모양(runs/<이름>/results.csv·args.yaml·TRAINING_DONE)으로
        읽기 사본에 펼치고, 가중치는 받지 않고 크기·시각만 files로 (b24 T5). 채택되지 않은 옛 runs/는 보이지 않음."""
        import h_agg as HA
        runs = self.base / "runs"
        shutil.rmtree(runs, ignore_errors=True)
        files: Dict[str, tuple] = {}
        for m in HA.adopted_models(self.store):
            try:                                       # 한 모델의 받기·변환 실패가 다른 모델을 막지 않음 (b26 U3)
                d = runs / m["name"]
                d.mkdir(parents=True, exist_ok=True)
                for rel in ("results.csv", "args.yaml"):
                    if rel in m["files"]:
                        try:
                            self.store.get_file(m["files"][rel], str(d / rel))
                        except StoreError:
                            pass
                (d / "TRAINING_DONE").write_text(f"v4.33 채택 버전 {m['version']}", encoding="utf-8")
                at = m.get("adopted_at") if isinstance(m.get("adopted_at"), (int, float)) else m["meta"].get("made_at")
                files[f"runs/{m['name']}/weights/best.pt"] = (m["sizes"].get("best.pt", 0), float(at or 0))
                progress(f"모델 {m['name']}")
            except Exception:
                shutil.rmtree(runs / str(m.get("name")), ignore_errors=True)
                continue
        return files


class NoCvat(H.CvatOps):
    """CVAT_TOKEN이 없는 호스트 — CVAT를 부르면 실패 (거짓 완료 없음)."""

    def __getattribute__(self, name):
        if name.startswith("__") or name in ("WRITES",):
            return object.__getattribute__(self, name)
        def fail(*a, **k):
            raise HostError("이 실행기에는 CVAT 접속(CVAT_TOKEN)이 없음")
        return fail


def build_env(cfg: HostConfig, store, raw_cvat=None, revisions=None, log: Callable[..., None] = print) -> H.Env:
    """능력에 맞는 처리기 환경. raw_cvat를 주지 않으면 환경 변수 CVAT_TOKEN으로 RealCvat를 만듦."""
    pid = cfg.project_scope()
    if raw_cvat is None:
        tok = os.environ.get("CVAT_TOKEN")
        if tok:
            from cvat_ops import RealCvat
            raw_cvat = RealCvat(cfg.exec_cfg["cvat_host"], tok, cfg.exec_cfg.get("cvat_org"))
        else:
            raw_cvat = NoCvat()                         # 토큰이 없으면 CVAT 일만 실패 (저장소만 쓰는 일은 함)
    work = cfg.work or tempfile.mkdtemp(prefix="egg_host_")
    os.makedirs(work, mode=0o700, exist_ok=True)
    env = H.Env(store, H.ScopedCvat(raw_cvat, test=cfg.test, project_id=pid), tmp=os.path.join(work, "tmp"),
                test=cfg.test, log=log)
    env.server = cfg.exec_cfg["cvat_host"]
    media = Media(store, os.path.join(work, "media"), log=log)
    env.media = media
    env.base_model = cfg.exec_cfg.get("base_model", "yolo11s.pt")
    if "gpu" in cfg.caps:
        env.engine = make_engine(cfg, raw_cvat, media)
        env.trainer = LazyTrainer(int(cfg.exec_cfg.get("imgsz", 1920)), cfg.scripts_dir)
    if "cpu" in cfg.caps:
        env.builder = HostBuilder(cfg, media)
    if "agg" in cfg.caps and not isinstance(raw_cvat, NoCvat):
        uld = RcloneStore(cfg.exec_cfg["uld_remote"]) if cfg.exec_cfg.get("uld_remote") else None
        env.web_state = WebState(store, work, raw_cvat, cfg.exec_cfg, uld_store=uld)
    if "colab_oauth" in cfg.caps:
        env.revisions = revisions
    return env


# ---------------------------------------------------------------- 실행 고리
def my_active_work(store, me: str) -> bool:
    """이 세션에 맡겨진 진행 중 배정이 있는가 (읽지 못하면 있다고 봄 — 일하던 중에 끝내지 않게)."""
    try:
        for e in store.list(A.P_ASSIGN, False):
            a = store.read_json(e.path)
            if isinstance(a, dict) and a.get("session") == me and a.get("state") == "active":
                return True
    except StoreError:
        return True
    return False


def run_loop(store, accounts: Dict[str, str], caps: List[str], env: H.Env, session: str, fp: str,
             kernel: Optional[str] = None, interval: float = 20, hb_every: float = 60,
             stop: Callable[[], bool] = lambda: False, idle_exit: Optional[float] = None,
             max_steps: Optional[int] = None, sleep=time.sleep, clock=time.time, join_timeout: float = 90) -> X.Executor:
    if access.mode() != "exec":
        raise access.AccessError("실행기는 EGG_ACCESS=exec에서만 돕니다")
    ex = X.Executor(store, session, fp, caps, accounts, H.Dispatch(env=env), clock=clock)
    ex.kernel = kernel
    beat = Beat(ex.heartbeat, hb_every, final=lambda: ex.heartbeat(stopping=True))
    beat.start()
    n, last_work = 0, clock()
    try:
        while not stop() and (max_steps is None or n < max_steps):
            with access.exec_scope():                  # 같은 커널의 분석 셀 가드가 실행기 쓰기를 막지 않게 (2c-1)
                r = ex.step()
            n += 1
            if r == "work" or my_active_work(store, session):
                last_work = clock()
            elif idle_exit is not None and clock() - last_work >= idle_exit:
                ex.notes.append("idle_exit")
                break
            if max_steps is None or n < max_steps:
                sleep(interval)
    finally:
        beat.stop()
        beat.join(timeout=join_timeout)
        if beat.is_alive():
            ex.notes.append("beat_join_timeout")
    return ex


# ---------------------------------------------------------------- Kaggle GPU 작업자
def main_gpu(files: Dict[str, bytes], remote: str, admin_remote: str, test: bool, kernel: Optional[str] = None,
             store=None, admin=None, raw_cvat=None, log=print, **loop_kw) -> X.Executor:
    """뿌리 노트북(ROLE='gpu')이 배포 검증 뒤 부름."""
    import master_main as MM
    MM.check_remotes(MM.Boot(files=files, remote=remote, admin_remote=admin_remote, test=test))
    store = store or RcloneStore(remote)
    admin = admin or RcloneStore(admin_remote)
    accounts = admin.read_json("config/accounts.json")
    exec_cfg = load_exec_config(admin)
    os.environ[access.MODE_VAR] = "exec"
    fp = access.machine_fingerprint()
    session = access.new_session_id("kgg", fp)
    code = MM.write_code_dir(files)
    cfg = HostConfig(test=test, caps=["gpu"], exec_cfg=exec_cfg, scripts_dir=str(code), kernel=kernel,
                     device=_gpu_devices())
    env = build_env(cfg, store, raw_cvat=raw_cvat, log=log)
    H.load_all()
    log(f"[GPU 작업자 {HOST_VERSION}] 세션 {session} · {'시험' if test else '운영'} · GPU {cfg.device}")
    loop_kw.setdefault("idle_exit", float(exec_cfg.get("idle_exit_min", 15)) * 60)
    ex = run_loop(store, accounts, ["gpu"], env, session, fp, kernel=kernel, **loop_kw)
    log(f"[GPU 작업자] 끝냄 ({', '.join(ex.notes[-3:]) or '멈춤'})")
    return ex


def _gpu_devices() -> str:
    try:
        import torch
        n = torch.cuda.device_count() if torch.cuda.is_available() else 0
    except Exception:
        n = 0
    return ",".join(str(i) for i in range(n)) if n > 1 else "0"


# ---------------------------------------------------------------- Colab 30번 셀
class ColabRclone:
    """Colab 로그인(google.colab.auth)의 접근 토큰으로 세션 전용 rclone 설정을 만들고 만료 전에 다시 씀.
    토큰 갱신 정보(refresh token)는 받지도 쓰지도 않음. 설정 파일은 0600, 세션 임시 폴더."""
    REFRESH_SEC = 1800

    def __init__(self, folders: Dict[str, str], creds=None, clock=time.time):
        self.folders, self.clock = folders, clock          # {연결 이름: Drive 폴더 ID}
        self.creds = creds
        self.dir = Path(tempfile.mkdtemp(prefix="egg_rc_"))
        os.chmod(self.dir, 0o700)
        self.path = self.dir / "rclone.conf"
        self.at = 0.0

    def _token(self) -> dict:
        import google.auth.transport.requests
        if self.creds is None:
            import google.auth
            self.creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
        self.creds.refresh(google.auth.transport.requests.Request())
        exp = getattr(self.creds, "expiry", None)
        return {"access_token": self.creds.token, "token_type": "Bearer",
                "expiry": (exp.isoformat() + "Z") if exp else ""}

    def conf_text(self, tok: dict) -> str:
        out = []
        for name, fid in self.folders.items():
            out += [f"[{name}]", "type = drive", "scope = drive", f"token = {json.dumps(tok, separators=(',', ':'))}",
                    f"root_folder_id = {fid}", ""]
        return "\n".join(out)

    def write(self, tok: Optional[dict] = None):
        tok = tok or self._token()
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self.conf_text(tok))
        os.environ["RCLONE_CONFIG"] = str(self.path)
        self.at = self.clock()

    def keep_fresh(self, halt: threading.Event):
        def loop():
            while not halt.wait(60):
                if self.clock() - self.at >= self.REFRESH_SEC:
                    try:
                        self.write()
                    except Exception:
                        pass                                # 다음 분에 다시 — 실패가 이어지면 저장소 쓰기가 실패해 실행기가 기다림
        threading.Thread(target=loop, daemon=True).start()


def main_colab(base: str, folders: Dict[str, str], test: bool, scripts_dir: str, caps=("gpu", "colab_oauth"),
               drive_base: str = "", raw_cvat=None, log=print, **loop_kw) -> X.Executor:
    """30번 셀. folders = {'gdrive': 공유 폴더 ID, 'gadmin': 관리자 폴더 ID} (시험이면 이름 끝 _test).
    base = 공유 폴더 연결 이름 (예 'gdrive:'). 사람이 셀을 멈추면(KeyboardInterrupt) 지금 단계를 마치고 끝남."""
    names = list(folders)
    if test != all("test" in n for n in names) or (not test and any("test" in n for n in names)):
        raise HostError("시험·운영과 연결 이름이 맞지 않음")
    from google.colab import auth as colab_auth                 # noqa: F401  (Colab에서만)
    colab_auth.authenticate_user()
    rc = ColabRclone(folders)
    rc.write()
    halt = threading.Event()
    rc.keep_fresh(halt)
    store = RcloneStore(base)
    admin = RcloneStore(next(n for n in names if n.startswith("gadmin")) + ":")
    accounts = admin.read_json("config/accounts.json")
    exec_cfg = load_exec_config(admin)
    prev_mode = os.environ.get(access.MODE_VAR)
    os.environ[access.MODE_VAR] = "exec"
    stopped = {"v": False}
    try:
        fp = access.machine_fingerprint()
        session = access.new_session_id("col", fp)
        import h_run as HR
        cfg = HostConfig(test=test, caps=list(caps), exec_cfg=exec_cfg, scripts_dir=scripts_dir, device=_gpu_devices())
        env = build_env(cfg, store, raw_cvat=raw_cvat,
                        revisions=HR.RealRevisions(drive_base) if "colab_oauth" in caps and drive_base else None, log=log)
        H.load_all()
        log(f"[Colab 실행기 {HOST_VERSION}] 세션 {session} · {'시험' if test else '운영'} · 능력 {', '.join(caps)}")
        return run_loop(store, accounts, list(caps), env, session, fp, stop=lambda: stopped["v"], **loop_kw)
    except KeyboardInterrupt:
        stopped["v"] = True
        raise
    finally:
        halt.set()
        if prev_mode is None:                          # 30번 셀이 끝나면 이 커널은 다시 분석 모드 (2c-1)
            os.environ.pop(access.MODE_VAR, None)
        else:
            os.environ[access.MODE_VAR] = prev_mode
