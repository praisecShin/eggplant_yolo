"""v4.33 2a 시험 — 배포 묶음(build_deploy), 뿌리 노트북(검증·불러오기), 마스터 본체(master_main).
실제 Drive·Kaggle·CVAT에 접속하지 않음. 실행: python3 tests/test_master_main_433.py drive
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(ROOT / "dev_tools"))
import access
import arbiter as A
import arb_io as IO
import master_main as MM
import build_deploy as BD

ok = True


def check(c, msg):
    global ok
    print(("✅ " if c else "❌ ") + msg)
    ok &= bool(c)


TMP = Path(tempfile.mkdtemp(prefix="mm433_"))
GPU_NB = TMP / "gpu.ipynb"
GPU_NB.write_text('{"cells": []}', encoding="utf-8")

# ======================================================== 배포 묶음
info = BD.build(TMP / "dep", "kuser", test=True, gpu_notebook=GPU_NB)
dep = TMP / "dep"
man = json.loads((dep / "manifest.json").read_text())
nb_b = (dep / info["master_notebook"]).read_bytes()
check(info["master_notebook"] == "eggplant_cpu_master_test.ipynb" and info["master_slug"] == "kuser/eggplant-cpu-master-test",
      "시험 묶음: 노트북 이름 끝 _test, 주소 끝 -test")
check(BD.sha256((dep / "manifest.json").read_bytes()) == info["manifest_sha256"] and info["manifest_sha256"] in nb_b.decode(),
      "③ 목록 해시가 마스터 노트북에 고정됨")
check(BD.sha256(nb_b) == info["master_nb_sha256"], "④ Keeper용 해시 = 마스터 노트북 파일의 해시")
check(info["master_notebook"] not in man["files"] and "manifest.json" not in man["files"]
      and "scripts/master_main.py" in man["files"] and "kernel-metadata-gpu-worker.json" in man["files"],
      "② 목록에 마스터 노트북·목록 자신은 없고, scripts·GPU 실행 설정은 있음 (한 방향 사슬)")
gm = json.loads((dep / "kernel-metadata-gpu-worker.json").read_text())
km = json.loads((dep / "kernel-metadata.json").read_text())
check(gm["id"] == "kuser/eggplant-gpu-worker-test" and gm["enable_gpu"] == "true" and km["code_file"] == info["master_notebook"]
      and km["enable_gpu"] == "false", "실행 설정: GPU 작업자 -test·GPU 켬, 마스터는 Keeper가 읽는 kernel-metadata.json")
src = "".join(json.loads(nb_b)["cells"][0]["source"])
check("RESERVED_MODULES = [" in src and "'arbiter'" in src and "'kaggle_cpu_master'" in src,
      "묶음이 가지 앱 모듈 이름(지금 scripts + 옛 이름)을 뿌리 노트북에 고정함 (V3)")
check('TEST = True' in src and 'REMOTE = "gdrive_test:"' in src and 'ADMIN_REMOTE = "gadmin_test:"' in src,
      "시험 노트북은 시험 연결(gdrive_test·gadmin_test)을 가리킴")
info_p = BD.build(TMP / "dep_p", "kuser", test=False, gpu_notebook=GPU_NB)
src_p = "".join(json.loads((TMP / "dep_p" / info_p["master_notebook"]).read_bytes())["cells"][0]["source"])
check('TEST = False' in src_p and 'REMOTE = "gdrive:"' in src_p and info_p["master_slug"].endswith("/eggplant-cpu-master"),
      "운영 묶음은 운영 연결·운영 주소")
check(not any(k in json.dumps(info) for k in ("token", "KAGGLE_KEY", "CVAT_TOKEN")), "묶음 정보에 비밀 값 칸 없음")

# ======================================================== 뿌리 노트북
NS = {"__name__": "boot_test"}
exec(compile(src, "master_nb", "exec"), NS)


def fake_rclone(root):
    def r(*a):
        if a[0] == "copy":
            shutil.copytree(root, a[2], dirs_exist_ok=True)
            return subprocess.CompletedProcess(a, 0, b"", b"")
        return subprocess.CompletedProcess(a, 1, b"", b"")
    return r


got = NS["fetch_deploy"]("gadmin_test:", fake_rclone(dep))
check(set(got["files"]) == set(man["files"]) and got["files"]["scripts/arbiter.py"] == (dep / "scripts/arbiter.py").read_bytes(),
      "뿌리: 목록 해시 → 파일별 해시 확인 뒤 검증한 바이트를 돌려줌")
bad = TMP / "bad1"
shutil.copytree(dep, bad)
(bad / "scripts" / "arbiter.py").write_text("print('바뀜')")
try:
    NS["fetch_deploy"]("gadmin_test:", fake_rclone(bad)); check(False, "파일 변조")
except NS["BootStop"] as e:
    check("arbiter.py" in str(e), "뿌리: scripts 하나가 바뀌면 실행하지 않음")
bad2 = TMP / "bad2"
shutil.copytree(dep, bad2)
m2 = json.loads((bad2 / "manifest.json").read_text())
m2["files"]["scripts/arbiter.py"] = BD.sha256(b"print(1)")
(bad2 / "manifest.json").write_text(json.dumps(m2))
(bad2 / "scripts" / "arbiter.py").write_text("print(1)")
try:
    NS["fetch_deploy"]("gadmin_test:", fake_rclone(bad2)); check(False, "목록 변조")
except NS["BootStop"] as e:
    check("고정값" in str(e), "뿌리: 목록과 파일을 함께 바꿔도 목록 해시가 고정값과 달라 실행하지 않음")
(TMP / "bad3").mkdir()
try:
    NS["fetch_deploy"]("gadmin_test:", fake_rclone(TMP / "bad3")); check(False, "목록 없음")
except NS["BootStop"]:
    check(True, "뿌리: 목록이 없으면 실행하지 않음")
one_line = ("[gdrive] type = drive scope = drive token = {\"access_token\":\"x\",\"expiry\":\"2026\"} root_folder_id = AAA "
            "[gadmin] type = drive token = {\"access_token\":\"x\"} root_folder_id = BBB "
            "[gdrive_test] type = drive token = {\"access_token\":\"x\"} root_folder_id = CCC")
conf = NS["parse_rclone_conf"](one_line)
check("[gdrive]" in conf and "[gadmin]" in conf and "[gdrive_test]" in conf and "root_folder_id = BBB" in conf
      and conf.count("token = {") == 3, "한 줄로 눌린 RCLONE_CONF에서 연결 여럿을 되살림")
check("[gdrive]" in NS["parse_rclone_conf"]("type = drive token = {\"a\":1} root_folder_id = Z"),
      "섹션 머리 없는 옛 형식은 gdrive로")
# 검증한 바이트로만 불러오는지: 디스크의 scripts를 경로에 두지 않은 새 프로세스에서
probe = TMP / "probe.py"
probe.write_text(f"""
import json, shutil, subprocess, sys
NS = {{"__name__": "x"}}
exec(compile(open({str(TMP / 'nb.py')!r}, encoding='utf-8').read(), 'nb', 'exec'), NS)
def r(*a):
    shutil.copytree({str(dep)!r}, a[2], dirs_exist_ok=True)
    return subprocess.CompletedProcess(a, 0, b'', b'')
d = NS['fetch_deploy']('gadmin_test:', r)
sys.meta_path.insert(0, NS['VerifiedFinder'](d['files']))
import master_main, arbiter, worker_cpu
print(json.dumps([master_main.__file__, arbiter.__file__, worker_cpu.__file__, master_main.VERSION]))
""", encoding="utf-8")
(TMP / "nb.py").write_text(src, encoding="utf-8")
pr = subprocess.run([sys.executable, "-I", str(probe)], capture_output=True, text=True, cwd=str(TMP))
outj = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.returncode == 0 else None
check(outj is not None and all(x.startswith("deploy:scripts/") for x in outj[:3]),
      "뿌리: scripts 모듈은 검증한 바이트에서만 불러옴 (디스크 경로 없음)" + ("" if outj else " — " + pr.stderr[-300:]))

# U2: import 경계 — 목록 밖 모듈, 디스크의 같은 이름, 먼저 불린 모듈
u2 = TMP / "u2"
(u2 / "disk").mkdir(parents=True)
(u2 / "disk" / "b14_unlisted.py").write_text("SOURCE = 'disk without manifest'\n")
(u2 / "disk" / "arbiter.py").write_text("SOURCE = 'disk arbiter'\n")
(u2 / "disk" / "preloaded_x.py").write_text("SOURCE = 'preloaded'\n")
probe2 = u2 / "probe2.py"
probe2.write_text(f"""
import json, sys
sys.path.insert(0, {str(u2 / 'disk')!r})
import preloaded_x
NS = {{"__name__": "x"}}
exec(compile(open({str(TMP / 'nb.py')!r}, encoding='utf-8').read(), 'nb', 'exec'), NS)
files = {{"scripts/entry.py": b"import b14_unlisted\\n", "scripts/arbiter.py": b"SOURCE = 'verified arbiter'\\n"}}
NS['lock_imports'](files)
out = {{}}
import arbiter
out['arbiter'] = arbiter.SOURCE
out['preloaded_gone'] = 'preloaded_x' not in sys.modules
try:
    import entry
    out['entry'] = 'imported'
except ImportError as e:
    out['entry'] = 'refused'
try:
    import preloaded_x
    out['preloaded'] = 'reimported'
except ImportError:
    out['preloaded'] = 'refused'
import json as _j, hashlib
out['stdlib'] = bool(hashlib.sha256)
print(_j.dumps(out))
""", encoding="utf-8")
pr2 = subprocess.run([sys.executable, str(probe2)], capture_output=True, text=True, cwd=str(u2 / "disk"))
o2 = json.loads(pr2.stdout.strip().splitlines()[-1]) if pr2.returncode == 0 and pr2.stdout.strip() else {}
check(o2.get("arbiter") == "verified arbiter", "U2: 디스크·현재 폴더에 같은 이름 파일이 있어도 검증한 바이트를 씀" + ("" if o2 else " — " + pr2.stderr[-300:]))
check(o2.get("entry") == "refused", "U2: 검증한 모듈이 목록 밖 모듈을 import하면 거절 (디스크에서 찾지 않음)")
check(o2.get("preloaded_gone") and o2.get("preloaded") == "refused", "U2: 허락된 폴더 밖에서 먼저 불린 모듈은 버리고 다시 불러오지 못함")
check(o2.get("stdlib") is True, "U2: 표준 라이브러리는 그대로 씀")
fake_sp = TMP / "u3" / "site-packages"
fake_sp.mkdir(parents=True)
(fake_sp / "b15_unlisted.py").write_text("SOURCE = 'unverified fake package'\n")
import sysconfig as _sc
real_sp = Path(_sc.get_paths()["purelib"])
probe3 = TMP / "u3" / "probe3.py"
probe3.write_text(f"""
import json, sys
sys.path.insert(0, {str(fake_sp)!r})
NS = {{"__name__": "x"}}
exec(compile(open({str(TMP / 'nb.py')!r}, encoding='utf-8').read(), 'nb', 'exec'), NS)
files = {{"scripts/entry.py": b"import b15_unlisted\\nSOURCE = b15_unlisted.SOURCE\\n",
          "scripts/entry2.py": b"import web_bridge_gone\\n"}}
NS['RESERVED_MODULES'] = ['web_bridge_gone']
NS['lock_imports'](files)
out = {{"path_kept": {str(fake_sp)!r} in sys.path}}
try:
    import entry; out['entry'] = entry.SOURCE
except ImportError:
    out['entry'] = 'refused'
try:
    import entry2; out['entry2'] = 'imported'
except ImportError as e:
    out['entry2'] = 'refused'
import json as _j
print(_j.dumps(out))
""", encoding="utf-8")
pr3 = subprocess.run([sys.executable, "-I", str(probe3)], capture_output=True, text=True)
o3 = json.loads(pr3.stdout.strip().splitlines()[-1]) if pr3.returncode == 0 and pr3.stdout.strip() else {}
check(o3.get("path_kept") is False and o3.get("entry") == "refused",
      "V3: 이름만 site-packages인 폴더는 허락하지 않음 — 목록 밖 모듈을 거절" + ("" if o3 else " — " + pr3.stderr[-300:]))
check(o3.get("entry2") == "refused", "V3: 가지 앱 모듈 이름(예약)은 목록에 없으면 설치 폴더에서도 찾지 않음")
probe4 = TMP / "u3" / "probe4.py"
probe4.write_text(f"""
import json, sys, types, sysconfig
NS = {{"__name__": "x"}}
exec(compile(open({str(TMP / 'nb.py')!r}, encoding='utf-8').read(), 'nb', 'exec'), NS)
inst = sysconfig.get_paths()['purelib']
for name in ('eggplant_common', 'eggplant_common.sub', 'arbiter'):
    m = types.ModuleType(name); m.__file__ = inst + '/' + name.replace('.', '/') + '.py'; m.SOURCE = 'preloaded unverified'
    sys.modules[name] = m
NS['RESERVED_MODULES'] = ['eggplant_common']
files = {{"scripts/entry.py": b"import eggplant_common\\n", "scripts/entry_sub.py": b"import eggplant_common.sub\\n",
          "scripts/arbiter.py": b"SOURCE = 'verified arbiter'\\n"}}
NS['lock_imports'](files)
out = {{}}
for n in ('entry', 'entry_sub'):
    try:
        __import__(n); out[n] = 'imported'
    except ImportError:
        out[n] = 'refused'
import arbiter; out['arbiter'] = arbiter.SOURCE
print(json.dumps(out))
""", encoding="utf-8")
pr4 = subprocess.run([sys.executable, "-I", str(probe4)], capture_output=True, text=True)
o4 = json.loads(pr4.stdout.strip().splitlines()[-1]) if pr4.returncode == 0 and pr4.stdout.strip() else {}
check(o4 == {"entry": "refused", "entry_sub": "refused", "arbiter": "verified arbiter"},
      "W3: 설치 폴더에서 먼저 불린 가지 앱 모듈(하위 모듈 포함)도 버림 — 목록 밖이면 거절, 목록 안이면 검증한 바이트" + ("" if o4 else " — " + pr4.stderr[-300:]))

# ======================================================== 마스터 본체
A0, G = "a0@x", "g@x"
ACC = {"A0": A0, "G": G, "K": "k@x"}
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request", "wake", "release"], "status": "active"}]
DAY = 1794618000.0                        # 2026-11-14 10:00 KST
NIGHT = DAY + 13 * 3600                   # 23:00 KST
FILES = got["files"]


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Proc:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15


def world(t0, grant=True, test=True, min_ver="4.33.0", gpu_running=False, people=PEOPLE):
    w = type("W", (), {})()
    w.clk = Clock(t0)
    root = Path(tempfile.mkdtemp(dir=TMP))
    w.store = IO.LocalStore(root / "share", default_owner=A0, clock=w.clk)
    w.admin = IO.LocalStore(root / "admin", default_owner=A0, clock=w.clk)
    w.admin.write_json("config/people.json", people)
    w.admin.write_json("config/accounts.json", ACC)
    if test:
        w.admin.write_json("config/exec.json", {"test_project_id": 77})    # 시험 실행은 시험 프로젝트 번호가 있어야 시작 (2b-6)
    if min_ver:
        w.admin.write_json("config/min_version.json", {"master": min_ver})
    w.kcalls, w.spawned, w.logs = [], [], []

    def kaggle(args):
        w.kcalls.append(list(args))
        if args[:2] == ["kernels", "status"]:
            return 0, ('has status "running"' if gpu_running else 'has status "complete"'), ""
        if args[:2] == ["kernels", "push"]:
            w.pushed_meta = json.loads(Path(args[3], "kernel-metadata.json").read_text())
            w.pushed_nb = sorted(p.name for p in Path(args[3]).iterdir())
            return 0, "ok", ""
        return 1, "", ""
    w.kaggle = kaggle

    def spawn(cmd, env):
        p = Proc()
        w.spawned.append((cmd, env.get(access.MODE_VAR), p))
        return p
    w.spawn = spawn
    w.grant = grant
    w.hooks = []

    def sleep(sec):
        w.clk.t += sec if sec > 1 else 1
        asks = [e for e in w.store.list("jobs/arbiter_ask/", False)]
        if w.grant and asks and not w.store.exists(A.P_GRANT):
            s = w.store.read_json(asks[0].path)["session"]
            w.store.write_json(A.P_GRANT, {"epoch": 1, "session": s, "at": w.clk()}, owner=G)
        for h in list(w.hooks):
            h(w)
    w.sleep = sleep
    w.boot = MM.Boot(files=FILES, remote="gdrive_test:" if test else "gdrive:",
                     admin_remote="gadmin_test:" if test else "gadmin:", test=test, interval=25)
    return w


def run(w, rounds=40, **kw):
    return MM.main(w.boot, store=w.store, admin=w.admin, kaggle=w.kaggle, spawn=w.spawn,
                   cvat_imports=kw.pop("cvat_imports", lambda ts: {t: False for t in ts}),
                   clock=w.clk, sleep=w.sleep, log=w.logs.append, max_rounds=rounds, **kw)


# 시작 조건
for b, why in [(MM.Boot(files=FILES, remote="gdrive:", admin_remote="gadmin:", test=True), "시험인데 운영 연결"),
               (MM.Boot(files=FILES, remote="gdrive_test:", admin_remote="gadmin_test:", test=False), "운영인데 시험 연결")]:
    try:
        MM.check_remotes(b); check(False, why)
    except MM.BootError:
        check(True, f"시작 거절: {why}")
w = world(DAY, min_ver="4.34.0")
try:
    run(w, 2); check(False, "최소 버전")
except MM.BootError as e:
    check("최소 버전" in str(e) and not w.store.exists("jobs/arbiter_ask") and not list(w.store.list("workers/", False)),
          "최소 버전보다 낮으면 시작하지 않음 — 자격 신청·생존 신호도 쓰지 않음")
w = world(DAY, min_ver=None)
try:
    run(w, 2); check(False, "최소 버전 없음")
except MM.BootError:
    check(True, "최소 버전 파일을 못 읽으면 시작하지 않음")
check(MM.version_tuple("4.33.0g") >= MM.version_tuple("4.33.0") and MM.version_tuple("4.33.1") > MM.version_tuple("4.33.0"),
      "버전은 숫자로 비교")

# 낮: 자격 → 판정 → 작업 프로세스 → GPU 올리기
w = world(DAY)
w.store.write_json("requests/REQ_r1__track__pending.json", {"tasks": ["1"], "created": DAY}, owner=A0)
reason = run(w, 20)
arb = w.store.read_json(A.P_ARBITER)
check(arb.get("by_session") and arb["wake"]["gpu_needed"] == 1 and w.store.exists(A.P_INTAKE + "r1.json"),
      "자격을 받은 뒤 판정: 요청 접수, 회차 기록에 'GPU 필요' 1")
check(len(w.spawned) == 1 and w.spawned[0][1] == "exec" and "-I" in w.spawned[0][0] and "--stop-file" in w.spawned[0][0],
      "작업 프로세스 하나를 EGG_ACCESS=exec·격리 모드(-I)·멈춤 파일과 함께 띄움")
code_dir = Path(w.spawned[0][0][w.spawned[0][0].index("-c") + 2])
check(oct(code_dir.stat().st_mode & 0o777) == "0o700" and (code_dir / "worker_cpu.py").read_bytes() == FILES["scripts/worker_cpu.py"],
      "작업 프로세스용 scripts는 검증한 바이트를 본인 전용 폴더(0700)에 씀")
pushes = [c for c in w.kcalls if c[:2] == ["kernels", "push"]]
check(len(pushes) == 1 and w.pushed_meta["id"] == "kuser/eggplant-gpu-worker-test"
      and "eggplant_gpu_worker_test.ipynb" in w.pushed_nb,
      "GPU 필요 → 배포 목록의 GPU 노트북·실행 설정만 올림, 10분 안에 다시 올리지 않음 (회차 20번 = 8분 20초 중 한 번)")
check(reason == "max_rounds", "낮에는 할 일이 없어도 끝내지 않음")
w2 = world(DAY)
w2.store.write_json("requests/REQ_r1__track__pending.json", {"tasks": ["1"], "created": DAY}, owner=A0)
run(w2, 30)
check(len([c for c in w2.kcalls if c[:2] == ["kernels", "push"]]) == 2, "GPU 작업자가 계속 안 뜨면 10분 뒤 다시 올림 (회차 30번 = 12분 30초에 두 번)")
wk = w.store.read_json([e.path for e in w.store.list("workers/", False) if "kgl-" in e.path][0])
check(wk["stopping"] is True and Path(w.spawned[0][0][-1]).exists(), "끝낼 때: 작업 프로세스에 멈춤 파일, 마지막 생존 신호는 '끝남'")


# b22 R2: arb/ 목록을 못 읽은 회차에는 옛 요약으로 GPU를 켜지 않음
w = world(DAY)
w.store.write_json("requests/REQ_r1__track__pending.json", {"tasks": ["1"], "created": DAY}, owner=A0)
state = {"rounds": 0}
kg0 = w.kaggle
def kg_r2(args):
    if args[:2] == ["kernels", "status"]:
        w.kcalls.append(list(args))
        return 0, ('has status "running"' if state["rounds"] < 4 else 'has status "complete"'), ""
    return kg0(args)
w.kaggle = kg_r2
real_list = w.store.list
def list_r2(prefix, recursive, include=None):
    if prefix == "requests/":
        state["rounds"] += 1                   # 회차마다 한 번
    if prefix == "arb/" and state["rounds"] >= 4:
        raise IO.StoreError("arb list down")
    return real_list(prefix, recursive, include)
w.store.list = list_r2
run(w, 40)
pushes = [c for c in w.kcalls if c[:2] == ["kernels", "push"]]
check(not pushes, "arb/ 목록을 못 읽는 회차에는 지난 회차의 요약(GPU 필요)으로 GPU 작업자를 켜지 않음 (R2)")

# GPU 작업자가 이미 실행 중이면 올리지 않음
w = world(DAY, gpu_running=True)
w.store.write_json("requests/REQ_r1__track__pending.json", {"tasks": ["1"], "created": DAY}, owner=A0)
run(w, 10)
check(not [c for c in w.kcalls if c[:2] == ["kernels", "push"]], "GPU 작업자가 이미 실행 중(Kaggle 상태)이면 올리지 않음")

# 정지 보류 중에는 GPU를 켜지 않음
gl = MM.GpuLauncher(FILES, lambda a: (0, "complete", ""), test=True, clock=lambda: DAY)
check(gl.maybe_start({"gpu_needed": 2, "holds": ["stop__p__1"]}) == "hold" and gl.maybe_start({"gpu_needed": 0}) == "not_needed",
      "GPU 올리기: 정지 보류 중이면 안 함, 필요 없으면 안 함")
check(MM.GpuLauncher(FILES, lambda a: (0, "", ""), test=False).maybe_start({"gpu_needed": 1}) == "bad_deploy",
      "운영 실행이 시험 GPU 노트북(-test)을 올리려 하면 거절 (예행 연습 혼입 방지)")
calls = []
def kg7(a):
    calls.append(a[1])
    return (1, "", "timeout") if a[1] == "status" else (0, "", "")
g7 = MM.GpuLauncher(FILES, kg7, test=True, clock=lambda: DAY)
check(g7.maybe_start({"gpu_needed": 1}) == "status_unknown" and calls == ["status"],
      "GPU 상태 조회가 실패하면 올리지 않고 다음 회차에 다시 조회 (U7)")
calls.clear()
g8 = MM.GpuLauncher(FILES, lambda a: (calls.append(a[1]), (1, "", "404 not found") if a[1] == "status" else (0, "", ""))[1],
                    test=True, clock=lambda: DAY)
check(g8.maybe_start({"gpu_needed": 1}) == "status_unknown" and calls == ["status"] and g8.unknown_since == DAY,
      "404·not found여도 올리지 않음 (처음 만들기는 배포 단계), 'GPU 상태 모름' 시작 시각을 기록 (V5)")
calls.clear()
g9 = MM.GpuLauncher(FILES, lambda a: (calls.append(a[1]), (0, 'u/k has status "weird"', "") if a[1] == "status" else (0, "", ""))[1],
                    test=True, clock=lambda: DAY)
check(g9.maybe_start({"gpu_needed": 1}) == "status_unknown" and calls == ["status"], "상태 값을 모르면 올리지 않음")
nogpu = {k: v for k, v in FILES.items() if not k.startswith("kernel-metadata-gpu")}
check(MM.GpuLauncher(nogpu, lambda a: (0, "", ""), test=True).maybe_start({"gpu_needed": 1}) == "bad_deploy",
      "배포 목록에 GPU 실행 설정이 없으면 올리지 않음")

# 자격을 못 받으면 끝냄
w = world(DAY, grant=False)
reason = run(w, 100)
check(reason == "not_granted" and not w.spawned and not w.store.exists(A.P_ARBITER),
      "10분 안에 자격을 못 받으면 끝냄 — 작업 프로세스도 띄우지 않고 판정 파일도 쓰지 않음")

# 자격을 잃으면 끝냄
w = world(DAY)


def steal(w):
    if w.clk() > DAY + 300:
        w.store.write_json(A.P_GRANT, {"epoch": 2, "session": "kgl-other", "at": w.clk()}, owner=G)
w.hooks.append(steal)
check(run(w, 100) == "grant_lost", "Keeper가 다른 마스터에 자격을 주면 10분 뒤 끝냄")

# 밤: 할 일이 없으면 끝냄, 야간 승인된 일이 있으면 계속
w = world(NIGHT)
check(run(w, 100) == "night_idle", "밤에 할 일이 없으면 끝냄 (Keeper가 다음에 깨움)")
w = world(NIGHT)
def fail_requests_later(op, path):
    return op == "list" and path.startswith("requests") and w.clk() > NIGHT + 250
w.store.fail = fail_requests_later
check(run(w, 40) == "max_rounds", "밤이라도 요청 목록을 못 읽은 회차 뒤에는 '할 일 없음'으로 끝내지 않음 (U6)")
w = world(NIGHT)
w.store.write_json("requests/REQ_r1__track__pending.json", {"tasks": ["1"], "created": NIGHT}, owner=A0)


def approve(w):
    if w.store.exists(A.P_INTAKE + "r1.json") and not w.store.exists(A.P_SIGNALS + "approve_night__p__1.json"):
        w.store.write_json(A.P_SIGNALS + "approve_night__p__1.json", {"rid": "r1"}, owner=A0)
w.hooks.append(approve)
check(run(w, 40) == "max_rounds", "밤에도 야간 승인된 일(GPU 필요)이 있으면 끝내지 않음")

# 작업 프로세스가 죽으면 새 세션으로 다시 띄우고, 너무 자주 죽으면 그만둠
w = world(DAY)


def kill(w):
    for c, e, p in w.spawned:
        p.code = 1
w.hooks.append(kill)
run(w, 30)
sess = [c[c.index("--session") + 1] for c, e, p in w.spawned]
check(len(w.spawned) == MM.WORKER_RESTARTS and len(set(sess)) == len(sess) and any("gave_up" in x for x in w.logs),
      "작업 프로세스가 죽으면 새 세션으로 다시 띄움, 한 시간에 5번을 넘으면 그만두고 기록")

# 실제 하위 프로세스: 검증한 코드 폴더에서 worker_cpu가 뜨고 멈춤 파일로 끝남
share = TMP / "real_share"
share.mkdir()
accf = TMP / "acc.json"
accf.write_text(json.dumps(ACC))
sup = MM.WorkerSupervisor(MM.write_code_dir(FILES), str(share), accf, "cpu", "fpx")
sup.tick()
t0 = time.time()
while time.time() - t0 < 20 and not list((share / "workers").glob("*.json")) if (share / "workers").exists() else time.time() - t0 < 20:
    time.sleep(0.2)
sup.stop(wait=30)
recs = [json.loads(p_.read_text()) for p_ in (share / "workers").glob("*.json")] if (share / "workers").exists() else []
check(sup.proc.poll() == 0 and recs and recs[0]["stopping"] is True and recs[0]["session"] == sup.session,
      "실제 하위 프로세스: 검증한 코드 폴더에서 작업 프로세스가 뜨고, 멈춤 파일로 지금 단계를 마친 뒤 '끝남'을 남김")

# ======================================================== 바깥 조회
st = IO.LocalStore(TMP / "probe_share", default_owner=A0)
st.write_json("workers/g1__f.json", {"session": "g1", "kernel": "kuser/eggplant-gpu-worker", "caps": ["gpu"], "hb": 1})
st.write_json("workers/c1__f.json", {"session": "c1", "caps": ["cpu"], "hb": 1})
st.write_json("workers/bad__f.json", ["x"])
st.write_json(A.P_LOCK_TASK + "7.json", {"state": "confirm_approved"})
st.write_json(A.P_LOCK_TASK + "8.json", {"state": "free"})
seen = []
pc = MM.ProbeCache(st, lambda a: (0, 'has status "error"', ""), lambda ts: (seen.append(ts), {t: True for t in ts})[1])
pc.refresh()
pr_ = pc.probes()
check(pr_.kernel_status() == {"g1": "ended"} and seen == [["7"]] and pr_.import_pending() == {"7": True},
      "바깥 조회: 커널 주소를 적은 실행기만 상태 조회, 확정 승인·확인 필요 TASK만 가져오기 조회")
pc2 = MM.ProbeCache(st, lambda a: (1, "", "x"), lambda ts: (_ for _ in ()).throw(IOError()))
pc2.refresh()
check(pc2.probes().kernel_status() == {"g1": "unknown"} and pc2.probes().import_pending() == {} and pc2.errors == 1,
      "조회가 실패하면 '모름'(unknown)")
# U4: 성공 → 실패 → 오래됨 → 회복
ck = {"t": 1000.0}
st_ok = {"k": True, "i": True}
def kg(a):
    if not st_ok["k"]:
        raise IOError("down")
    return (0, 'u/k has status "error"', "")
def ci(ts):
    if not st_ok["i"]:
        raise IOError("down")
    return {t: False for t in ts}
pc3 = MM.ProbeCache(st, kg, ci, clock=lambda: ck["t"])
pc3.refresh()
p3 = pc3.probes()
first = (p3.kernel_status(), p3.import_pending())
st_ok["k"] = st_ok["i"] = False
ck["t"] += 60; pc3.refresh()
after_fail = (p3.kernel_status(), p3.import_pending())
check(first == ({"g1": "ended"}, {"7": False}) and after_fail == ({"g1": "unknown"}, {"7": None}),
      "성공 뒤 조회가 실패하면 옛 '끝남'·'가져오기 없음'을 주지 않고 '모름' (U4)")
# V4: 조회 묶음이 오래 걸리면 앞쪽 값에 묶음 시작 시각이 붙어 곧 만료
slow = MM.ProbeCache(st, lambda a: (0, 'u/k has status "error"', ""),
                     lambda ts: (ck.__setitem__("t", ck["t"] + MM.PROBE_MAX_AGE + 1), {t: False for t in ts})[1],
                     clock=lambda: ck["t"])
slow.refresh()
sp = slow.probes()
check(sp.kernel_status() == {"g1": "unknown"} and sp.import_pending() == {"7": None},
      "조회 묶음 도중 3분이 지나면 앞에서 얻은 값도 '모름' (묶음 시작 시각 기준, V4)")
st_ok["k"] = st_ok["i"] = True
ck["t"] += 60; pc3.refresh()
ok_again = (p3.kernel_status(), p3.import_pending())
ck["t"] += MM.PROBE_MAX_AGE + 1
stale = (p3.kernel_status(), p3.import_pending())
check(ok_again == ({"g1": "ended"}, {"7": False}) and stale == ({"g1": "unknown"}, {"7": None}),
      "회복하면 다시 값을 줌, 마지막 성공 조회가 3분보다 오래되면 '모름'")
check([MM.parse_kernel_status(x) for x in ('u/k has status "queued"', 'u/k has status "KernelWorkerStatus.RUNNING"',
                                           'u/k has status "complete"', 'u/k has status "KernelWorkerStatus.ERROR"',
                                           'u/k has status "cancelRequested"', '')] ==
      ["running", "running", "ended", "ended", "running", "unknown"], "커널 상태 해석: 상태 값만 정확히 (KernelWorkerStatus. 접두어 포함)")
check(MM.parse_kernel_status('error-user/error-worker has status "unrecognized"') == "unknown"
      and MM.parse_kernel_status('running-user/x has status "complete"') == "ended"
      and MM.parse_kernel_status('x has status "running" ... has status "complete"') == "unknown",
      "주소에 error·running이 들어 있어도 상태 값으로만 판단, 상태가 둘이면 모름 (U3)")
check(MM.parse_kernel_status("", 1, "404 Not Found") == "unknown" and MM.parse_kernel_status("", 1, "local configuration file not found") == "unknown",
      "조회 실패는 오류 문구와 상관없이 모두 모름 — '노트북 없음'으로 판단하지 않음 (V5)")
answers = {"1": {"results": [{"status": "started"}]}, "2": {"results": [{"status": "finished"}]}, "3": {"x": 1},
           "5": {"results": [{"state": "started"}]}, "6": {"results": [{}]}, "8": {"results": [{"status": "weird"}]},
           "9": {"results": [{"status": "finished"}], "next": "p2:9"}, "p2:9": {"results": [{"status": "queued"}], "next": None},
           "10": {"results": [{"status": "finished"}], "next": "loop:10"}, "loop:10": {"results": [], "next": "loop:10"}}


def fake_get(url):
    if url.startswith(("p2:", "loop:")):
        return answers[url]
    t = url.split("task_id=")[1].split("&")[0]
    if t == "4":
        raise IOError("down")
    return answers[t]
q = MM.cvat_import_query("https://app.cvat.ai", "tok", get=fake_get)
check(q(["1", "2", "3", "4"]) == {"1": True, "2": False, "3": None, "4": None}
      and MM.cvat_import_query("h", None)(["1"]) == {"1": None},
      "CVAT 가져오기 조회: 진행 중 True, 끝남 False, 형식이 다르거나 실패하거나 토큰이 없으면 None(모름)")
check(q(["5", "6", "8"]) == {"5": None, "6": None, "8": None},
      "행에 상태 칸이 없거나 처음 보는 값이면 '없음'이 아니라 모름 (U5)")
check(q(["9", "10"]) == {"9": True, "10": None},
      "다음 페이지까지 봄 (둘째 쪽의 진행 중을 찾음), 끝없이 이어지면 다 보지 못한 것이라 모름")

# 비밀 값이 기록·생존 신호에 남지 않음
os.environ["CVAT_TOKEN"] = "SECRET-TOKEN-XYZ"
w = world(DAY)
run(w, 5)
dump = "".join(p.read_text(errors="ignore") for p in (w.store.root).rglob("*.json")) + "".join(w.logs)
check("SECRET-TOKEN-XYZ" not in dump, "CVAT 토큰이 공유 폴더 파일·기록에 남지 않음")
os.environ.pop("CVAT_TOKEN", None)

shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
