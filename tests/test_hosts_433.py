"""v4.33 2b-6 시험 — 실행 호스트(exec_host): 시험 범위 강제, 영상·모델 받기, 쉬는 시간 끝내기, GPU 뿌리 노트북,
CPU 작업 프로세스 인자, Colab 세션 설정. 실제 Drive·CVAT·Kaggle에 접속하지 않습니다.
실행: python3 tests/test_hosts_433.py drive
"""
import json, os, shutil, stat, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "dev_tools"))
import access, arbiter as A, arb_io as IO, executor as X, handlers as H, exec_host as EH, master_main as MM
import build_deploy as BD
from fake_cvat import FakeCvat

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

TMP = Path(tempfile.mkdtemp(prefix="host433_"))
A0, G = "a0@x", "g@x"
ACC = {"A0": A0, "G": G}

# ---------------------------------------------------------------- 실행 설정·시험 범위
adm = IO.LocalStore(TMP / "adm", default_owner=A0)
check(EH.load_exec_config(adm)["cvat_host"] == "https://app.cvat.ai", "실행 설정 파일이 없으면 기본값")
adm.write_json("config/exec.json", ["깨짐"])
try:
    EH.load_exec_config(adm); check(False, "깨진 설정")
except EH.HostError:
    check(True, "실행 설정이 있는데 객체가 아니면 시작하지 않음")
st = IO.LocalStore(TMP / "share", default_owner=A0)
try:
    EH.build_env(EH.HostConfig(test=True, caps=["cpu"]), st, raw_cvat=FakeCvat()); check(False, "프로젝트 없는 시험")
except EH.HostError:
    check(True, "시험 실행인데 시험 프로젝트 번호가 없으면 실행기를 띄우지 않음 (시험 범위 강제)")
cv = FakeCvat(); cv.add_task(5, "eggplant_G6_1_uld", project_id=77); cv.add_task(6, "REH_eggplant_G6_1_uld", project_id=77)
env_t = EH.build_env(EH.HostConfig(test=True, caps=["cpu"], exec_cfg=dict(EH.DEFAULT_EXEC, test_project_id=77)), st, raw_cvat=cv)
env_p = EH.build_env(EH.HostConfig(test=False, caps=["cpu"]), st, raw_cvat=cv)
def refused(fn):
    try:
        fn(); return False
    except H.ScopeError:
        return True
check(isinstance(env_t.cvat, H.ScopedCvat) and env_t.test and refused(lambda: env_t.cvat.rename_task(5, "REH_x"))
      and not refused(lambda: env_t.cvat.rename_task(6, "REH_y")), "시험 실행 환경: 시험 프로젝트의 REH_ TASK에만 씀")
check(refused(lambda: env_p.cvat.remove_annotations(6)) and not refused(lambda: env_p.cvat.remove_annotations(5)),
      "운영 실행 환경: REH_ TASK에는 쓰지 않음")
check(hasattr(env_p, "builder") and not hasattr(env_p, "engine") and not hasattr(env_p, "revisions"),
      "능력에 맞는 엔진만 (cpu → 데이터셋 만들기)")
os.environ.pop("CVAT_TOKEN", None)
env_n = EH.build_env(EH.HostConfig(test=False, caps=["cpu"]), st)
try:
    env_n.cvat.get_task(1); check(False, "토큰 없이 CVAT")
except EH.HostError:
    check(True, "CVAT_TOKEN이 없는 호스트는 CVAT 일만 실패 (저장소 일은 함)")
check(not any("CVAT_TOKEN" in json.dumps(v, default=str) for v in [EH.DEFAULT_EXEC]), "실행 설정에 비밀 칸 없음")

# ---------------------------------------------------------------- 영상·모델 받기
src = IO.LocalStore(TMP / "src", default_owner=A0)
f = TMP / "v.mp4"; f.write_bytes(b"video")
src.put_file(str(f), "videos/261026/eggplant_G6_261026_1_4.mp4")
src.put_file(str(f), "videos/261026/other.mp4")
md = EH.Media(src, str(TMP / "media"))
v = md.video("", "eggplant_G6_261026_1_4_uld")
check(v and Path(v).name == "eggplant_G6_261026_1_4.mp4" and not (TMP / "media/videos/261026/other.mp4").exists(),
      "영상: TASK 기본 이름과 같은 영상만 받음")
check(md.video("", "eggplant_G9_261026_9_9_uld") is None, "영상이 없으면 None (처리기가 실패로 보고)")
w_ = TMP / "best.pt"; w_.write_bytes(b"W")
H.publish_version(src, "model", "m1", "train_a", {"best.pt": str(w_)})
src.write_json("runs/m1/CURRENT.json", {"version": "train_a"})
p_ = md.model("m1")
check(Path(p_).read_bytes() == b"W", "모델: 채택된 버전의 best.pt를 목록 해시와 대조해 받음")
H.publish_version(src, "model", "m2", "train_b", {"best.pt": str(w_)})
src.write_json("runs/m2/CURRENT.json", {"version": "train_b"})
(TMP / "src/runs/m2/v/train_b/best.pt").write_bytes(b"evil")
try:
    md.model("m2"); check(False, "바뀐 모델")
except Exception as e:
    check("hash" in str(e), "모델 파일이 목록과 다르면 받지 않음")
try:
    md.model("m3"); check(False, "채택 없음")
except EH.HostError:
    check(True, "채택된 버전이 없는 모델은 쓰지 않음")
legacy = TMP / "lg.pt"; legacy.write_bytes(b"L")
src.put_file(str(legacy), "runs/old/weights/best.pt")
src.write_json("runs/old/v/legacy/_files.json", {"files": {"best.pt": {"sha256": H.sha256_file(str(legacy)), "size": 1}},
                                                  "verified": True, "legacy": True, "paths": {"best.pt": "runs/old/weights/best.pt"}})
src.write_json("runs/old/CURRENT.json", {"version": "legacy"})
check(Path(md.model("old")).read_bytes() == b"L", "옛 산출물 등록(v/legacy)은 옛 위치의 파일을 해시 대조해 받음")
z = TMP / "e.zip"
import zipfile
with zipfile.ZipFile(z, "w") as zz:
    zz.writestr("annotations.xml", "<annotations><meta><task><id>9</id><name>eggplant_G6_261026_1_4_uld</name>"
                                   "<source>GX01.MP4</source></task></meta></annotations>")
check(EH.zip_task_meta(str(z)) == {"name": "eggplant_G6_261026_1_4_uld", "source": "GX01.MP4", "id": "9", "images": False},
      "export zip에서 TASK 이름·원본 파일 이름")

# ---------------------------------------------------------------- 실행 고리: 쉬는 시간 끝내기·커널 주소
os.environ[access.MODE_VAR] = "exec"
class Clk:
    def __init__(self): self.t = 1763000000.0
    def __call__(self): return self.t
c = Clk()
s2 = IO.LocalStore(TMP / "loop", default_owner=A0, clock=c)
env2 = EH.build_env(EH.HostConfig(test=False, caps=["gpu"]), s2, raw_cvat=FakeCvat())
ex = EH.run_loop(s2, ACC, ["gpu"], env2, "GPU1", "fp", kernel="kuser/eggplant-gpu-worker", interval=60, hb_every=3600,
                 idle_exit=900, sleep=lambda s: setattr(c, "t", c.t + s), clock=c, max_steps=100)
hb = json.loads((TMP / "loop/workers").glob("*.json").__next__().read_text())
check("idle_exit" in ex.notes and hb.get("kernel") == "kuser/eggplant-gpu-worker",
      "GPU 작업자: 맡은 일 없이 15분이면 끝냄 · 생존 신호에 Kaggle 주소")
s3 = IO.LocalStore(TMP / "loop3", default_owner=A0, clock=c)
s3.write_json(A.P_ASSIGN + "x.json", {"session": "GPU2", "state": "active"})
env3 = EH.build_env(EH.HostConfig(test=False, caps=["gpu"]), s3, raw_cvat=FakeCvat())
ex3 = EH.run_loop(s3, ACC, ["gpu"], env3, "GPU2", "fp", interval=60, hb_every=3600, idle_exit=900,
                  sleep=lambda s: setattr(c, "t", c.t + s), clock=c, max_steps=40)
check("idle_exit" not in ex3.notes, "맡은 배정이 남아 있으면(확정 대기 등) 쉬는 시간으로 끝내지 않음")
check(EH.my_active_work(type("S", (), {"list": lambda *a: (_ for _ in ()).throw(IO.StoreError("x"))})(), "Q"),
      "배정 목록을 못 읽으면 일이 있는 것으로 봄 (일하던 중에 끝내지 않음)")
# main_gpu: 시험인데 시험 프로젝트가 없으면 시작하지 않음 · 있으면 kernel이 생존 신호에
ga = IO.LocalStore(TMP / "gadm", default_owner=A0); ga.write_json("config/accounts.json", ACC)
gs = IO.LocalStore(TMP / "gshare", default_owner=A0, clock=c)
try:
    EH.main_gpu({}, "gdrive_test:", "gadmin_test:", True, kernel="k/x", store=gs, admin=ga, raw_cvat=FakeCvat(),
                log=lambda *a: None, max_steps=1, sleep=lambda s: None, clock=c)
    check(False, "프로젝트 없는 시험 GPU")
except EH.HostError:
    check(True, "GPU 작업자: 시험인데 시험 프로젝트 번호가 없으면 띄우지 않음")
ga.write_json("config/exec.json", {"test_project_id": 77, "idle_exit_min": 1})
exg = EH.main_gpu({}, "gdrive_test:", "gadmin_test:", True, kernel="k/x-test", store=gs, admin=ga, raw_cvat=FakeCvat(),
                  log=lambda *a: None, interval=30, hb_every=3600, sleep=lambda s: setattr(c, "t", c.t + s), clock=c, max_steps=10)
check("idle_exit" in exg.notes and exg.kernel == "k/x-test" and "prepare" in H.REGISTRY.get("track", {}),
      "GPU 작업자: 처리기 등록 뒤 실행, 쉬는 시간 한도(설정 1분)로 끝냄")
try:
    EH.main_gpu({}, "gdrive:", "gadmin_test:", False, store=gs, admin=ga, raw_cvat=FakeCvat(), log=lambda *a: None, max_steps=1)
    check(False, "연결 섞임")
except MM.BootError:
    check(True, "GPU 작업자: 운영인데 시험 연결이 섞이면 멈춤")

# ---------------------------------------------------------------- CPU 작업 프로세스 명령
sup = MM.WorkerSupervisor(Path("/code"), "gdrive_test:", Path("/acc.json"), "cpu,agg", "fp", spawn=lambda c_, e: None,
                          test=True, exec_file=Path("/x/exec.json"))
sup.session = "S"
cmd = sup._cmd()
check("--test" in cmd and cmd[cmd.index("--exec-config") + 1] == "/x/exec.json", "마스터가 작업 프로세스에 시험 여부·실행 설정을 넘김")
sup_p = MM.WorkerSupervisor(Path("/code"), "gdrive:", Path("/acc.json"), "cpu,agg", "fp", spawn=lambda c_, e: None)
sup_p.session = "S"
check("--test" not in sup_p._cmd(), "운영 작업 프로세스에는 시험 표시 없음")

# ---------------------------------------------------------------- 배포 묶음: GPU 뿌리 노트북
info = BD.build(TMP / "dep", "kuser", test=True)
dep = TMP / "dep"
man = json.loads((dep / "manifest.json").read_text())
wman_b = (dep / "worker_manifest.json").read_bytes()
gnb = json.loads((dep / "eggplant_gpu_worker_test.ipynb").read_text())
gsrc = "".join(gnb["cells"][0]["source"])
check(info["gpu_notebook"] == "built" and "worker_manifest.json" in man["files"] and "eggplant_gpu_worker_test.ipynb" in man["files"]
      and BD.sha256(wman_b) in gsrc and 'ROLE = "gpu"' in gsrc and 'KERNEL = "kuser/eggplant-gpu-worker-test"' in gsrc
      and 'MANIFEST_NAME = "worker_manifest.json"' in gsrc,
      "GPU 뿌리 노트북: 작업자 목록 해시 고정 · 노트북과 작업자 목록은 배포 목록에 (사슬)")
wman = json.loads(wman_b)
check(set(wman["files"]) == {k for k in man["files"] if k.startswith("scripts/")}, "작업자 목록 = scripts만 (노트북·실행 설정 없음)")
msrc = "".join(json.loads((dep / info["master_notebook"]).read_text())["cells"][0]["source"])
check('ROLE = "master"' in msrc and 'MANIFEST_NAME = "manifest.json"' in msrc, "마스터 뿌리 노트북은 그대로 manifest.json")
NS = {"__name__": "gpu_boot"}
exec(compile(gsrc, "gpu_nb", "exec"), NS)
def fake_rclone(root):
    def r(*a):
        shutil.copytree(root, a[2], dirs_exist_ok=True)
        return subprocess.CompletedProcess(a, 0, b"", b"")
    return r
got = NS["fetch_deploy"]("gadmin_test:", fake_rclone(dep))
check(set(got["files"]) == set(wman["files"]), "GPU 뿌리: 작업자 목록 해시 → scripts 해시 확인")
bad = TMP / "bad"; shutil.copytree(dep, bad)
(bad / "scripts" / "exec_host.py").write_text("print('바뀜')")
try:
    NS["fetch_deploy"]("gadmin_test:", fake_rclone(bad)); check(False, "변조")
except NS["BootStop"]:
    check(True, "GPU 뿌리: scripts 하나가 바뀌면 실행하지 않음")

# ---------------------------------------------------------------- Colab 세션 rclone 설정
cr = EH.ColabRclone({"gdrive_test": "F1", "gadmin_test": "F2"})
cr.write({"access_token": "tok-x", "token_type": "Bearer", "expiry": "2026-11-17T00:00:00Z"})
mode = stat.S_IMODE(os.stat(cr.path).st_mode)
txt = cr.path.read_text()
check(mode == 0o600 and stat.S_IMODE(os.stat(cr.dir).st_mode) == 0o700 and "[gdrive_test]" in txt
      and "root_folder_id = F2" in txt and "refresh_token" not in txt and os.environ.get("RCLONE_CONFIG") == str(cr.path),
      "Colab: 로그인 토큰으로 세션 전용 rclone 설정(0600, 갱신 토큰 없음)")
cell = (PKG / "notebooks/A0_colab/cell30_v4.33.py").read_text(encoding="utf-8")
check("userdata.get(\"CVAT_TOKEN\")" in cell and "RCLONE_CONF" not in cell.split("import os")[1] and "print(os.environ" not in cell,
      "30번 셀: CVAT_TOKEN은 Colab 보안 비밀에서, 출력하지 않음")
try:
    EH.main_colab("gdrive:", {"gdrive": "a", "gadmin_test": "b"}, False, "/s"); check(False, "섞인 연결")
except EH.HostError:
    check(True, "Colab: 시험·운영 연결이 섞이면 멈춤")


# ---------------------------------------------------------------- 청소: 끝난 확정의 복구 자료 30일
import h_mgmt as HM
rs = IO.LocalStore(TMP / "rec", default_owner=A0, clock=lambda: 0)
for job in ("E1-7-1-aa", "E1-7-2-bb", "E1-8-1-cc"):
    t = job.split("-")[1]
    rs.write_json(f"recovery/{t}/{job}/result_plan.json", {"task": t})
    (TMP / "rec" / f"recovery/{t}/{job}/before_upload.zip").write_bytes(b"z")
    rs.write_json(f"recovery/{t}/{job}/steps/001_intent.json", {})
rs.write_json(A.P_LOCK_TASK + "8.json", {"state": "quarantine", "job": "E1-8-1-cc"})
rs.write_json(A.P_LOCK_TASK + "7.json", {"state": "free", "job": "E1-7-2-bb"})
rs.write_json("recovery/create/c1/run1/intent.json", {"state": "unknown"})
rs.write_json("recovery/create/c2/run2/intent.json", {"state": "created"})
old = 1e9
for p_ in (TMP / "rec").rglob("*"):
    if p_.is_file():
        os.utime(p_, (old, old))
rp = HM.recovery_plan(rs, old + 31 * 86400)
dirs = [r["dir"] for r in rp]
check(dirs == ["recovery/7/E1-7-1-aa/", "recovery/7/E1-7-2-bb/", "recovery/create/c2/run2/"]
      and rp[0]["files"][0].endswith("result_plan.json") and len(rp[0]["files"]) == 3,
      "청소: 30일 지난 끝난 확정의 복구 자료만 (확인 필요 TASK의 것·결과 모르는 만들기는 남김, 결과 계획 먼저)")
check(HM.recovery_plan(rs, old + 10 * 86400) == [], "30일이 안 된 복구 자료는 남김")
rs.write_json(A.P_INTAKE + "rcv1.json", {"rid": "rcv1", "kind": "recovery", "origin_job": "E1-7-1-aa"})
rs.write_json("requests/REQ_rcv1__recovery__pending.json", {})
check("recovery/7/E1-7-1-aa/" not in [r["dir"] for r in HM.recovery_plan(rs, old + 31 * 86400)],
      "끝나지 않은 복구 요청이 쓰는 원래 복구 자료는 남김")

# ---------------------------------------------------------------- 웹 상태 (옛 취합 계산을 읽기 사본 위에서)
import web_bridge as WB, cvat_task_tools as CT
ws_store = IO.LocalStore(TMP / "ws", default_owner=A0)
ws_store.write_json("web/label_stats.json", {"1": {"n": 3}})
(TMP / "ws/logs/shards").mkdir(parents=True); (TMP / "ws/logs/shards/a.csv").write_text("x")
(TMP / "ws/exports/r1").mkdir(parents=True); (TMP / "ws/exports/r1/t.zip").write_bytes(b"z")
(TMP / "ws/exports/big").mkdir(parents=True); (TMP / "ws/exports/big/deep").mkdir(); (TMP / "ws/exports/big/deep/v.mp4").write_bytes(b"v")
seen = {}
saved = {k: getattr(WB, k) for k in ("media_names", "snapshots", "compute_stats", "compute_corrections", "build_state")}
saved_c = {k: getattr(CT, k) for k in ("set_scope", "list_tasks_all", "whoami")}
WB.media_names = lambda base, **k: (seen.setdefault("media", k) and (set(), set())) or (set(), set())
WB.snapshots = lambda base, **k: []
WB.compute_stats = lambda base, tasks, **k: {}
WB.compute_corrections = lambda base, tasks, **k: {}
WB.build_state = lambda base, tasks, **k: (seen.setdefault("pulled", sorted(p.relative_to(base).as_posix() for p in Path(base).rglob("*") if p.is_file())), {"tasks": tasks, "server": k["server"]})[1]
CT.set_scope = lambda c, o, p: {"org": o}
CT.list_tasks_all = lambda c, limit=5000: ([{"task_id": 1}], {})
CT.whoami = lambda c: "me"
class RawC:
    def client(self): return "CLIENT"
wsb = EH.WebState(ws_store, str(TMP / "wswork"), RawC(), dict(EH.DEFAULT_EXEC))
out = wsb.build(lambda *a: None)
for k, v in saved.items(): setattr(WB, k, v)
for k, v in saved_c.items(): setattr(CT, k, v)
check(set(out) == {"web/state.json", "web/label_stats.json"} and out["web/state.json"]["server"] == "me@app.cvat.ai"
      and "logs/shards/a.csv" in seen["pulled"] and "exports/r1/t.zip" in seen["pulled"]
      and "exports/big/deep/v.mp4" not in seen["pulled"] and not (TMP / "ws/web/state.json").exists(),
      "웹 상태: 필요한 기록만 읽기 사본으로 받아 옛 계산을 부르고, 공유 폴더에는 쓰지 않음 (게시는 취합 처리기)")


# ---------------------------------------------------------------- b24 T4: 학습은 별도 프로세스 묶음, 부모가 지켜봄
import h_run as HR, signal, time as _time
child = TMP / "fake_child.py"
child.write_text(r"""
import json, os, sys, time, subprocess
spec = json.load(open(sys.argv[1]))
mode = spec["args"].get("mode", "ok")
d = os.path.join(spec["project"], spec["name"]); os.makedirs(os.path.join(d, "weights"), exist_ok=True)
# DDP 자식 흉내: 같은 묶음 안의 손자 프로세스 — 자기 pid를 자기 폴더에만 기록
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(os.path.join(spec["project"], "grandchild.pid"), "w").write(str(g.pid))
with open(os.path.join(d, "results.csv"), "w") as f:
    f.write("epoch,metrics/mAP50(B)\n")
for e in range(1, 4):
    time.sleep(0.15)
    with open(os.path.join(d, "results.csv"), "a") as f:
        f.write(f"{e},0.{e}\n")
    print("epoch", e, flush=True)
if mode == "fail":
    g.kill(); sys.exit(3)
if mode == "hang":
    time.sleep(60)
open(os.path.join(d, "weights", "best.pt"), "wb").write(b"W")
g.kill()
json.dump({"metrics": {"metrics/mAP50(B)": 0.3}}, open(spec["done"], "w"))
""")
ds = TMP / "ds"; ds.mkdir(); (ds / "data.yaml").write_text("path: /old\nnames: [a]\n")
seen_ep, alive = [], []
tr = HR.RealTrainer(child=str(child), sleep=lambda s_: _time.sleep(0.05))
out = tr.train(str(ds), "s.pt", {"mode": "ok"}, str(TMP / "tw1"), seen_ep.append, on_tick=lambda: None,
               on_alive=lambda: alive.append(1))
check(seen_ep == [1, 2, 3] and Path(out["best"]).read_bytes() == b"W" and out["metrics"] == {"metrics/mAP50(B)": 0.3}
      and alive and f"path: {ds}" in (ds / "data.yaml").read_text(),
      "학습 자식 프로세스: 부모가 results.csv로 에폭을 읽어 알림, 끝남 파일이 있을 때만 결과")
def alive_pid(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        st_ = open(f"/proc/{pid}/stat").read().split()[2]
        return st_ != "Z"
    except Exception:
        return True
lost = {"n": 0}
def tick():
    lost["n"] += 1
    if lost["n"] > 6:
        raise access.AuthorityLost("권한 잃음")
tr.GRACE, tr.KILL_WAIT = 1, 8
try:
    tr.train(str(ds), "s.pt", {"mode": "hang"}, str(TMP / "tw2"), lambda n: None, on_tick=tick)
    check(False, "권한 잃음")
except access.AuthorityLost:
    gpid = int((TMP / "tw2/grandchild.pid").read_text())
    _time.sleep(0.3)
    check(not alive_pid(gpid) and not (TMP / "tw2/done.json").exists(),
          "권한을 잃으면 학습 프로세스 묶음 전체(DDP 자식 흉내 포함)를 끝내고 결과를 내지 않음 (T4)")
try:
    tr.train(str(ds), "s.pt", {"mode": "fail"}, str(TMP / "tw3"), lambda n: None)
    check(False, "실패")
except RuntimeError:
    check(True, "학습 프로세스가 실패하면(종료 코드≠0·끝남 파일 없음) 실패로")
src_child = (PKG / "scripts/train_child.py").read_text(encoding="utf-8")
check("callbacks" not in src_child and "add_callback" not in src_child and "RcloneStore" not in src_child
      and 'spec["project"]' in src_child, "학습 자식은 콜백·공유 저장소 없이 자기 작업 폴더에만 씀 (T4·11/17 결정)")
import pickle
check(isinstance(pickle.loads(pickle.dumps({"data": "x", "args": {"device": "0,1"}})), dict),
      "자식에게 넘기는 것은 직렬화 가능한 설정 파일뿐")

# ---------------------------------------------------------------- b24 T5: 채택된 모델이 웹·relabel 모델 목록에
import h_agg as HA
ms = IO.LocalStore(TMP / "ms", default_owner=A0)
bw = TMP / "bw.pt"; bw.write_bytes(b"B")
rcsv = TMP / "results.csv"; rcsv.write_text("epoch,metrics/mAP50(B),metrics/mAP50-95(B)\n1,0.5,0.3\n")
tj = TMP / "train.json"; tj.write_text(json.dumps({"metrics": {"metrics/mAP50(B)": 0.5, "metrics/mAP50-95(B)": 0.3},
                                                   "args": {"imgsz": 1920}, "classes": ["healthy_fruit"], "made_at": 1763000000}))
H.publish_version(ms, "model", "fruit_n", "train_x", {"best.pt": str(bw), "results.csv": str(rcsv), "train.json": str(tj)})
ms.write_json("runs/fruit_n/CURRENT.json", {"version": "train_x", "at": 1763000100})
H.publish_version(ms, "model", "fr_B", "mgmt_y", {"best.pt": str(bw)})
ms.write_json("runs/fr_B/CURRENT.json", {"version": "mgmt_y", "at": 1763000200})
H.publish_version(ms, "model", "unadopted", "train_z", {"best.pt": str(bw)})
am = HA.adopted_models(ms)
rows_ = HA.model_rows(am)
check([m["name"] for m in am] == ["fr_B", "fruit_n"] and {r["name"]: r["map50"] for r in rows_}["fruit_n"] == 0.5
      and {r["name"]: r["classes"] for r in rows_}["fruit_n"] == ["healthy_fruit"],
      "채택된 모델 버전 목록(학습·복원) — 채택 안 된 버전은 목록에 없음 (T5)")
saved_c = {k: getattr(CT, k) for k in ("set_scope", "list_tasks_all", "whoami")}
CT.set_scope = lambda c, o, p: None
CT.list_tasks_all = lambda c, limit=5000: ([], {"orgs": [], "projects": []})
CT.whoami = lambda c: "me"
saved_w = {k: getattr(WB, k) for k in ("compute_stats", "compute_corrections")}
WB.compute_stats = lambda base, tasks, **k: {}
WB.compute_corrections = lambda base, tasks, **k: {}
try:
    wsx = EH.WebState(ms, str(TMP / "msw"), RawC(), dict(EH.DEFAULT_EXEC))
    outx = wsx.build(lambda *a: None)
    names_ = sorted(m["name"] for m in outx["web/state.json"].get("models") or [])
    check(names_ == ["fr_B", "fruit_n"], f"실제 웹 상태 계산(build_state)에 채택된 모델이 나옴 (T5) — {names_}")
except Exception as e:
    check(False, f"실제 웹 상태 계산 실패: {type(e).__name__}: {str(e)[:120]}")
finally:
    for k, v in saved_c.items(): setattr(CT, k, v)
    for k, v in saved_w.items(): setattr(WB, k, v)


# ---------------------------------------------------------------- b25 F1: TERM을 무시하는 손자까지 묶음 전체 정리
stub = TMP / "stub_child.py"
stub.write_text(r"""
import json, os, sys, time, subprocess, signal
spec = json.load(open(sys.argv[1]))
mode = spec["args"].get("mode")
d = os.path.join(spec["project"], spec["name"]); os.makedirs(os.path.join(d, "weights"), exist_ok=True)
g = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"])
open(os.path.join(spec["project"], "grandchild.pid"), "w").write(str(g.pid))
time.sleep(0.3)
if mode == "exit3":
    sys.exit(3)                                     # 리더가 먼저 끝남 — 손자는 남아 있음
if mode == "ok":
    open(os.path.join(d, "weights", "best.pt"), "wb").write(b"W")
    json.dump({"metrics": {}}, open(spec["done"], "w"))
    sys.exit(0)                                     # 정상 끝 — 손자(낙오 DDP)는 남아 있음
time.sleep(120)
""")
tr2 = HR.RealTrainer(child=str(stub), sleep=lambda s_: _time.sleep(0.05))
tr2.GRACE, tr2.KILL_WAIT = 1, 8
cnt = {"n": 0}
def tick2():
    cnt["n"] += 1
    if cnt["n"] > 10:
        raise access.AuthorityLost("권한 잃음")
res_ = {}
for mode_, kw in (("hang", {"on_tick": tick2}), ("exit3", {}), ("ok", {})):
    wdir = TMP / f"f1_{mode_}"
    try:
        tr2.train(str(ds), "s.pt", {"mode": mode_}, str(wdir), lambda n: None, **kw)
        res_[mode_] = "returned"
    except access.AuthorityLost:
        res_[mode_] = "lost"
    except RuntimeError:
        res_[mode_] = "failed"
    gp = int((wdir / "grandchild.pid").read_text())
    _time.sleep(0.2)
    res_[mode_ + "_alive"] = alive_pid(gp)
    if alive_pid(gp):
        os.kill(gp, signal.SIGKILL)
check(res_ == {"hang": "lost", "hang_alive": False, "exit3": "failed", "exit3_alive": False, "ok": "returned", "ok_alive": False},
      f"권한 상실·리더 먼저 실패·정상 끝 모두 TERM을 무시하는 손자까지 묶음 전체를 끝냄 (b25 F1) — {res_}")

# ---------------------------------------------------------------- b25 F2: 잘못된 모델 목록 하나는 그 모델만 뺌
for bad_name, bad in (("bad_list", []), ("bad_null", None), ("bad_empty_best", {"files": {"best.pt": []}, "verified": True}),
                      ("bad_unverified", {"files": {"best.pt": {"sha256": "a" * 64, "size": 1}}, "verified": "yes"})):
    ms.write_json(f"runs/{bad_name}/v/v1/_files.json", bad)
    ms.write_json(f"runs/{bad_name}/CURRENT.json", {"version": "v1"})
ms.write_json("runs/bad_cur/CURRENT.json", ["x"])
sk = []
am2 = HA.adopted_models(ms, sk)
check([m["name"] for m in am2] == ["fr_B", "fruit_n"] and sorted(x[0] for x in sk) == ["bad_empty_best", "bad_list", "bad_null", "bad_unverified"],
      "목록이 깨진 모델([]·null·빈 가중치·확인 안 됨)은 그 모델만 빼고 이유를 남김 — 정상 모델은 그대로 (b25 F2)")


# ---------------------------------------------------------------- b26 U1·U5: 새 세션으로 나간 작업자·좀비
sess_child = TMP / "sess_child.py"
sess_child.write_text(r"""
import json, os, sys, time, subprocess
spec = json.load(open(sys.argv[1]))
mode = spec["args"].get("mode")
if mode == "zombie":
    subprocess.Popen(["true"])                      # 끝났지만 거두지 않음 → 좀비 손자
    open(os.path.join(spec["project"], "grandchild.pid"), "w").write("0")
    time.sleep(120)
g = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"],
                     start_new_session=True)       # DDP 작업자처럼 새 세션
open(os.path.join(spec["project"], "grandchild.pid"), "w").write(str(g.pid))
time.sleep(0.4)
if mode == "leader_dies":
    os._exit(3)                                     # 리더가 먼저 죽음 — 작업자는 고아
time.sleep(120)
""")
tr3 = HR.RealTrainer(child=str(sess_child), sleep=lambda s_: _time.sleep(0.05))
tr3.GRACE, tr3.KILL_WAIT = 1, 8
res3 = {}
for mode_ in ("lost", "leader_dies", "zombie"):
    wdir = TMP / f"u1_{mode_}"
    n3 = {"n": 0}
    def tick3():
        n3["n"] += 1
        if n3["n"] > 12:
            raise access.AuthorityLost("권한 잃음")
    t0_ = _time.monotonic()
    try:
        tr3.train(str(ds), "s.pt", {"mode": mode_}, str(wdir), lambda n: None, on_tick=tick3)
        res3[mode_] = "returned"
    except HR.CleanupUnknown as e:
        res3[mode_] = "cleanup_unknown"
    except access.AuthorityLost:
        res3[mode_] = "lost"
    except RuntimeError:
        res3[mode_] = "failed"
    res3[mode_ + "_sec"] = round(_time.monotonic() - t0_, 1)
    gp = int((wdir / "grandchild.pid").read_text() or 0)
    if gp:
        _time.sleep(0.2)
        res3[mode_ + "_alive"] = alive_pid(gp)
        if alive_pid(gp):
            os.kill(gp, signal.SIGKILL)
check(res3.get("lost") == "lost" and res3.get("lost_alive") is False and res3.get("leader_dies") in ("failed", "lost")
      and res3.get("leader_dies_alive") is False,
      f"새 세션으로 나간 작업자(DDP 흉내)도 부모 사슬로 추적해 끝냄 — 권한 상실·리더가 먼저 죽은 경우 (b26 U1) {res3}")
check(res3.get("zombie") == "lost" and res3.get("zombie_sec", 99) < 8,
      f"좀비만 남은 것은 살아 있는 것으로 보지 않고 회수 — 정리 실패로 가지 않음 (b26 U5) {res3}")

import subprocess as _sp2
zp = _sp2.Popen([sys.executable, "-c", "import subprocess, time; p = subprocess.Popen(['true']); open(%r, 'w').write(str(p.pid)); time.sleep(5)" % str(TMP / "zpid")])
_time.sleep(0.2)
pt = HR.ProcTree(zp.pid)
for _ in range(20):
    pt.scan()
    if (TMP / "zpid").exists() and (TMP / "zpid").read_text():
        break
    _time.sleep(0.05)
zg = int((TMP / "zpid").read_text())
pt.scan(); _time.sleep(0.4)
al = pt.alive()
check(zg in pt.known and zg not in al and zp.pid in al, "추적 중 좀비(남의 자식)는 '살아 있음'에서 뺌 (b26 U5)")
zp.kill(); zp.wait()


# b27 F1: poll 사이에 리더가 새 세션 손자를 만들고 바로 끝나도 — 손자는 감독 아래로 넘어와 정리됨
race = TMP / "race_child.py"
race.write_text(r"""
import json, os, sys, subprocess
spec = json.load(open(sys.argv[1]))
g = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"],
                     start_new_session=True)
open(os.path.join(spec["project"], "grandchild.pid"), "w").write(str(g.pid))
os._exit(3)
""")
tr4 = HR.RealTrainer(child=str(race), sleep=lambda s_: _time.sleep(2))      # 실행기 poll은 느리게 — 손자를 직접 보지 못함
tr4.GRACE, tr4.KILL_WAIT = 1, 8
adopted = {}
orig_stat = HR._stat
t0_ = _time.monotonic()
try:
    tr4.train(str(ds), "s.pt", {}, str(TMP / "race"), lambda n: None)
    r4 = "returned"
except RuntimeError as e:
    r4 = type(e).__name__
gp4 = int((TMP / "race/grandchild.pid").read_text())
_time.sleep(0.2)
st4 = json.loads((TMP / "race/supervisor.json").read_text())
check(r4 == "RuntimeError" and not alive_pid(gp4) and st4["clean"] is True and st4["child_rc"] == 3,
      f"리더가 poll 사이에 새 세션 손자를 만들고 끝나도 감독이 넘겨받아 끝냄 — 실행기의 다른 자식과 섞이지 않음 (b27 F1) {r4} {st4}")
if alive_pid(gp4):
    os.kill(gp4, signal.SIGKILL)
# b28 V4: subreaper를 켜지 못하면 학습을 띄우지 않고 '준비 실패' (거짓 '깨끗함'으로 고아를 놓치지 않음)
import train_supervisor as TS
v4sup = TMP / "v4_supervisor.py"
v4sup.write_text("import sys\nsys.path.insert(0, %r)\nimport train_supervisor as T\n"
                 "T.set_subreaper = lambda: 'prctl(SET_CHILD_SUBREAPER) 실패 errno=1 (시험)'\n"
                 "sys.exit(T.main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])))\n" % str(Path(HR.__file__).parent))
tr6 = HR.RealTrainer(child=str(race), sleep=lambda s_: _time.sleep(0.05))
tr6.supervisor, tr6.GRACE, tr6.KILL_WAIT = str(v4sup), 1, 8
try:
    tr6.train(str(ds), "s.pt", {}, str(TMP / "v4"), lambda n: None)
    r6 = "returned"
except HR.CleanupUnknown:
    r6 = "cleanup_unknown"
except RuntimeError as e:
    r6 = "failed:" + str(e)
st6 = json.loads((TMP / "v4/supervisor.json").read_text())
check(r6.startswith("failed:") and "감독 준비 실패" in r6 and not (TMP / "v4/grandchild.pid").exists()
      and st6["child_started"] is False and st6["setup_failed"],
      f"감독이 subreaper를 켜지 못하면 학습 자식을 띄우지 않고 '학습 준비 실패'로 끝남 (b28 V4) {r6[:60]}")
check(TS.set_subreaper() is None and TS.can_observe(os.getpid()) is None,
      "이 시험 환경(Linux)에서는 subreaper 설정을 다시 읽어 확인하고 /proc 관측도 됨")
TS.ctypes.CDLL(None).prctl(36, 0, 0, 0, 0)                               # 시험 프로세스는 원래대로
_orig_cdll = TS.ctypes.CDLL
class _FakeLibc:
    def prctl(self, *a):
        return -1
TS.ctypes.CDLL = lambda *a, **k: _FakeLibc()
try:
    check(TS.set_subreaper() is not None, "prctl이 -1을 돌려주면 설정 실패로 봄 (반환값 확인)")
finally:
    TS.ctypes.CDLL = _orig_cdll
# 감독이 KILL로 죽어 '깨끗함'이 없으면 확인 필요
tr5 = HR.RealTrainer(child=str(sess_child), sleep=lambda s_: _time.sleep(0.05))
tr5.GRACE, tr5.KILL_WAIT = 30, 0.5                                       # 실행기가 감독을 오래 기다리지 않음
n5 = {"n": 0}
def tick5():
    n5["n"] += 1
    if n5["n"] > 12:
        raise access.AuthorityLost("권한 잃음")
try:
    tr5.train(str(ds), "s.pt", {"mode": "lost"}, str(TMP / "sup_kill"), lambda n: None, on_tick=tick5)
    r5 = "returned"
except HR.CleanupUnknown as e:
    r5 = "cleanup_unknown" if isinstance(e.__cause__, access.AuthorityLost) else "cleanup_unknown_nocause"
except Exception as e:
    r5 = type(e).__name__
check(r5 == "cleanup_unknown", f"감독이 정리를 마치지 못하고 강제로 끝나면 '정리 확인 불가'(확인 필요), 원래 원인 보존 — {r5}")
import subprocess as _sp5
_sp5.run(["pkill", "-9", "-f", str(TMP / "sup_kill")], check=False)
gp5 = int((TMP / "sup_kill/grandchild.pid").read_text() or 0)
if gp5 and alive_pid(gp5):
    os.kill(gp5, signal.SIGKILL)

# U2: 정리 확인 실패·신호 권한 오류 → CleanupUnknown (원래 예외는 원인으로 남음)
orig_killpg, orig_kill = os.killpg, os.kill
def deny(pid, sig):
    if sig != 0:
        raise PermissionError("모형")
    return orig_killpg(pid, sig)
n4 = {"n": 0}
def tick4():
    n4["n"] += 1
    if n4["n"] > 8:
        raise access.AuthorityLost("권한 잃음")
os.killpg, os.kill = deny, (lambda p_, s_: deny(p_, s_) if s_ else orig_kill(p_, s_))
try:
    tr2.train(str(ds), "s.pt", {"mode": "hang"}, str(TMP / "u2perm"), lambda n: None, on_tick=tick4)
    check(False, "권한 오류")
except HR.CleanupUnknown as e:
    check(isinstance(e.__cause__, access.AuthorityLost) and e.reason == "cleanup_unknown",
          "종료 신호 권한 오류는 '정리 확인 불가'(확인 필요)로, 원래 권한 상실은 원인으로 남음 (b26 U2)")
finally:
    os.killpg, os.kill = orig_killpg, orig_kill
    gp = int((TMP / "u2perm/grandchild.pid").read_text())
    for p_ in [gp] + [int(x) for x in os.listdir("/proc") if x.isdigit()]:
        st_ = HR._stat(p_)
        if st_ and p_ == gp:
            os.kill(p_, signal.SIGKILL)
    import subprocess as _sp
    _sp.run(["pkill", "-9", "-f", str(TMP / "u2perm")], check=False)       # 감독·자식 (권한 오류 모형으로 못 끝낸 것)
    _sp.run(["pkill", "-9", "-f", str(TMP / "stub_child.py")], check=False)

# U4: 자식의 설정·캐시·임시 폴더는 실행별 작업 폴더 안, 연동 환경 변수는 넘기지 않음
os.environ["MLFLOW_TRACKING_URI"] = "http://x"; os.environ["YOLO_CONFIG_DIR"] = "/shared/cfg"
envc = HR.RealTrainer().child_env(TMP / "u4wd")
os.environ.pop("MLFLOW_TRACKING_URI"); os.environ.pop("YOLO_CONFIG_DIR")
root4 = str(TMP / "u4wd") + os.sep
check(all(envc[k].startswith(root4) for k in ("YOLO_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "TMPDIR", "HOME", "TORCH_HOME"))
      and "MLFLOW_TRACKING_URI" not in envc and envc["YOLO_OFFLINE"] == "1",
      "학습 자식 환경: 설정·캐시·임시·홈 폴더가 실행별 작업 폴더 안, 외부 기록 연동 변수는 빼고 넘김 (b26 U4)")
import importlib.util as _ilu
spec_tc = _ilu.spec_from_file_location("tc", str(PKG / "scripts/train_child.py")); tc = _ilu.module_from_spec(spec_tc); spec_tc.loader.exec_module(tc)
os.environ.update({"YOLO_CONFIG_DIR": "/shared/cfg", "XDG_CONFIG_HOME": str(TMP / "u4wd/x"), "TMPDIR": str(TMP / "u4wd/t")})
try:
    tc.check_own_dirs(str(TMP / "u4wd")); check(False, "밖")
except SystemExit:
    check(True, "학습 자식은 설정 폴더가 작업 폴더 밖이면 시작하지 않음 (b26 U4)")
finally:
    for k in ("YOLO_CONFIG_DIR", "XDG_CONFIG_HOME", "TMPDIR"):
        os.environ.pop(k, None)
check("settings.update" in (PKG / "scripts/train_child.py").read_text() and "wandb" in (PKG / "scripts/train_child.py").read_text(),
      "학습 자식은 실행 전용 설정에서 외부 기록 연동(wandb·mlflow 등)을 끔")

# U3: train.json 하위 값·legacy 경로 값이 틀려도 정상 모델은 목록에
bad_tj = TMP / "bad_train.json"; bad_tj.write_text(json.dumps({"metrics": [1], "args": [1], "classes": "x"}))
H.publish_version(ms, "model", "badmeta", "train_m", {"best.pt": str(bw), "train.json": str(bad_tj)})
ms.write_json("runs/badmeta/CURRENT.json", {"version": "train_m"})
ms.write_json("runs/badlegacy/v/legacy/_files.json", {"files": {"best.pt": {"sha256": "a" * 64, "size": 1},
              "results.csv": {"sha256": "b" * 64, "size": 1}}, "verified": True, "legacy": True,
              "paths": {"best.pt": "runs/badlegacy/weights/best.pt", "results.csv": ["x"]}})
ms.write_json("runs/badlegacy/CURRENT.json", {"version": "legacy"})
sk3 = []
am3 = HA.adopted_models(ms, sk3)
rows3 = {r["name"]: r for r in HA.model_rows(am3)}
check("fruit_n" in rows3 and "badmeta" in rows3 and rows3["badmeta"]["map50"] is None and rows3["badmeta"]["classes"] is None
      and ["badlegacy", "legacy_paths_invalid"] in sk3,
      "train.json 하위 값이 틀리면 그 칸만 비우고, legacy 경로 값이 틀리면 그 모델만 뺌 — 정상 모델 그대로 (b26 U3)")

os.environ.pop(access.MODE_VAR, None)
shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
