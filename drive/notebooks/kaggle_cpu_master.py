"""
Kaggle CPU 상주 마스터 노트북 엔진 (v4.32.0)
v4.32.0: 취합자 임대(jobs/STATE_OWNER.json, 우선순위 3)를 가진 때만 상태 파일 · 숨기기 등 · 요청은 받은 세션만 쓰고(올리기 전 확인) 받은 뒤 다시 읽어 확인 · TASK 기록은 공용 rb.sync_record
v4.31.13: TASK 기록은 sync_task_record로만(받기 실패 시 쓰지 않음 R14 · 상태 갱신·AA 작업의 통째 올리기 없앰 R15) · 실행 한도는 준비 뒤부터
v4.31.12: 받는 중 확인 뒤 relabel/tasks 통째 올리기 없앰 — 바꾼 TASK 기록만 최신본에 고쳐 올림(R11)
v4.31.11: GPU 워커 생존 신호도 보고 쓰기 직전 요청 재확인(R6) · 누적 결과로 최종 상태(R7) · CVAT_TOKEN 없으면 멈춤(R8) · 실패·기한 초과 track도 GPU 깨움(R9)
v4.31.10: 백업 판정을 scripts의 wb.backup_verdict로 공용(R1) · 보안 비밀은 Kaggle Secrets만, 설정 파일은 세션 임시 폴더 0600(R2) · 받는 중 AA 백업을 마스터가 받고 GPU 워커를 깨움(R4)
v4.31.9: 재처리(AA앱) 백업을 TASK별로 판정(받는 중·실패) · 백업을 기다리던 GPU 요청도 워커 시작 이유 · 상태 파일에 ULD·사라진 TASK
v4.31.7: kaggle_gpu 배정 요청이 있으면 GPU 워커 노트북(0번 + 30번 셀 W_ROLE='gpu')을 Kaggle API로 시작 — 워커가 직접 받고 할 일이 없으면 스스로 끝남
v4.31.4 고친 것
- 문자열 안의 줄바꿈 문자(백슬래시 n 등)를 chr()로 바꿈 → 내려받기·붙여넣기에서 깨지지 않음
- rclone sync 제거: 요청 폴더는 copy + 바뀐 옛 이름만 deletefile (다른 작업자가 쓴 새 요청·배정 파일을 지우지 않음)
- 처리하지 않는 종류(upload·cleanup·LC discard/hide/unhide/refresh)는 받지 않음 (거짓 완료 금지)
- GPU 작업은 routing.json "gpu_worker_enabled": true 일 때만, 한 요청에 한 번만 준비
- 요청을 id로 받음 · 낮에도 routing.json 배정(requests/assign) 따름 · 배정 파일 없는 요청은 받지 않음
- 다른 작업자(31번·30번 셀)가 살아 있으면 그 worker 파일을 덮어쓰지 않고, AA 요청은 받지 않음
- 정지 표시(STOP_MASTER.json)를 긴 작업 중간에도 확인 · 지우기 실패 시 종료 · 수동 시작이 푼 정지는 기록
- CVAT 범위: config/app_settings.json (기본 조직 horti, 프로젝트 전체)
- 가동 시간: 주간 08:00 ~ 19:00 KST 상시 가동 (그 외 시간은 명시적으로 승인된 야간 작업이 있을 때만 가동 후 자동 종료)
- 원격 강제 종료 및 Hold 연동:
  1) 기동 시가 아닌 폴링 루프 중 새로 발행된 jobs/STOP_MASTER.json(또는 until 유효기간이 남은 Hold) 감지 시 즉시 안전 종료
  2) 기동 시 만료된 STOP_MASTER.json 잔여물은 자동 정리
- RCLONE_CONF 안전 파서 탑재:
  한 줄 문자열 시크릿에서 JSON 토큰({...}) 내부를 마스킹 보호한 뒤 team_drive 등 모든 옵션을 완벽 분리하고 JSON 유효성 검증
- rclone 자동 설치:
  User-Agent 헤더 적용(HTTP 403 차단 방지) + 타임아웃/재시도 + apt-get 폴백 탑재
- 역할 1 (요청 감시 및 단일 취합): 30초마다 LC웹(requests/) 및 AA웹(relabel/requests/)을 스캔하고,
         작업 완료 시 compact_shards(), 검토 수정량(corrections), web/state.json, relabel/state.json을 독점 갱신
- 역할 2 (CPU 작업 직접 처리): backup(검토완료 자동 export 연쇄 포함), export(삭제된 TASK 복원 포함),
         upload, cleanup, discard, hide/unhide, refresh, 데이터셋 빌드(build_only)를 CPU에서 직접 처리
- 역할 3 (GPU 참여 판별 및 사전 준비):
         shape, track, compare, train 요청에 대해 영상/백업 확보 및 스냅숏 준비를 CPU에서 먼저 완료한 뒤
         GPU가 꼭 필요한 순간에만 jobs/gpu_queue.json에 등록하고 Kaggle API로 GPU 워커 노트북을 Start 시킴
- 역할 4 (실시간 Google Drive 백업): 임시 폴더(/tmp/eggplant_yolo)의 모든 변경사항을 rclone으로 즉시 Drive에 백업
"""
__version__ = "4.32.0"
NL, CR, TAB, BS = chr(10), chr(13), chr(9), chr(92)   # v4.31.4: 문자열 안 제어 문자는 이것으로 (내려받기에서 깨지지 않게)
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

BASE = Path(os.environ.get("KAGGLE_BASE", "/tmp/eggplant_yolo"))
REMOTE = os.environ.get("KAGGLE_REMOTE", "gdrive:")
SESSION_ID = os.environ.get("EGGPLANT_SHARD") or f"kg_cpu_master_{uuid.uuid4().hex[:6]}"
POLL_SEC = int(os.environ.get("MASTER_POLL_SEC", "30"))
DAY_START_H = int(os.environ.get("DAY_START_H", "8"))
DAY_END_H = int(os.environ.get("DAY_END_H", "19"))
MAX_RUN_HOURS = float(os.environ.get("MAX_RUN_HOURS", "11.2"))

START_TS = time.time()
_RC_LOCK = threading.RLock()
_STATE = {"stop": False, "busy": "대기 중", "dirty": True, "last_refresh": 0.0,
          "stop_req": None, "lc_peer": None, "aa_peer": None, "aa_gpu_peer": None, "owner": False, "gpu_prepped": set(), "skipped": set()}
PEER_STALE_SEC = 180


class StopRequested(Exception):
    """긴 작업 중간에 정지 표시를 봄"""

CPU_DIRECT_KINDS = ("backup", "export")          # v4.31.4: 실제로 처리하는 것만 (upload·cleanup 등은 받지 않음 → 31번 셀이 처리)
AA_DIRECT_KINDS = ("discard", "backup")
AA_STATE_KINDS = ("hide", "unhide", "refresh")   # v4.32.0: tracked.json·상태를 고치는 일 → 취합자만
GPU_KINDS = ("shape", "aa", "track", "compare", "train")


def ensure_environment():
    """1. rclone 바이너리(HTTP 403 방지 User-Agent 및 apt 폴백 포함) 및 필수 파이썬 패키지 자동 설치"""
    if not shutil.which("rclone"):                 # v4.31.5: 붙인 Kaggle 데이터셋의 rclone 파일이 있으면 복사만 (1~2초)
        import glob as _g
        _src = next((p for p in _g.glob("/kaggle/input/**/rclone", recursive=True) if os.path.isfile(p)), None)
        if _src:
            _dst = "/usr/local/bin/rclone" if os.access("/usr/local/bin", os.W_OK) else os.path.expanduser("~/.local/bin/rclone")
            os.makedirs(os.path.dirname(_dst), exist_ok=True)
            shutil.copy(_src, _dst)
            os.chmod(_dst, 0o755)
            os.environ["PATH"] = os.path.dirname(_dst) + ":" + os.environ.get("PATH", "")
            print(f"✅ rclone 설치 완료 (붙인 데이터셋): {_src}")
    if not shutil.which("rclone"):
        print("[*] rclone 바이너리 다운로드 및 설치 중...")
        installed = False
        urls = [
            "https://downloads.rclone.org/rclone-current-linux-amd64.zip",
            "https://github.com/rclone/rclone/releases/latest/download/rclone-current-linux-amd64.zip",
        ]
        for url in urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"}
                )
                data = urllib.request.urlopen(req, timeout=180).read()
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    exe = z.read([n for n in z.namelist() if n.endswith("/rclone")][0])
                dst = "/usr/local/bin/rclone" if os.access("/usr/local/bin", os.W_OK) else os.path.expanduser("~/.local/bin/rclone")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(exe)
                os.chmod(dst, 0o755)
                os.environ["PATH"] = os.path.dirname(dst) + ":" + os.environ.get("PATH", "")
                installed = True
                print(f"✅ rclone 설치 완료: {dst}")
                break
            except Exception as e:
                print(f"⚠️ rclone 다운로드 시도 실패 ({url}): {e}")

        if not installed and shutil.which("apt-get"):
            print("[*] apt-get으로 rclone 폴백 설치 시도 중...")
            subprocess.run(["apt-get", "update", "-qq"], check=False)
            subprocess.run(["apt-get", "install", "-y", "-qq", "rclone"], check=False)

        if not shutil.which("rclone"):
            raise RuntimeError("rclone 설치에 실패했습니다. Kaggle 세션의 Internet 설정이 On인지 확인하세요.")

    missing_pkgs = []
    for mod, pkg in [("cvat_sdk", "cvat-sdk"), ("kaggle", "kaggle"), ("openpyxl", "openpyxl")]:
        try:
            __import__(mod)
        except ImportError:
            missing_pkgs.append(pkg)
    if missing_pkgs:
        print(f"[*] 필수 파이썬 패키지 설치 중: {missing_pkgs}")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing_pkgs, "cvat-cli"], check=False)


def kst_now():
    tz = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(tz)


def is_daytime_kst():
    h = kst_now().hour
    return DAY_START_H <= h < DAY_END_H


def _remote(rel=""):
    r = REMOTE if REMOTE.endswith(":") else REMOTE.rstrip("/") + "/"
    return r + rel.strip("/")


def rclone(*args, quiet=True, check=False):
    with _RC_LOCK:
        cmd = ["rclone", *args]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 and not quiet:
            err_msg = (res.stderr or res.stdout or "").strip()
            print(f"⚠️ rclone 오류 (cmd={' '.join(cmd[:3])}): {err_msg[-400:]}")
        if check and res.returncode != 0:
            err_msg = (res.stderr or res.stdout or "").strip()
            raise RuntimeError(f"rclone 실행 실패 ({cmd}): {err_msg}")
        return res


def _parse_rclone_conf(raw_conf: str) -> str:
    """
    Kaggle Secrets가 줄바꿈을 제거하여 한 줄로 만든 RCLONE_CONF 문자열에서
    token = {...} 뒤에 붙은 team_drive = 등으로 인해 발생하는
    'invalid character t after top-level value' 에러를 100% 방지하는 파서.
    """
    s = raw_conf.replace(CR + NL, NL).replace(CR, NL).strip()
    if not s:
        raise ValueError("RCLONE_CONF 시크릿 값이 비어 있습니다.")

    sec_match = re.match(r"^\s*\[([^\]]+)\]\s*(.*)$", s, flags=re.DOTALL)
    if sec_match:
        sec_name = sec_match.group(1).strip()
        body = sec_match.group(2).strip()
    else:
        sec_name = "gdrive"
        body = s

    json_blobs = []
    def _mask_json(m):
        idx = len(json_blobs)
        blob = m.group(0).strip()
        json_blobs.append(blob)
        return f"__JSON_BLOB_{idx}__"

    masked_body = re.sub(r"\{[^{}]*\}", _mask_json, body)
    masked_body = masked_body.replace(CR + NL, NL).replace(BS + "n", NL)   # 한 줄 시크릿에 글자 그대로 남은 백슬래시-n → 줄바꿈

    chunks = re.split(r"(?:^|\s+)(?=[a-zA-Z0-9_]+\s*=)", masked_body.strip())
    kv_lines = []
    for ch in chunks:
        ch = ch.strip()
        if not ch or "=" not in ch:
            continue
        k, v = ch.split("=", 1)
        k = k.strip()
        v = v.strip()
        for idx, blob in enumerate(json_blobs):
            v = v.replace(f"__JSON_BLOB_{idx}__", blob)
        if k == "token" and v:
            jm = re.search(r"\{.*\}", v, flags=re.DOTALL)
            if jm:
                v = jm.group(0)
            tok_obj = json.loads(v)
            v = json.dumps(tok_obj, separators=(",", ":"))
        kv_lines.append(f"{k} = {v}".rstrip())

    out_blocks = [f"[{sec_name}]"] + kv_lines
    if sec_name != "gdrive":
        out_blocks += ["", "[gdrive]"] + kv_lines
    return NL.join(out_blocks) + NL


def _on_kaggle():
    return bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE")) or Path("/kaggle/input").exists()


def _secret_file(path, text):
    """v4.31.10 (R2): 비밀 파일은 처음부터 본인만 읽게(0600) 만듦 — 쓰고 나서 권한을 바꾸면 그 사이에 읽힐 수 있음"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


SECRET_DIR = None                                             # 세션 임시 폴더 (홈·작업 폴더 밖) — setup_credentials에서 만듦


def setup_credentials():
    """v4.31.10 (R2): Kaggle에서는 Kaggle 보안 비밀만 읽음 (환경 변수 먼저 읽지 않음).
    rclone.conf·kaggle.json은 홈이 아닌 세션 임시 폴더에 0600으로 만들고 RCLONE_CONFIG·KAGGLE_CONFIG_DIR로 연결.
    Kaggle이 아닌 로컬 실행(시험)에서만 환경 변수를 씀"""
    global SECRET_DIR
    kaggle = _on_kaggle()
    if SECRET_DIR is None:
        SECRET_DIR = Path(tempfile.mkdtemp(prefix="eggplant_sec_"))   # mkdtemp는 처음부터 0700

    def _get_sec(key_name):
        if kaggle:
            try:
                from kaggle_secrets import UserSecretsClient
                v = UserSecretsClient().get_secret(key_name)
            except Exception:
                v = None
        else:
            v = os.environ.get(key_name)
        return (v or "").strip()

    rconf_raw = _get_sec("RCLONE_CONF")
    if rconf_raw:
        clean_conf = _parse_rclone_conf(rconf_raw)
        cp = SECRET_DIR / "rclone.conf"
        _secret_file(cp, clean_conf)
        os.environ["RCLONE_CONFIG"] = str(cp)
        keys_found = [line.split("=")[0].strip() for line in clean_conf.splitlines() if "=" in line]
        print(f"✅ rclone 설정 준비 (세션 임시 폴더 · 인식된 설정 키: {keys_found})")
    elif kaggle or not os.environ.get("RCLONE_CONFIG"):
        raise RuntimeError("Kaggle Secrets에서 'RCLONE_CONF'를 찾을 수 없습니다. 우측 Add-ons -> Secrets 부착 여부를 확인하세요.")

    cvat_tok = _get_sec("CVAT_TOKEN")
    if cvat_tok:
        os.environ["CVAT_TOKEN"] = cvat_tok          # cvat_backup에 넘기려고 이 프로세스 안에서만 둠 (파일·로그에 쓰지 않음)
    elif kaggle:                                     # v4.31.11 (R8): Kaggle에서 비밀이 없으면 멈춤 — 남아 있던 환경 값을 쓰지 않음
        os.environ.pop("CVAT_TOKEN", None)
        raise RuntimeError("Kaggle Secrets에서 'CVAT_TOKEN'을 찾을 수 없습니다. 우측 Add-ons -> Secrets 부착 여부를 확인하세요.")
    else:
        print("⚠️ 경고: CVAT_TOKEN 시크릿이 비어 있습니다.")

    kg_user = _get_sec("KAGGLE_USERNAME")
    kg_key = _get_sec("KAGGLE_KEY")
    if kg_user and kg_key:
        kd = SECRET_DIR / "kaggle"
        _secret_file(kd / "kaggle.json", json.dumps({"username": kg_user, "key": kg_key}))
        os.environ["KAGGLE_CONFIG_DIR"] = str(kd)
        os.environ["KAGGLE_USERNAME"] = kg_user      # GPU 워커 시작 판단용 (키 값은 환경에 두지 않음)
        print(f"✅ kaggle 설정 준비 (세션 임시 폴더 · 계정: {kg_user})")


def initial_pull():
    """Google Drive 원격 연결 검증, 루트 경로 자동 보정 및 필수 폴더/스크립트 동기화"""
    global REMOTE
    print(f"[*] Google Drive 원격 연결({REMOTE}) 테스트 중...")
    test_res = rclone("lsf", REMOTE, quiet=False)
    if test_res.returncode != 0:
        raise RuntimeError("rclone 원격 연결 실패: " + NL + str(test_res.stderr))

    top_items = [x.rstrip("/") for x in test_res.stdout.splitlines() if x.strip()]
    print(f"✅ Drive 연결 성공! 최상위 항목 샘플: {top_items[:8]}")

    if "scripts" not in top_items and "eggplant_yolo" in top_items:
        REMOTE = _remote("eggplant_yolo")
        print(f"[*] 'eggplant_yolo' 하위 폴더 감지 → 원격 경로를 '{REMOTE}'로 자동 보정합니다.")

    for d in ("scripts", "config", "requests/assign", "relabel/requests", "relabel/tasks", "web", "logs/shards", "jobs", "backups", "exports", "notebooks"):
        (BASE / d).mkdir(parents=True, exist_ok=True)

    for sub in ("scripts", "config", "requests", "relabel", "web", "logs/shards", "jobs"):
        rclone("copy", _remote(sub), str(BASE / sub), quiet=False)

    # 수동으로 켰는데 기한 없는(until 없음) 또는 기한 지난 정지 표시가 있으면 푼다 (설계: 수동 시작 > 정지 표시)
    # v4.31.4: 푼 사실을 jobs/STOP_MASTER_released.json에 남기고, Drive에서 지우지 못하면 경고 후 종료
    stop_f = BASE / "jobs" / "STOP_MASTER.json"
    if stop_f.exists():
        try:
            info = json.loads(stop_f.read_text(encoding="utf-8") or "{}")
        except Exception:
            info = {}
        if _until_passed(info.get("until")) is not False:      # 기한 없음(None) 또는 지남(True)
            res = rclone("deletefile", _remote("jobs/STOP_MASTER.json"))
            if res.returncode != 0 and "not found" not in (res.stderr or "").lower():
                raise RuntimeError("정지 표시(jobs/STOP_MASTER.json)를 Drive에서 지우지 못했습니다 — 그대로 두면 Apps Script가 계속 정지로 봅니다. "
                                   "Drive에서 직접 지우고 다시 시작하세요: " + (res.stderr or "")[-200:])
            stop_f.unlink()
            rel = BASE / "jobs" / "STOP_MASTER_released.json"
            rel.write_text(json.dumps({"released_at": kst_now().isoformat(timespec="seconds"), "session": SESSION_ID,
                                       "by": "수동 시작 (CPU 마스터)", "stop": info}, ensure_ascii=False, indent=1), encoding="utf-8")
            rclone("copyto", str(rel), _remote("jobs/STOP_MASTER_released.json"))
            print(f"ℹ️ 정지 표시를 풀었습니다 (수동 시작 · 원래 사유: {info.get('reason', '')}) → jobs/STOP_MASTER_released.json")
        else:
            print(f"🛑 기한이 남은 정지 표시가 있습니다 (until {info.get('until')}) → 시작하지 않습니다. 풀려면 Drive의 jobs/STOP_MASTER.json을 지우세요.")
            raise SystemExit(0)

    for csv_f in ("task_registry.csv", "backup_index.csv", "backup_status.csv"):
        rclone("copyto", _remote(csv_f), str(BASE / csv_f))

    scripts_dir = BASE / "scripts"
    py_files = sorted(f.name for f in scripts_dir.glob("*.py"))
    print(f"✅ scripts/ 동기화 완료 ({len(py_files)}개 파일): {py_files}")
    if "cvat_task_tools.py" not in py_files:
        raise RuntimeError(f"Drive의 {_remote('scripts')} 폴더에 cvat_task_tools.py가 없습니다. Drive 폴더 구조를 확인하세요.")


def _until_passed(until_str):
    """None = 기한 없음 · True = 지남 · False = 아직 유효"""
    if not until_str:
        return None
    try:
        exp_dt = datetime.datetime.fromisoformat(str(until_str).replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
        return exp_dt <= datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        return False


def _peer(rel, my_session):
    """Drive의 worker 파일(web/worker.json · relabel/WORKER.json)에 다른 살아 있는 작업자가 있으면 그 내용"""
    tmp = BASE / "jobs" / ("_peer_" + rel.replace("/", "_"))
    tmp.unlink(missing_ok=True)
    res = rclone("copyto", _remote(rel), str(tmp))
    if res.returncode != 0 or not tmp.exists():
        return None
    try:
        w = json.loads(tmp.read_text(encoding="utf-8"))
        hb = datetime.datetime.fromisoformat(w["heartbeat"])
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - hb).total_seconds()
    except Exception:
        return None
    if w.get("session") == my_session or w.get("stopping") or age > PEER_STALE_SEC or w.get("who") == "kaggle-cpu-master":
        return None
    w["age_sec"] = round(age)
    return w


def _beat_obj(busy_obj, started_str, stopping=False, app="LC"):
    return {"who": "kaggle-cpu-master", "session": SESSION_ID, "host": "Kaggle CPU Master",
            "heartbeat": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
            "busy": busy_obj, "started": started_str, "stopping": stopping, "version": __version__, "app": app}


def send_heartbeat_once(wb, rb, started_str, stopping=False):
    """생존 신호. 다른 작업자(31번 셀 → web/worker.json, 30번 셀 → relabel/WORKER.json)가 살아 있으면
    그 파일은 덮어쓰지 않고 web/worker_cpu_master.json · relabel/WORKER_cpu_master.json 에만 씀 (v4.31.4)"""
    now_iso = kst_now().isoformat(timespec="seconds")
    busy_obj = {"what": "꺼짐 (안전 종료됨)" if stopping else _STATE["busy"], "loop_at": now_iso,
                "mode": "주간(08~19시)" if is_daytime_kst() else "야간 승인 가동"}
    _STATE["lc_peer"] = _peer("web/worker.json", SESSION_ID)
    _STATE["aa_peer"] = _peer("relabel/WORKER.json", SESSION_ID)
    _STATE["aa_gpu_peer"] = _peer("relabel/WORKER_gpu.json", SESSION_ID)   # v4.31.11 (R6): GPU 워커(W_ROLE='gpu')의 생존 신호
    try:
        lease_tick(wb, stopping=stopping)          # v4.32.0: 생존 신호와 같이 취합자 임대도 갱신
    except Exception as e:
        _STATE["owner"] = False
        print(f"⚠️ 취합자 임대 확인 실패: {e}")
    for rel, peer, app in (("web/worker.json", _STATE["lc_peer"], "LC"), ("relabel/WORKER.json", _STATE["aa_peer"], "AA")):
        own = rel.replace(".json", "_cpu_master.json")
        p = BASE / own
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_beat_obj(busy_obj, started_str, stopping, app), ensure_ascii=False, indent=1), encoding="utf-8")
        for t in [own] + ([] if peer else [rel]):
            rclone("copyto", str(p), _remote(t))


def lease_tick(wb, stopping=False):
    """v4.32.0 (F3·F14): 취합자 임대(jobs/STATE_OWNER.json) — CPU 마스터는 우선순위 3. 맡으면 상태 파일을 이 마스터만 씀"""
    rel = wb.LEASE_FILE
    tmp = BASE / "jobs" / "_lease_remote.json"
    tmp.unlink(missing_ok=True)
    got = _fetch_remote(rel, tmp)
    if got == "fail":
        _STATE["owner"] = False                    # Drive를 못 읽으면 맡지 않음 (두 명이 되지 않게)
        return False
    try:
        cur = json.loads(tmp.read_text(encoding="utf-8")) if got == "ok" else None
    except Exception:
        cur = None
    tmp.unlink(missing_ok=True)
    mine_now = bool(cur) and cur.get("session") == SESSION_ID
    if stopping:
        if mine_now:
            wb.lease_write(BASE, wb.lease_body(SESSION_ID, "kaggle-cpu-master", "cpu_master", wb.LEASE_PRIO["cpu_master"], stopping=True))
            _put_remote(rel, BASE / rel)
        _STATE["owner"] = False
        return False
    if not wb.lease_should_take(cur, SESSION_ID, wb.LEASE_PRIO["cpu_master"]):
        _STATE["owner"] = False
        return False
    wb.lease_write(BASE, wb.lease_body(SESSION_ID, "kaggle-cpu-master", "cpu_master", wb.LEASE_PRIO["cpu_master"]))
    if not _put_remote(rel, BASE / rel):
        _STATE["owner"] = False
        return False
    if not mine_now:                               # 새로 맡음 → 잠시 뒤 다시 읽어 확인
        time.sleep(CLAIM_CONFIRM_SEC)
        if _fetch_remote(rel, tmp) != "ok":
            _STATE["owner"] = False
            return False
        try:
            again = json.loads(tmp.read_text(encoding="utf-8"))
        except Exception:
            again = None
        tmp.unlink(missing_ok=True)
        if not again or again.get("session") != SESSION_ID:
            _STATE["owner"] = False
            return False
        print(f"🔑 [{kst_now().strftime('%H:%M:%S')}] 상태 파일 취합자를 맡음 (jobs/STATE_OWNER.json)")
    _STATE["owner"] = True
    return True


def dirty_markers():
    """다른 작업자가 남긴 '상태 새로 만들어 주세요' 표시 (jobs/DIRTY_*.json) — Drive에서 받아 목록"""
    rclone("copy", _remote("jobs"), str(BASE / "jobs"), "--include", "DIRTY_*.json")
    return sorted((BASE / "jobs").glob("DIRTY_*.json"))


def heartbeat_loop(started_str):
    """60초마다 생존 신호 + 정지 표시 확인 (긴 작업 중에도 정지를 알아채게 — v4.31.4)"""
    import web_bridge as wb
    import relabel_bridge as rb
    while not _STATE["stop"]:
        try:
            send_heartbeat_once(wb, rb, started_str)
            info = read_stop_signal()
            if info is not None and _STATE["stop_req"] is None:
                _STATE["stop_req"] = info
                print(f"🛑 정지 표시 감지 (사유: {info.get('reason', '')}) → 지금 하는 TASK를 마치고 멈춥니다")
        except Exception as e:
            print(f"⚠️ 생존 신호 오류: {e}")
        for _ in range(60):
            if _STATE["stop"]:
                return
            time.sleep(1)


def check_stop():
    """긴 작업의 TASK 사이에서 부름"""
    if _STATE["stop_req"] is not None:
        raise StopRequested(_STATE["stop_req"].get("reason", "정지 표시"))


def read_gpu_queue():
    p = BASE / "jobs" / "gpu_queue.json"
    if not p.exists():
        return {"updated": "", "items": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"updated": "", "items": []}


def write_gpu_queue(q_obj):
    p = BASE / "jobs" / "gpu_queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    q_obj["updated"] = kst_now().isoformat(timespec="seconds")
    p.write_text(json.dumps(q_obj, ensure_ascii=False, indent=1), encoding="utf-8")
    rclone("copyto", str(p), _remote("jobs/gpu_queue.json"))


def is_gpu_kernel_running(kernel_slug):
    """Kaggle CLI로 GPU 워커 노트북이 현재 running 상태인지 확인"""
    kg_user = os.environ.get("KAGGLE_USERNAME", "")
    if not kg_user or not shutil.which("kaggle"):
        return False
    full_slug = kernel_slug if "/" in kernel_slug else f"{kg_user}/{kernel_slug}"
    r = subprocess.run(["kaggle", "kernels", "status", full_slug], capture_output=True, text=True)
    out = (r.stdout or "").lower()
    return "running" in out or "queued" in out


def start_gpu_worker_if_needed(reason="", prefer_train=False):
    """GPU 대기열(jobs/gpu_queue.json)에 작업이 있을 때 Kaggle GPU 워커 노트북을 Start (enable_gpu: true)"""
    kg_user = os.environ.get("KAGGLE_USERNAME", "")
    kg_ok = (Path(os.environ.get("KAGGLE_CONFIG_DIR", "")) / "kaggle.json").is_file() or bool(os.environ.get("KAGGLE_KEY"))   # v4.31.10 (R2)
    if not (kg_user and kg_ok and shutil.which("kaggle")):
        print(f"ℹ️ [GPU 점화 대기] KAGGLE_USERNAME/KAGGLE_KEY가 없어 수동 GPU 워커 실행이 필요합니다 (사유: {reason})")
        return False

    routing_path = BASE / "config" / "routing.json"
    rcfg = json.loads(routing_path.read_text(encoding="utf-8")) if routing_path.exists() else {}
    kcfg = rcfg.get("kaggle_kernels") or {}
    slug = kcfg.get("gpu_train_slug" if prefer_train else "gpu_worker_slug") or "eggplant-gpu-worker"
    full_slug = slug if "/" in slug else f"{kg_user}/{slug}"

    if is_gpu_kernel_running(full_slug):
        print(f"ℹ️ GPU 워커({full_slug})가 이미 실행 중입니다 — 큐(gpu_queue.json)를 통해 이어서 처리합니다.")
        return True

    stop_f = BASE / "jobs" / "STOP_GPU.json"
    if stop_f.exists():
        stop_f.unlink()
    rclone("deletefile", _remote("jobs/STOP_GPU.json"))

    if time.time() - _STATE.get("gpu_start_t", 0) < 600:    # v4.31.7: 막 시작했으면 (Kaggle이 띄우는 데 몇 분) 다시 올리지 않음
        return True
    rclone("copy", _remote("notebooks"), str(BASE / "notebooks"), "--include", "eggplant_kaggle_gpu_worker_v*.ipynb")   # Drive의 최신 것
    nbs = sorted((BASE / "notebooks").glob("eggplant_kaggle_gpu_worker_v*.ipynb"),
                 key=lambda p: [int(x) for x in re.findall(r"\d+", p.stem.rsplit("_v", 1)[-1])])
    if not nbs:
        print("⚠️ GPU 워커 노트북(notebooks/eggplant_kaggle_gpu_worker_v*.ipynb)이 Drive에 없습니다 — 올린 뒤 다시")
        return False
    src_nb = nbs[-1]                                   # v4.31.7: 0번 셀 + 30번 셀(W_ROLE='gpu') 노트북
    with tempfile.TemporaryDirectory() as tmpd:
        tmp_path = Path(tmpd)
        shutil.copy2(src_nb, tmp_path / src_nb.name)
        meta = {
            "id": full_slug,
            "title": full_slug.split("/")[-1],
            "code_file": src_nb.name,
            "language": "python",
            "kernel_type": "notebook",
            "is_private": "true",
            "enable_gpu": "true",
            "enable_tpu": "false",
            "enable_internet": "true",
            "dataset_sources": kcfg.get("gpu_worker_datasets") or [],
            "competition_sources": [],
            "kernel_sources": [],
        }
        (tmp_path / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        res = subprocess.run(["kaggle", "kernels", "push", "-p", str(tmp_path)], capture_output=True, text=True)
        if res.returncode == 0:
            _STATE["gpu_start_t"] = time.time()
            print(f"🚀 [GPU 워커 Start 완료] {full_slug} ← {src_nb.name} (enable_gpu=true, 사유: {reason})")
            return True
        print(f"⚠️ GPU 워커 Start 실패: {(res.stderr or res.stdout)[-300:]}")
        return False


def gpu_pending(wb, rb):
    """v4.31.7: kaggle_gpu로 배정된 대기 요청 수 (LC + 재처리) — GPU 워커를 시작할지"""
    n = 0
    rclone("copyto", _remote("backups/pending_backups.csv"), str(BASE / "backups/pending_backups.csv"))
    rclone("copyto", _remote("backup_status.csv"), str(BASE / "backup_status.csv"))
    rows = wb._read_csv(BASE / "backup_status.csv")
    for r in rb.list_requests(BASE):                   # v4.31.10 (R1·R4): 백업을 기다리던 GPU 요청 — 남은 TASK의 백업을 실제로 받았으면 워커를 다시 켬
        if r["status"] == "waiting" and r.get("kind") in ("track", "shape") and r.get("taken_host") == "kaggle_gpu":
            ok, wait, bad = wb.backup_verdict(BASE, rows, r.get("remaining") or [])
            try:
                since = float(r.get("waiting_t") or 0)
            except (TypeError, ValueError):
                since = 0
            late = bool(wait) and since and time.time() - since > TRACK_GIVEUP_H * 3600
            if ok or bad or late:                      # v4.31.11 (R9): 받은 것뿐 아니라 실패·기한 초과만 남아도 깨워 GPU 워커가 마무리
                n += 1
    for lst in (wb.list_requests(BASE), rb.list_requests(BASE)):
        for r in lst:
            if r["status"] != "pending":
                continue
            if not (BASE / "requests" / "assign" / f"ASSIGN_{r['id']}.json").exists():
                continue
            if wb._assigned_to_me(BASE, r["id"], "kaggle_gpu"):
                n += 1
    return n


def stop_gpu_worker_signal(reason="사용자 취소 또는 마스터 중지"):
    """실행 중인 GPU 워커가 즉시 안전 종료하도록 jobs/STOP_GPU.json 신호 발행"""
    p = BASE / "jobs" / "STOP_GPU.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"time": kst_now().isoformat(), "reason": reason}, ensure_ascii=False), encoding="utf-8")
    rclone("copyto", str(p), _remote("jobs/STOP_GPU.json"))
    print(f"🛑 [GPU 워커 Stop 신호 전송] {reason}")


def read_stop_signal():
    """Drive의 jobs/STOP_MASTER.json 확인 (v4.31.4: 있을 때만 받아 옴 · 없어졌으면 로컬 것도 지움).
    반환: 유효한 정지 정보 dict 또는 None. 기한(until)이 지난 것은 지우고 None.
    주의: 유효한 정지 표시는 Drive에서 지우지 않음 — Apps Script readMasterHold_()가 정지로 보고 깨우지 않게"""
    stop_f = BASE / "jobs" / "STOP_MASTER.json"
    res = rclone("lsf", "--files-only", "--include", "STOP_MASTER.json", _remote("jobs"))
    if res.returncode != 0:
        return None                                   # 확인 못함 → 다음 차례에
    if "STOP_MASTER.json" not in res.stdout:
        if stop_f.exists():
            stop_f.unlink()
        return None
    rclone("copyto", _remote("jobs/STOP_MASTER.json"), str(stop_f))
    try:
        info = json.loads(stop_f.read_text(encoding="utf-8") or "{}")
    except Exception:
        info = {"reason": "STOP_MASTER.json 감지"}
    if _until_passed(info.get("until")) is True:
        r = rclone("deletefile", _remote("jobs/STOP_MASTER.json"))
        if r.returncode != 0:
            print(f"⚠️ 기한 지난 정지 표시를 Drive에서 지우지 못함: {(r.stderr or '')[-200:]}")
        stop_f.unlink(missing_ok=True)
        return None
    return info


def app_settings():
    """config/app_settings.json — CVAT 조직·프로젝트 범위 (v4.31.4, 밀린 과제 #2). 없으면 기본값"""
    st = {"cvat_org": "horti", "cvat_project": ""}
    p = BASE / "config" / "app_settings.json"
    try:
        st.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return st


def routing_cfg():
    try:
        return json.loads((BASE / "config" / "routing.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def gpu_enabled():
    """GPU 워커 쓰기 (routing.json "gpu_worker_enabled": true 일 때만) — v4.31.7부터 실제로 처리함"""
    return routing_cfg().get("gpu_worker_enabled") is True


# ---------------- 요청 파일 (rclone sync 없이) ----------------
def pull_requests(sub):
    """Drive 요청 폴더를 받아 오고, Drive에 없는 로컬 REQ_ 파일은 지움 (다른 작업자가 이름을 바꾼 것)"""
    rclone("copy", _remote(sub), str(BASE / sub))
    res = rclone("lsf", "--files-only", _remote(sub))
    if res.returncode != 0:
        return False
    remote = {x.strip() for x in res.stdout.splitlines() if x.strip()}
    for f in (BASE / sub).glob("REQ_*.json"):
        if f.name not in remote:
            f.unlink()
    return True


def remote_req(sub, rid):
    """v4.32.0: Drive에 있는 그 요청 — (파일 이름 목록, 내용 dict 또는 None). 목록을 못 읽으면 (None, None)"""
    res = rclone("lsf", "--files-only", "--include", f"REQ_{rid}__*", _remote(sub))
    if res.returncode != 0:
        return None, None
    names = sorted(x.strip() for x in res.stdout.splitlines() if x.strip())
    if len(names) != 1:
        return names, None
    tmp = BASE / "jobs" / f"_remote_{names[0]}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    try:
        if rclone("copyto", _remote(f"{sub}/{names[0]}"), str(tmp)).returncode != 0:
            return names, None
        return names, json.loads(tmp.read_text(encoding="utf-8"))
    except Exception:
        return names, None
    finally:
        tmp.unlink(missing_ok=True)


def push_req(before, after, sub, adopt=False):
    """상태를 바꾼 요청 하나만 Drive에 반영: 새 이름 파일 올리고, 옛 이름 파일만 지움.
    v4.32.0 (F3·F14): 올리기 직전 Drive의 요청이 아직 이 세션 것인지 확인 (wb.request_owned) — 아니면 올리지 않고 False.
    adopt=True는 '받는 중' 요청을 넘겨받을 때 (호출한 쪽이 _same_waiting으로 이미 확인함)"""
    import web_bridge as _wb
    if not adopt:
        _, cur = remote_req(sub, before["id"])
        if not _wb.request_owned(cur, before, SESSION_ID):
            print(f"ℹ️ 요청 {before['id']}: Drive에서 이 세션 것이 아님(다른 작업자가 받았거나 끝냄·취소) → 올리지 않음")
            return False
    new = Path(after["_path"])
    rclone("copyto", str(new), _remote(f"{sub}/{new.name}"), quiet=False)
    olds = {Path(x).name for x in [before.get("_path")] + list(before.get("_dups") or []) if x}
    for old in olds - {new.name}:
        rclone("deletefile", _remote(f"{sub}/{old}"))
    return True


def still_pending(req, sub):
    """받기 직전에 Drive에서 다시 확인 — 다른 작업자가 먼저 받았으면 False"""
    res = rclone("lsf", "--files-only", "--include", f"REQ_{req['id']}__*", _remote(sub))
    names = sorted(x.strip() for x in res.stdout.splitlines() if x.strip())
    return res.returncode == 0 and names == [f"REQ_{req['id']}__{req['kind']}__pending.json"]


def mine(wb, req):
    """배정자(Apps Script)가 kaggle_cpu로 배정한 요청만 (배정 파일이 없으면 받지 않음 — v4.31.4)"""
    if not (BASE / "requests" / "assign" / f"ASSIGN_{req['id']}.json").exists():
        return False
    return wb._assigned_to_me(BASE, req["id"], "kaggle_cpu")


def claim(wb, rb, req, scope):
    """요청 하나를 id로 받음 (taken) — 받은 요청 dict, 다른 작업자가 먼저 받았으면 None"""
    sub = "requests" if scope == "lc" else "relabel/requests"
    if not still_pending(req, sub):
        return None
    fields = dict(taken_by="kaggle-cpu-master", taken_session=SESSION_ID, taken_at=kst_now().isoformat(timespec="seconds"),
                  taken_host="kaggle_cpu", by="kaggle-cpu-master", host="kaggle_cpu")
    new = wb.set_status(BASE, req, "taken", **fields) if scope == "lc" else rb.set_status(BASE, req, "taken", **fields)
    if not push_req(req, new, sub):
        return None
    time.sleep(CLAIM_CONFIRM_SEC)                  # v4.32.0: 받은 뒤 다시 읽어 확인 — 거의 동시에 받은 다른 작업자가 있으면 물러남
    names, cur = remote_req(sub, req["id"])
    if names != [Path(new["_path"]).name] or not cur or cur.get("taken_session") != SESSION_ID:
        print(f"ℹ️ 요청 {req['id']}: 다른 작업자가 거의 동시에 받음 → 물러남")
        return None
    return new


CLAIM_CONFIRM_SEC = float(os.environ.get("MASTER_CLAIM_CONFIRM_SEC", "2"))


def release(wb, rb, req, scope, why):
    """정지로 중간에 멈춘 요청을 대기(pending)로 되돌림 — 다른 작업자가 이어서 받을 수 있게"""
    sub = "requests" if scope == "lc" else "relabel/requests"
    f = dict(by="kaggle-cpu-master", summary=why, released_at=kst_now().isoformat(timespec="seconds"))
    back = wb.set_status(BASE, req, "pending", **f) if scope == "lc" else rb.set_status(BASE, req, "pending", **f)
    push_req(req, back, sub)


def note_skip(req, why):
    if req["id"] not in _STATE["skipped"]:
        _STATE["skipped"].add(req["id"])
        print(f"ℹ️ 요청 {req['id']} ({req['kind']}) 받지 않음: {why}")


def _zip_names(ctt, want_ids, live_by_id, scan):
    """export zip 파일 이름: 같은 이름의 TASK가 둘 이상이면 이름 끝에 __TASK ID (v4.31.4 — 같은 경로로 실패하던 문제)"""
    names = {}
    for tid in want_ids:
        t = live_by_id.get(tid)
        n = t["name"] if t else next((x.get("name") for x in scan if str(x.get("task_id")) == str(tid)), "") or f"task_{tid}"
        names[tid] = n
    stems = [ctt.export_file_stem(n) for n in names.values()]
    out = {}
    for tid, n in names.items():
        st = ctt.export_file_stem(n)
        out[tid] = (n, f"{st}__{tid}.zip" if stems.count(st) > 1 else f"{st}.zip")
    return out


def run_cpu_export(ctt, wb, req):
    params = req.get("params") or {}
    want_ids = [int(x) for x in ctt.as_task_ids(req.get("task_ids") or params.get("task_ids") or [])]
    fmt = params.get("format") or "CVAT for images 1.1"
    snap = params.get("snapshot")
    org = params.get("org", app_settings()["cvat_org"])
    folder_name = wb.snapshot_folder(snap) if snap else f"{ctt.stamp()}_cvat_for_images_1_1"
    out_dir = BASE / "exports" / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    rclone("copy", _remote("exports"), str(BASE / "exports"))
    client = ctt.connect("https://app.cvat.ai", os.environ["CVAT_TOKEN"])
    ctt.set_scope(client, org, "")
    live_tasks = ctt.list_tasks(client, limit=5000, project=None)
    live_by_id = {int(t["task_id"]): t for t in live_tasks}

    scan = ctt.scan_exports(BASE / "exports", names=None, log=print)
    pending_path = BASE / "exports" / "pending_exports.csv"
    pending = ctt.read_pending(pending_path)
    server = f"{ctt.whoami(client)}@app.cvat.ai"
    zipn = _zip_names(ctt, want_ids, live_by_id, scan)

    try:
        for i, tid in enumerate(want_ids):
            check_stop()                               # v4.31.4: TASK 사이마다 정지 확인
            _STATE["busy"] = f"export {i + 1}/{len(want_ids)} ({req['id']})"
            t = live_by_id.get(tid)
            t_upd = t.get("updated_utc") if t else None
            tname, fname = zipn[tid]
            dst = out_dir / fname
            ex, ex_st = ctt.best_export(scan, tid, t_upd, kind="images", need_images=False)
            if ex and (ex_st == "최신" or t is None):
                if Path(ex["zip"]).resolve() != dst.resolve():
                    shutil.copy2(ex["zip"], dst)
                note_prefix = "CVAT 삭제됨 → 이전 export 복원 복사" if t is None else "이전 export 복사"
                pending.append({
                    "request_time": ctt.now(), "server": server, "task_id": tid, "task_name": tname,
                    "format": fmt, "images": "", "out_path": str(dst.relative_to(BASE)),
                    "status": "받음", "result_file": str(dst.relative_to(BASE)),
                    "note": f"{note_prefix}: {ex['folder']}/{ex['file']}", "org": org,
                })
            elif t is not None:
                task_obj = client.tasks.retrieve(int(tid))
                ctt.export_labels(task_obj, dst, fmt=fmt, include_images=False)
                pending.append({
                    "request_time": ctt.now(), "server": server, "task_id": tid, "task_name": tname,
                    "format": fmt, "images": "", "out_path": str(dst.relative_to(BASE)),
                    "status": "받음", "result_file": str(dst.relative_to(BASE)),
                    "note": "CPU 마스터 직접 export 완료", "org": org,
                })
    finally:
        ctt.write_pending(pending_path, pending)
        if snap:
            wb.write_snapshot_manifest(BASE, folder_name, log=print)
        rclone("copy", str(out_dir), _remote(f"exports/{folder_name}"))
        rclone("copyto", str(pending_path), _remote("exports/pending_exports.csv"))
        rclone("copy", str(BASE / "logs/shards"), _remote("logs/shards"))


def run_cpu_backup_and_export(ctt, wb, req):
    import cvat_backup as cb
    params = req.get("params") or {}
    tids = ctt.as_task_ids(req.get("task_ids") or params.get("task_ids") or [])
    mode = params.get("mode") or "all"

    cb.HOST = "https://app.cvat.ai"
    cb.AUTH_MODE = "token"
    cb.CREDENTIALS = os.environ["CVAT_TOKEN"]
    cb.BASE = BASE
    cb.ORGANIZATION_SLUG = params.get("org", app_settings()["cvat_org"])
    cb.NAME_QUERY = params.get("query", "")
    cb.MODE = mode
    cb.PREVIEW = False
    cb.UPDATE_BOARD = True
    cb.BOARD_MODE = "file"

    def push():
        rclone("copy", str(BASE / "backups"), _remote("backups"))
        rclone("copyto", str(BASE / "backup_status.csv"), _remote("backup_status.csv"))
        rclone("copy", str(BASE / "reports"), _remote("reports"))
        rclone("copy", str(BASE / "logs/shards"), _remote("logs/shards"))

    status_rows = []
    chunks = [tids[i:i + 5] for i in range(0, len(tids), 5)] if tids else [None]   # v4.31.4: 5개씩, 사이마다 정지 확인
    try:
        for k, chunk in enumerate(chunks):
            check_stop()
            _STATE["busy"] = f"backup {k + 1}/{len(chunks)}묶음 ({req['id']})"
            cb.TASK_IDS = chunk
            status_rows += cb.run_backup() or []
            push()
    finally:
        push()

    _STATE["last_backup_rows"] = status_rows          # v4.31.9 (F1): 호출자가 TASK별로 판정
    if params.get("export_reviewed", True) and status_rows:
        reviewed_ids = [int(r["task_id"]) for r in status_rows
                        if ctt.is_reviewed(r.get("task_name", ""), "vf") and r.get("in_cvat") == "예"]
        if reviewed_ids:
            print(f"[*] [자동 결합] 검토 완료 TASK {len(reviewed_ids)}건 → 라벨 Export(CVAT for images 1.1) 연쇄 실행")
            run_cpu_export(ctt, wb, {"id": f"{req['id']}_autoex", "task_ids": reviewed_ids,
                                     "params": {"mode": mode, "format": "CVAT for images 1.1", "images": False, "org": cb.ORGANIZATION_SLUG}})


ULD_REMOTE = os.environ.get("ULD_REMOTE") or "gdrive,root_folder_id=root:CVAT_UpLoader"   # 0번 셀 ULD_REMOTE와 같게 (읽기만)
ULD_TMP = Path(tempfile.gettempdir()) / "_uld_registry"                                     # 작업 폴더 밖 (Drive로 올라가지 않음)


def uld_info(wb):
    """v4.31.9 (F16): ULD 기록을 읽기만 해서 {'index', 'lineage'} — 실패하면 빈 것 (앱에 ULD 표시만 빠짐)"""
    try:
        ULD_TMP.mkdir(parents=True, exist_ok=True)
        rclone("copy", ULD_REMOTE + ("" if ULD_REMOTE.endswith(":") else "/") + "registry/tasks", str(ULD_TMP), "--include", "*.json")
        return wb.uld_scan(ULD_TMP) if hasattr(wb, "uld_scan") else {"index": {}, "lineage": {}}
    except Exception as e:
        print(f"(ULD 기록을 읽지 못함 — 앱에 ULD 표시만 빠짐: {e})")
        return {"index": {}, "lineage": {}}


def aggregate_and_sync_state(ctt, wb, rb):
    """샤드 병합 + 검토 수정량 + web/state.json & relabel/state.json 갱신 (v4.31.4: sync 없이)"""
    _STATE["busy"] = "상태 파일(state.json) 및 샤드 통합 갱신 중"
    sh = BASE / "logs/shards"
    rclone("copy", _remote("logs/shards"), str(sh))
    rclone("copy", _remote("relabel/tasks"), str(BASE / "relabel/tasks"))
    rclone("copy", _remote("exports"), str(BASE / "exports"), "--include", "*.csv", "--include", "*/*.zip")

    before = {str(p.relative_to(sh)) for p in sh.rglob("*") if p.is_file()}
    compacted = ctt.compact_shards(BASE, min_age_h=24, min_files=8, log=print)
    if compacted:
        after = {str(p.relative_to(sh)) for p in sh.rglob("*") if p.is_file()}
        rclone("copy", str(sh), _remote("logs/shards"))
        for rel in sorted(before - after):              # 합친 옛 샤드만 지움 (24시간 지난 것만 합치므로 다른 세션의 쓰는 중 파일은 아님)
            rclone("deletefile", _remote(f"logs/shards/{rel}"))

    st_cfg = app_settings()
    client = ctt.connect("https://app.cvat.ai", os.environ["CVAT_TOKEN"])
    scope = ctt.set_scope(client, st_cfg["cvat_org"], st_cfg["cvat_project"])
    wb.repair_pending(BASE)
    wb.settle(BASE, ("backup", "export"), who="kaggle-cpu-master")
    tasks, cat = ctt.list_tasks_all(client, limit=5000)

    rclone("copyto", _remote("status/cvat_tasks.json"), str(BASE / "status/cvat_tasks.json"))   # v4.31.9 (F16): 사라진 TASK
    uld = uld_info(wb)
    v_lines = rclone("lsf", "-R", "--files-only", _remote("videos")).stdout.splitlines()
    b_lines = rclone("lsf", "-R", "--files-only", _remote("backups")).stdout.splitlines()
    vn, bn = wb.media_names(BASE, remote_videos=v_lines, remote_backups=b_lines)

    # v4.31.13 (R15): update_tracked가 쓰는 '사라짐' 이력은 모아 두었다가 sync_task_record로 그 TASK 파일만 고쳐 올림
    gone_notes = []
    _orig_add = rb.add_history
    rb.add_history = lambda base, tid, **entry: gone_notes.append((str(tid), entry))
    try:
        tracked = rb.update_tracked(BASE, tasks)
    finally:
        rb.add_history = _orig_add
    retry = [tid for tid, entry in gone_notes if not sync_task_record(tid, lambda tid=tid, entry=entry: _history_once(rb, tid, **entry))]
    if retry:                                      # 못 쓴 것은 gone_at을 지워 다음 갱신 때 다시 적게 함
        for tid in retry:
            (tracked.get(tid) or {}).pop("gone_at", None)
        rb._write_json(rb.root(BASE) / "tracked.json", tracked)
    rb.build_state(BASE, tracked=tracked, media=(vn, bn), server=f"{ctt.whoami(client)}@app.cvat.ai", scope_text=ctt.scope_text(scope),
                   uld=uld["index"], replaced=uld["lineage"])

    snaps = wb.snapshots(BASE, refresh=True, log=None)
    stats = wb.compute_stats(BASE, tasks, client=client, cvat_max=25, log=None)
    corr = wb.compute_corrections(BASE, tasks, reviewed_rule="vf", max_new=80, log=None)
    st = wb.build_state(
        BASE, tasks, operator="kaggle-cpu-master", app_version=ctt.__version__,
        reviewed_rule="vf", val_rule="plant=3|plant=7", server=f"{ctt.whoami(client)}@app.cvat.ai",
        video_stems=vn, backup_bases=bn, stats=stats, snaps=snaps, scope=scope, catalog=cat, corrections=corr,
        uld=uld["index"], replaced=uld["lineage"]
    )
    wb.write_state(BASE, st)

    for done_f in (BASE / "jobs").glob("DONE_*.json"):
        done_f.unlink()
        rclone("deletefile", _remote(f"jobs/{done_f.name}"))

    # worker 파일(다른 작업자 것)과 요청 폴더는 여기서 올리지 않음 — 덮어쓰기·되살리기 방지
    rclone("copy", str(BASE / "web"), _remote("web"), "--exclude", "worker*.json", "--exclude", "*.tmp")
    rclone("copy", str(BASE / "relabel"), _remote("relabel"), "--exclude", "requests/**", "--exclude", "tasks/**",     # v4.31.13 (R15): TASK 기록은 올리지 않음
           "--exclude", "WORKER*.json", "--exclude", "*.tmp")
    _STATE["dirty"] = False
    _STATE["last_refresh"] = time.time()
    _STATE["busy"] = "대기 중"
    print(f"✅ [{kst_now().strftime('%H:%M:%S')}] 상태 취합 및 Drive 반영 완료 (TASK {len(tasks)}개)")


def has_approved_night_work(wb, rb):
    """야간: kaggle_cpu로 배정되고 야간 승인된(배정 파일이 awaiting이 아닌) 대기 요청이 있는지"""
    for r in wb.list_requests(BASE) + rb.list_requests(BASE):
        if r.get("status") == "pending" and (r["kind"] in CPU_DIRECT_KINDS or r["kind"] in AA_DIRECT_KINDS) and mine(wb, r):
            return True
    return False


def handle_lc(ctt, wb, rb, req, started_str):
    kind = req["kind"]
    got = claim(wb, rb, req, "lc")
    if got is None:
        note_skip(req, "다른 작업자가 먼저 받음")
        return
    _STATE["busy"] = f"LC {kind} 처리 중 ({req['id']})"
    send_heartbeat_once(wb, rb, started_str)
    try:
        if kind == "backup":
            run_cpu_backup_and_export(ctt, wb, got)
        elif kind == "export":
            run_cpu_export(ctt, wb, got)
        done = wb.finish(BASE, [got["id"]], ok=True, summary=f"CPU 마스터 {kind} 완료", job_id=SESSION_ID, who="kaggle-cpu-master")
    except StopRequested as e:
        release(wb, rb, got, "lc", f"CPU 마스터 정지로 중간에 멈춤 — 대기로 되돌림 ({e})")
        return
    except Exception as e:
        done = wb.finish(BASE, [got["id"]], ok=False, summary=f"오류: {e}", job_id=SESSION_ID, who="kaggle-cpu-master")
    for d in done:
        push_req(got, d, "requests")
    _STATE["dirty"] = True


def backup_verdict(wb, status_rows, tids):
    """v4.31.10 (R1): 판정은 scripts의 wb.backup_verdict (30번 셀과 같은 기준 — '최신'이고 파일이 있어야 받음)"""
    return wb.backup_verdict(BASE, status_rows, tids)


TRACK_GIVEUP_H = float(os.environ.get("MASTER_TRACK_GIVEUP_H", "6"))   # 30번 셀 RL_BACKUP_GIVEUP_H와 같게
BK_POLL_SEC = int(os.environ.get("MASTER_BK_POLL_SEC", "300"))
BK_GIVEUP_H = float(os.environ.get("MASTER_BK_GIVEUP_H", "24"))


def _fetch_remote(rel, dest):
    """Drive 파일 하나 받기 → 'ok' · 'missing'(목록이 성공했고 없음, 또는 폴더 자체가 없음) · 'fail'"""
    d, name = rel.rsplit("/", 1)
    ls = rclone("lsf", "--files-only", "--include", name, _remote(d))
    if ls.returncode != 0:
        return "missing" if "directory not found" in str(ls.stderr or "").lower() else "fail"
    if name not in {x.strip() for x in (ls.stdout or "").splitlines()}:
        return "missing"
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    got = rclone("copyto", _remote(rel), str(dest))
    return "ok" if got.returncode == 0 and Path(dest).is_file() else "fail"


def _put_remote(rel, src):
    return rclone("copyto", str(src), _remote(rel)).returncode == 0


def sync_task_record(tid, mutate):
    """v4.31.13 (R14·R15) → v4.32.0: 공용 rb.sync_record (Colab 30번 셀·GPU 워커와 같은 길) — 최신본 받기 → mutate() → 그 파일만 올림"""
    import relabel_bridge as _rb
    return _rb.sync_record(BASE, tid, mutate, _fetch_remote, _put_remote)


def _history_once(rb, tid, **entry):
    """같은 요청·종류·상태의 이력이 이미 있으면 다시 쓰지 않음 (실패 뒤 다시 할 때 두 번 적히지 않게)"""
    rec = rb.task_record(BASE, tid)
    keys = ("kind", "status", "request", "note")
    if any(all(h.get(k) == entry.get(k) for k in keys if k in entry) for h in rec.get("history") or []):
        return
    rb.add_history(BASE, tid, **entry)


def aa_worker_alive():
    """v4.31.11 (R6): 30번 셀 작업자(relabel/WORKER.json)나 GPU 워커(relabel/WORKER_gpu.json)가 살아 있는지"""
    return _STATE.get("aa_peer") is not None or _STATE.get("aa_gpu_peer") is not None


def _same_waiting(r):
    """v4.31.11 (R6): 결과를 쓰기 직전에 Drive의 요청을 다시 읽어, 처음 읽은 것과 같을 때만 True (그 사이 다른 작업자가 바꿨으면 손대지 않음)"""
    name = Path(r["_path"]).name
    res = rclone("lsf", "--files-only", "--include", f"REQ_{r['id']}__*", _remote("relabel/requests"))
    if res.returncode != 0 or sorted(x.strip() for x in res.stdout.splitlines() if x.strip()) != [name]:
        return False
    tmp = BASE / "jobs" / f"_fresh_{name}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    if rclone("copyto", _remote(f"relabel/requests/{name}"), str(tmp)).returncode != 0 or not tmp.exists():
        return False
    try:
        cur = json.loads(tmp.read_text(encoding="utf-8"))
    except Exception:
        return False
    finally:
        tmp.unlink(missing_ok=True)
    keys = ("status", "remaining", "results", "result", "taken_session", "history")   # history = 상태를 바꿀 때마다 늘어남 (세대)
    return all(cur.get(k) == r.get(k) for k in keys)


def poll_waiting_backups(ctt, wb, rb):
    """v4.31.10 (R4): '받는 중'(waiting) AA 요청의 백업을 CPU 마스터가 받음 — GPU 워커가 꺼져 있어도 누군가 받게.
    백업 요청은 여기서 끝내고, track·shape 요청은 받은 뒤 GPU 워커를 깨워(gpu_pending) 마저 하게 함. 30번 셀이 살아 있으면 그쪽이 함"""
    if aa_worker_alive() or time.time() - _STATE.get("bk_poll_t", 0) < BK_POLL_SEC:
        return 0
    _STATE["bk_poll_t"] = time.time()
    reqs = [r for r in rb.waiting_requests(BASE) if r.get("remaining")]
    need = sorted({int(t) for r in reqs for t in r.get("remaining") or []})
    if not need:
        return 0
    rclone("copyto", _remote("backups/pending_backups.csv"), str(BASE / "backups/pending_backups.csv"))
    rclone("copyto", _remote("backups/backup_index.csv"), str(BASE / "backups/backup_index.csv"))
    _STATE["busy"] = f"받는 중 백업 확인 {len(need)}개"
    _STATE["last_backup_rows"] = []
    run_cpu_backup_and_export(ctt, wb, {"id": "bkpoll", "task_ids": need, "params": {"mode": "download", "export_reviewed": False}})
    ok, wait, bad = wb.backup_verdict(BASE, _STATE.get("last_backup_rows"), need)
    print(f"[*] 받는 중 백업 확인: 받음 {len(ok)} · 받는 중 {len(wait)} · 실패 {len(bad)}")
    for r in reqs:
        if r.get("kind") != "backup":
            continue                               # track·shape → gpu_pending이 받은 것을 보고 GPU 워커를 깨움
        rem = [str(t) for t in r.get("remaining") or []]
        got = [t for t in rem if t in ok]
        left = [t for t in rem if t in wait]
        lost = [t for t in rem if t in bad]
        try:
            since = float(r.get("waiting_t") or 0) or time.time()
        except (TypeError, ValueError):
            since = time.time()
        late = bool(left) and time.time() - since > BK_GIVEUP_H * 3600
        if not got and not lost and not late:
            continue
        _STATE["aa_peer"] = _peer("relabel/WORKER.json", SESSION_ID)          # v4.31.11 (R6): 받는 사이 작업자가 켜졌으면 손대지 않음
        _STATE["aa_gpu_peer"] = _peer("relabel/WORKER_gpu.json", SESSION_ID)
        live = {w.get("session") for w in (_STATE["lc_peer"], _STATE["aa_peer"], _STATE["aa_gpu_peer"]) if w}
        if aa_worker_alive() or not _same_waiting(r) or not wb.may_adopt(r, SESSION_ID, live):
            print(f"ℹ️ {r['id']}: 다른 작업자가 있거나 요청이 바뀜 → 이번 결과는 쓰지 않음")
            continue
        adopt = {} if r.get("taken_session") == SESSION_ID else {"taken_session": SESSION_ID, "taken_host": "kaggle_cpu",
                                                                  "adopted_from": r.get("taken_session") or ""}   # v4.32.0: 넘겨받음을 기록
        # v4.31.13 (R14): TASK 기록은 sync_task_record로만 — 하나라도 실패하면 이 요청은 이번에 끝내지 않고 다음 확인 때 다시
        if not all([sync_task_record(t, lambda t=t: _history_once(rb, int(t), kind="backup", status="받음", request=r["id"], who="kaggle-cpu-master"))
                    for t in got]):
            print(f"ℹ️ {r['id']}: TASK 기록을 쓰지 못함 → 요청은 '받는 중'으로 두고 다음 확인 때 다시")
            continue
        prev = {str(x.get("task_id")): x for x in r.get("results") or []}
        for t in got:
            prev[t] = {"task_id": t, "status": "받음", "note": ""}
        for t in lost:
            prev[t] = {"task_id": t, "status": "실패", "note": "백업이 만들어지지 않음"}
        for t in (left if late else []):
            prev[t] = {"task_id": t, "status": "포기 (준비 안 됨)", "note": f"{BK_GIVEUP_H:g}시간 넘게 준비 안 됨"}
        res = list(prev.values())
        txt = (str(r.get("result", "")) + f" · 받음 {len(got)}" + (f" · 실패 {len(lost)}" if lost else "") + (" · 포기" if late else ""))[:500]
        if left and not late:
            fin = rb.set_status(BASE, r, "waiting", by="kaggle-cpu-master", remaining=[int(t) for t in left], waiting_t=since, results=res, result=txt, **adopt)
        else:                                      # v4.31.11 (R7): 누적 결과에 실패·포기가 하나라도 있으면 실패
            fin = rb.set_status(BASE, r, "failed" if wb.failed_results(res) else "done", by="kaggle-cpu-master",
                                remaining=[], results=res, result=txt, done_at=kst_now().isoformat(timespec="seconds"), **adopt)
        push_req(r, fin, "relabel/requests", adopt=True)
        _STATE["dirty"] = True
    return len(ok)                                 # v4.31.12 (R11): relabel/tasks 폴더를 통째로 올리지 않음


def handle_aa(ctt, wb, rb, req, started_str):
    kind = req["kind"]
    got = claim(wb, rb, req, "aa")
    if got is None:
        note_skip(req, "다른 작업자가 먼저 받음")
        return
    _STATE["busy"] = f"AA {kind} 처리 중 ({req['id']})"          # v4.31.4: AA 처리 중에도 busy 갱신
    send_heartbeat_once(wb, rb, started_str)
    try:
        tids = ctt.as_task_ids(got.get("task_ids") or [])
        if kind in ("hide", "unhide"):
            rclone("copyto", _remote("relabel/tracked.json"), str(BASE / "relabel/tracked.json"))   # 최신본에 고침
            rb.set_hidden(BASE, tids, kind == "hide")
            rclone("copyto", str(BASE / "relabel/tracked.json"), _remote("relabel/tracked.json"))
        elif kind == "discard":
            bad = [t for t in tids if not sync_task_record(t, lambda t=t: rb.set_pending_track(BASE, t, None))]   # v4.31.13
            if bad:
                raise RuntimeError(f"TASK 기록을 쓰지 못함 {bad} → 다시 요청하세요")
        elif kind == "backup":
            _STATE["last_backup_rows"] = []
            run_cpu_backup_and_export(ctt, wb, got)
            ok, wait, bad = backup_verdict(wb, _STATE.get("last_backup_rows"), tids)
            res = ([{"task_id": t, "status": "받음", "note": ""} for t in ok] + [{"task_id": t, "status": "받는 중", "note": "CVAT 준비 중"} for t in wait]
                   + [{"task_id": t, "status": "실패", "note": "백업이 만들어지지 않음"} for t in bad])
            txt = f"백업 받음 {len(ok)} · 받는 중 {len(wait)} · 실패 {len(bad)}"
            if wait:                                   # 남은 것은 '받는 중' — 30번 셀 작업자가 준비되는 대로 받음
                fin = rb.set_status(BASE, got, "waiting", by="kaggle-cpu-master", remaining=[int(t) for t in wait], results=res, result=txt,
                                    waiting_t=time.time())
            else:
                fin = rb.set_status(BASE, got, "done" if ok else "failed", by="kaggle-cpu-master", results=res, result=txt,
                                    done_at=kst_now().isoformat(timespec="seconds"))
            push_req(got, fin, "relabel/requests")
            _STATE["dirty"] = True
            return
        fin = rb.set_status(BASE, got, "done", by="kaggle-cpu-master", result=f"CPU 마스터 {kind} 완료")
    except StopRequested as e:
        release(wb, rb, got, "aa", f"CPU 마스터 정지로 중간에 멈춤 — 대기로 되돌림 ({e})")
        return
    except Exception as e:
        fin = rb.set_status(BASE, got, "failed", by="kaggle-cpu-master", result=f"오류: {e}")
    push_req(got, fin, "relabel/requests")
    _STATE["dirty"] = True                         # v4.31.13: relabel/tasks 폴더를 통째로 올리지 않음 (TASK 기록은 sync_task_record로만)


def main():
    ensure_environment()
    setup_credentials()
    print(f"[*] Kaggle CPU 상주 마스터 v{__version__} 기동 (SESSION_ID={SESSION_ID}, KST={kst_now().strftime('%Y-%m-%d %H:%M:%S')})")
    initial_pull()

    scripts_path = str(BASE / "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)

    import cvat_task_tools as ctt
    import web_bridge as wb
    import relabel_bridge as rb

    ctt.set_shard(SESSION_ID)
    started_str = kst_now().strftime("%Y-%m-%d %H:%M:%S")

    send_heartbeat_once(wb, rb, started_str)
    print("✅ 첫 번째 생존 신호 전송 완료" + (" (31번 셀 작업자가 켜져 있어 web/worker_cpu_master.json에만 씀)" if _STATE["lc_peer"] else ""))
    threading.Thread(target=heartbeat_loop, args=(started_str,), daemon=True).start()

    global START_TS
    START_TS = time.time()                         # v4.31.13: 실행 한도는 준비(받기·첫 생존 신호)가 끝난 뒤부터 셈
    stop_info = None
    try:
        while (time.time() - START_TS) < (MAX_RUN_HOURS * 3600):
            pull_requests("requests")
            pull_requests("relabel/requests")
            rclone("copy", _remote("config"), str(BASE / "config"))     # 배정 규칙이 바뀌면 바로 따름

            stop_info = _STATE["stop_req"] or read_stop_signal()
            if stop_info is not None:
                print(f"🛑 [{kst_now().strftime('%H:%M:%S')}] 정지 표시(STOP_MASTER.json) → 안전 종료 (사유: {stop_info.get('reason')})")
                break

            if not is_daytime_kst() and not has_approved_night_work(wb, rb):
                print(f"🌙 [{kst_now().strftime('%H:%M')}] 주간(08:00~19:00) 끝 · 야간 승인 작업 없음 → 안전 종료")
                break

            # 1) LC 요청 — kaggle_cpu로 배정된 것만, id로 받기
            for req in wb.list_requests(BASE):
                if req["status"] != "pending" or _STATE["stop_req"]:
                    continue
                if not mine(wb, req):
                    continue
                kind = req["kind"]
                if kind in CPU_DIRECT_KINDS:
                    handle_lc(ctt, wb, rb, req, started_str)
                elif kind in GPU_KINDS:
                    note_skip(req, "GPU 작업은 kaggle_gpu 배정으로 GPU 워커가 받음 (이 요청은 CPU로 배정됨)")
                else:
                    note_skip(req, "CPU 마스터가 처리하지 않는 종류 (31번 셀이 처리)")

            # 2) AA 요청 — 숨기기·다시 보이기·새로 고침(tracked.json·상태를 고침)은 취합자만 (배정과 관계없이, v4.32.0)
            #    그 밖은 30번 셀 작업자가 살아 있으면 받지 않음
            for req in rb.list_requests(BASE):
                if req["status"] != "pending" or _STATE["stop_req"]:
                    continue
                kind = req["kind"]
                if kind in AA_STATE_KINDS:
                    if _STATE["owner"]:
                        handle_aa(ctt, wb, rb, req, started_str)
                    continue
                if _STATE["aa_peer"] is None and mine(wb, req):
                    if kind in AA_DIRECT_KINDS:
                        handle_aa(ctt, wb, rb, req, started_str)
                    else:
                        note_skip(req, "CPU 마스터가 처리하지 않는 종류 (30번 셀이 처리)")

            # 2.4) v4.31.10 (R4): 받는 중 백업 — 30번 셀이 꺼져 있으면 CPU 마스터가 받음 (받으면 아래에서 GPU 워커를 깨움)
            if not _STATE["stop_req"]:
                try:
                    poll_waiting_backups(ctt, wb, rb)
                except StopRequested:
                    pass
                except Exception as e:
                    print(f"⚠️ 받는 중 백업 확인 실패 (다음 차례에 다시): {e}")

            # 2.5) v4.31.7: kaggle_gpu로 배정된 GPU 요청 → GPU 워커 시작 (워커가 직접 받고, 할 일이 없으면 스스로 끝남)
            if gpu_enabled() and not _STATE["stop_req"]:
                n_gpu = gpu_pending(wb, rb)
                if n_gpu:
                    _STATE["busy"] = f"GPU 요청 {n_gpu}건 → GPU 워커"
                    start_gpu_worker_if_needed(reason=f"GPU 요청 {n_gpu}건")

            # 3) 상태 갱신 — v4.32.0 (F3·F14): 취합자만. 내 작업 뒤 · GPU 완료 표시 · 다른 작업자의 DIRTY 표시 · 15분마다
            #    취합자가 아니면 상태 파일을 쓰지 않고 DIRTY 표시만 남김
            done_markers = list((BASE / "jobs").glob("DONE_*.json"))
            if _STATE["owner"]:
                dirty_m = dirty_markers()
                periodic = time.time() - _STATE["last_refresh"] > 900
                if _STATE["dirty"] or done_markers or dirty_m or periodic:
                    try:
                        aggregate_and_sync_state(ctt, wb, rb)
                        for f in dirty_m:
                            f.unlink(missing_ok=True)
                            rclone("deletefile", _remote(f"jobs/{f.name}"))
                    except Exception as e:
                        print(f"⚠️ 상태 갱신 실패 (다음 차례에 다시): {e}")
                        _STATE["last_refresh"] = time.time()
            elif _STATE["dirty"]:
                mk = wb.dirty_mark(BASE, SESSION_ID, why="kaggle-cpu-master 작업 뒤")
                if rclone("copyto", str(mk), _remote(f"jobs/{mk.name}")).returncode == 0:
                    _STATE["dirty"] = False

            _STATE["busy"] = "대기 중"
            for _ in range(POLL_SEC):
                if _STATE["stop_req"]:
                    break
                time.sleep(1)
    finally:
        _STATE["stop"] = True
        if stop_info is not None and stop_info.get("stop_gpu", True) and gpu_enabled():
            stop_gpu_worker_signal(reason=f"마스터 종료 연동 ({stop_info.get('reason', '원격 종료')})")
        try:
            send_heartbeat_once(wb, rb, started_str, stopping=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
