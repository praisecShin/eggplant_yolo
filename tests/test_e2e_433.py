"""v4.33 2b-7 연결 시험 — 실제 심판(MasterLoop)·실행기(Executor) 여럿·처리기(h_*)·가짜 CVAT 하나로 끝에서 끝까지.
Codex 요청 목록(IMPL_CHECKLIST 2b-7):
  ① 백업 선행  ② 사람 라벨 보호  ③ 한 요청(한 TASK)은 한 실행기만  ④ 정지·취소와 확정의 경계
  ⑤ 권한이 바뀐 뒤 복원하지 않음  ⑥ LC·AA·자동 요청의 params가 처리기까지
실제 Drive·CVAT·Kaggle에 접속하지 않습니다. 실행: python3 tests/test_e2e_433.py drive
"""
import json, os, shutil, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(ROOT))
import access, arbiter as A, arb_io as IO, arb_master as M, executor as X, handlers as H
import h_task as HT
from fake_cvat import FakeCvat

H.load_all()
ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

A0, K, G = "a0@x", "k@x", "g@x"
ACC = {"A0": A0, "K": K, "G": G}
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request", "wake", "release"], "status": "active"},
          {"id": "M2", "account": K, "role": "member", "perms": ["request"], "status": "active"}]
_t0 = 1763000000
DAY = _t0 - (_t0 + 9 * 3600) % 86400 + 10 * 3600
TMP = Path(tempfile.mkdtemp(prefix="e2e433_"))
WRITES = ("import_annotations", "remove_annotations", "rename_task")


class Clk:
    def __init__(self, t=DAY): self.t = t
    def __call__(self): return self.t


class Tagged:
    """실행기마다 같은 CVAT(가짜)를 보는 창 — 쓰기마다 누가 했는지 남김."""
    def __init__(self, cv, name, log):
        self._cv, self._name, self._log = cv, name, log

    def __getattr__(self, n):
        f = getattr(self._cv, n)
        if n in WRITES or n == "request_export":
            def g(*a, **k):
                self._log.append((self._name, n, a[0]))
                return f(*a, **k)
            return g
        return f


class Engine:
    def __init__(self): self.calls, self.hook = [], None
    def make_track(self, info, ref_zip, workdir, params, progress):
        self.calls.append(("track", info["id"], dict(params)))
        if self.hook:
            self.hook("prepare", info["id"])
        f = Path(workdir) / "tracks.json"
        f.write_text(json.dumps({"tracks": [{"id": i} for i in range(2)]}))
        return {"file": str(f), "fmt": HT.IMPORT_FMT, "count": 2}
    def make_shapes(self, info, workdir, params, progress):
        self.calls.append(("shape", info["id"], dict(params)))
        return {"shapes": [{"frame": 0, "label": "bud"}]}


class World:
    n = 0

    def __init__(self, gpus=("GPU1",)):
        World.n += 1
        self.clk = Clk()
        self.store = IO.LocalStore(TMP / f"w{World.n}", default_owner=A0, clock=self.clk)
        self.store.write_json(A.P_GRANT, {"epoch": 1, "session": "MS1"}, owner=G)
        self.master = M.MasterLoop(self.store, "MS1", "fpm", lambda: {"accounts": ACC, "people": PEOPLE}, clock=self.clk)
        self.cv, self.log, self.eng = FakeCvat(steps=1, clock=self.clk), [], Engine()
        self.execs, self.dead = {}, set()
        for g in gpus:
            env = H.Env(self.store, H.ScopedCvat(Tagged(self.cv, g, self.log), test=False, project_id=7),
                        tmp=str(TMP / f"t{World.n}_{g}"), clock=self.clk)
            env.engine, env.server, env.import_wait = self.eng, "m1@app.cvat.ai", 600
            env.sleep = lambda s: setattr(self.clk, "t", self.clk.t + s)
            self.execs[g] = X.Executor(self.store, g, "fp" + g, ["gpu"], ACC, H.Dispatch(env=env), clock=self.clk,
                                       mono=self.clk, sleep=lambda s: setattr(self.clk, "t", self.clk.t + s))

    def request(self, rid, kind, tasks, owner=A0, app="requests/", **kw):
        self.store.write_json(f"{app}REQ_{rid}__{kind}__pending.json",
                              dict({"tasks": [str(t) for t in tasks], "created": self.clk()}, **kw), owner=owner)

    def signal(self, kind, owner=A0, **kw):
        sid = f"{kind}__app__{len(list((self.store.root / 'jobs/signals').glob('*.json'))) if (self.store.root / 'jobs/signals').exists() else 0}"
        self.store.write_json(A.P_SIGNALS + sid + ".json", kw, owner=owner)
        return sid

    def tick(self, rounds=1):
        for _ in range(rounds):
            self.clk.t += 20
            self.master.heartbeat()
            for name, e in self.execs.items():
                if name not in self.dead:
                    e.heartbeat()
                    e.step()
            self.master.run_once()

    def lock(self, t):
        f = self.store.root / A.P_LOCK_TASK / f"{t}.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def results(self, rid):
        return {r["task"]: r["result"] for r in (json.loads(f.read_text()) for f in (self.store.root / "arb/results").glob("*.json"))
                if r.get("rid") == rid}

    def status(self, rid):
        return [f.name.rsplit("__", 1)[1][:-5] for d in ("requests", "relabel/requests") if (self.store.root / d).exists()
                for f in (self.store.root / d).glob(f"REQ_{rid}__*")]

    def intake(self, rid):
        f = self.store.root / A.P_INTAKE / f"{rid}.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def master_rounds(self, n):
        """심판만 몇 회차 (처리기 안에서 부를 때 — 실행기는 다시 부르지 않음)."""
        for _ in range(n):
            self.clk.t += 20
            self.master.heartbeat()
            self.master.run_once()

    def writes(self, t=None):
        return [x for x in self.log if x[1] in WRITES and (t is None or x[2] == t)]


# ======================================================== ⑥ LC·AA·자동 요청의 params가 처리기까지
w = World()
for t, nm in ((201, "eggplant_G6_261101_1_1_uld"), (202, "eggplant_G6_261101_1_2_uld"), (203, "eggplant_G6_261101_1_3_uld")):
    w.cv.add_task(t, nm)
w.request("lc1", "track", [201], params={"conf": 0.41, "model": "fruit_a"})
w.request("aa1", "shape", [202], owner=K, app="relabel/requests/", params={"conf": 0.52})
w.request("au1", "track", [203], owner=G, params={"conf": 0.33, "auto": True})
w.request("au2", "dataset", [], owner=G, name="x")
w.tick(25)
got = {c[1]: c[2] for c in w.eng.calls}
check(got.get(201) == {"conf": 0.41, "model": "fruit_a"} and got.get(202) == {"conf": 0.52} and got.get(203) == {"conf": 0.33, "auto": True},
      "⑥ LC(요청 폴더)·AA(relabel)·수집기(G) 요청의 params가 처리기 계산까지 그대로")
check(w.status("lc1") == ["done"] and w.status("aa1") == ["done"] and w.status("au1") == ["done"]
      and w.intake("au1").get("requester") == "system:G" and w.intake("aa1").get("requester") == "M2",
      "세 출처 요청 모두 끝까지 '완료' · 접수에 요청자(사람·수집기)")
check(w.intake("au2").get("reason") == "g_kind_not_allowed" and not w.status("au2") == ["done"],
      "수집기(G)는 자동 요청 종류만 — 관리 일 요청은 접수 거절")

# ======================================================== ① 백업 선행 · ③ 한 TASK는 한 실행기만
w = World(gpus=("GPU1", "GPU2"))
ids = list(range(301, 308))
for t in ids:
    w.cv.add_task(t, f"eggplant_G6_261101_2_{t - 300}_uld", ann={"shapes": [{"old": t}], "tracks": [], "tags": []})
w.request("big", "track", ids[:5])
w.request("big_k", "track", ids[5:], owner=K)                 # 다른 사람의 요청 → 두 실행기가 동시에
w.request("big2", "shape", [301, 302])
w.tick(60)

def backup_before_each_write(seq):
    """쓰기(지우기·가져오기) 묶음마다 그 앞에 업로드 전 export가 있는가."""
    seen_export = False
    for x in seq:
        if x[1] == "request_export":
            seen_export = True
        elif x[1] in ("remove_annotations", "import_annotations"):
            if not seen_export:
                return False
        elif x[1] == "rename_task":
            seen_export = False                               # 다음 확정은 다시 백업부터
    return True
order_ok = all(backup_before_each_write([x for x in w.log if x[2] == t]) for t in ids)
check(order_ok and all((w.store.root / "recovery" / str(t)).exists() for t in ids),
      "① 모든 TASK에서 업로드 전 백업(export)과 복구 자료 게시가 지우기·가져오기보다 먼저")
by_task = {t: {x[0] for x in w.writes(t)} for t in ids}
per_req_imports = [x for x in w.writes() if x[1] == "import_annotations"]
check(all(len(v) == 1 for v in by_task.values()) and {e for v in by_task.values() for e in v} == {"GPU1", "GPU2"},
      "③ 각 TASK의 쓰기는 한 실행기만 (두 실행기가 묶음을 나눠 맡음)")
check(w.status("big") == ["done"] and w.status("big_k") == ["done"] and w.status("big2") == ["done"]
      and len([x for x in per_req_imports if x[2] in (301, 302)]) == 4 and len(per_req_imports) == 9,
      "같은 TASK의 두 요청은 차례대로 (겹쳐 쓰지 않음) · 가져오기 횟수 = 요청×TASK")
rp = [p for p in (w.store.root / "recovery/301").iterdir() if p.is_dir()]
check(len(rp) == 2 and len({p.name for p in rp}) == 2, "같은 TASK의 두 확정은 서로 다른 복구 자료 폴더 (작업 번호 겹침 없음)")

# ======================================================== ② 사람 라벨 보호
w = World()
w.cv.add_task(401, "eggplant_G6_261101_3_1_vf", ann={"shapes": [{"human": 1}], "tracks": [], "tags": []})
w.cv.add_task(402, "humanAA", ann={"shapes": [], "tracks": [], "tags": [{"t": 1}]})
w.cv.add_task(403, "eggplant_G6_261101_3_3_vf", ann={"shapes": [{"human": 3}], "tracks": [], "tags": []})
w.request("h1", "track", [401, 402])
w.request("h2", "track", [403], params={"allow_replace": True})
w.request("h3", "track", [403], params={"allow_replace": "yes"})
w.tick(30)
check(w.results("h1") == {"401": "held:human_labels", "402": "held:human_labels"} and not w.writes(401) and not w.writes(402)
      and w.cv.tasks[401]["ann"]["shapes"] == [{"human": 1}],
      "② 사람 라벨(박스·태그만 있는 것도)이 있는 TASK는 명시 동의 없이 쓰지 않음 · 결과 '보류'")
check(w.results("h2") == {"403": "done"} and (w.store.root / "recovery/403").exists() and
      any(x[1] == "remove_annotations" for x in w.writes(403)),
      "명시 동의(allow_replace = true)가 있으면 업로드 전 백업 뒤 교체")
check(w.results("h3") == {"403": "held:human_labels"} and len([x for x in w.writes(403) if x[1] == "import_annotations"]) == 1,
      "동의 값은 정확히 true만 ('yes' 같은 값은 동의가 아님 → 보류)")

# ======================================================== ④ 취소·정지와 확정의 경계
w = World()
for t in (501, 502, 503):
    w.cv.add_task(t, f"eggplant_G6_261101_4_{t - 500}_uld")
def cancel_at_prepare(stage, tid):
    if tid == 502:
        w.signal("cancel", rid="c1")
w.eng.hook = cancel_at_prepare
w.request("c1", "track", [501, 502, 503])
w.tick(30)
w.eng.hook = None
r = w.results("c1")
check(r == {"501": "canceled", "502": "canceled", "503": "canceled"} and not w.writes() and w.status("c1") == ["canceled"],
      "④ 준비 단계의 취소: 확정 승인 전이던 TASK는 하나도 쓰지 않고 바로 멈춤 · 요청 '취소됨'")
w = World()
for t in (511, 512, 513):
    w.cv.add_task(t, f"eggplant_G6_261101_5_{t - 510}_uld")
at_cancel = {}
def cancel_in_commit(tid):
    if tid == 511 and not at_cancel:
        at_cancel.update({t: w.lock(t).get("state") for t in (511, 512, 513)})
        w.signal("cancel", rid="c2")
        w.master_rounds(2)                                # 심판이 취소를 반영한 뒤에도
w.cv.before_import_hook = cancel_in_commit
w.request("c2", "track", [511, 512, 513])
w.tick(30)
w.cv.before_import_hook = None
r2 = w.results("c2")
approved = [t for t, st_ in at_cancel.items() if st_ == "confirm_approved"]
not_yet = [t for t, st_ in at_cancel.items() if st_ != "confirm_approved"]
check(approved == [511] and all(r2.get(str(t)) == "done" for t in approved)
      and all(r2.get(str(t)) == "canceled" and not w.writes(t) for t in not_yet),
      "확정 승인 뒤의 취소: 확정 신청은 TASK 하나씩 → 지금 확정 중인 TASK 하나만 마치고 나머지는 쓰지 않음 (b24 E15)")
w = World()
for t in (521, 522):
    w.cv.add_task(t, f"eggplant_G6_261101_6_{t - 520}_uld")
def stop_at_prepare(stage, tid):
    if tid == 522 and not getattr(w, "stopped", None):
        w.stopped = w.signal("stop")
w.eng.hook = stop_at_prepare
w.request("s1", "track", [521, 522])
w.tick(25)
w.eng.hook = None
mid_522 = w.writes(522)
w.request("s2", "track", [521])
w.tick(10)
s2_before = w.results("s2")
w.signal("release", stop_id=w.stopped); w.tick(30)
check(w.results("s1").get("521") == "done" and not mid_522 and not s2_before,
      "정지: 확정 중인 TASK만 마치고, 정지 동안 다른 TASK·새 요청은 시작하지 않음")
check(w.results("s1").get("522") == "done" and w.results("s2").get("521") == "done",
      "정지 해제 뒤 남은 TASK·새 요청을 이어서 처리")

# ======================================================== ⑤ 권한이 바뀐 뒤 복원하지 않음
w = World(gpus=("GPU1",))
w.cv.add_task(601, "eggplant_G6_261101_7_1_uld", ann={"shapes": [{"keep": 1}], "tracks": [], "tags": []})
w.cv.import_fail.add(601)                                  # 가져오기가 분명히 실패 → 원래는 되돌리기
real_status = w.cv.import_status
def master_moves_on(job):
    if not getattr(w, "moved", False):                     # 가져오기는 끝났고(실패), 되돌리기 직전에
        w.moved = True
        w.master_rounds(12)                                # GPU1 생존 신호 없이 4분 — 심판이 '확인 필요'로
    return real_status(job)
w.cv.import_status = master_moves_on
w.request("p1", "track", [601])
w.tick(30)
q = w.lock(601)
check(w.moved and q.get("state") == "quarantine" and [x[1] for x in w.writes(601)] == ["remove_annotations", "import_annotations"],
      "⑤ 실행기가 끊긴 것으로 처리된 뒤에는 실패한 가져오기를 되돌리지 않음 (되돌리기 지우기·가져오기 없음) → '확인 필요'")
check(w.status("p1") == ["needs_check"] or "601" not in w.results("p1"),
      "그 TASK의 결과는 '완료'가 아님 (사람 선택 대기)")
w.cv.import_fail.discard(601)
w.cv.import_status = real_status
w.clk.t += 1000; w.tick(2)
w.signal("confirm_choice", task="601", decision=w.lock(601)["decision"], choice="revert")
w.tick(20)
check(w.cv.tasks[601]["ann"]["shapes"] == [{"keep": 1}] and w.cv.tasks[601]["ann"]["tracks"] == []
      and any(s_ == ["done"] for s_ in [w.status(f.name.split("__")[0][4:]) for f in (w.store.root / "requests").glob("REQ_*__recovery__*")]),
      "사람이 '되돌리기'를 고르면 복구 일이 원래 업로드 전 백업으로 되돌림")

shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
