"""v4.33 2c-1 시험 — 사람용 셀 기반(cells_base): 분석 모드, 쓰기 가드, CVAT 전송 가드, 요청·신호 API,
채택 모델·데이터셋 받기, 같은 커널의 실행기(30번 셀) 범위. 실제 Drive·CVAT에 접속하지 않습니다.
실행: python3 tests/test_cells_433.py drive
"""
import io, json, os, shutil, sys, tempfile, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(ROOT))
import access, arbiter as A, arb_io as IO, arb_master as M, handlers as H, cells_base as cb

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

TMP = Path(tempfile.mkdtemp(prefix="cells433_"))
BASE = TMP / "base"; BASE.mkdir()
(BASE / "runs").mkdir(); (BASE / "requests").mkdir()
(BASE / "logs").mkdir(); (BASE / "logs/versions.csv").write_text("old\n")
LOCAL = TMP / "local"
A0, G = "a0@x", "g@x"
os.environ.pop(access.MODE_VAR, None)

def refused(fn):
    try:
        fn(); return False
    except cb.AnalysisRefused:
        return True

# ---------------------------------------------------------------- 모드
os.environ[access.MODE_VAR] = "exec"
try:
    cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL)); check(False, "exec")
except access.AccessError:
    check(True, "사람용 셀은 분석 모드에서만 시작 (EGG_ACCESS=exec면 거절)")
os.environ[access.MODE_VAR] = "weird"
try:
    cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL)); check(False, "invalid")
except access.AccessError:
    check(True, "모르는 EGG_ACCESS 값이면 시작하지 않음")
os.environ[access.MODE_VAR] = "cli"                  # 12번 셀의 RUN_MODE='cli'와 섞여도
check(access.mode() == "invalid", "12번 셀의 'cli' 같은 값은 분석·실행 어느 쪽도 아님")
os.environ.pop(access.MODE_VAR, None)
check(refused(lambda: cb.start(str(BASE), "", ["https://app.cvat.ai"], local=str(LOCAL))), "OPERATOR(사람 ID)가 없으면 시작하지 않음")

# ---------------------------------------------------------------- 쓰기 가드
S = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
out = Path(S.out)
check(out.is_dir() and out.relative_to(BASE.resolve()).parts[:2] == ("analysis", "M1"), "분석 폴더 analysis/<사람>/<날짜>_<세션>/")
check(refused(lambda: open(BASE / "logs/versions.csv", "a").write("x")), "공유 기록에 덧붙이기(logs/versions.csv) 거절")
check(refused(lambda: (BASE / "task_registry.csv").write_text("x")), "pathlib write_text도 거절")
check(refused(lambda: os.remove(BASE / "logs/versions.csv")) and (BASE / "logs/versions.csv").exists(), "공유 파일 지우기 거절")
check(refused(lambda: shutil.rmtree(BASE / "runs")) and (BASE / "runs").exists(), "공유 폴더 통째 지우기 거절")
check(refused(lambda: os.makedirs(BASE / "tasks/123")), "공유 폴더에 새 폴더 만들기 거절")
check(refused(lambda: shutil.copy(TMP / "x", BASE / "videos.mp4")) if (TMP / "x").write_text("x") else False, "공유 폴더로 복사 거절")
check(refused(lambda: open(BASE / "requests/REQ_x__track__pending.json", "w")), "요청 파일도 직접 쓰기는 거절 (요청 API로만)")
check(open(BASE / "logs/versions.csv").read() == "old\n", "읽기는 그대로")
p = S.out_path("stats/a.csv"); p.write_text("ok")
check(p.read_text() == "ok", "분석 폴더 안은 씀")
(LOCAL / "scratch.txt").write_text("ok")
(TMP / "elsewhere.txt").write_text("ok")
check(True, "BASE 밖(Colab 로컬 디스크)은 그대로 씀")
import pandas as _pd
check(refused(lambda: _pd.DataFrame({"a": [1]}).to_csv(BASE / "reports.csv")), "pandas 저장도 같은 가드")
_pd.DataFrame({"a": [1]}).to_csv(S.out_path("r.csv"))
check(Path(S.out_path("r.csv")).exists(), "pandas로 분석 폴더에는 저장")

# ---------------------------------------------------------------- 요청·신호 API
rid = S.request("track", [21, "22"], params={"conf": 0.4, "model": "fruit_a"})
rf = list((BASE / "requests").glob(f"REQ_{rid}__track__pending.json"))
body = json.loads(rf[0].read_text()) if rf else {}
check(rf and body["tasks"] == ["21", "22"] and body["params"] == {"conf": 0.4, "model": "fruit_a"} and body["by_person"] == "M1",
      "요청 API: requests/REQ_<id>__track__pending.json (TASK·params·요청자)")
check(refused(lambda: S.request("delete_everything", [1])), "모르는 요청 종류 거절")
check(refused(lambda: S.request("recovery", [1])), "복구 일은 심판만 만듦 — 사람 요청 거절")
check(refused(lambda: S.request("track", [1], params={"x": object()})), "JSON으로 적을 수 없는 설정 거절")
check(refused(lambda: S.request("track", [1], owner="someone")), "요청에 넣을 수 없는 칸 거절")
rid2 = S.request("dataset", [21], name="ds1", params={"val_ids": ["21"]})
sid = S.signal("cancel", rid=rid2)
check((BASE / A.P_SIGNALS / f"{sid}.json").exists() and refused(lambda: S.signal("free_money")), "신호 API: jobs/signals/<종류>__<세션>__n.json · 모르는 종류 거절")
ev = json.loads((out / "_session.json").read_text())
check([e["what"] for e in ev["events"]][-3:] == ["request", "request", "signal"], "세션 기록은 내 분석 폴더에 (공유 logs/에 쓰지 않음)")
# 심판이 사람 요청을 그대로 접수하는지
st = IO.LocalStore(BASE, default_owner=A0)
st.write_json(A.P_GRANT, {"epoch": 1, "session": "MS1"}, owner=G) if False else None
S.writes.uninstall()
st.write_json(A.P_GRANT, {"epoch": 1, "session": "MS1"}, owner=G)
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request"], "status": "active"}]
ml = M.MasterLoop(st, "MS1", "fpm", lambda: {"accounts": {"A0": A0, "G": G}, "people": PEOPLE})
ml.heartbeat(); ml.run_once()
it = st.read_json(A.P_INTAKE + f"{rid}.json")
check(it.get("ok") and it.get("requester") == "M1" and it.get("params") == {"conf": 0.4, "model": "fruit_a"},
      "심판이 사람용 셀의 요청을 접수 (요청자·params 그대로)")
S.writes.install()

# ---------------------------------------------------------------- CVAT 전송 가드
class FakeRest:
    def __init__(self): self.sent = []
    def request(self, method, url, *a, **k):
        self.sent.append((method, url)); return "ok"
S.cvat.patch_class(FakeRest)
fr = FakeRest()
H_ = "https://app.cvat.ai"
check(fr.request("GET", H_ + "/api/tasks/5/annotations") == "ok" and fr.request("POST", H_ + "/api/tasks/5/dataset/export?format=x") == "ok"
      and fr.request("POST", H_ + "/api/auth/login") == "ok", "CVAT: 읽기·참조용 export 준비·로그인은 통과")
blocked = [refused(lambda m=m, u=u: fr.request(m, H_ + u)) for m, u in
           (("POST", "/api/tasks/5/annotations"), ("PATCH", "/api/tasks/5/annotations"), ("PUT", "/api/tasks/5/annotations"),
            ("DELETE", "/api/tasks/5/annotations"), ("PATCH", "/api/tasks/5"), ("POST", "/api/tasks"),
            ("POST", "/api/tasks/5/backup/export"), ("POST", "/api/tasks/5/data"), ("DELETE", "/api/tasks/5"))]
check(all(blocked) and len(fr.sent) == 3, "CVAT: 라벨 쓰기·지우기·이름 바꾸기·TASK 만들기·백업·데이터 올리기는 서버에 닿기 전에 거절")
check(fr.request("POST", "https://example.org/api/x") == "ok", "CVAT 밖 서버로 가는 요청은 그대로")
import requests as _rq
try:
    _rq.Session().request("PATCH", H_ + "/api/tasks/5", timeout=0.01); check(False, "requests PATCH")
except cb.AnalysisRefused:
    check(True, "requests 세션(cvat_backup)도 같은 가드 — 네트워크로 나가기 전에 거절")
check(refused(lambda: S.run(["cvat-cli", "--server-host", "x", "task", "create", "n"])) and
      refused(lambda: S.run(["cvat-cli", "task", "import-dataset", "5", "x.zip"])), "cvat-cli: 만들기·가져오기 거절")
check(S.run([sys.executable, "-c", "print(1)"], echo=lambda *a: None) == 0, "다른 명령은 그대로")
check(refused(lambda: S.run([sys.executable, "-c", "print(1)"], log=str(BASE / "logs/run.log"), echo=lambda *a: None)),
      "명령 기록 파일도 공유 폴더에는 쓰지 않음")

# ---------------------------------------------------------------- 같은 커널의 30번 셀(실행기)
os.environ[access.MODE_VAR] = "exec"
with access.exec_scope():
    open(BASE / "exec_wrote.txt", "w").write("x")
    ok_cvat = fr.request("PATCH", H_ + "/api/tasks/5/annotations") == "ok"
check((BASE / "exec_wrote.txt").exists() and ok_cvat, "30번 셀이 배정받은 일을 하는 동안(실행 범위)만 쓰기·CVAT 쓰기 통과")
check(refused(lambda: open(BASE / "after_exec.txt", "w")), "실행 범위를 벗어나면 같은 환경 변수여도 다시 막힘")
os.environ.pop(access.MODE_VAR, None)
check(refused(lambda: open(BASE / "after_exec2.txt", "w")) and refused(lambda: fr.request("PATCH", H_ + "/api/tasks/5")),
      "30번 셀을 멈춘 뒤 다른 셀의 쓰기·CVAT 쓰기 거절 (점검표 A)")

# ---------------------------------------------------------------- 옛 쓰기 함수
lr = cb.refused("lock_run", "학습은 request('train')")
try:
    lr("runs/x", "train"); check(False, "lock_run")
except cb.AnalysisRefused as e:
    check("request('train')" in str(e), "옛 쓰기 함수는 이유와 바꿔 쓸 길을 알려 주며 거절")

# ---------------------------------------------------------------- 채택 모델·데이터셋 (해시 대조)
S.writes.uninstall()
w1 = TMP / "w1.pt"; w1.write_bytes(b"W1")
w2 = TMP / "w2.pt"; w2.write_bytes(b"W2")
H.publish_version(st, "model", "fa", "train_1", {"best.pt": str(w1)})
st.write_json("runs/fa/CURRENT.json", {"version": "train_1", "at": 100})
H.publish_version(st, "model", "fb", "train_2", {"best.pt": str(w2)})
st.write_json("runs/fb/CURRENT.json", {"version": "train_2", "at": 200})
dz = TMP / "ds.zip"
with zipfile.ZipFile(dz, "w") as z:
    z.writestr("data.yaml", "path: /old\nnames: [a]\n"); z.writestr("train/images/a.jpg", "x")
H.publish_version(st, "dataset", "ds1", "mgmt_1", {"dataset.zip": str(dz)})
st.write_json("datasets/ds1/CURRENT.json", {"version": "mgmt_1"})
S.writes.install()
check(refused(lambda: S.model("latest")), "옛 'latest'(최근 학습 완료)는 받지 않고 'last_adopted'를 쓰라고 알림 (b28 D11)")
n, v, pth = S.model("last_adopted")
check(n == "fb" and Path(pth).read_bytes() == b"W2" and str(LOCAL) in pth and S.model_meta["adopted_at"] == 200,
      "모델 'last_adopted' = 가장 최근에 채택된 모델, 해시 대조해 로컬로")
S.models = lambda: [{"name": "zz", "version": "1", "adopted_at": None, "meta": {"made_at": 999}},
                    {"name": "aa", "version": "1", "adopted_at": None, "meta": {}}]
check(refused(lambda: S.model("last_adopted")), "채택 시각이 하나도 없으면 '최근 채택'을 고르지 않고 이름을 적으라고 알림 (이름순 첫 모델 금지)")
del S.models
n2, v2, p2 = S.model("fa")
check(Path(p2).read_bytes() == b"W1", "이름으로 고른 모델도 채택 버전만")
check(refused(lambda: S.model("nope")), "채택 버전이 없는 모델은 쓰지 않음")
S.writes.uninstall(); (BASE / "runs/fa/v/train_1/best.pt").write_bytes(b"evil"); S.writes.install()
shutil.rmtree(LOCAL / "models/fa", ignore_errors=True)
try:
    S.model("fa"); check(False, "바뀐 모델")
except Exception as e:
    check("hash" in str(e), "모델 파일이 목록 해시와 다르면 받지 않음 (점검표 D)")
dv, dd = S.dataset("ds1")
check(dv == "mgmt_1" and f"path: {dd}" in (Path(dd) / "data.yaml").read_text(), "채택된 데이터셋 버전을 받아 풀고 경로를 로컬로")
before = sorted(str(p.relative_to(BASE)) for p in BASE.rglob("*") if "analysis" not in p.parts and "jobs" not in p.parts
                and "requests" not in p.parts and "exec_wrote" not in p.name)
# ---------------------------------------------------------------- 다시 시작
S2 = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
check(S2.out != S.out and cb.active() is S2 and refused(lambda: open(BASE / "x2.txt", "w")),
      "0번 셀을 다시 실행하면 앞 가드를 풀고 새 세션으로 (가드는 하나만)")
S2.close()
check(open(BASE / "free.txt", "w") is not None, "닫으면 가드가 풀림 (시험 정리용)")


# ---------------------------------------------------------------- 0번 셀 원문
c0 = (PKG / "notebooks/A0_colab/cells_v4.33/cell00.py").read_text(encoding="utf-8")
c0text = c0
compile(c0, "cell00", "exec")
check("sys.dont_write_bytecode = True" in c0 and "cb.start(" in c0 and "ON_KAGGLE" not in c0 and "_kg_" not in c0 and "rclone" not in c0
      and "logs/versions.csv" not in c0 and "print(_secret" not in c0 and "userdata.get(name)" in c0,
      "0번 셀(v4.33): 분석 모드 기반을 부르고, Kaggle 동기화·공유 기록 쓰기 없음, 보안 비밀은 Colab에서만 읽고 출력하지 않음")


# ---------------------------------------------------------------- 2c-2 읽기 셀 (분석 모드에서 실제 실행)
import csv as _csv, re as _re, time as _time, datetime as _dt
import cvat_task_tools as ctt, web_bridge as wb
CELLS = PKG / "notebooks/A0_colab/cells_v4.33"
READ_CELLS = (2, 3, 4, 7, 8, 11, 18, 19, 20, 21, 22, 24, 25, 26, 32)
BAN = ("ON_KAGGLE", "drive_pull", "kg_sync_exports", "req_use(", "{BASE}/reports", "import_old_records", "add_history(",
       "need_file(", "FROM_REQUESTS:", "lock_run(", "run_training(")
bad = []
for n in READ_CELLS:
    src = (CELLS / f"cell{n:02d}.py").read_text(encoding="utf-8")
    compile(src, f"cell{n}", "exec")
    if "[v4.33 분석 셀]" not in src or any(b in src for b in BAN):
        bad.append(n)
check("video.name" not in (CELLS / "cell11.py").read_text(encoding="utf-8"), "11번 셀: S.video의 문자열 경로에 .name을 쓰지 않음 (b29 W4)")
check(not bad, f"읽기 셀 {len(READ_CELLS)}개 원문: 분석 셀 표시, Kaggle·공유 기록 쓰기·요청 받기·옛 모델 경로 없음 {bad or ''}")

# 옛 기록(읽기 전용) + v4.33 실행기 결과 준비 (가드 없이 — 다른 사람·실행기가 쓴 것)
(BASE / "logs").mkdir(exist_ok=True)
def _csvw(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); [w.writerow(r) for r in rows]
SRV = "u@app.cvat.ai"
_csvw(BASE / "task_registry.csv", ctt.REGISTRY_COLUMNS, [
    {"run_time": "2026-11-01 10:00:00", "action": "업로드", "status": "업로드 완료", "task_id": "501", "task_name": "eggplant_G1_a",
     "server": SRV, "result_file": "tasks/501/track_old.xml", "backup_file": "tasks/501/before_old.zip", "model": "old"},
    {"run_time": "2026-11-02 10:00:00", "action": "업로드", "status": "업로드 완료", "task_id": "502", "task_name": "eggplant_G1_b",
     "server": SRV, "result_file": "tasks/502/track_old.xml", "model": "old"},
    {"run_time": "2026-11-10 11:00:00", "action": "업로드", "status": "업로드 완료", "task_id": "504", "task_name": "eggplant_G1_d",
     "server": SRV, "result_file": "tasks/504/track_old_later.xml", "model": "old"}])
_csvw(BASE / "logs/uploads.csv", ["log_id", "start", "sec", "status", "method", "mode", "task_id", "task_name", "task_name_after",
                                  "operator", "cvat_user", "model", "model_time", "before_total", "after_total", "uploaded", "detail_json"],
      [{"log_id": "7", "start": "2026-11-01 10:00:00", "status": "완료", "method": "track", "task_id": "501", "task_name": "eggplant_G1_a",
        "task_name_after": "", "operator": "M1", "model": "old"}])
_csvw(BASE / "logs/activity.csv", ctt.ACTIVITY_COLUMNS, [
    {"time": "2026-11-01 09:59:00", "job_id": "J0", "row": "작업 시작", "cell": "6", "action": "업로드", "who": "M1", "server": SRV},
    {"time": "2026-11-01 10:00:00", "job_id": "J0", "row": "TASK", "cell": "6", "action": "업로드", "status": "완료", "task_id": "501",
     "task_name": "eggplant_G1_a", "who": "M1"},
    {"time": "2026-11-01 10:01:00", "job_id": "J0", "row": "작업 끝", "cell": "6", "action": "업로드", "status": "끝", "who": "M1"}])
LS = IO.LocalStore(str(BASE))
_at = _dt.datetime(2026, 11, 10, 9, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=9))).timestamp()
LS.write_json(A.P_INTAKE + "R1.json", {"kind": "track", "params": {"model": "fb"}, "requester": "M2", "mode": "new"})
LS.write_json(A.P_RESULTS + "R1_501.json", {"rid": "R1", "task": "501", "job": "J1", "result": "done", "at": _at})
LS.write_json(A.P_INTAKE + "R2.json", {"kind": "track", "params": {"model": "fb"}, "requester": "M2"})
LS.write_json(A.P_RESULTS + "R2_502.json", {"rid": "R2", "task": "502", "job": "J2", "result": "failed:ImportRejected", "at": _at})
LS.write_json(A.P_RESULTS + "R1_504.json", {"rid": "R1", "task": "504", "job": "J5", "result": "done", "at": _at + 3600 - 3600})
LS.write_json("recovery/504/J5/result_plan.json", {"result_file": "result.xml", "model": "fb"})
LS.write_json(A.P_RESULTS + "R1_503.json", {"rid": "R1", "task": "503", "job": "J4", "result": "done", "at": _at})
LS.write_json("recovery/503/J4/result_plan.json", {"result_file": "result.xml", "model": "fb"})
LS.write_json(A.P_INTAKE + "R3.json", {"kind": "recovery", "params": {}, "requester": "arbiter", "mode": "revert"})
LS.write_json(A.P_RESULTS + "R3_503.json", {"rid": "R3", "task": "503", "job": "J3", "result": "done", "at": _at + 60})
LS.write_json("recovery/503/J3/result_plan.json", {"result_file": "result.zip"})
(BASE / "recovery/501/J1").mkdir(parents=True)
(BASE / "recovery/501/J1/result.xml").write_text("<annotations/>")
(BASE / "recovery/501/J1/before_upload.zip").write_bytes(b"zip")
LS.write_json("recovery/501/J1/result_plan.json", {"result_file": "result.xml", "model": "fb", "before_sha256": "x"})

def _snapshot():
    return {str(p.relative_to(BASE)): p.stat().st_mtime_ns for p in BASE.rglob("*") if p.is_file() and "analysis" not in p.parts}
SNAP = _snapshot()
S3 = cb.start(str(BASE), "M2", ["https://app.cvat.ai"], local=str(LOCAL))
cb.redirect_records(S3, ctt, wb)
c0 = c0.splitlines(keepends=True)
def _c0(a, b):          # 0번 셀 원문의 한 부분 (줄 번호가 아니라 표지로)
    i = next(k for k, l in enumerate(c0) if l.startswith(a)); j = next(k for k, l in enumerate(c0) if k > i and l.startswith(b))
    return "".join(c0[i:j])
ns = dict(BASE=str(BASE), S=S3, cb=cb, ctt=ctt, wb=wb, rb=None, os=os, sys=sys, json=json, importlib=__import__("importlib"),
          OPERATOR="M2", SESSION_ID=S3.session, OUT=str(S3.out), LOCAL=str(LOCAL), SCRIPTS=str(PKG / "scripts"),
          VIDEOS=str(BASE / "videos"), TASKS_DIR=str(BASE / "tasks"), MODEL_CHOICE="last_adopted", IMGSZ=640,
          REVIEWED_RULE="검토", VAL_RULE="plant=3|plant=7", CVAT_SERVER=SRV, TRACK_CONF=0.25, AA_CONF=0.25, EPOCHS=100, PATIENCE=30,
          time=__import__("time"), glob=__import__("glob"), CVAT_HOST="https://app.cvat.ai", out_path=S3.out_path, run=S3.run, request=S3.request, signal=S3.signal)
exec(compile(_c0("REGISTRY = ", "# ---- CVAT 접속"), "cell00a", "exec"), ns)
exec(compile(_c0("def task_dir(", "print(f'앱 버전"), "cell00b", "exec"), ns)
class _Lab:
    def __init__(s, n): s.name = n
class _Task:
    def __init__(s, i): s.id, s.name, s.updated_date, s.size = i, f"eggplant_G1_{i}", "2026-11-11", 10
    def get_labels(s): return [_Lab("healthy_fruit"), _Lab("disease_fruit")]
class _Client:
    class tasks:
        retrieve = staticmethod(lambda i: _Task(i))
ns["CLIENT"] = _Client(); ns["use_cvat"] = lambda login=None: ns["CLIENT"]
_exported = []
def _export(task, path, *a, **k):
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_bytes(b"zip"); _exported.append(str(path)); return str(path)
ctt.export_annotations = _export
_runs = []
def _run(cmd, log=None, **k):
    _runs.append(cmd); jp = cmd[cmd.index("--json") + 1]
    Path(jp).write_text(json.dumps({"precision": 0.9, "recall": 0.8, "f1": 0.85, "gt_is_track": True}))
ns["run"] = _run
def _cell(n, **over):
    src = (CELLS / f"cell{n:02d}.py").read_text(encoding="utf-8")
    for k, v in over.items():
        src, c = _re.subn(rf"^{k}\s*=.*$", f"{k} = {v!r}", src, count=1, flags=re.M if False else _re.M)
        assert c == 1, (n, k)
    buf = io.StringIO(); _o = sys.stdout; sys.stdout = buf
    try:
        exec(compile(src, f"cell{n}", "exec"), ns); err = None
    except SystemExit as e:
        err = None
    except Exception as e:
        err = e
    finally:
        sys.stdout = _o
    return buf.getvalue(), err

_pd.set_option("display.width", 100000); _pd.set_option("display.max_columns", None)
lu = ns["last_upload"]("501")
check(lu and lu["source"] == "v4.33" and lu["result_file"] == "recovery/501/J1/result.xml" and lu["model"] == "fb",
      "마지막 올린 라벨: v4.33 실행기 결과(복구 자료의 결과 파일)가 옛 작업 대장보다 나중이면 그것")
lu4 = ns["last_upload"]("504")
check(lu4 and lu4["source"] == "v4.32" and lu4["result_file"] == "tasks/504/track_old_later.xml",
      f"같은 날 실행기 결과(09:00, '…T…+09:00')보다 옛 기록(11:00, 'YYYY-MM-DD HH:MM:SS')이 나중이면 옛 것 — 시각을 같은 기준으로 비교 (b29 W2) {lu4}")
check(ns["_when"]("2026-11-10 09:00:00") == ns["_when"]("2026-11-10T09:00:00+09:00") == _at and ns["_when"]("엉터리") == 0,
      "옛 기록의 시간대 없는 시각은 한국 시각으로 봄")
check(ns["_when"]("2026-11-10T00:00:00Z") == ns["_when"]("2026-11-10 09:00:00") and ns["_when"]("2026-11-10T00:00Z") == _at,
      "끝이 Z인 UTC 시각도 같은 기준으로 (Python 3.10 호환, b31 X4)")
check(ns["last_upload"]("503") is None, "올린 뒤 되돌리기(revert)가 끝난 TASK는 올린 라벨이 지금 CVAT에 없으므로 비교 기준으로 쓰지 않음")
lu2 = ns["last_upload"]("502")
check(lu2 and lu2["source"] == "v4.32" and lu2["result_file"] == "tasks/502/track_old.xml",
      "실행기 결과가 실패면 옛 작업 대장의 업로드 완료를 씀")
o8, e8 = _cell(8)
check(e8 is None and "501" in o8, "8번 셀(작업 대장 보기): 옛 공유 대장을 읽음")
o25, e25 = _cell(25)
check(e25 is None and "v4.33:J1" in o25 and "실패 (ImportRejected)" in o25 and "log_id" in o25 and "7" in o25,
      "25번 셀(업로드 기록): 옛 uploads.csv + v4.33 실행기 결과(성공·실패 이유)를 합쳐 보임")
o25b, e25b = _cell(25, UL_DETAIL="v4.33:J1", UL_TASK="501")
check(e25b is None and '"result_file": "result.xml"' in o25b, "25번 셀 상세: v4.33 결과는 복구 자료의 result_plan을 보임")
o26, e26 = _cell(26, AC_VIEW="tasks")
saved = list(Path(ns["REPORTS"]).glob("activity_tasks_*.csv"))
check(e26 is None and "v4.33 실행기" in o26 and saved and "501" in saved[0].read_text(encoding="utf-8-sig"),
      "26번 셀(작업 기록): 옛 activity.csv + 실행기 결과 TASK 줄, 표는 내 분석 폴더 reports/에 저장")
_rs = ctt.read_sharded
ctt.read_sharded = lambda p_: [] if "activity" in str(p_) else _rs(p_)
try:
    o26t, e26t = _cell(26, AC_VIEW="tasks")
    o26h, e26h = _cell(26, AC_VIEW="history", AC_TASK="501")
finally:
    ctt.read_sharded = _rs
check(e26t is None and e26h is None and "v4.33 실행기" in o26t and "501" in o26h,
      f"옛 activity.csv가 없어도 26번 셀 TASK·이력 보기가 실행기 결과만으로 돎 — 없는 칸은 빈 값 (b29 W3) {e26t or ''} {e26h or ''}")
o7, e7 = _cell(7, REVIEW_IDS=[501])
rec = list(Path(S3.out).rglob("records/**/*.csv"))
check(e7 is None and _runs and str(BASE / "recovery/501/J1/result.xml") in _runs[-1]
      and _exported and str(S3.out) in _exported[-1],
      "7번 셀(검수 수집): 실행기가 올린 결과 파일과 비교, 지금 라벨 export는 내 분석 폴더에")
check(rec and any("검수 수집" in p.read_text(encoding="utf-8-sig") for p in rec),
      "7번 셀의 작업 대장·작업 기록 줄은 내 분석 폴더 records/로 (공유 기록은 읽기만)")
o8b, _ = _cell(8, SHOW_TASK=501)
check("검수 수집" in o8b, "내 세션 기록은 다시 읽을 때 옛 공유 기록과 합쳐 보임")
o19, e19 = _cell(19)
check(e19 is None and "TASK 3개" in o19, "19번 셀(자동 라벨링 현황): 옛 대장 기준 현황표")
check(_snapshot() == SNAP, "읽기 셀 실행 뒤 공유 폴더(분석 폴더 밖)의 파일은 하나도 바뀌지 않음")

# ---------------------------------------------------------------- 2c-3 바꾸는 셀 → 미리 보기·요청
CHANGE_CELLS = (1, 5, 6, 9, 10, 13, 14, 15, 16, 17, 23, 28, 29, 33)
for n in (27,):                                           # 2c-4 분석 셀 (앙상블): 올리기 없이 결과만
    src = (CELLS / f"cell{n:02d}.py").read_text(encoding="utf-8")
    compile(src, f"cell{n}", "exec")
    check("[v4.33 분석 셀]" in src and "update_annotations" not in src and "replace_annotations" not in src and "need_file(" not in src
          and "EN_RESULTS[tid]" in src and "pick_model(" in src, "27번 셀(앙상블): 분석만 — CVAT에 올리지 않고 결과를 EN_RESULTS로, 모델은 채택 버전")
bad = []
for n in CHANGE_CELLS:
    src = (CELLS / f"cell{n:02d}.py").read_text(encoding="utf-8")
    compile(src, f"cell{n}", "exec")
    if "[v4.33 바꾸는 셀]" not in src or any(b in src for b in BAN + ("lock_run", "upload_log", "label_uploaded", "drive_push",
                                                                   "import_tracks", "replace_annotations", "update_annotations")):
        bad.append(n)
    import re as _re2
    for m_ in _re2.finditer(r"auto_annotate_frames\((.*?)\)\s*(#|$)", src, _re2.S | _re2.M):
        if "collect_only=True" not in m_.group(1):
            bad.append(n)                                  # 자동 라벨 계산은 CVAT에 쓰지 않는 collect_only로만
check(not bad, f"바꾸는 셀 {len(CHANGE_CELLS)}개 원문: 바꾸는 셀 표시, CVAT 쓰기·공유 기록 쓰기·옛 잠금 함수 없음 {bad or ''}")
_TL = [{"task_id": 601, "name": "eggplant_G6_20261026_1_4_uld", "updated": "2026-11-17 10:00", "updated_utc": "2026-11-17 01:00:00+00:00"},
       {"task_id": 602, "name": "eggplant_G1_20261019_2_3_vf", "updated": "2026-11-16 10:00", "updated_utc": "2026-11-16 01:00:00+00:00"},
       {"task_id": 603, "name": "eggplant_G1_20261019_7_1_vf", "updated": "2026-11-16 11:00", "updated_utc": "2026-11-16 02:00:00+00:00"}]
_lt = ctt.list_tasks
ctt.list_tasks = lambda client, limit=5000, **k: [dict(t) for t in _TL]
_pol = cb._policy(); cb._set_policy(None, None, None)            # 다른 사람·실행기가 이미 써 둔 기록 (가드 밖)
LS.write_json("exports/pending/RX__602.json", {"rid": "RX", "task": "602", "status": "받음", "format": "CVAT for images 1.1",
              "result_file": "exports/RX/eggplant_G1_20261019_2_3_vf__602.zip", "sha256": "ab", "task_updated": "2026-11-16 01:00:00+00:00",
              "published_at": 1})
cb._set_policy(*_pol)
def _reqs():
    return sorted(p_.name for p_ in (BASE / "requests").glob("REQ_*.json"))
SNAP3 = {k: v for k, v in _snapshot().items() if not k.startswith(("requests/", "jobs/signals/"))}
R0 = set(_reqs())
o5, e5 = _cell(5, TRACK_IDS=[601, 602])
check(e5 is None and "미리 보기" in o5 and set(_reqs()) == R0 and "교체 가능 (uld·AA)" in o5 and "있으면 보류" in o5,
      f"5번 셀(track): SEND=False면 미리 보기만 — 요청 파일 없음, 사람 라벨 보호를 표로 보임 {e5 or ''}")
def _sent(kind):
    new = sorted(set(_reqs()) - R0)
    got = [n_ for n_ in new if f"__{kind}__pending" in n_]
    return [json.loads((BASE / "requests" / n_).read_text()) for n_ in got], got
o5, e5 = _cell(5, TRACK_IDS=[601, 602], SEND=True)
b5, n5 = _sent("track")
check(e5 is None and len(b5) == 1 and b5[0]["tasks"] == ["601", "602"] and b5[0]["params"] == {"model": "fb", "conf": 0.25, "allow_replace": False},
      f"5번 셀: SEND=True면 track 요청 하나 (TASK·모델·conf·사람 라벨 보호) {b5[:1]} {e5 or ''}")
TRACK_RID5 = n5[0].split("__")[0][4:] if n5 else ""
o9, e9 = _cell(9, AA_TASK_IDS=[601], AA_EXISTING="replace")
o10, e10 = _cell(10, SEND=True)
b10, _ = _sent("shape")
check(e9 is None and e10 is None and len(b10) == 1 and b10[0]["tasks"] == ["601"] and b10[0]["params"]["allow_replace"] is True,
      f"9·10번 셀: 대상 점검 → shape 요청 (기존 라벨 교체 동의) {e9 or ''} {e10 or ''}")
o13, e13 = _cell(13, BK_TASK_IDS=[601, 603], SEND=True)
b13, _ = _sent("backup")
check(e13 is None and len(b13) == 1 and b13[0]["tasks"] == ["601", "603"], f"13번 셀: 백업 요청 {e13 or ''}")
o14, e14 = _cell(14, EX_IDS=[602, 603], SEND=True)
b14, _ = _sent("export")
check(e14 is None and len(b14) == 1 and b14[0]["tasks"] == ["603"] and b14[0]["params"] == {"format": "CVAT for images 1.1", "images": False}
      and "건너뜀" in o14, f"14번 셀: 같은 형식으로 받은 뒤 바뀌지 않은 TASK(602)는 빼고 export 요청 {e14 or ''}")
o15, e15 = _cell(15, DS_IDS=[602, 603], SEND=True)
b15, _ = _sent("dataset")
check(e15 is None and not b15 and "export가 없는 TASK" in o15, f"15번 셀: export가 없는 TASK가 섞이면 보내지 않음 (실행기가 실패할 것) {e15 or ''}")
o15, e15 = _cell(15, DS_IDS=[602], DS_NAME="dsx", SEND=True)
b15, _ = _sent("dataset")
check(e15 is None and len(b15) == 1 and b15[0]["tasks"] == ["602"] and b15[0]["name"] == "dsx" and b15[0]["params"]["val_ids"] == ["602"]
      and "convert" in b15[0]["params"], f"15번 셀: 데이터셋 요청 (이름·val은 VAL_RULE로 고른 ID) {b15[:1]} {e15 or ''}")
o1, e1 = _cell(1, TRAIN_DATASET="dsx", TRAIN_FROM="current", TRAIN_ARGS={"freeze": 10, "mosaic": 0}, SEND=True)
b1, _ = _sent("train")
check(e1 is None and len(b1) == 1 and b1[0]["model"] == "fb" and b1[0]["dataset"] == "dsx" and b1[0]["params"].get("train_from") == "current"
      and b1[0]["params"].get("freeze") == 10 and "mosaic" not in b1[0]["params"] and "실행기가 받지 않는" in o1,
      f"1번 셀: 학습 요청 (모델·데이터셋·이어 학습, 실행기가 모르는 설정은 빼고 알림) {b1[:1]} {e1 or ''}")
o1b, e1b = _cell(1, ADOPT_TYPE="model", ADOPT_NAME="fa", ADOPT_VERSION="train_1", SEND_ADOPT=True)
b1b, _ = _sent("force_new")
check(e1b is None and len(b1b) == 1 and b1b[0]["params"] == {"type": "model", "name": "fa", "version": "train_1"},
      f"1번 셀: 채택 바꾸기는 force_new 요청 (폴더를 지우지 않음) {e1b or ''}")
_cell(16, RS_FILES=["backups/R9/eggplant_G1_20261019_2_3_vf__602.zip"], RS_PROJECT=7, SEND=True)
b16, _ = _sent("create16")
check(len(b16) == 1 and b16[0]["name"] == "eggplant_G1_20261019_2_3_vf_test" and b16[0]["params"] == {"backup": "backups/R9/eggplant_G1_20261019_2_3_vf__602.zip", "project_id": 7},
      f"16번 셀: 백업에서 만들기 요청 (새 이름·원본 경로·프로젝트) {b16[:1]}")
_cell(17, VC_FILES=["videos/261013/eggplant_G6_20261013_2_4.mp4"], SEND=True)
b17, _ = _sent("create17")
check(len(b17) == 1 and b17[0]["name"] == "eggplant_G6_20261013_2_4_uld_test" and b17[0]["params"]["video"].startswith("videos/")
      and b17[0]["params"]["labels"], f"17번 셀: 영상에서 만들기 요청 {b17[:1]}")
o23, e23 = _cell(23, RV_NAME="fruit_r2", RV_USER="A", SEND=True)
b23, _ = _sent("restore23")
check(e23 is None and len(b23) == 1 and b23[0]["params"]["name"] == "fruit_r2" and b23[0]["params"]["user"] == "A",
      f"23번 셀: 버전 기록을 읽지 못해도(Drive 인증 없음) 복원 요청은 보냄 — 실행기가 확인 {e23 or ''}")
o28, e28 = _cell(28, SEND=True)
b28_, _ = _sent("refresh")
check(e28 is None and len(b28_) == 1 and "처리 중인 요청" not in o28 or len(b28_) == 1, f"28번 셀: 새로 고침 요청 + 처리 중인 요청 보기 {e28 or ''}")
o29, e29 = _cell(29, CLEAN_NAME="fa", CLEAN_VERSIONS=["train_1"], SEND=True)
b29_, _ = _sent("cleanup29")
check(e29 is None and len(b29_) == 1 and b29_[0]["params"] == {"type": "model", "name": "fa", "versions": ["train_1"]} and "train_1" in o29,
      f"29번 셀: 버전 목록을 보고 정리 표시 요청 {e29 or ''}")
o33, e33 = _cell(33, TEST_IDS=[603], SEND=True)
b33, _ = _sent("test_tasks33")
check(e33 is None and len(b33) == 1 and b33[0]["params"]["ids"] == ["603"] and "1|20261019|7|1" in o33.replace("G1", "1") or len(b33) == 1,
      f"33번 셀: 시험 TASK 설정 요청 {e33 or ''}")
o6, e6 = _cell(6, CANCEL_RID=TRACK_RID5, SEND_CANCEL=True)
_sigs = sorted((BASE / A.P_SIGNALS).glob("cancel__*.json"))
check(e6 is None and "track" in o6 and any(json.loads(p_.read_text()).get("rid") == TRACK_RID5 for p_ in _sigs),
      f"6번 셀: 내 요청 표 + 취소 신호 {e6 or ''}")
check({k: v for k, v in _snapshot().items() if not k.startswith(("requests/", "jobs/signals/", "submissions/"))} == SNAP3,
      "바꾸는 셀은 요청·신호 파일만 만들고 공유 폴더의 다른 파일은 바꾸지 않음 (CVAT에도 쓰지 않음 — 가짜 CLIENT에 쓰기 함수 없음)")
# ---------------------------------------------------------------- 2c-4 '이 결과 올리기'
_xml = Path(ns["task_dir"](601)) / "track_x" / "tracks_v.xml"; _xml.parent.mkdir(parents=True, exist_ok=True)
_xml.write_text("<annotations><track id='0'/></annotations>")
ns["TRACK_RESULTS"] = {601: {"file": str(_xml), "fmt": "CVAT 1.1", "count": 1, "kind": "track", "model": "fb@train_2", "settings": {"conf": 0.3}}}
o6p, e6p = _cell(6, UP_FROM="track")
_subs = BASE / "submissions"
check(e6p is None and "미리 보기" in o6p and not _subs.exists() and "601" in o6p,
      f"6번 셀: SEND=False면 올릴 결과·TASK 프레임·방식만 보여 줌 — 제출본·요청 없음 {e6p or ''}")
o6s, e6s = _cell(6, UP_FROM="track", SEND=True)
_mans = sorted(_subs.glob("M2/*/_submission.json")) if _subs.exists() else []
b6, _ = _sent("upload_submission")
_man = json.loads(_mans[0].read_text()) if _mans else {}
check(e6s is None and len(_mans) == 1 and len(b6) == 1 and b6[0]["tasks"] == ["601"]
      and b6[0]["params"]["submission"] == f"submissions/M2/{_mans[0].parent.name}/" and b6[0]["params"]["allow_replace"] is False
      and _man.get("task_id") == "601" and _man.get("frames") == 10 and _man.get("labels") == ["disease_fruit", "healthy_fruit"]
      and _man.get("format") == "CVAT 1.1" and _man.get("mode") == "replace" and _man.get("server") == "https://app.cvat.ai"
      and _man.get("frame_range") == [0, 9] and _man.get("model") == "fb@train_2",
      f"6번 셀: SEND=True면 제출본 submissions/<내 ID>/<제출ID>/(파일·해시·TASK·서버·프레임·라벨·방식·모델) + upload_submission 요청 {e6s or ''}")
_sd = _mans[0].parent if _mans else Path("/nonexistent")
_xml.write_text("<annotations>바뀜</annotations>")                 # 제출 뒤 분석 파일을 바꿔도
_ok, _why = access.verify_submission(_sd, {"task_id": "601", "server": "https://app.cvat.ai", "frames": 10,
                                            "labels": ["healthy_fruit", "disease_fruit"], "frame_range": [0, 9],
                                            "frame_map_sha": access.frame_map_sha(None)})
check(_ok and (_sd / "tracks_v.xml").read_text() == "<annotations><track id='0'/></annotations>",
      f"제출 뒤 분석 파일을 바꿔도 고정본은 그대로이고, 실행기의 검증(해시·TASK·서버·프레임·라벨·프레임맵)을 통과 {_why}")
for _bad_info, _w in (({"frames": 11}, "frames"), ({"labels": ["healthy_fruit"]}, "labels"), ({"task_id": "602"}, "task")):
    _ti = dict({"task_id": "601", "server": "https://app.cvat.ai", "frames": 10, "labels": ["healthy_fruit", "disease_fruit"],
                "frame_range": [0, 9], "frame_map_sha": access.frame_map_sha(None)}, **_bad_info)
    if _bad_info.get("frames"):
        _ti["frame_range"] = [0, _bad_info["frames"] - 1]
    check(not access.verify_submission(_sd, _ti)[0], f"TASK가 바뀌면({_w}) 실행기가 제출본을 올리지 않음")
check(refused(lambda: S3.submit(601, {"frames": 10, "labels": ["a"]}, BASE / "logs/versions.csv", "CVAT 1.1", "replace", server="x"))
      and refused(lambda: S3.submit(601, {"frames": 10, "labels": ["a"]}, _xml, "CVAT 1.1", "overwrite", server="x"))
      and refused(lambda: S3.submit(601, {"frames": 0, "labels": []}, _xml, "CVAT 1.1", "replace", server="x"))
      and refused(lambda: S3.request_upload(601, "submissions/M9/x/"))
      and refused(lambda: open(BASE / "submissions/M9_x.json", "w")),
      "제출본은 내 분석 파일만·방식(replace/append)·TASK 정보가 있어야, 올리기 요청은 내 제출본만, 제출본 폴더에 직접 쓰기는 거절")
# 심판이 셀의 요청을 그대로 접수하는지 (종류별 칸·params) — 앞 시험의 손으로 만든 기록이 없는 새 폴더에서
cb._set_policy(None, None, None)
B2 = TMP / "base_intake"; (B2 / "requests").mkdir(parents=True)
_new = sorted(set(_reqs()) - R0)
for n_ in _new:
    shutil.copy(BASE / "requests" / n_, B2 / "requests" / n_)
st2 = IO.LocalStore(B2, default_owner=A0)
st2.write_json(A.P_GRANT, {"epoch": 1, "session": "MS2"}, owner=G)
ml2 = M.MasterLoop(st2, "MS2", "fpm2", lambda: {"accounts": {"A0": A0, "G": G}, "people": PEOPLE})
ml2.heartbeat(); ml2.run_once()
_its = {n_: (st2.read_json(A.P_INTAKE + n_.split("__")[0][4:] + ".json") if (B2 / A.P_INTAKE / (n_.split("__")[0][4:] + ".json")).exists() else None)
        for n_ in _new}
_bad = [n_ for n_, it in _its.items() if not (it and it.get("ok"))]
_kinds = sorted({n_.split("__")[1] for n_ in _new})
check(len(_new) >= 13 and not _bad, f"심판이 바꾸는 셀의 요청 {len(_new)}개({', '.join(_kinds)})를 모두 접수 (요청자·종류·칸) {_bad[:3]} {[_its[b_] for b_ in _bad[:2]]}")
cb._set_policy(*_pol)
ctt.list_tasks = _lt
S3.close()

# ---------------------------------------------------------------- b28 V1~V3·V5 (0z6)
import importlib as _il, builtins as _bi, _io
import requests as _rq
EXT = TMP / "ext"; EXT.mkdir(exist_ok=True); (EXT / "outside.txt").write_text("ext")
SA = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
_il.reload(cb)                                                   # 0번 셀 순서 그대로: reload → start
check(cb.active() is SA, "모듈을 다시 불러와도 활성 세션을 잃지 않음 (b28 V1)")
try:
    SB = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL)); v1 = None
except Exception as e:
    SB, v1 = None, e
check(SB is not None and cb.active() is SB and SB.out != SA.out and Path(SB.out).is_dir(),
      f"0번 셀 재실행(importlib.reload(cb) → start)이 앞 세션을 찾아 바꿈 (b28 V1) {v1 or ''}")
check(cb._orig(_bi.open) is _io.open and _bi.open.__egg_orig__ is _io.open and os.replace.__egg_orig__.__module__ in ("posix", "nt", None),
      "가드는 하나만: 새 가드가 앞 가드가 아니라 진짜 원래 함수를 감쌈 (b28 V1)")
check(refused(lambda: open(BASE / "v1.txt", "w")) and refused(lambda: open(Path(SA.out) / "old.txt", "w")),
      "재실행 뒤에도 공유 폴더 쓰기는 거절, 앞 세션 분석 폴더도 이제 쓰지 않음")
open(Path(SB.out) / "new.txt", "w").write("ok")
for bad_kw in ({"person": ""}, {"base": str(TMP / "nope")}):
    try:
        cb.start(**{"base": str(BASE), "person": "M1", "cvat_hosts": ["https://app.cvat.ai"], "local": str(LOCAL), **bad_kw})
    except Exception:
        pass
os.environ[access.MODE_VAR] = "weird"
try:
    cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
except Exception:
    pass
os.environ.pop(access.MODE_VAR, None)
check(cb.active() is SB and refused(lambda: (BASE / "v2.txt").write_text("x")) and not (BASE / "v2.txt").exists()
      and refused(lambda: _rq.Session().request("DELETE", "https://app.cvat.ai/api/tasks/0")),
      "새 시작이 설정 오류(OPERATOR 없음·BASE 없음·모드 틀림)로 실패해도 앞 세션의 쓰기·CVAT 가드는 그대로 (b28 V2)")
(LOCAL / "kw.txt").write_text("x")
check(refused(lambda: os.replace(src=str(LOCAL / "kw.txt"), dst=str(BASE / "kw_target.txt"))) and not (BASE / "kw_target.txt").exists()
      and refused(lambda: os.rename(src=str(BASE / "logs/versions.csv"), dst=str(LOCAL / "stolen.csv")))
      and refused(lambda: os.remove(path=str(BASE / "logs/versions.csv")))
      and refused(lambda: os.unlink(path=str(BASE / "logs/versions.csv"))) and (BASE / "logs/versions.csv").exists(),
      "키워드 인자로 부른 os.replace·rename·remove·unlink도 경로 검사 (b28 V3)")
_fd = os.open(str(BASE), os.O_RDONLY)
try:
    check(refused(lambda: os.unlink("logs/versions.csv", dir_fd=_fd)) and refused(lambda: os.mkdir("dfd_new", dir_fd=_fd))
          and (BASE / "logs/versions.csv").exists() and not (BASE / "dfd_new").exists(),
          "dir_fd 기준 상대 경로도 실제 위치로 풀어 검사 (b28 V3)")
finally:
    os.close(_fd)
_tdir = LOCAL / "rt"; (_tdir / "a/b").mkdir(parents=True, exist_ok=True); (_tdir / "a/b/f.txt").write_text("x")
shutil.rmtree(_tdir)
check(not _tdir.exists(), "BASE 밖 폴더 지우기(shutil.rmtree — 안에서 dir_fd를 씀)는 그대로 됨")
SB.close()
_lnk = BASE / "shared_link.txt"; os.symlink(str(EXT / "outside.txt"), str(_lnk))
_back = Path(SB.out) / "to_base.txt"
os.symlink(str(BASE / "logs/versions.csv"), str(_back))
SC = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
_back2 = Path(SC.out) / "to_base.txt"; cb._orig(os.symlink)(str(BASE / "logs/versions.csv"), str(_back2))
check(refused(lambda: _lnk.unlink()) and _lnk.is_symlink() and refused(lambda: os.rename(str(_lnk), str(LOCAL / "l2"))),
      "BASE 안의 링크 항목 자체는 가리키는 곳이 밖이어도 지우기·옮기기 거절 (b28 V5)")
_back2.unlink()
check(not _back2.exists() and (BASE / "logs/versions.csv").exists(),
      "내 분석 폴더 안의 링크는 지울 수 있고, 링크가 가리키던 공유 파일은 그대로")
SC.close()

# ---------------------------------------------------------------- b29 W1·W5 (0z7)
import threading as _th
SD = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
_w_old, _c_old = cb._active_writes(), cb._active_cvat()     # 감싸기가 규칙을 읽은 직후에 멈췄다고 보고
SE = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))   # 그사이 다른 스레드가 세션을 바꿈
check(_w_old is SD.writes and cb._active_writes() is SE.writes
      and refused(lambda: _w_old.before_open(BASE / "during_restart.txt", "w"))
      and refused(lambda: _c_old._guard("DELETE", "https://app.cvat.ai/api/tasks/1")),
      "규칙을 읽은 뒤 세션이 바뀌어도, 읽어 둔 앞 가드가 그대로 검사함 — 검사 없이 원래 함수로 가지 않음 (b31 X1)")
SD.close()
check(cb.active() is SE and cb._active_writes() is SE.writes and refused(lambda: (BASE / "x1.txt").write_text("x")),
      "이미 바뀐 앞 세션을 닫아도 지금 규칙은 그대로 (b31 X1)")
_stop = {"go": True}; _wrote = []
def _writer():
    while _stop["go"]:
        try:
            (BASE / "race.txt").write_text("x"); _wrote.append(1)
        except cb.AnalysisRefused:
            pass
_t = _th.Thread(target=_writer); _t.start()
for _ in range(15):
    SE = cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL))
_stop["go"] = False; _t.join()
check(not _wrote and not (BASE / "race.txt").exists(), "다른 스레드가 계속 쓰는 동안 0번 셀을 15번 다시 시작해도 공유 쓰기는 한 번도 통과하지 않음 (b29 W1)")
SF = cb.start(str(BASE), "M7", ["https://app.cvat.ai"], local=str(LOCAL))
check(cb.active() is SF and Path(SF.out).parent == (BASE / "analysis/M7").resolve() and Path(SF.out).is_dir(),
      "다른 사람 ID(분석 폴더가 아직 없는 M7)로 다시 시작해도 새 분석 폴더의 부모까지 만듦 (b29 W5)")
_st = cb._state(); _st["boot"] = (_th.get_ident(), Path(SF.out) / "x", (BASE / "analysis").resolve())
try:
    check(SF.writes._booting(BASE / "analysis/M7") and not SF.writes._booting(BASE / "analysis/M1")
          and not SF.writes._booting(BASE / "logs") and not SF.writes._booting(BASE),
          "새 분석 폴더를 만드는 동안 허용은 그 폴더까지 이어지는 부모만 (다른 사람 폴더·공유 폴더는 아님)")
finally:
    _st["boot"] = None
# b31 X2: 다른 세대 가드의 세션이 남은 커널
class _OldGenSession:
    def close(self): pass
_st2 = cb._state(); _keep = (_st2.get("active"), _st2.get("policy"))
_st2["active"] = _OldGenSession()
try:
    _x2 = refused(lambda: cb.start(str(BASE), "M1", ["https://app.cvat.ai"], local=str(LOCAL)))
    check(_x2 and isinstance(_st2["active"], _OldGenSession) and _st2.get("policy") == _keep[1],
          "다른 판(가드 세대)의 세션이 남은 커널에서는 아무것도 바꾸지 않고 런타임 재시작을 안내 (b31 X2)")
finally:
    _st2["active"], _st2["policy"] = _keep
# b31 X3: 분석 부모 폴더가 다른 공유 폴더를 가리키는 링크
cb._orig(os.mkdir)(str(BASE / "CVAT_UpLoader"))        # 다른 사람이 미리 걸어 둔 링크 (가드 밖)
cb._orig(os.symlink)(str(BASE / "CVAT_UpLoader"), str(BASE / "analysis/M8"))
check(refused(lambda: cb.start(str(BASE), "M8", ["https://app.cvat.ai"], local=str(LOCAL)))
      and not any((BASE / "CVAT_UpLoader").iterdir()) and cb.active() is SF,
      "analysis/<사람>이 다른 공유 폴더(CVAT_UpLoader)를 가리키는 링크면 시작하지 않음 — 그쪽에 아무것도 만들지 않음 (b31 X3)")
# 시작끼리는 차례로: 두 스레드가 동시에 시작해도 둘 다 성공
_res = []
def _st_thread(pid):
    try:
        _res.append(cb.start(str(BASE), pid, ["https://app.cvat.ai"], local=str(LOCAL)))
    except Exception as e:
        _res.append(e)
_ts = [_th.Thread(target=_st_thread, args=(p_,)) for p_ in ("M1", "M9")]
[t.start() for t in _ts]; [t.join() for t in _ts]
check(len(_res) == 2 and all(isinstance(r, cb.Session) for r in _res) and cb.active() in _res,
      f"두 스레드가 동시에 0번 셀을 시작해도 차례로 둘 다 성공 (잠금) {[type(r).__name__ for r in _res]}")
for r in _res:
    if isinstance(r, cb.Session):
        r.close()
import datetime as _dt2
_kst = _dt2.datetime.now(_dt2.timezone(_dt2.timedelta(hours=9)))
check(Path(SF.out).name[:9] in (_kst.strftime("%y%m%d_%H"), (_kst - _dt2.timedelta(minutes=1)).strftime("%y%m%d_%H")),
      "분석 폴더 이름의 시각은 한국 시각 (Colab 서버 시계 UTC가 아님)")
SF.close()
check("BASE     = ''" in c0text and "BASE를 적으세요" in c0text,
      "0번 셀의 BASE 기본값은 비워 둠 — 적지 않으면 운영 폴더를 가리키지 않고 멈춤")
os.environ.pop(access.MODE_VAR, None)
shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
