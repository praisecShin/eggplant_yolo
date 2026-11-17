"""v4.33 2b 시험 — 처리기 기반(2b-1)부터. 가짜 CVAT(tests/fake_cvat.py)와 폴더 저장소로 끝까지 돌림.
실제 Drive·CVAT·Kaggle에 접속하지 않습니다.
실행: python3 tests/test_handlers_433.py drive
"""
import json, os, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(ROOT))
import access, arbiter as A, arb_io as IO, arb_master as M, executor as X, handlers as H
from fake_cvat import FakeCvat

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

A0, G = "a0@x", "g@x"
ACC = {"A0": A0, "G": G}
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request", "wake", "release"], "status": "active"}]
_t0 = 1763000000
DAY = _t0 - (_t0 + 9 * 3600) % 86400 + 10 * 3600
TMP = Path(tempfile.mkdtemp(prefix="h433_"))


class Clk:
    def __init__(self, t=DAY): self.t = t
    def __call__(self): return self.t


class World:
    n = 0

    def __init__(self):
        World.n += 1
        self.clk = Clk()
        self.store = IO.LocalStore(TMP / f"w{World.n}", default_owner=A0, clock=self.clk)
        self.store.write_json(A.P_GRANT, {"epoch": 1, "session": "MS1"}, owner=G)
        self.master = M.MasterLoop(self.store, "MS1", "fpm", lambda: {"accounts": ACC, "people": PEOPLE}, clock=self.clk)
        self.execs = []

    def executor(self, name, caps, handlers):
        e = X.Executor(self.store, name, "fp" + name, caps, ACC, handlers, clock=self.clk, mono=self.clk,
                       sleep=lambda s: setattr(self.clk, "t", self.clk.t + s))
        self.execs.append(e)
        return e

    def request(self, rid, kind, tasks=(), **kw):
        self.store.write_json(f"requests/REQ_{rid}__{kind}__pending.json",
                              dict({"tasks": [str(t) for t in tasks], "created": self.clk()}, **kw))

    def tick(self, rounds=1):
        for _ in range(rounds):
            self.clk.t += 20
            self.master.heartbeat()
            for e in self.execs:
                e.heartbeat()
                e.step()
            self.master.run_once()

    def j(self, path):
        f = self.store.root / path
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def lock(self, t):
        return self.j(A.P_LOCK_TASK + f"{t}.json") or {}

    def alerts(self, kind):
        d = self.store.root / "arb/alerts"
        return [o for o in (json.loads(f.read_text()) for f in d.glob("*.json"))] if d.exists() else []


# ======================================================== 2b-1 등록부
reg = {}
try:
    H.register("x_bad", oops=lambda c: None); check(False, "모르는 단계")
except ValueError:
    check(True, "등록부: 모르는 단계 이름은 거절")
H.register("x_k", run=lambda c: {"report": "done_job"})
check(H.registered("x_k", "run") and not H.registered("x_k", "commit"), "등록부: 종류·단계별 등록 확인")
try:
    H.Dispatch().commit(X.Ctx(rid="r", kind="x_k", lane="task", assign="a", chunk=1, decision="d")); check(False, "NoHandler")
except H.NoHandler:
    check(True, "등록되지 않은 단계는 NoHandler (거짓 완료 없음)")
import worker_cpu as W
check(W.HANDLERS is H.REGISTRY and W.Dispatch is H.Dispatch, "CPU 작업 프로세스는 같은 등록부를 씀 (옛 이름 유지)")
check(H.LEGACY_KIND["aa"] == "auto" and H.LEGACY_KIND["discard"] is None, "옛 요청 종류 대응표 (2f 전환 도구용)")

# ======================================================== 2b-1 시험 범위 (ScopedCvat)
cv = FakeCvat()
cv.add_task(1, "REH_eggplant_G6_261026_1_4_uld", project_id=7)
cv.add_task(2, "eggplant_G6_261026_1_5_uld", project_id=7)
cv.add_task(3, "REH_eggplant_G6_261026_1_6_uld", project_id=9)
cv.add_task(4, "REH_x", project_id=7); cv.fail_get.add(4)
src = TMP / "ann.json"; src.write_text(json.dumps({"shapes": [{"f": 0}]}))
sc = H.ScopedCvat(cv, test=True, project_id=7)
def refused(fn):
    try:
        fn(); return False
    except H.ScopeError:
        return True
check(not refused(lambda: sc.import_annotations(1, str(src), "CVAT 1.1")), "시험 실행: 프로젝트 7의 REH_ TASK에는 씀")
check(refused(lambda: sc.import_annotations(2, str(src), "CVAT 1.1")) and refused(lambda: sc.remove_annotations(3))
      and refused(lambda: sc.rename_task(4, "REH_y")), "시험 실행: REH_가 아닌 TASK·다른 프로젝트·정보를 못 읽은 TASK에는 쓰지 않음")
check(refused(lambda: sc.rename_task(1, "eggplant_x")), "시험 실행: REH_가 아닌 이름으로 바꾸지 않음")
check(refused(lambda: sc.create_task("eggplant_new", project_id=7)) and not refused(lambda: sc.create_task("REH_new", project_id=7)),
      "시험 실행: 새 TASK는 프로젝트 7에 REH_ 이름으로만")
check(sc.get_task(2)["id"] == 2 and sc.get_annotations(2) is not None, "시험 실행: 읽기는 그대로")
prod = H.ScopedCvat(cv, test=False, project_id=None)
check(refused(lambda: prod.import_annotations(1, str(src), "CVAT 1.1")) and not refused(lambda: prod.remove_annotations(2)),
      "운영 실행: 시험 TASK(REH_)에는 쓰지 않고 운영 TASK에는 씀")
check(refused(lambda: getattr(sc, "create_task_raw", None) or sc.__getattr__("import_annotations")), "감싼 객체를 우회해 쓰기 함수를 꺼내지 못함")

# ======================================================== 2b-1 산출물 게시와 최종 검증
st = IO.LocalStore(TMP / "pub", default_owner=A0)
f1 = TMP / "best.pt"; f1.write_bytes(os.urandom(5000))
f2 = TMP / "args.yaml"; f2.write_text("epochs: 3\n")
notes = []
man = H.publish_version(st, "model", "m", "run1", {"weights/best.pt": str(f1), "args.yaml": str(f2)},
                        extra={"train_keys": ["t1"]}, progress=notes.append, auth=lambda: notes.append("AUTH"))
mf = st.read_json("runs/m/v/run1/_files.json")
check(mf["verified"] is True and mf["files"]["weights/best.pt"]["size"] == 5000 and mf["train_keys"] == ["t1"]
      and A.input_problem("vfiles", mf) == "", "게시: 올린 뒤 다시 받아 해시·크기를 확인하고 목록(verified)을 씀 — 심판의 형태 검사 통과")
check(notes.index("AUTH") > max(i for i, n in enumerate(notes) if str(n).startswith("확인")), "게시: 목록을 쓰기 바로 앞에서 권한을 다시 확인")
check(H.verify_version(st, "model", "m", "run1"), "검증: 게시된 버전의 파일이 목록과 맞음")
(st.root / "runs/m/v/run1/args.yaml").write_text("epochs: 999\n")
check(not H.verify_version(st, "model", "m", "run1"), "검증: 나중에 파일이 바뀌면 맞지 않음으로 봄")
class Corrupt(IO.LocalStore):
    def put_file(self, local, path):
        super().put_file(local, path)
        if path.endswith("best.pt"):
            (self.root / path).write_bytes(b"broken")
cst = Corrupt(TMP / "pub2", default_owner=A0)
try:
    H.publish_version(cst, "model", "m", "run2", {"weights/best.pt": str(f1)}); check(False, "VerifyError")
except H.VerifyError:
    check(not (cst.root / "runs/m/v/run2/_files.json").exists(), "게시: 올린 파일이 다르면 목록을 쓰지 않음 (VerifyError)")
try:
    H.publish_version(st, "model", "m", "run3", {"../x": str(f1)}); check(False, "밖")
except H.VerifyError:
    check(True, "게시: 버전 밖을 가리키는 이름은 거절")

# ======================================================== 2b-1 진행 시각과 '멈춘 것 같음'
class StallH(X.Handlers):
    def __init__(self, w, ex_name, stall=False):
        self.w, self.ex_name, self.stall, self.seen, self.writes = w, ex_name, stall, [], []

    def prepare(self, ctx):
        ctx.progress("받기 끝")
        ex = [e for e in self.w.execs if e.me == self.ex_name][0]
        ex.heartbeat()
        self.seen.append(self.w.j(access.worker_record_name(ex.me, ex.fp)).get("busy"))
        return {}

    def commit(self, ctx):
        ex = [e for e in self.w.execs if e.me == self.ex_name][0]
        if self.stall:                                  # 가져오기 응답을 기다리다 멈춤 → 그동안 마스터는 계속 돎
            ex.heartbeat()
            self.w.clk.t += A.STALL_SEC["task"] + 60
            ex.heartbeat()                              # 생존 신호는 오지만 진행 시각은 그대로
            self.w.master.heartbeat(); self.w.master.run_once()
        ctx.auth("recovery_publish").call("recovery", lambda: None)
        ctx.auth("cvat_write").call("import", lambda: self.writes.append(ctx.task))
        return "done"

w = World(); h = StallH(w, "E1")
e1 = w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1])
w.tick(6)
b = h.seen[0] if h.seen else {}
check(b and b.get("phase") == "prepare" and b.get("rid") == "r1" and b.get("task") == "1" and b.get("note") == "받기 끝"
      and b.get("lane") == "gpu", "진행: 처리기가 일하는 동안 생존 신호에 단계·요청·TASK·진행 메모가 실림")
rec = w.j(access.worker_record_name(e1.me, e1.fp))
check("busy" not in rec and h.writes == ["1"], "진행: 일이 끝나면 생존 신호에서 빠짐 (정상 처리는 그대로 끝남)")
check(A.input_problem("worker", {"session": "E1", "fp": "f", "hb": 1, "busy": {"lane": "task"}}) == ""
      and A.input_problem("worker", {"session": "E1", "fp": "f", "hb": 1, "busy": "x"}) == "busy", "심판 형태 표: busy는 객체")

w = World(); h = StallH(w, "E1", stall=True)
e1 = w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1])
w.tick(8)
check(w.lock(1).get("state") == "quarantine" and not h.writes,
      "멈춘 것 같음: 확정 중 진행이 30분 넘게 멈추면 생존 신호가 와도 격리('확인 필요') — 그 뒤의 CVAT 쓰기는 권한 확인에서 막힘")
check(any(a.get("kind") == "worker_stalled" and a.get("task") == "1" and a.get("phase") == "commit" for a in w.alerts("x")),
      "멈춘 것 같음: 'worker_stalled' 알림 (세션·TASK·단계)")
check(e1.mem and any(m.get("stopped") == "lost" for m in e1.mem.values()), "멈췄던 처리기가 깨어나면 쓰지 않고 '권한 잃음'으로 멈춤 보고")


# 오래 걸려도 진행을 알리면 멈춘 것으로 보지 않음
class SlowH(StallH):
    def commit(self, ctx):
        ex = [e for e in self.w.execs if e.me == self.ex_name][0]
        for _ in range(5):                              # 50분 동안 10분마다 진행을 알림
            self.w.clk.t += 600
            ctx.progress("가져오는 중")
            ex.heartbeat(); self.w.master.heartbeat(); self.w.master.run_once()
        ctx.auth("recovery_publish").call("recovery", lambda: None)
        ctx.auth("cvat_write").call("import", lambda: self.writes.append(ctx.task))
        return "done"
w = World(); h = SlowH(w, "E1")
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1]); w.tick(8)
check(h.writes == ["1"] and w.lock(1).get("state") != "quarantine", "오래 걸려도 10분마다 진행을 알리면 멈춘 것으로 보지 않고 끝까지 처리")
# 실행형 일(관리 일)이 멈춤 → 확인 필요
class StallRun(X.Handlers):
    def __init__(self, w): self.w, self.pub = w, []
    def run(self, ctx):
        ex = self.w.execs[0]
        ex.heartbeat(); self.w.clk.t += A.STALL_SEC["mgmt"] + 60; ex.heartbeat()
        self.w.master.heartbeat(); self.w.master.run_once()
        ctx.auth("run").call("publish", lambda: self.pub.append(ctx.run))
        return {"report": "done_job", "result": "done"}
w = World(); h = StallRun(w)
w.executor("C1", ["cpu"], h)
w.request("c1", "cleanup34", []); w.tick(6)
mg = w.j(A.P_LOCK_MGMT) or {}
check(mg.get("state") == "needs_check" and not h.pub, "멈춘 것 같음(관리 일 1시간): '확인 필요'로, 깨어난 처리기는 게시하지 않음")


# ======================================================== 2b-2 받는 중 일 (백업·export)
import h_read as HR
def rw_world(steps=3, test=False):
    w = World()
    cv = FakeCvat(steps=steps, clock=w.clk)
    cv.add_task(11, "REH_eggplant_G6_261026_1_4_uld" if test else "eggplant_G6_261026_1_4_uld")
    cv.add_task(12, "REH_eggplant G5/261026 2 1_vf" if test else "eggplant G5/261026 2 1_vf",
                ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
    env = H.Env(w.store, H.ScopedCvat(cv, test=test, project_id=7), tmp=str(TMP / f"tmp{World.n}"), clock=w.clk)
    ex = w.executor("C1", ["cpu"], H.Dispatch(env=env))
    return w, cv, ex
def zips(w, kind, rid):
    d = w.store.root / kind / rid
    return sorted(p.name for p in d.glob("*.zip")) if d.exists() else []
def req_status(w, rid):
    for f in (w.store.root / "requests").glob(f"REQ_{rid}__*.json"):
        return A.parse_req_name(f.name)[2]

w, cv, ex = rw_world()
w.request("b1", "backup", [11, 12], owner=G) if False else w.store.write_json("requests/REQ_b1__backup__pending.json",
    {"tasks": ["11", "12"], "created": w.clk(), "params": {"mode": "all", "auto": "uld"}}, owner=G)
w.tick(3)
pend = w.j("backups/pending/b1__11.json") or {}
check(pend.get("status") in ("requested", "started") and pend.get("task_updated") == cv.tasks[11]["updated"]
      and [c for c in cv.calls if c[0] == "request_backup"] == [("request_backup", 11), ("request_backup", 12)],
      "백업: TASK마다 서버에 준비를 한 번 요청하고, 받는 중 기록에 요청 시각의 CVAT 라벨 버전을 남김 (J1·G9)")
w.tick(12)
got = zips(w, "backups", "b1")
check(got == ["eggplant_G5_261026_2_1_vf__12.zip", "eggplant_G6_261026_1_4_uld__11.zip"]
      and (w.store.root / "backups/b1/eggplant_G6_261026_1_4_uld__11.zip").read_text() == json.dumps(cv.tasks[11]),
      "백업: 준비되면 게시 잠금 아래 받아 backups/<요청>/<TASK 이름>__<TASK>.zip에 올림 (이름의 특수문자는 _)")
p11 = w.j("backups/pending/b1__11.json")
check(p11["status"] == "받음" and p11["sha256"] == H.sha256_file(str(w.store.root / p11["result_file"])),
      "백업: 다시 받아 해시를 확인한 뒤 받는 중 기록을 '받음'으로 (해시·크기 기록)")
check(req_status(w, "b1") == "done" and len([c for c in cv.calls if c[0] == "request_backup"]) == 2 and not cv.writes(),
      "백업: 요청이 '완료'로 끝나고, 다시 요청하지 않으며 CVAT에는 쓰지 않음")
check(not any(f.name.endswith(".tmp") for f in (w.store.root / "backups").rglob("*")), "백업: 임시 파일이 남지 않음")

# export: params의 형식이 처리기까지
w, cv, ex = rw_world()
w.store.write_json("requests/REQ_e1__export__pending.json",
    {"tasks": ["12"], "created": w.clk(), "params": {"format": "COCO 1.0", "images": False, "auto": "vf"}}, owner=G)
w.tick(15)
check(("request_export", 12, "COCO 1.0") in cv.calls and zips(w, "exports", "e1") == ["eggplant_G5_261026_2_1_vf__12.zip"]
      and req_status(w, "e1") == "done", "export: 요청의 params(형식)가 접수 기록을 거쳐 처리기까지 전달 — 받아서 exports/<요청>/에")
check((w.j(A.P_INTAKE + "e1.json") or {}).get("params", {}).get("format") == "COCO 1.0", "접수 기록에 params가 실림")
w, cv, ex = rw_world()
w.store.write_json("requests/REQ_e2__export__pending.json", {"tasks": ["11"], "created": w.clk()}, owner=G)
w.tick(15)
check(("request_export", 11, "CVAT for images 1.1") in cv.calls, "export: 형식이 없으면 'CVAT for images 1.1'")

# 실행기가 바뀌어도 다시 요청하지 않음 (받는 중 기록의 작업 번호로 이어 감)
w, cv, ex = rw_world(steps=50)
w.store.write_json("requests/REQ_b2__backup__pending.json", {"tasks": ["11"], "created": w.clk()}, owner=G)
w.tick(3)
w.execs.clear()
env2 = H.Env(w.store, H.ScopedCvat(cv, test=False, project_id=None), tmp=str(TMP / "tmpb2"), clock=w.clk)
w.executor("C2", ["cpu"], H.Dispatch(env=env2))
w.clk.t += 400; w.tick(12)
for j in cv.jobs.values():
    j["asked"] = 99
w.tick(10)
check(len([c for c in cv.calls if c[0] == "request_backup"]) == 1 and zips(w, "backups", "b2") == ["eggplant_G6_261026_1_4_uld__11.zip"],
      "실행기가 바뀌어도(끊긴 뒤 다른 실행기) 같은 작업 번호로 이어 받음 — 서버에 다시 요청하지 않음")

# 서버 준비 실패 → 실패 보고 (거짓 완료 없음)
w, cv, ex = rw_world(steps=2)
w.store.write_json("requests/REQ_b3__backup__pending.json", {"tasks": ["11"], "created": w.clk()}, owner=G)
w.tick(2)
for j in cv.jobs.values():
    cv.job_status = lambda job: "failed"
w.tick(10)
res = [json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json")]
check(any(r.get("rid") == "b3" and str(r.get("result")).startswith("failed:JobFailed") for r in res) and req_status(w, "b3") == "failed"
      and not zips(w, "backups", "b3"), "서버 준비가 실패하면 그 TASK는 실패로 보고하고 요청은 '실패'로 (올린 파일 없음)")
# TASK가 CVAT에 없음 → 실패
w, cv, ex = rw_world()
w.store.write_json("requests/REQ_b4__backup__pending.json", {"tasks": ["99"], "created": w.clk()}, owner=G)
w.tick(10)
res = [json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json")]
check(any(r.get("rid") == "b4" and "TaskMissing" in str(r.get("result")) for r in res), "TASK 정보를 못 읽으면 실패 (TaskMissing)")
# 올린 파일이 다르면 실패
w, cv, ex = rw_world(steps=1)
real_put = w.store.put_file
w.store.put_file = lambda local, path: (real_put(local, path), (w.store.root / path).write_text("broken"))
w.store.write_json("requests/REQ_b5__backup__pending.json", {"tasks": ["11"], "created": w.clk()}, owner=G)
w.tick(12)
res = [json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json")]
check(any(r.get("rid") == "b5" and "VerifyError" in str(r.get("result")) for r in res)
      and (w.j("backups/pending/b5__11.json") or {}).get("status") != "받음", "다시 받아 보니 다르면 실패 — 받는 중 기록을 '받음'으로 바꾸지 않음")
# 취소: 준비 중 취소 → 받지 않음
w, cv, ex = rw_world(steps=50)
w.store.write_json("requests/REQ_b6__backup__pending.json", {"tasks": ["11"], "created": w.clk()}, owner=G)
w.tick(3)
w.store.write_json(A.P_SIGNALS + "cancel__p__1.json", {"rid": "b6"})
w.tick(4)
for j in cv.jobs.values():
    j["asked"] = 99
w.tick(6)
check(not [c for c in cv.calls if c[0] == "download"] and not zips(w, "backups", "b6"), "준비 중 취소되면 받지 않음")


# 실제 CVAT 어댑터(cvat_ops.RealCvat): 지금 쓰는 함수로 가는지 (가짜 모듈로 바꿔 끼워 확인 — 접속하지 않음)
import types
calls = []
fctt = types.SimpleNamespace(
    connect=lambda host, tok: calls.append(("connect", host)) or types.SimpleNamespace(),
    set_scope=lambda c, org, p: calls.append(("scope", org)),
    request_export=lambda c, tid, fmt, include_images=False: calls.append(("rx", tid, fmt)) or "R1",
    export_status=lambda c, rq: {"status": "finished", "result_url": "/u", "message": ""},
    download_result=lambda c, url, path: calls.append(("dx", url)) or Path(path).write_text("ZIP"))
fcb = types.SimpleNamespace(
    new_session=lambda: types.SimpleNamespace(), login=lambda s, m: calls.append(("login", m)),
    request_backup=lambda s, tid: calls.append(("rb", tid)) or "B1",
    check_backup=lambda s, rq: ("queued", None, "", ""),
    fetch_backup=lambda s, url, path: calls.append(("db", url)))
saved = {k: sys.modules.get(k) for k in ("cvat_task_tools", "cvat_backup")}
sys.modules["cvat_task_tools"], sys.modules["cvat_backup"] = fctt, fcb
try:
    import cvat_ops
    rc = cvat_ops.RealCvat("https://app.cvat.ai/", "tok-secret", org="horti")
    jb, je = rc.request_backup(11), rc.request_export(12, "COCO 1.0")
    out = str(TMP / "dl.zip"); rc.download(je, out)
    check(jb == "bk:B1" and je == "ex:R1" and rc.job_status(jb) == "started" and rc.job_status(je) == "finished"
          and Path(out).read_text() == "ZIP" and ("scope", "horti") in calls and ("login", "token") in calls,
          "실제 CVAT 어댑터: 백업은 cvat_backup, export는 cvat_task_tools로 — 작업 번호에 종류를 붙여 구분")
    try:
        rc.download(jb, out); check(False, "준비 전 받기")
    except RuntimeError:
        check(True, "실제 CVAT 어댑터: 준비 전이면 받지 않음")
    check("tok-secret" not in json.dumps(calls), "실제 CVAT 어댑터: 토큰을 호출 기록에 남기지 않음")
finally:
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


# ======================================================== 2b-3 TASK 쓰기 (track·shape·auto·제출본)
import h_task as HT
class FakeEngine:
    def __init__(self, n=3):
        self.n, self.calls = n, []
    def make_track(self, info, ref_zip, workdir, params, progress):
        self.calls.append(("track", info["id"], json.loads(Path(ref_zip).read_text())))
        progress("track 만드는 중")
        f = Path(workdir) / "tracks.json"
        f.write_text(json.dumps({"tracks": [{"id": i, "label": "fruit"} for i in range(self.n)]}))
        return {"file": str(f), "fmt": HT.IMPORT_FMT, "count": self.n}
    def make_shapes(self, info, workdir, params, progress):
        self.calls.append(("shapes", info["id"], params.get("conf")))
        return {"shapes": [{"type": "rectangle", "frame": i, "label": "bud", "points": [0, 0, 1, 1]} for i in range(self.n)]}

def tw_world(test=False, n=3, project=7):
    w = World()
    cv = FakeCvat(steps=1, clock=w.clk)
    env = H.Env(w.store, H.ScopedCvat(cv, test=test, project_id=project), tmp=str(TMP / f"tt{World.n}"), clock=w.clk)
    env.engine, env.server, env.import_wait = FakeEngine(n), "m1@app.cvat.ai", 600
    w.executor("E1", ["gpu"], H.Dispatch(env=env))
    return w, cv, env
def results(w, rid):
    return {r["task"]: r["result"] for r in (json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json"))
            if r.get("rid") == rid}
def call_names(cv):
    return [c[0] for c in cv.calls]

# ① 비어 있는 _uld TASK에 track → 백업 먼저, 올림, 이름 _uld_AA
w, cv, env = tw_world()
cv.add_task(21, "eggplant_G6_261026_1_4_uld")
w.request("t1", "track", [21], params={"conf": 0.4}); w.tick(10)
names = call_names(cv)
check(results(w, "t1") == {"21": "done"} and cv.tasks[21]["name"] == "eggplant_G6_261026_1_4_uld_AA"
      and len(cv.tasks[21]["ann"]["tracks"]) == 3, "track: 만들고 바로 올림(11/17 결정), 이름은 …_uld → …_uld_AA")
imp = names.index("import_annotations")
check(names.count("request_export") == 2 and max(i for i, n in enumerate(names) if n == "download") < imp,
      "track: 참고 라벨(준비)과 업로드 전 백업(확정)을 받은 뒤에만 가져오기 — 백업 선행")
rdir = next((w.store.root / "recovery/21").glob("*"))
check((rdir / "before_upload.zip").exists() and json.loads((rdir / "result_plan.json").read_text())["count"] == 3,
      "track: 업로드 전 백업을 복구 자료(recovery/<TASK>/<작업번호>/)로 게시")
_plan = json.loads((rdir / "result_plan.json").read_text())
_rf = rdir / str(_plan.get("result_file"))
check(_rf.exists() and H.sha256_file(str(_rf)) == _plan.get("result_sha256") and "model" in _plan,
      "track: 올린 결과 파일도 복구 자료에 해시와 함께 (사람용 셀 7·19·32번이 비교 기준으로 읽음, 2c-2)")
check(env.engine.calls and env.engine.calls[0][0] == "track", "track: 계산은 준비 단계에서 (승인 전, CVAT에 쓰지 않음)")

# ② 모델 라벨이 있는 _uld TASK → 교체 (지우고 가져오기)
w, cv, env = tw_world()
cv.add_task(22, "eggplant_G6_261026_1_5_uld", ann={"shapes": [{"f": 1}] * 4, "tracks": [], "tags": []})
w.request("t2", "track", [22]); w.tick(10)
names = call_names(cv)
check(results(w, "t2") == {"22": "done"} and names.index("remove_annotations") < names.index("import_annotations")
      and len(cv.tasks[22]["ann"]["shapes"]) == 0 and len(cv.tasks[22]["ann"]["tracks"]) == 3,
      "기존 라벨이 있는 uld TASK: 지우고 가져와 교체")

# ③ 사람 라벨 보호: 이름이 uld·AA가 아니고 라벨이 있으면 쓰지 않음
w, cv, env = tw_world()
cv.add_task(23, "eggplant_G6_261026_1_6_vf", ann={"shapes": [], "tracks": [{"t": 1}], "tags": []})
w.request("t3", "track", [23]); w.tick(10)
check(results(w, "t3") == {"23": "held:human_labels"} and not cv.writes() and cv.tasks[23]["ann"]["tracks"] == [{"t": 1}],
      "사람 라벨 보호: 검토 단계(vf) TASK에 라벨이 있으면 쓰지 않고 '보류' (백업은 남김)")
w, cv, env = tw_world()
cv.add_task(24, "eggplant_G6_261026_1_7_vf", ann={"shapes": [], "tracks": [{"t": 1}], "tags": []})
w.request("t4", "track", [24], params={"allow_replace": True}); w.tick(10)
check(results(w, "t4") == {"24": "done"} and "remove_annotations" in call_names(cv), "params.allow_replace = true(명시)일 때만 사람 라벨 TASK를 교체")
w, cv, env = tw_world()
cv.add_task(25, "eggplant_G6_261026_1_8_vf", ann={"shapes": [], "tracks": [{"t": 1}], "tags": []})
w.request("t5", "track", [25], params={"allow_replace": "yes"}); w.tick(10)
check(results(w, "t5") == {"25": "held:human_labels"}, "allow_replace는 참(true)만 — 문자열 'yes'는 동의로 보지 않음")

# ④ 가져오기 실패 → 백업으로 되돌림
w, cv, env = tw_world()
cv.add_task(26, "eggplant_G6_261026_1_9_uld", ann={"shapes": [{"f": 9}] * 2, "tracks": [], "tags": []})
real_imp, state = cv.import_annotations, {"n": 0}
def imp_once_fail(tid, path, fmt, **kw):
    state["n"] += 1
    if state["n"] == 1:
        cv.import_fail.add(tid)
    else:
        cv.import_fail.discard(tid)
    return real_imp(tid, path, fmt, **kw)
cv.import_annotations = imp_once_fail
w.request("t6", "track", [26]); w.tick(10)
check(str(results(w, "t6").get("26", "")).startswith("failed:") and "restored" in results(w, "t6")["26"]
      and cv.tasks[26]["ann"]["shapes"] == [{"f": 9}] * 2 and cv.tasks[26]["name"].endswith("_uld"),
      "가져오기 실패 → 업로드 전 백업으로 되돌림, 이름은 바꾸지 않음")

# ⑤ 가져오기가 끝나지 않음 → 되돌리지 않고 '확인 필요'
w, cv, env = tw_world()
cv.add_task(27, "eggplant_G6_261026_2_1_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
cv.hang_imports = True
env.sleep = lambda s: setattr(w.clk, "t", w.clk.t + 120)
w.request("t7", "track", [27]); w.tick(12)
check(call_names(cv).count("import_annotations") == 1 and call_names(cv).count("remove_annotations") == 1
      and w.lock(27).get("state") == "quarantine",
      "서버 가져오기가 끝났는지 모르면(시간 초과) 되돌리지 않고 멈춤 보고 → 격리('확인 필요')")

# ⑥ 쓰는 도중 권한을 잃음 → 다음 호출을 하지 않고 되돌리지도 않음
w, cv, env = tw_world()
cv.add_task(28, "eggplant_G6_261026_2_2_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
real_rm = cv.remove_annotations
def rm_then_lose(tid):
    real_rm(tid)
    lk = w.lock(tid); lk["state"] = "quarantine"
    w.store.write_json(A.P_LOCK_TASK + f"{tid}.json", lk)
cv.remove_annotations = rm_then_lose
w.request("t8", "track", [28]); w.tick(10)
check(call_names(cv).count("remove_annotations") == 1 and "import_annotations" not in call_names(cv)
      and any(m.get("stopped") == "lost" for m in w.execs[0].mem.values()),
      "쓰는 도중 권한을 잃으면 다음 쓰기(가져오기)도, 되돌리기도 하지 않고 '권한 잃음'으로 멈춤")

# ⑦ 시험 범위: 시험 실행은 REH_ TASK에만 — 준비 단계에서 무거운 계산 전에 멈춤
w, cv, env = tw_world(test=True)
cv.add_task(29, "eggplant_G6_261026_2_3_uld"); cv.add_task(30, "REH_eggplant_G6_261026_2_4_uld")
w.request("t9", "track", [29, 30]); w.tick(10)
r9 = results(w, "t9")
check(str(r9.get("29", "")).startswith("failed:ScopeError") and r9.get("30") == "done"
      and [c for c in env.engine.calls if c[1] == 29] == [] and cv.tasks[30]["name"] == "REH_eggplant_G6_261026_2_4_uld_AA",
      "시험 실행: REH_가 아닌 TASK는 준비에서 거절(계산·쓰기 없음), REH_ TASK는 처리하고 이름도 REH_…_uld_AA")

# ⑧ 준비 뒤 TASK가 바뀜 → 쓰지 않음
w, cv, env = tw_world()
cv.add_task(31, "eggplant_G6_261026_2_5_uld")
real_prep = HT.prepare
def prep_then_change(ctx):
    out = real_prep(ctx); cv.tasks[int(ctx.task)]["size"] = 99; return out
H.REGISTRY["track"]["prepare"] = prep_then_change
w.request("t10", "track", [31]); w.tick(10)
H.REGISTRY["track"]["prepare"] = real_prep
check(not cv.writes() and w.lock(31).get("state") == "quarantine", "준비 뒤 TASK의 프레임 수가 바뀌면 쓰지 않고 '확인 필요'")

# ⑨ 업로드 전 백업을 받지 못함 → 쓰지 않음
w, cv, env = tw_world()
cv.add_task(32, "eggplant_G6_261026_2_6_uld")
real_rx, rstate = cv.request_export, {"n": 0}
def rx_second_fails(tid, fmt, images=False):
    rstate["n"] += 1
    j = real_rx(tid, fmt, images)
    if rstate["n"] == 2:
        cv.jobs[j]["kind"] = "broken"; cv.job_status = (lambda jj, _j=j, _o=cv.job_status: "failed" if jj == _j else _o(jj))
    return j
cv.request_export = rx_second_fails
w.request("t11", "track", [32]); w.tick(10)
check(not cv.writes() and w.lock(32).get("state") == "quarantine", "업로드 전 백업을 받지 못하면 쓰지 않음 (확인 필요)")

# ⑩ shape·auto: 준비에서 탐지만, 확정에서 올림
w, cv, env = tw_world(n=5)
cv.add_task(33, "eggplant_G6_261026_2_7_uld"); cv.add_task(34, "eggplant_G6_261026_2_8_uld_AA", ann={"shapes": [{"old": 1}], "tracks": [], "tags": []})
w.request("s1", "shape", [33], params={"conf": 0.25}); w.request("s2", "auto", [34]); w.tick(12)
check(results(w, "s1") == {"33": "done"} and len(cv.tasks[33]["ann"]["shapes"]) == 5 and ("shapes", 33, 0.25) in env.engine.calls
      and cv.tasks[33]["name"].endswith("_uld_AA"), "shape: 준비에서 탐지(설정값 conf 전달), 확정에서 올림 · 이름 규칙")
check(results(w, "s2") == {"34": "done"} and cv.tasks[34]["name"] == "eggplant_G6_261026_2_8_uld_AA"
      and list((w.store.root / "exports/_aa_replaced").glob("*__34__s2.zip")), "auto(=shape): AA TASK 교체 → 이름 그대로, 이전 라벨을 exports/_aa_replaced/에 보관")

# ⑪ 제출본 올리기: 받은 바이트를 검증해 올림
w, cv, env = tw_world()
cv.add_task(35, "eggplant_G6_261026_2_9_uld", size=10)
sub = w.store.root / "submissions/M1/S1"; sub.mkdir(parents=True)
(sub / "result.json").write_text(json.dumps({"shapes": [{"f": 0}, {"f": 1}]}))
man = {"task_id": "35", "server": "m1@app.cvat.ai", "frames": 10, "labels": ["fruit", "bud"], "mode": "replace",
       "frame_range": [0, 9], "frame_map_sha": access.frame_map_sha(None), "format": HT.SHAPES_FMT, "count": 2,
       "data": "result.json", "files": [{"name": "result.json", "sha256": H.sha256_file(str(sub / "result.json")),
                                         "size": (sub / "result.json").stat().st_size}]}
(sub / "_submission.json").write_text(json.dumps(man))
w.request("u1", "upload_submission", [35], params={"submission": "submissions/M1/S1/"}); w.tick(10)
check(results(w, "u1") == {"35": "done"} and len(cv.tasks[35]["ann"]["shapes"]) == 2, "제출본: 받아 해시·TASK 일치를 확인하고 그 바이트를 올림")
w, cv, env = tw_world()
cv.add_task(36, "eggplant_G6_261026_3_1_uld", size=12)
sub = w.store.root / "submissions/M1/S2"; sub.mkdir(parents=True)
(sub / "result.json").write_text("{}")
man2 = dict(man, task_id="36", files=[{"name": "result.json", "sha256": H.sha256_file(str(sub / "result.json")), "size": 2}])
(sub / "_submission.json").write_text(json.dumps(man2))
w.request("u2", "upload_submission", [36], params={"submission": "submissions/M1/S2/"}); w.tick(10)
check(str(results(w, "u2").get("36", "")).startswith("failed:AccessError") and not cv.writes(),
      "제출본: TASK의 프레임 수가 다르면(10 ≠ 12) 실패 — 올리지 않음")


# ======================================================== b23 회귀 (0t)
# S1 사람 라벨 보호: 밑줄까지 맞는 꼬리만, 태그도 라벨
check(not HT.is_target("humanAA") and not HT.is_target("eggplant_xuld") and HT.is_target("eggplant_G6_1_uld")
      and HT.is_target("e_uld_AA") and HT.is_target("e_vf_AA_r2") and not HT.is_target("e_AA_rx"),
      "이름 규칙: 밑줄까지 맞는 꼬리(_uld·_AA·_AA_rN)만 모델 라벨 TASK (humanAA·xuld는 아님) (S1)")
w, cv, env = tw_world()
cv.add_task(41, "humanAA", ann={"shapes": [{"h": 1}], "tracks": [], "tags": []})
cv.add_task(42, "human_vf", ann={"shapes": [], "tracks": [], "tags": [{"t": 1}]})
w.request("p1", "track", [41, 42]); w.tick(12)
check(results(w, "p1") == {"41": "held:human_labels", "42": "held:human_labels"} and not cv.writes(),
      "humanAA(박스)·human_vf(태그만)는 동의 없이 쓰지 않고 보류 (S1)")
# S2 가져오기 응답을 잃음 → 되돌리지 않고 확인 필요
w, cv, env = tw_world()
cv.add_task(43, "eggplant_G6_3_1_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
real_imp2 = cv.import_annotations
def imp_lost(tid, path, fmt, **kw):
    cv.hang_imports = True
    real_imp2(tid, path, fmt, **kw)                    # 서버는 받았는데
    raise TimeoutError("응답 잃음")                      # 응답만 잃음
cv.import_annotations = imp_lost
w.request("p2", "track", [43]); w.tick(10)
check(call_names(cv).count("remove_annotations") == 1 and call_names(cv).count("import_annotations") == 1
      and w.lock(43).get("state") == "quarantine" and "43" not in results(w, "p2"),
      "가져오기 응답을 잃으면(서버에서 진행 중일 수 있음) 되돌리지 않고 '확인 필요' (S2)")
# S3 되돌리기의 각 쓰기 앞에서 권한 확인
w, cv, env = tw_world()
cv.add_task(44, "eggplant_G6_3_2_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
cv.import_fail.add(44)
real_rm2, rm_n = cv.remove_annotations, {"n": 0}
def rm_lose_on_restore(tid):
    rm_n["n"] += 1
    real_rm2(tid)
    if rm_n["n"] == 2:                                 # 되돌리기의 지우기 직후 권한을 잃음
        lk = w.lock(tid); lk["state"] = "quarantine"; w.store.write_json(A.P_LOCK_TASK + f"{tid}.json", lk)
cv.remove_annotations = rm_lose_on_restore
w.request("p3", "track", [44]); w.tick(10)
check(call_names(cv).count("remove_annotations") == 2 and call_names(cv).count("import_annotations") == 1
      and any(m.get("stopped") == "lost" for m in w.execs[0].mem.values()),
      "되돌리기 중 지우기 뒤 권한을 잃으면 백업 가져오기를 하지 않음 — 쓰기마다 권한 확인 (S3)")
# 한 함수 안의 여러 쓰기(shape 묶음)도 쓸 때마다 권한 확인
w, cv, env = tw_world()
cv.add_task(45, "eggplant_G6_3_3_uld")
def lose_inside(tid):
    lk = w.lock(tid); lk["state"] = "quarantine"; w.store.write_json(A.P_LOCK_TASK + f"{tid}.json", lk)
cv.before_import_hook = lose_inside
w.request("p4", "shape", [45]); w.tick(10)
check(("import_done", 45) not in cv.calls and any(m.get("stopped") == "lost" for m in w.execs[0].mem.values()),
      "가져오기 함수 안의 서버 쓰기 앞에서도 권한 확인 — 잃었으면 쓰지 않음 (S3, before_each)")
# S6 가져오기 형식
w, cv, env = tw_world()
cv.add_task(46, "eggplant_G6_3_4_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
cv.import_fail.add(46)
w.request("p5", "track", [46]); w.tick(10)
fmts = [c[2] for c in cv.calls if c[0] == "import_annotations"]
check(fmts == ["CVAT 1.1", "CVAT 1.1"] and w.lock(46).get("state") == "quarantine" and "46" not in results(w, "p5"),
      "가져오기·되돌리기는 가져오기 형식 'CVAT 1.1'(받기 형식과 나눔) · 되돌리기도 실패하면 '확인 필요' (S6)")
check([c[2] for c in cv.calls if c[0] == "request_export"] == ["CVAT for video 1.1"] * 1 + ["CVAT for video 1.1"] * 1,
      "받기(참고 라벨·업로드 전 백업)는 'CVAT for video 1.1'")
# S4 확인을 마친 버전은 바꾸지 않음
st4 = IO.LocalStore(TMP / "pub4", default_owner=A0)
fa = TMP / "a.bin"; fa.write_bytes(b"old")
H.publish_version(st4, "model", "m", "v1", {"a.bin": str(fa)})
fa.write_bytes(b"new")
try:
    H.publish_version(st4, "model", "m", "v1", {"a.bin": str(fa)}); check(False, "재게시")
except H.VerifyError:
    check((st4.root / "runs/m/v/v1/a.bin").read_bytes() == b"old" and H.verify_version(st4, "model", "m", "v1"),
          "확인을 마친 버전에 다시 게시하면 거절 — 파일도 목록도 그대로 (11/17 결정, S4)")
# S5 실제 track 명령이 yolo_track_to_cvat.py의 인자 해석을 통과
import subprocess
eng = HT.RealEngine(PKG / "scripts", None, lambda p: "m.pt", lambda i, r: ("v.mp4", None))
args = eng.track_args("m.pt", "v.mp4", "r.zip", str(TMP / "o"), {"conf": 0.4})
pr = subprocess.run(args, capture_output=True, text=True, cwd=str(TMP))
check(pr.returncode != 2 and "invalid" not in pr.stderr and "--near" in args and args[args.index("--near") + 1] == "1"
      and args[args.index("--box-source") + 1] == "detection", "실제 track 명령이 yolo_track_to_cvat.py 인자 해석을 통과 (near 정수·box-source detection) (S5)")
eng2 = HT.RealEngine(PKG / "scripts", None, None, None, settings={"near": 2, "box_source": "tracker"})
check(eng2.s["near"] == 2 and eng2.s["box_source"] == "tracker", "설정으로 기본값을 덮을 수 있음 (S5)")
args_fm = eng.track_args("m.pt", "v.mp4", "r.zip", str(TMP / "o"), {}, fm=[0, 8, 16])
pr = subprocess.run(args_fm, capture_output=True, text=True, cwd=str(TMP))
check(pr.returncode != 2 and args_fm[args_fm.index("--frame-map") + 1] == "0,8,16", "사진 TASK(프레임맵) 명령도 인자 해석 통과 (S5)")
# S7 범위가 걸린 묶음에서 원래 연결을 꺼낼 수 없음
cv7 = FakeCvat(); cv7.client = lambda: "RAW"; cv7.add_task(61, "eggplant_x", project_id=9)
sc7 = H.ScopedCvat(cv7, test=True, project_id=7)
check(refused(lambda: sc7.client()) and refused(lambda: sc7.session) and refused(lambda: sc7.ops),
      "범위가 걸린 CVAT 묶음은 원래 연결(client·session)을 내주지 않음 (S7)")
# 큰 전송 중에도 진행을 알림
import time as _t
seen = []
with H.ticking(seen.append, "올리는 중", every=0.05):
    _t.sleep(0.3)
check(len(seen) >= 3 and seen[0] == "올리는 중", "큰 파일 전송 동안 일정 간격으로 진행을 알림 (멈춤 한도 30분 < 전송 한도 1시간, b23 보충)")


# ======================================================== 2b-4 취합 일 (hide·unhide·refresh)
import h_agg as HA
def ag_world(test=False):
    w = World()
    cv = FakeCvat(steps=1, clock=w.clk)
    env = H.Env(w.store, H.ScopedCvat(cv, test=test, project_id=7), tmp=str(TMP / f"ag{World.n}"), test=test, clock=w.clk)
    w.executor("AG", ["agg"], H.Dispatch(env=env))
    return w, cv, env
def rj(w, p):
    f = w.store.root / p
    return json.loads(f.read_text()) if f.exists() else None
def req_status(w, rid):
    return [f.name.rsplit("__", 1)[1][:-5] for f in (w.store.root / "requests").glob(f"REQ_{rid}__*")]

w, cv, env = ag_world()
for tid, nm in ((81, "eggplant_G6_1_uld"), (82, "eggplant_G6_2_uld_AA"), (83, "eggplant_G6_3_vf"), (84, "humanAA")):
    cv.add_task(tid, nm)
w.store.write_json("relabel/tasks/81.json", {"history": [{"kind": "track", "status": "업로드 완료"}], "track_pending": None})
w.store.write_json("backups/pending/rb1__81.json", {"rid": "rb1", "task": "81", "kind": "backup", "status": "requested",
                                                    "requested_at": w.clk() - 600, "task_updated": "u"})
w.store.write_json("exports/pending/re1__82.json", {"rid": "re1", "task": "82", "kind": "export", "status": "받음",
                                                    "requested_at": w.clk() - 60})
w.store.write_json("requests/REQ_t9__track__pending.json", {"tasks": ["81"], "created": w.clk() + 999999})
w.request("f1", "refresh", []); w.tick(6)
tr = rj(w, "relabel/tracked.json")
check(tr and set(HA.tasks_of(tr)) == {"81", "82"} and tr["_pub"]["epoch"] == 1 and tr["_pub"]["gen"] >= 1,
      "새로 고침: 이름 꼬리가 대상(_uld·_AA)인 TASK만 tracked에 더함, 게시 파일에 epoch·회차 (humanAA·_vf 제외)")
st = rj(w, "relabel/state.json")
row = {str(t["id"]): t for t in (st or {}).get("tasks", [])}
check(st and row["81"]["runs"] == 1 and row["81"]["open"] and row["81"]["open"][0]["id"] == "t9"
      and st["summary"]["targets"] == 2 and st["_pub"] == tr["_pub"],
      "새로 고침: TASK 이력 요약(실행 수·마지막)과 열린 요청을 relabel/state.json에")
ps = rj(w, "web/pending_status.json")
check(ps and ps["counts"] == {"backup:requested": 1, "export:받음": 1} and ps["active"][0]["age_min"] >= 10
      and ps["recent_done"][0]["rid"] == "re1", "새로 고침: 받는 중 백업·export 기록(요청·TASK별)을 요약 (J1)")
check(req_status(w, "f1") == ["done"] and rj(w, "backups/pending/rb1__81.json")["status"] == "requested",
      "새로 고침 요청의 최종 상태는 취합 실행이 씀 · 받는 중 기록 파일은 바꾸지 않음")
# hide → unhide (TASK를 적은 요청도 실행 하나로 끝남)
w.request("h1", "hide", [81]); w.tick(6)
tr = rj(w, "relabel/tracked.json")
check(tr["81"]["hidden"] is True and tr["82"]["hidden"] is False and req_status(w, "h1") == ["done"],
      "숨기기: 최신 tracked에 숨김 표시 · 요청은 '완료' (TASK를 적은 취합 요청도 끝남)")
g_hide = tr["_pub"]["gen"]
w.request("h2", "unhide", [81]); w.tick(6)
tr = rj(w, "relabel/tracked.json")
check(tr["81"]["hidden"] is False and tr["_pub"]["gen"] > g_hide and req_status(w, "h2") == ["done"],
      "다시 보이기: 숨김 해제, 회차가 올라감")
w.request("h3", "hide", [999]); w.tick(6)
check(req_status(w, "h3") == ["failed"], "대상이 아닌 TASK만 숨기라고 하면 '실패' (거짓 완료 없음)")
# 사라짐: 끝까지 읽은 목록에서만
del cv.tasks[82]
w.request("f2", "refresh", []); w.tick(6)
tr = rj(w, "relabel/tracked.json")
check(tr["82"]["in_cvat"] is False and tr["82"].get("gone_at") and tr["82"]["progressed"] and not (w.store.root / "relabel/tasks/82.json").exists(),
      "목록 끝까지 읽음 → 없는 TASK는 '사라짐' 표시만 (TASK 이력은 그 TASK 권한 경로가 씀)")
w2, cv2, env2 = ag_world()
cv2.add_task(85, "eggplant_G6_5_uld"); cv2.add_task(86, "eggplant_G6_6_uld")
w2.request("f1", "refresh", []); w2.tick(6)
old_limit = HA.LIST_LIMIT; HA.LIST_LIMIT = 1
w2.request("f2", "refresh", []); w2.tick(6)
HA.LIST_LIMIT = old_limit
tr = rj(w2, "relabel/tracked.json")
check(all(tr[t]["in_cvat"] is True and not tr[t].get("gone_at") for t in ("85", "86")) and rj(w2, "relabel/state.json")["list_complete"] is False,
      "목록이 한도에 닿으면 보이지 않은 TASK를 '사라짐'으로 보지 않음")
# 옛 실행·권한
w, cv, env = ag_world()
cv.add_task(87, "eggplant_G6_7_uld")
w.store.write_json("relabel/tracked.json", {"87": {"first_name": "x", "hidden": False}, "_pub": {"epoch": 9, "gen": 1}})
w.request("f1", "refresh", []); w.tick(6)
tr = rj(w, "relabel/tracked.json")
check(tr["_pub"]["epoch"] == 9 and "name" not in tr["87"] and any(m.get("out", {}).get("report") == "stop_run" for m in w.execs[0].mem.values()),
      "더 높은 (epoch, 회차)가 이미 게시돼 있으면 덮어쓰지 않고 멈춤 보고")
w, cv, env = ag_world()
cv.add_task(88, "eggplant_G6_8_uld")
w.store.write_json("relabel/tracked.json", ["깨진 파일"])
w.request("f1", "refresh", []); w.tick(6)
check(rj(w, "relabel/tracked.json") == ["깨진 파일"] and req_status(w, "f1") == ["failed"],
      "지금 tracked를 읽지 못하면(객체 아님) 덮어쓰지 않고 실패")
w, cv, env = ag_world()
cv.add_task(89, "eggplant_G6_9_uld")
real_list = cv.list_tasks
def list_then_lose(limit=5000):
    rows = real_list(limit=limit)
    lk = rj(w, A.P_LOCK_AGG); lk["state"] = "needs_check"; w.store.write_json(A.P_LOCK_AGG, lk)
    return rows
cv.list_tasks = list_then_lose
w.request("f1", "refresh", []); w.tick(6)
check(rj(w, "relabel/tracked.json") is None and any(m.get("out", {}).get("report") == "stop_run" for m in w.execs[0].mem.values()),
      "계산 중 취합 권한을 잃으면 아무것도 게시하지 않고 멈춤 보고")
# 시험 실행: test/ 아래에만, REH_ TASK만
w, cv, env = ag_world(test=True)
cv.add_task(90, "REH_eggplant_G6_1_uld"); cv.add_task(91, "eggplant_G6_1_uld")
w.request("f1", "refresh", []); w.tick(6)
tr = rj(w, "test/relabel/tracked.json")
check(tr and set(HA.tasks_of(tr)) == {"90"} and rj(w, "relabel/tracked.json") is None,
      "시험 실행 취합: test/ 아래에만 게시하고 REH_ TASK만 다룸 (운영 상태 파일 그대로)")
import relabel_bridge as RB
(TMP / "rbb/relabel").mkdir(parents=True, exist_ok=True)
(TMP / "rbb/relabel/tracked.json").write_text(json.dumps({"5": {"hidden": False}, "_pub": {"epoch": 1}}))
check(list(RB.load_tracked(TMP / "rbb")) == ["5"], "옛 읽는 쪽(relabel_bridge.load_tracked)은 게시 표시(_pub)를 TASK로 보지 않음")



# 2b-6: 취합이 웹 상태 계산 결과를 epoch·회차와 함께 게시 (허용한 파일만)
class FakeWeb:
    def build(self, progress):
        return {"web/state.json": {"tasks": [1]}, "web/corrections.json": {"by_task": {}}, "relabel/evil.json": {"x": 1}}
w, cv, env = ag_world()
env.web_state = FakeWeb()
cv.add_task(95, "eggplant_G6_9_uld")
w.request("f1", "refresh", []); w.tick(6)
ws = rj(w, "web/state.json")
check(ws and ws["tasks"] == [1] and ws["_pub"] == rj(w, "relabel/tracked.json")["_pub"] and rj(w, "web/corrections.json")
      and rj(w, "relabel/evil.json") is None, "새로 고침: web/state.json 등을 같은 epoch·회차로 게시 (정해 둔 파일만)")

# ======================================================== 2b-5a 관리 일 (dataset·test_tasks33·force_new·cleanup29·cleanup34)
import h_mgmt as HM
class FakeBuilder(HM.DatasetBuilder):
    def __init__(self): self.calls = []
    def build(self, zips, out_dir, settings, val_tasks, progress):
        self.calls.append({"zips": [Path(z).name for z in zips], "settings": settings, "val": val_tasks})
        for d in ("train/images", "val/images"):
            (Path(out_dir) / d).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "train/images/a.jpg").write_bytes(b"img")
        (Path(out_dir) / "data.yaml").write_text("names: [healthy_fruit]")
        return {"train": 1, "val": 0}
def mg_world():
    w = World()
    cv = FakeCvat(steps=1, clock=w.clk)
    env = H.Env(w.store, H.ScopedCvat(cv, test=False, project_id=7), tmp=str(TMP / f"mg{World.n}"), clock=w.clk)
    env.builder = FakeBuilder()
    w.executor("C1", ["cpu"], H.Dispatch(env=env))
    return w, cv, env
def add_export(w, tid, name, rid="r0", body=None, at=None):
    body = body or f"zip-{tid}".encode()
    f = TMP / f"exp_{World.n}_{tid}_{rid}.zip"; f.write_bytes(body)
    path = f"exports/{rid}/{name}__{tid}.zip"
    w.store.put_file(str(f), path)
    w.store.write_json(f"exports/pending/{rid}__{tid}.json", {"rid": rid, "task": str(tid), "kind": "export", "status": "받음",
        "result_file": path, "sha256": H.sha256_file(str(f)), "format": "CVAT for video 1.1", "task_name": name,
        "task_updated": "u", "published_at": at or w.clk()})
def req_st(w, rid):
    return [f.name.rsplit("__", 1)[1][:-5] for d in ("requests",) for f in (w.store.root / d).glob(f"REQ_{rid}__*")]
def cur(w, typ, n=""):
    return rj(w, A.CURRENT_OF[typ].format(n=n)) or {}
def last_result(w, rid):
    return [r for r in (json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json")) if r.get("rid") == rid]

w, cv, env = mg_world()
add_export(w, 101, "eggplant_G6_261026_1_4_uld")
add_export(w, 102, "eggplant_G6_261026_2_1_vf")
add_export(w, 102, "eggplant_G6_261026_2_1_vf", rid="r_old", body=b"old", at=w.clk() - 100)
w.request("d1", "dataset", [101, 102], name="ds1", params={"val_ids": ["102"], "convert": {"KEEP_CLASSES": ["healthy_fruit"]}})
w.tick(8)
c = cur(w, "dataset", "ds1")
vf = rj(w, f"datasets/ds1/v/{c.get('version')}/_files.json") or {}
meta = json.loads((w.store.root / f"datasets/ds1/v/{c.get('version')}/dataset.json").read_text()) if c.get("version") else {}
check(c.get("version", "").startswith("mgmt_") and vf.get("verified") and set(vf["files"]) == {"dataset.zip", "dataset.json"}
      and req_st(w, "d1") == ["done"], "데이터셋: 버전 경로에 올리고 확인 뒤 _files.json → 심판이 채택 · 요청 '완료'")
check(vf.get("task_keys") == ["G6|261026|1|4", "G6|261026|2|1"] and vf.get("tasks") == ["101", "102"]
      and env.builder.calls[0]["val"] == {"101": False, "102": True}
      and [s_["export_rid"] for s_ in meta["sources"]] == ["r0", "r0"],
      "데이터셋 목록에 출처 키(task_keys)·TASK, val 고정, TASK마다 가장 나중에 받은 export")
# 시험 TASK 설정 → 채택 → 같은 그루·촬영일은 데이터셋에서 빠짐
cv.add_task(103, "eggplant_G6_261026_1_4_vf")
w.request("t1", "test_tasks33", [], params={"ids": ["103"], "note": "기준"}); w.tick(8)
tc = cur(w, "test_tasks")
tvf = rj(w, f"sets/test_tasks/v/{tc.get('version')}/_files.json") or {}
check(tc.get("keys") == ["G6|261026|1|4"] and tvf.get("ids") == ["103"] and req_st(w, "t1") == ["done"],
      "시험 TASK 바꾸기: 이름에서 그루·촬영일 키 → 버전 게시 → 채택 표시에 키")
w.request("d2", "dataset", [101, 102], name="ds1"); w.tick(8)
c2 = cur(w, "dataset", "ds1")
m2 = json.loads((w.store.root / f"datasets/ds1/v/{c2['version']}/dataset.json").read_text())
check(c2["version"] != c["version"] and [x["task"] for x in m2["excluded"]] == ["101"] and m2["test_version"] == tc["version"]
      and env.builder.calls[-1]["zips"] == ["102.zip"], "새 데이터셋은 채택된 시험 TASK와 같은 그루·촬영일 TASK를 뺌")
check((w.store.root / f"datasets/ds1/v/{c['version']}/_files.json").exists(), "이전 버전은 그대로 남음 (옮기거나 지우지 않음)")
# 실패: export 없음 · 받은 파일이 기록과 다름
w.request("d3", "dataset", [101, 999], name="ds1"); w.tick(8)
check(req_st(w, "d3") == ["failed"] and any(str(r.get("result")).startswith("failed:no_export:999") for r in last_result(w, "d3")),
      "export가 없는 TASK가 있으면 데이터셋을 만들지 않고 '실패'")
(w.store.root / "exports/r0/eggplant_G6_261026_2_1_vf__102.zip").write_bytes(b"tampered")
w.request("d4", "dataset", [102], name="ds1"); w.tick(8)
check(req_st(w, "d4") == ["failed"] and cur(w, "dataset", "ds1")["version"] == c2["version"],
      "받은 export가 기록의 해시와 다르면 만들지 않음 · 채택 그대로")
# FORCE_NEW: 채택 표시만
w.request("f1", "force_new", [], params={"type": "dataset", "name": "ds1", "version": c["version"]}); w.tick(8)
check(cur(w, "dataset", "ds1")["version"] == c["version"] and req_st(w, "f1") == ["done"],
      "학습 초기화(FORCE_NEW): 확인된 이전 버전으로 채택만 바꿈")
w.request("f2", "force_new", [], params={"type": "dataset", "name": "ds1", "version": "nope"}); w.tick(8)
check(req_st(w, "f2") == ["failed"] and cur(w, "dataset", "ds1")["version"] == c["version"],
      "없는(확인 안 되는) 버전으로는 채택을 바꾸지 않음")
w.request("f3", "force_new", [], params={"type": "dataset", "name": "ds1"}); w.tick(8)
check(cur(w, "dataset", "ds1").get("version") is None and req_st(w, "f3") == ["done"], "빈 시작으로 초기화 (파일은 그대로)")
# 29번 정리: 표시만
w.request("f4", "force_new", [], params={"type": "dataset", "name": "ds1", "version": c2["version"]}); w.tick(8)
w.request("c1", "cleanup29", [], params={"type": "dataset", "name": "ds1"}); w.tick(8)
mk = [json.loads(f.read_text()) for f in (w.store.root / "arb/mgmt").glob("*/marks.json")]
check(len(mk) == 1 and [m_["version"] for m_ in mk[0]["marks"]] == [c["version"]]
      and [s_["version"] for s_ in mk[0]["skipped"]] == [c2["version"]]
      and (w.store.root / f"datasets/ds1/v/{c['version']}/dataset.zip").exists(),
      "29번 정리: 채택 안 된 버전에 '정리 대상' 표시만 (채택된 것은 건너뜀, 파일은 그대로)")
# 34번 청소: 미리 보기 → 30일 뒤 적용
w.store.write_json("arb/ask/OLD__x__j.json", {"type": "confirm"})
w.store.write_json("workers/OLD.json", {"session": "OLD", "hb": 1})
w.request("k1", "cleanup34", []); w.tick(8)
pl = [json.loads(f.read_text()) for f in (w.store.root / "arb/mgmt").glob("*/plan.json")]
check(len(pl) == 1 and pl[0]["counts"]["versions"] == 0 and pl[0]["apply"] is False and req_st(w, "k1") == ["done"],
      "청소 미리 보기: 기간이 안 된 것은 목록에 없음 · 지우지 않음")
w.clk.t += 31 * 86400
w.request("k2", "cleanup34", [], params={"apply": True}); w.tick(8)
check(not (w.store.root / f"datasets/ds1/v/{c['version']}/_files.json").exists()
      and not (w.store.root / f"datasets/ds1/v/{c['version']}/dataset.zip").exists()
      and (w.store.root / f"datasets/ds1/v/{c2['version']}/dataset.zip").exists()
      and (w.store.root / f"sets/test_tasks/v/{tc['version']}/_files.json").exists(),
      "청소 적용: 표시 뒤 30일 지난 채택 안 된 버전만 지움 (채택된 데이터셋·시험 설정은 남음)")
check(not (w.store.root / "arb/ask/OLD__x__j.json").exists() and not (w.store.root / "requests/REQ_d1__dataset__done.json").exists()
      and (w.store.root / "requests/REQ_k2__cleanup34__done.json").exists() and (w.store.root / "exports/r0").exists(),
      "청소 적용: 7일 지난 확정 신청, 30일 지난 끝난 요청을 지움 · exports는 지우지 않음")
check(not (w.store.root / "workers/OLD.json").exists() and (w.store.root / "workers").exists(), "7일 넘게 멈춘 생존 신호 파일을 지움")
# 청소 판단 재료를 못 읽으면 지우지 않음
st6 = IO.LocalStore(TMP / "cl6", default_owner=A0)
st6.write_json("datasets/x/v/r1/_files.json", {"files": {}, "verified": True})
st6.write_json("datasets/x/CURRENT.json", ["깨짐"])
try:
    HM.cleanup_plan(st6, 1e10); check(False, "못 읽어도 계획")
except HM.MgmtFailed:
    check(True, "채택 표시를 못 읽으면 청소 계획을 만들지 않음 (모르면 지우지 않음)")
# 신호: 완료 기록이 있는 7일 지난 신호만, 완료 기록·계획은 신호가 없어진 뒤 30일 (계획 먼저)
st7 = IO.LocalStore(TMP / "cl7", default_owner=A0, clock=lambda: 0)
for p_ in ("jobs/signals/s1.json", "arb/signal_done/s1.json", "jobs/signals/s2.json", "arb/signal_done/s3.json", "arb/signal_plan/s3.json"):
    st7.write_json(p_, {})
pl7 = HM.cleanup_plan(st7, 40 * 86400)
check([x["path"] for x in pl7["signals"]] == ["jobs/signals/s1.json"]
      and [x["path"] for x in pl7["signal_records"]] == ["arb/signal_plan/s3.json", "arb/signal_done/s3.json"],
      "청소: 완료 기록이 없는 신호는 남기고, 완료 기록은 신호가 없어진 뒤 계획 다음에 지움")
# 진행 중 학습이 참조하는 버전은 지우지 않음
st8 = IO.LocalStore(TMP / "cl8", default_owner=A0, clock=lambda: 0)
st8.write_json("runs/m/v/train_a/_files.json", {"files": {}, "verified": True})
st8.write_json(A.P_LOCK_TRAIN + "m2.json", {"state": "running", "run": "train_b", "start_version": "train_a"})
check("model|m|train_a" in HM.protected(st8), "진행 중 학습이 시작점으로 쓰는 버전은 보호")


# ======================================================== 2b-5b 복구 일 · 학습 · 만들기 · 23번 복원
import h_run as HR
def quarantined_world(tid, name, shapes):
    """가져오기 응답을 잃어 '확인 필요'가 된 TASK (서버에는 반쯤 들어감)."""
    w, cv, env = tw_world()
    cv.add_task(tid, name, ann={"shapes": shapes, "tracks": [], "tags": []})
    real = cv.import_annotations
    def lost(t, path, fmt, **kw):
        real(t, path, fmt, **kw)
        raise TimeoutError("응답 잃음")
    cv.import_annotations = lost
    w.request("o1", "track", [tid]); w.tick(10)
    cv.import_annotations = real
    return w, cv, env
def choose(w, tid, choice):
    w.clk.t += 1000; w.tick(2)
    lk = w.lock(tid)
    w.store.write_json(A.P_SIGNALS + f"confirm_choice__app__{tid}{choice}.json",
                       {"task": str(tid), "decision": lk["decision"], "choice": choice})
    w.tick(14)
def rec_status(w):
    return [f.name.rsplit("__", 1)[1][:-5] for f in (w.store.root / "requests").glob("REQ_*__recovery__*")]

w, cv, env = quarantined_world(51, "eggplant_G6_5_1_uld", [{"f": 1}])
check(w.lock(51).get("state") == "quarantine" and len(cv.tasks[51]["ann"]["tracks"]) == 3, "준비: 가져오기 응답을 잃어 '확인 필요'(서버에는 들어감)")
choose(w, 51, "revert")
check(cv.tasks[51]["ann"] == {"shapes": [{"f": 1}], "tracks": [], "tags": []} and cv.tasks[51]["name"] == "eggplant_G6_5_1_uld"
      and rec_status(w) == ["done"], "복구 일 ② 되돌리기: 원래 업로드 전 백업으로 라벨을 되돌림 · 이름 그대로 · 복구 요청 '완료'")
rr = [r for r in (json.loads(f.read_text()) for f in (w.store.root / "arb/results").glob("*.json")) if str(r.get("rid", "")).startswith("rcv")]
check(len(rr) == 1 and rr[0]["result"] == "done" and rr[0]["task"] == "51",
      "복구 일의 결과는 그 TASK 결과로 기록")
check(len([d for d in (w.store.root / "recovery/51").iterdir() if (d / "before_upload.zip").exists()]) == 2,
      "되돌리기도 쓰기 전에 지금 라벨을 자기 복구 자료로 게시 (복구 자료 둘)")
w, cv, env = quarantined_world(52, "eggplant_G6_5_2_uld", [{"f": 1}])
choose(w, 52, "redo")
check(len(cv.tasks[52]["ann"]["tracks"]) == 3 and cv.tasks[52]["ann"]["shapes"] == [] and cv.tasks[52]["name"] == "eggplant_G6_5_2_uld_AA"
      and rec_status(w) == ["done"], "복구 일 ③ 다시 하기: 원요청 종류(track)로 다시 계산해 교체 · 이름 규칙 적용")
w, cv, env = quarantined_world(53, "eggplant_G6_5_3_uld", [{"f": 1}])
od = [d for d in (w.store.root / "recovery/53").iterdir() if d.is_dir()][0]
(od / "before_upload.zip").write_text('{"shapes": [{"evil": 1}]}')
n_writes = len(cv.writes())
choose(w, 53, "revert")
check(len(cv.writes()) == n_writes and rec_status(w) == ["failed"], "업로드 전 백업이 기록된 해시와 다르면 되돌리지 않음 (CVAT 쓰기 없음) · '실패'")

# ---- 학습
class FakeTrainer(HR.Trainer):
    def __init__(self, lose_at=None): self.calls, self.lose_at = [], lose_at
    def train(self, ds_dir, start, args, workdir, on_epoch, **kw):
        self.calls.append({"start": Path(start).name if os.path.exists(start) else start, "args": args,
                           "data": (Path(ds_dir) / "data.yaml").exists()})
        for e in range(1, 4):
            if self.lose_at == e:
                self.on_lose()
            on_epoch(e)
        d = Path(workdir); d.mkdir(parents=True, exist_ok=True)
        (d / "best.pt").write_bytes(b"weights-" + str(len(self.calls)).encode())
        (d / "results.csv").write_text("epoch,map\n1,0.5\n")
        return {"best": str(d / "best.pt"), "results": str(d / "results.csv"), "metrics": {"map50": 0.5}}
def tr_world():
    w = World()
    cv = FakeCvat(steps=1, clock=w.clk)
    env = H.Env(w.store, H.ScopedCvat(cv, test=False, project_id=7), tmp=str(TMP / f"tr{World.n}"), clock=w.clk)
    env.builder, env.trainer, env.base_model = FakeBuilder(), FakeTrainer(), "yolo11s.pt"
    w.executor("C1", ["cpu"], H.Dispatch(env=env)); w.executor("G1", ["gpu"], H.Dispatch(env=env))
    add_export(w, 111, "eggplant_G6_261026_1_4_uld")
    w.request("d1", "dataset", [111], name="ds1"); w.tick(8)
    return w, cv, env
w, cv, env = tr_world()
w.request("tr1", "train", [], model="m1", dataset="ds1", params={"epochs": 3, "lr0": 0.001, "evil": "x"}); w.tick(10)
mc = cur(w, "model", "m1")
mvf = rj(w, f"runs/m1/v/{mc.get('version')}/_files.json") or {}
check(mc.get("version", "").startswith("train_") and mvf.get("verified") and set(mvf["files"]) >= {"best.pt", "results.csv", "train.json"}
      and mvf.get("train_keys") == ["G6|261026|1|4"] and req_st(w, "tr1") == ["done"],
      "학습: 고정된 데이터셋 버전으로 학습 → 버전 경로에 best.pt 등 → 출처 키(train_keys) → 심판 채택")
check(env.trainer.calls[0]["start"] == "yolo11s.pt" and env.trainer.calls[0]["args"] == {"epochs": 3, "lr0": 0.001}
      and env.trainer.calls[0]["data"], "학습 설정은 정해 둔 항목만 넘김 · 기본 모델에서 시작")
w.request("tr2", "train", [], model="m1", dataset="ds1", params={"train_from": "current"}); w.tick(10)
mc2 = cur(w, "model", "m1")
check(mc2["version"] != mc["version"] and env.trainer.calls[1]["start"] == "start.pt", "이어 학습: 시작 때 채택된 모델의 best.pt(해시 대조)에서")
w, cv, env = tr_world()
dv = cur(w, "dataset", "ds1")["version"]
(w.store.root / f"datasets/ds1/v/{dv}/dataset.zip").write_bytes(b"tampered")
w.request("tr3", "train", [], model="m2", dataset="ds1"); w.tick(10)
check(req_st(w, "tr3") == ["failed"] and not cur(w, "model", "m2") and not env.trainer.calls,
      "데이터셋 파일이 목록 해시와 다르면 학습하지 않음")
w, cv, env = tr_world()
def lose():
    lp = next(iter((w.store.root / A.P_LOCK_TRAIN).glob("*.json")))
    lk = json.loads(lp.read_text()); lk["state"] = "needs_check"; lp.write_text(json.dumps(lk))
env.trainer = FakeTrainer(lose_at=2); env.trainer.on_lose = lose
w.request("tr4", "train", [], model="m3", dataset="ds1"); w.tick(10)
check(not (w.store.root / "runs/m3").exists() and any(m.get("out", {}).get("report") == "stop_run" for e in w.execs for m in e.mem.values()),
      "학습 중 권한을 잃으면 그 에폭에서 멈추고 아무것도 게시하지 않음")


# b26 U2: 정리 확인 불가 → 실행기 멈춤 보고 → 심판 '확인 필요' (일반 실패로 잠금을 풀지 않음)
class StuckTrainer(HR.Trainer):
    def train(self, *a, **k):
        raise HR.CleanupUnknown("학습 프로세스 1개가 남음")
w, cv, env = tr_world()
env.trainer = StuckTrainer()
w.request("tr9", "train", [], model="m9", dataset="ds1"); w.tick(10)
tl9 = rj(w, A.P_LOCK_TRAIN + "m9.json") or {}
check(tl9.get("state") == "needs_check" and tl9.get("stop_reason") == "cleanup_unknown" and req_st(w, "tr9") != ["failed"]
      and not cur(w, "model", "m9"), "학습 프로세스를 끝냈는지 모르면 '확인 필요'(잠금 유지) — 일반 실패로 풀지 않음 (b26 U2)")
w.request("tr10", "train", [], model="m9", dataset="ds1"); w.tick(6)
check((rj(w, A.P_LOCK_TRAIN + "m9.json") or {}).get("rid") == "tr9", "확인 전에는 같은 모델의 다음 학습을 시작하지 않음 (b26 U2)")

# ---- 새 TASK 만들기
def cr_world():
    w = World()
    cv = FakeCvat(steps=1, clock=w.clk)
    env = H.Env(w.store, H.ScopedCvat(cv, test=False, project_id=7), tmp=str(TMP / f"cr{World.n}"), clock=w.clk)
    w.executor("C1", ["cpu"], H.Dispatch(env=env))
    for rel in ("videos/261101/eggplant_G6_261101_1_1.mp4", "backups/eggplant_G6_1/x.zip"):
        f = TMP / f"src_{World.n}"; f.write_bytes(b"media"); w.store.put_file(str(f), rel)
    return w, cv, env
w, cv, env = cr_world()
w.request("c17", "create17", [], name="eggplant_G6_261101_1_1_uld", server="cvat1",
          params={"video": "videos/261101/eggplant_G6_261101_1_1.mp4", "project_id": 7, "frame_step": 10}); w.tick(8)
it = [json.loads(f.read_text()) for f in (w.store.root / "recovery/create/c17").rglob("intent.json")]
new_id = it[0].get("task_id") if it else None
check([c for c in call_names(cv) if c in cv.WRITES][:2] == ["create_task", "upload_video"] and it and it[0]["state"] == "created" and new_id in cv.tasks
      and it[0]["sha256"] and any(r.get("task_id") == new_id for r in last_result(w, "c17")) and req_st(w, "c17") == ["done"],
      "17번: 의도 기록 → 빈 TASK 먼저 → 번호 기록 → 영상 올리기 · 결과에 새 TASK 번호")
w.request("c16", "create16", [], name="eggplant_G6_1_vf_test", server="cvat1",
          params={"backup": "backups/eggplant_G6_1/x.zip", "project_id": 7}); w.tick(8)
nt = max(cv.tasks)
check(cv.tasks[nt]["name"] == "eggplant_G6_1_vf_test" and cv.tasks[nt]["project_id"] == 7 and req_st(w, "c16") == ["done"]
      and ("create_from_backup", "eggplant_G6_1_vf_test") in cv.calls, "16번: 백업에서 새 TASK → 번호 기록 뒤 이름·프로젝트")
w, cv, env = cr_world()
cv.fail_create = True
w.request("c1", "create17", [], name="eggplant_G6_261101_1_1_uld", server="cvat1",
          params={"video": "videos/261101/eggplant_G6_261101_1_1.mp4", "project_id": 7}); w.tick(8)
it = [json.loads(f.read_text()) for f in (w.store.root / "recovery/create/c1").rglob("intent.json")]
check(it and it[0]["state"] == "unknown" and call_names(cv).count("create_task") == 1
      and any(m.get("out", {}).get("report") == "stop_run" for m in w.execs[0].mem.values()),
      "만들기 응답을 잃으면 다시 만들지 않고 '확인 필요'(멈춤 보고)")
st_ = HR._intents(w.store, "c1")
check(len(st_) == 1 and st_[0]["state"] == "unknown", "같은 요청의 앞선 의도가 '모름'이면 다시 시작하지 않는 근거로 남음")
clp = next(iter((w.store.root / A.P_LOCK_CREATE).glob("*.json")))
clk_ = json.loads(clp.read_text())
cv.fail_create = False
rctx = X.Ctx(rid="c1", kind="create17", lane="create", assign="a", chunk=None, decision="d", run=clk_["run"],
             intake={"name": "eggplant_G6_261101_1_1_uld", "params": {"video": "videos/261101/eggplant_G6_261101_1_1.mp4"}},
             assign_obj={"key": clp.stem})
rctx.env = env
rctx.auth = lambda ph: (_ for _ in ()).throw(AssertionError("쓰기 시도"))
n0 = call_names(cv).count("create_task")
out_ = HR.run_create(rctx)
check(out_ == {"report": "stop_run", "reason": "earlier_create_unknown"} and call_names(cv).count("create_task") == n0,
      "다시 하기(새 실행)라도 앞선 만들기 결과를 모르면 사람 확인(retry_confirmed) 없이 만들지 않음")
w2, cv2, env2 = cr_world()
w2.request("c2", "create17", [], name="eggplant_x_uld", server="cvat1", params={"video": "../secret.mp4"}); w2.tick(8)
check(req_st(w2, "c2") == ["failed"] and not cv2.writes(), "원본 경로가 videos/ 밖이면 만들지 않음")
sc9 = H.ScopedCvat(FakeCvat(), test=True, project_id=7)
check(refused(lambda: sc9.create_from_backup("x", "eggplant_x", project_id=7)) and refused(lambda: sc9.create_task("REH_x", project_id=9)),
      "시험 실행 만들기는 REH_ 이름·정해진 프로젝트로만")

# ---- 23번 복원
class FakeRev(HR.RevisionSource):
    def rows(self, name, until=None):
        return [{"sub": "weights/best.pt", "kind": "run", "user": "a@x", "t": 1, "file_id": "f1", "rev_id": "r1"},
                {"sub": "results.csv", "kind": "run", "user": "a@x", "t": 2, "file_id": "f2", "rev_id": "r1"},
                {"sub": "weights/best.pt", "kind": "run", "user": "b@x", "t": 5, "file_id": "f1", "rev_id": "r2"}]
    def download(self, file_id, rev_id, dest):
        Path(dest).write_bytes(f"{file_id}:{rev_id}".encode())
w = World()
cv = FakeCvat(steps=1, clock=w.clk)
env = H.Env(w.store, None, tmp=str(TMP / f"rv{World.n}"), clock=w.clk); env.revisions = FakeRev()
w.executor("CO", ["colab_oauth"], H.Dispatch(env=env))
w.request("rv1", "restore23", [], params={"name": "fr", "user": "B"}); w.tick(8)
c23 = cur(w, "model", "fr_B")
v23 = rj(w, f"runs/fr_B/v/{c23.get('version')}/_files.json") or {}
check(c23.get("version", "").startswith("mgmt_") and set(v23.get("files", {})) == {"best.pt", "RESTORED_FROM.json"}
      and (w.store.root / f"runs/fr_B/v/{c23['version']}/best.pt").read_bytes() == b"f1:r2" and req_st(w, "rv1") == ["done"],
      "23번 복원: 고른 사용자(B)의 마지막 버전 → 새 이름 fr_B의 버전 경로 → 채택 · 원본 이름은 그대로")
w.request("rv2", "restore23", [], params={"name": "fr", "user": "C"}); w.tick(8)
check(req_st(w, "rv2") == ["failed"], "없는 사용자를 고르면 '실패'")


# ======================================================== b24 회귀 (0z)
# T2: 23번 복원 → 채택 → 모델 받기·이어 학습이 그대로 씀
import exec_host as EH
md = EH.Media(w.store, str(TMP / "t2media"))
check(Path(md.model("fr_B")).read_bytes() == b"f1:r2", "복원한 모델 버전을 채택 뒤 모델 받기(추론)가 그대로 씀 — 가중치는 버전 바로 아래 best.pt (T2)")
w.request("rv3", "restore23", [], params={"name": "fr", "user": "A"}); w.tick(8)
st_ = (TMP / "t2start.pt")
HR.get_verified(w.store, "model", "fr_A", cur(w, "model", "fr_A")["version"], "best.pt", str(st_))
check(st_.read_bytes() == b"f1:r1", "이어 학습의 시작 가중치 받기도 같은 이름(best.pt)으로 (T2)")
# T1: 접수 뒤 상태 조회 오류(401 등)는 거절이 아니라 '모름' → 되돌리지 않음
class ApiErr(Exception):
    status = 401
w, cv, env = tw_world()
cv.add_task(47, "eggplant_G6_3_7_uld", ann={"shapes": [{"f": 1}], "tracks": [], "tags": []})
cv.hang_imports = True
cv.status_raise = ApiErr("401 상태 조회")
w.request("p7", "track", [47]); w.tick(10)
check(call_names(cv).count("remove_annotations") == 1 and call_names(cv).count("import_annotations") == 1
      and w.lock(47).get("state") == "quarantine", "가져오기 접수 뒤 상태 조회가 401이어도 되돌리지 않고 '확인 필요' (T1)")
import cvat_ops as CO
rc = CO.RealCvat("https://x", "tok")
class FT:
    id = 5
    def get_labels(self): return []
rc.client = lambda: type("C", (), {"tasks": type("T", (), {"retrieve": staticmethod(lambda i: FT())})()})()
p_ = TMP / "imp.xml"; p_.write_text("<x/>")
def submit_401(t, path, fmt): raise ApiErr("upload 401")
rc._submit = submit_401
try:
    rc.import_annotations(5, str(p_), "CVAT 1.1"); check(False, "접수 거절")
except H.ImportRejected:
    check(True, "실제 어댑터: 접수 자체의 4xx만 '분명한 거절' (T1)")
class Conn(Exception):
    pass
def submit_lost(t, path, fmt): raise Conn("연결 끊김")
rc._submit = submit_lost
try:
    rc.import_annotations(5, str(p_), "CVAT 1.1"); check(False, "모름")
except H.ImportRejected:
    check(False, "접수 연결 끊김을 거절로 봄")
except Conn:
    check(True, "실제 어댑터: 접수 응답을 잃으면 거절이 아니라 '모름'(예외 그대로) (T1)")
rc._submit = lambda t, path, fmt: "rq-1"
check(rc.import_annotations(5, str(p_), "CVAT 1.1") == "rq:rq-1", "실제 어댑터: 접수만 하고 작업 번호를 돌려줌 (기다리지 않음)")
class Req:
    def __init__(self, v): self.status = type("S", (), {"value": v})()
calls_ = []
def retr(rid):
    calls_.append(rid)
    if rid == "bad":
        raise ApiErr("401")
    return Req({"rq-1": "failed", "rq-2": "started"}[rid]), None
rc.client = lambda: type("C", (), {"api_client": type("A", (), {"requests_api": type("R", (), {"retrieve": staticmethod(retr)})()})()})()
check(rc.import_status("rq:rq-1") == "failed" and rc.import_status("rq:rq-2") == "started",
      "실제 어댑터: 서버 작업의 failed는 상태로 (BackgroundRequestException을 거치지 않음)")
try:
    rc.import_status("rq:bad"); check(False, "조회 오류")
except ApiErr:
    check(True, "실제 어댑터: 상태 조회 오류는 예외 그대로 → 처리기가 '모름'")
# T3: 새 TASK 예외는 만든 직후 이름·프로젝트 맞춤에만
cv3 = FakeCvat()
sc3 = H.ScopedCvat(cv3, test=True, project_id=7)
nt3 = sc3.create_from_backup("x.zip", "REH_new", project_id=7)
sc3.rename_task(nt3, "REH_new")
check(refused(lambda: sc3.remove_annotations(nt3)), "만든 직후라도 라벨 지우기·가져오기는 늘 범위 확인 (T3)")
sc3.move_task(nt3, 7); sc3.release_new(nt3)
cv3.tasks[nt3]["name"] = "production_vf"; cv3.tasks[nt3]["project_id"] = 99
check(refused(lambda: sc3.rename_task(nt3, "REH_y")) and refused(lambda: sc3.remove_annotations(nt3)),
      "맞춤을 마치면 예외를 거둠 — 뒤에 범위 밖이 된 TASK는 쓰지 않음 (T3)")
w, cv, env = cr_world()
env.cvat = H.ScopedCvat(cv, test=False, project_id=7)
w.execs[0].h.env = env
w.request("c18", "create16", [], name="eggplant_G6_2_vf_test", server="cvat1",
          params={"backup": "backups/eggplant_G6_1/x.zip", "project_id": 7}); w.tick(8)
check(req_st(w, "c18") == ["done"] and not env.cvat._made, "16번 만들기가 끝나면 그 TASK의 예외가 남지 않음 (T3)")
# T7: 시험 범위로 거르기 전 원래 목록이 한도에 닿았으면 '끝까지'가 아님
w, cv, env = ag_world(test=True)
cv.add_task(96, "eggplant_G6_1_uld"); cv.add_task(97, "REH_eggplant_G6_1_uld")
w.request("f1", "refresh", []); w.tick(6)
old_limit = HA.LIST_LIMIT; HA.LIST_LIMIT = 1
w.request("f2", "refresh", []); w.tick(6)
HA.LIST_LIMIT = old_limit
tr = rj(w, "test/relabel/tracked.json")
check(tr["97"]["in_cvat"] is True and not tr["97"].get("gone_at") and rj(w, "test/relabel/state.json")["list_complete"] is False,
      "시험 범위 거르기 전 목록이 한도에 닿으면 보이지 않은 시험 TASK를 '사라짐'으로 보지 않음 (T7)")
# T6: 새 처리기의 작업 결과가 취합 이력·'작업함'에
w, cv, env = tw_world()
cv.add_task(48, "eggplant_G6_3_8_uld")
cv.add_task(49, "eggplant_G6_3_9_vf", ann={"shapes": [{"h": 1}], "tracks": [], "tags": []})
w.request("p8", "track", [48, 49], params={"model": "fruit_a"}); w.tick(14)
env2 = H.Env(w.store, H.ScopedCvat(cv, test=False, project_id=7), tmp=str(TMP / "t6agg"), clock=w.clk)
w.executor("AG", ["agg"], H.Dispatch(env=env2))
w.request("f6", "refresh", []); w.tick(8)
rows6 = {str(t["id"]): t for t in rj(w, "relabel/state.json")["tasks"]}
r48 = rows6.get("48") or {}
check(r48.get("runs") == 1 and (r48.get("last") or {}).get("status") == "done" and (r48.get("worked") or {}).get("model") == "fruit_a"
      , "새 처리기의 확정 결과가 취합 이력(실행 수·마지막·작업함)에 들어감 (T6)")
check("49" not in rows6 or not rows6["49"].get("worked"), "보류(사람 라벨)는 '작업함'이 아님 (T6)")

shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
