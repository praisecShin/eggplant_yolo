# 가지 앱 CPU 마스터 v4.33 — 뿌리 노트북 (설계 8판 '실행 코드의 신뢰 경계')
#
# 이 셀 하나가 마스터 노트북 전체입니다. Keeper가 이 노트북의 해시(MASTER_NB_SHA256)를 확인한 뒤에만 Kaggle에 올립니다.
# 이 셀은 배포 목록(manifest.json)을 아래 고정 해시로 검증하고, 목록의 파일을 하나씩 검증한 바로 그 바이트로
# scripts를 불러 master_main.main()을 부릅니다. 하나라도 다르면 실행하지 않습니다.
#
# 손으로 고치지 마세요 — dev_tools/build_deploy.py가 만듭니다 (고정 해시·시험 여부를 넣음).
MANIFEST_SHA256 = "__MANIFEST_SHA256__"
MANIFEST_NAME = "__MANIFEST_NAME__"  # 마스터: manifest.json · GPU 작업자: worker_manifest.json (scripts만, 2b-6)
ROLE = "__ROLE__"                    # master | gpu
KERNEL = "__KERNEL__"                # 이 노트북의 Kaggle 주소 (GPU 작업자 생존 신호에 실음)
TEST = __TEST__
REMOTE = "__REMOTE__"                # 공유 폴더 rclone 연결
ADMIN_REMOTE = "__ADMIN_REMOTE__"    # 관리자 폴더 rclone 연결 (같은 A0 토큰, 11/14 결정)
BOOT_VERSION = "4.33.0x"

import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
import zipfile
from pathlib import Path

NL, CR, BS = chr(10), chr(13), chr(92)
# 가지 앱 모듈 이름 — 배포 목록에 없으면 설치 폴더에 같은 이름이 있어도 불러오지 않음 (V3). 빌드 때 채움
RESERVED_MODULES = __RESERVED__


class BootStop(RuntimeError):
    pass


# ---------------------------------------------------------------- 도구 설치
def install_tools():
    if not shutil.which("rclone"):
        import glob
        src = next((p for p in glob.glob("/kaggle/input/**/rclone", recursive=True) if os.path.isfile(p)), None)
        dst = "/usr/local/bin/rclone" if os.access("/usr/local/bin", os.W_OK) else os.path.expanduser("~/.local/bin/rclone")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if src:
            shutil.copy(src, dst)
        else:
            req = urllib.request.Request("https://downloads.rclone.org/rclone-current-linux-amd64.zip",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=180).read())) as z:
                with open(dst, "wb") as f:
                    f.write(z.read([n for n in z.namelist() if n.endswith("/rclone")][0]))
        os.chmod(dst, 0o755)
        os.environ["PATH"] = os.path.dirname(dst) + ":" + os.environ.get("PATH", "")
    if not shutil.which("rclone"):
        raise BootStop("rclone 설치 실패 — Kaggle Internet 설정을 확인하세요")
    install_packages()


CVAT_LAST_KNOWN = "2.79.0"            # 서버 버전을 못 읽을 때 (v4.32 GPU 작업자와 같음)


def _ver(dist):
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return None


def install_packages():
    """마스터(작업 프로세스의 백업·export·데이터셋)와 GPU 작업자(track·학습)가 쓰는 패키지. 서버와 같은 X.Y의 cvat-sdk."""
    need = []
    if ROLE == "master" and _ver("kaggle") is None:
        need.append("kaggle")
    try:
        with urllib.request.urlopen("https://app.cvat.ai/api/server/about", timeout=15) as r:
            sv = json.loads(r.read().decode("utf-8")).get("version") or CVAT_LAST_KNOWN
    except Exception:
        sv = CVAT_LAST_KNOWN
    mj, mn = sv.split(".")[:2]
    cli, sdk = _ver("cvat-cli"), _ver("cvat-sdk")
    if not (cli and sdk and cli == sdk and cli.startswith(f"{mj}.{mn}.")):
        need.append(f"cvat-cli~={mj}.{mn}.0")
    mods = [("av", "av")] + ([("ultralytics", "ultralytics"), ("lap", "lap")] if ROLE == "gpu" else [])
    need += [p for p, m in mods if importlib.util.find_spec(m) is None]
    if need:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *need], check=False)


# ---------------------------------------------------------------- 보안 비밀 → 세션 임시 폴더(0600)
def parse_rclone_conf(raw: str) -> str:
    """Kaggle 보안 비밀이 줄바꿈을 없앤 rclone 설정을 되살림. 연결(섹션)이 여럿이어도 됨 (gdrive·gadmin·…_test)."""
    s = raw.replace(CR + NL, NL).replace(CR, NL).strip()
    if not s:
        raise BootStop("RCLONE_CONF가 비었습니다")
    blobs = []

    def mask(m):
        blobs.append(m.group(0).strip())
        return f"__JSON_BLOB_{len(blobs) - 1}__"
    s = re.sub(r"\{[^{}]*\}", mask, s).replace(BS + "n", NL)
    parts = re.split(r"\[([A-Za-z0-9_\-]+)\]", s)
    if parts[0].strip():                              # 섹션 머리 없이 시작하면 gdrive로 봄 (옛 형식)
        parts = ["", "gdrive", parts[0]] + parts[1:]
    out = []
    for i in range(1, len(parts), 2):
        name, body = parts[i], parts[i + 1]
        out.append(f"[{name}]")
        for ch in re.split(r"(?:^|\s+)(?=[a-zA-Z0-9_]+\s*=)", body.strip()):
            ch = ch.strip()
            if "=" not in ch:
                continue
            k, v = (x.strip() for x in ch.split("=", 1))
            for j, b in enumerate(blobs):
                v = v.replace(f"__JSON_BLOB_{j}__", b)
            if k == "token" and v:
                v = json.dumps(json.loads(re.search(r"\{.*\}", v, flags=re.DOTALL).group(0)), separators=(",", ":"))
            out.append(f"{k} = {v}")
        out.append("")
    return NL.join(out)


def secret_file(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def get_secret(name: str) -> str:
    on_kaggle = bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE")) or Path("/kaggle/input").exists()
    if on_kaggle:
        try:
            from kaggle_secrets import UserSecretsClient
            return (UserSecretsClient().get_secret(name) or "").strip()
        except Exception:
            return ""
    return (os.environ.get(name) or "").strip()          # Kaggle 밖(시험)에서만


def setup_credentials() -> Path:
    sec = Path(tempfile.mkdtemp(prefix="egg_sec_"))
    conf = parse_rclone_conf(get_secret("RCLONE_CONF"))
    for need in (REMOTE, ADMIN_REMOTE):
        if f"[{need.rstrip(':')}]" not in conf:
            raise BootStop(f"RCLONE_CONF에 연결 '{need}'가 없습니다 — 관리자 폴더 연결을 덧붙였는지 확인하세요")
    secret_file(sec / "rclone.conf", conf)
    os.environ["RCLONE_CONFIG"] = str(sec / "rclone.conf")
    tok = get_secret("CVAT_TOKEN")
    if not tok:
        raise BootStop("Kaggle 보안 비밀 CVAT_TOKEN이 없습니다")
    os.environ["CVAT_TOKEN"] = tok                       # 이 프로세스와 작업 프로세스 안에서만 (파일·로그에 쓰지 않음)
    ku, kk = get_secret("KAGGLE_USERNAME"), get_secret("KAGGLE_KEY")
    if ku and kk:
        secret_file(sec / "kaggle" / "kaggle.json", json.dumps({"username": ku, "key": kk}))
        os.environ["KAGGLE_CONFIG_DIR"] = str(sec / "kaggle")
    return sec


# ---------------------------------------------------------------- 배포 목록 검증
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch_deploy(admin_remote: str = None, rclone=None) -> dict:
    """관리자 폴더의 deploy/를 세션 임시 폴더로 받고, 목록 해시 → 파일별 해시를 확인. {상대 경로: 바이트}."""
    admin_remote = admin_remote or ADMIN_REMOTE
    rclone = rclone or (lambda *a: subprocess.run(["rclone", *a], capture_output=True, timeout=600))
    d = Path(tempfile.mkdtemp(prefix="egg_deploy_"))
    r = rclone("copy", admin_remote + "deploy", str(d))
    if r.returncode != 0:
        raise BootStop("deploy/를 받지 못했습니다")
    mb = (d / MANIFEST_NAME).read_bytes() if (d / MANIFEST_NAME).exists() else b""
    if not mb or sha256(mb) != MANIFEST_SHA256:
        raise BootStop("배포 목록 해시가 이 노트북의 고정값과 다릅니다 — 실행하지 않습니다")
    man = json.loads(mb.decode("utf-8"))
    files = {}
    for rel, want in sorted((man.get("files") or {}).items()):
        p = d / rel
        b = p.read_bytes() if p.is_file() else None
        if b is None or sha256(b) != want:
            raise BootStop(f"배포 파일 해시가 목록과 다릅니다: {rel} — 실행하지 않습니다")
        files[rel] = b                                  # 검증한 바로 그 바이트를 씀 (디스크를 다시 읽지 않음)
    shutil.rmtree(d, ignore_errors=True)
    return {"manifest": man, "files": files}


class VerifiedFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """scripts 모듈을 검증한 바이트에서만 불러옴. 디스크의 같은 이름 파일은 보지 않음."""

    def __init__(self, files: dict, reserved=()):
        self.src = {rel[len("scripts/"):-3]: b for rel, b in files.items()
                    if rel.startswith("scripts/") and rel.endswith(".py") and "/" not in rel[len("scripts/"):]}
        self.reserved = set(reserved) | set(RESERVED_MODULES)

    def find_spec(self, name, path=None, target=None):
        if name in self.src:
            return importlib.util.spec_from_loader(name, self, origin="deploy:scripts/" + name + ".py")
        if name.split(".")[0] in self.reserved:       # 우리 모듈 이름인데 목록에 없음 → 설치 폴더에서도 찾지 않음 (V3)
            raise ImportError(f"배포 목록에 없는 가지 앱 모듈입니다: {name}")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        module.__file__ = "deploy:scripts/" + name + ".py"
        exec(compile(self.src[name].decode("utf-8"), module.__file__, "exec"), module.__dict__)


def _allowed_roots():
    """import를 허락하는 폴더: 이 파이썬의 표준 라이브러리와 **실제 설치 폴더**뿐 (U2·V3).
    폴더 이름(site-packages)만으로는 허락하지 않음."""
    import site
    roots = set()
    for k in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(k)
        if p:
            roots.add(os.path.realpath(p))
    try:
        roots |= {os.path.realpath(p) for p in site.getsitepackages()}
    except Exception:
        pass
    return roots


def _allowed(path, roots) -> bool:
    if not path:
        return False
    rp = os.path.realpath(path)
    return any(rp == r or rp.startswith(r + os.sep) for r in roots)


def files_reserved(files: dict):
    try:
        return json.loads(files.get("reserved_modules.json", b"[]").decode("utf-8"))
    except Exception:
        return []


def lock_imports(files: dict):
    """배포 모듈의 import 경계를 닫음 (U2).
    1) sys.path를 표준 라이브러리·설치된 패키지 폴더로 좁힘 — 작업 폴더·입력 폴더·현재 폴더의 .py는 보지 않음
    2) 이미 불린 모듈 중 허락된 폴더 밖에서 온 것과 배포 모듈과 같은 이름은 버림
    3) 검증한 바이트를 맨 앞에서 내줌. 목록에 없는 우리 코드는 찾을 곳이 없어 ImportError"""
    roots = _allowed_roots()
    sys.path[:] = [p for p in sys.path if _allowed(p, roots)]
    finder = VerifiedFinder(files, reserved=(files_reserved(files)))
    ours = set(finder.src) | finder.reserved
    for n, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if n.split(".")[0] in ours:                     # 가지 앱 이름은 어디서 불렸든 모두 버림 (하위 모듈 포함, W3)
            del sys.modules[n]
        elif f and not str(f).startswith("deploy:") and not _allowed(os.path.dirname(f), roots) and n != "__main__":
            del sys.modules[n]
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, VerifiedFinder)]
    sys.meta_path.insert(0, finder)
    return finder


def boot(run=True):
    print(f"[뿌리 노트북 {BOOT_VERSION}] {ROLE} · {'시험' if TEST else '운영'} · 연결 {REMOTE} / {ADMIN_REMOTE}")
    install_tools()
    sec = setup_credentials()
    dep = fetch_deploy()
    lock_imports(dep["files"])
    if ROLE == "gpu":                                  # GPU 작업자: 같은 검증 뒤 실행기만 (2b-6)
        import exec_host
        print(f"✅ 배포 검증: 파일 {len(dep['files'])}개")
        return exec_host.main_gpu(dep["files"], REMOTE, ADMIN_REMOTE, TEST, kernel=KERNEL) if run else dep
    import master_main
    b = master_main.Boot(files=dep["files"], remote=REMOTE, admin_remote=ADMIN_REMOTE, test=TEST, secret_dir=sec)
    print(f"✅ 배포 검증: 파일 {len(dep['files'])}개")
    return master_main.main(b) if run else b


if __name__ == "__main__" and MANIFEST_SHA256 != "__MANIFEST" + "_SHA256__":
    boot()
