"""v4.33 1b 시험 — 마스터 판정 루프 + 실행기 뼈대 + 저장소 어댑터를 폴더 저장소에서 끝까지 돌림.
실제 Drive·CVAT·Kaggle에 접속하지 않습니다.
실행: python3 tests/test_master_433.py drive
"""
import json, os, shutil, sys, tempfile
from pathlib import Path
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
import access, arbiter as A, arb_io as IO, arb_master as M, executor as X, worker_cpu as W

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

A0, G = "a0@x", "g@x"
ACC = {"A0": A0, "G": G}
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request", "wake", "release"], "status": "active"}]
_t0 = 1763000000
DAY = _t0 - (_t0 + 9 * 3600) % 86400 + 10 * 3600
TMP = Path(tempfile.mkdtemp(prefix="m433_"))


class Clk:
    def __init__(self, t=DAY): self.t = t
    def __call__(self): return self.t


class World:
    """폴더 저장소 하나 + 마스터 + 실행기들. Keeper 역할(자격 주기)은 시험이 직접 함."""
    n = 0

    def __init__(self):
        World.n += 1
        self.clk = Clk()
        self.failing = {}
        self.store = IO.LocalStore(TMP / f"w{World.n}", default_owner=A0, clock=self.clk,
                                   fail=lambda op, path: self.failing.get((op, path), False) or self.failing.get((op, "*"), False))
        self.epoch = 0
        self.master = None
        self.execs = []
        self.seq = 0
        self.new_master()

    def new_master(self):
        self.epoch += 1
        me = f"MS{self.epoch}"
        self.store.write_json(A.P_GRANT, {"epoch": self.epoch, "session": me}, owner=G)
        self.master = M.MasterLoop(self.store, me, "fpm", lambda: {"accounts": ACC, "people": PEOPLE}, clock=self.clk)
        return self.master

    def executor(self, name, caps, handlers):
        e = X.Executor(self.store, name, "fp" + name, caps, ACC, handlers, clock=self.clk, mono=self.clk,
                       sleep=lambda s: setattr(self.clk, "t", self.clk.t + s))
        self.execs.append(e)
        return e

    def request(self, rid, kind, tasks=(), **kw):
        self.store.write_json(f"requests/REQ_{rid}__{kind}__pending.json",
                              dict({"tasks": [str(t) for t in tasks], "created": self.clk()}, **kw))

    def signal(self, kind, **kw):
        self.seq += 1
        sid = f"{kind}__p__{self.seq}"
        self.store.write_json(A.P_SIGNALS + sid + ".json", kw)
        return sid

    def tick(self, rounds=1, dead=()):
        out = None
        for _ in range(rounds):
            self.clk.t += 20
            self.master.heartbeat()
            for e in self.execs:
                if e.me not in dead:
                    e.heartbeat()
                    e.step()
            out = self.master.run_once()
        return out

    def j(self, path):
        f = self.store.root / path
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def lock(self, t):
        return self.j(A.P_LOCK_TASK + f"{t}.json") or {}

    def results(self, rid):
        d = self.store.root / "arb/results"
        return sorted((o["task"], o["result"]) for o in (json.loads(f.read_text()) for f in d.glob("*.json"))
                      if o["rid"] == rid) if d.exists() else []

    def req_status(self, rid):
        for f in (self.store.root / "requests").glob(f"REQ_{rid}__*.json"):
            return A.parse_req_name(f.name)[2]


class TrackH(X.Handlers):
    """track 요청 처리기 흉내: 준비 → (승인 뒤) 복구 자료 게시 → CVAT 쓰기 두 번."""
    def __init__(self):
        self.calls, self.cvat = [], []
        self.early = None
        self.between = None

    def prepare(self, ctx):
        self.calls.append(("prepare", ctx.task))
        if self.early == ctx.task:                      # 승인 전에 CVAT에 쓰려는 잘못된 처리기
            ctx.auth("cvat_write").call("import", lambda: self.cvat.append(("EARLY", ctx.task)))
        return {"xml": f"/tmp/{ctx.task}.xml"}

    def commit(self, ctx):
        self.calls.append(("commit", ctx.task, ctx.prepared["xml"]))
        ctx.auth("recovery_publish").call("recovery", lambda: None)
        w = ctx.auth("cvat_write")
        w.call("remove", lambda: self.cvat.append(("remove", ctx.task)))
        if self.between:
            self.between(ctx)
        try:
            w.call("import", lambda: self.cvat.append(("import", ctx.task)))
        except access.AuthorityLost:
            raise
        except Exception:
            w.call("restore", lambda: self.cvat.append(("restore", ctx.task)))
            return "failed(복원됨)"
        return "done"


# ======================================================== 끝까지: 요청 → 배정 → 확정 → 결과 → 요청 완료
w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1, 2, 3])
w.tick(8)
check(w.results("r1") == [("1", "done"), ("2", "done"), ("3", "done")], "요청 → 배정 → 확정 승인 → 결과: 세 TASK 완료")
check(w.req_status("r1") == "done", "마지막 묶음 뒤 실행기가 요청 이름을 '완료'로 바꿈")
check([c[0] for c in h.calls if c[1] == "1"] == ["prepare", "commit"] and h.cvat.count(("import", "1")) == 1,
      "처리기 순서: 준비 → (승인 뒤) 확정, CVAT 쓰기는 TASK마다 한 번")
steps = sorted(p.name for p in (w.store.root / "recovery/1").rglob("*.json"))
check(any("intent" in s for s in steps) and any("result" in s for s in steps), "단계 기록(의도·결과)이 recovery/<TASK>/<작업번호>/steps에 남음")
arb = w.j(A.P_ARBITER)
check(arb["session"] == "MS1" and arb["round"] >= 8 and w.j("workers/MS1__fpm.json")["last_round"] >= 7,
      "회차 기록은 판정 루프가, 생존 신호는 workers 파일에 (마지막 회차 포함)")
check(all((w.j(str(p.relative_to(w.store.root))) or {}).get("by_session") == "MS1" for p in (w.store.root / "arb/locks").rglob("*.json")),
      "판정 파일에 세션 지문")

# 승인 전 CVAT 쓰기는 권한 확인에서 막힘
w = World(); h = TrackH(); h.early = "7"
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [7]); w.tick(6)
check(not h.cvat and w.results("r1") == [("7", "failed:AuthorityLost")],
      "승인 전에 CVAT에 쓰려는 처리기 → 권한 확인이 막고 '실패'로 보고 (CVAT 호출 없음)")
check(w.req_status("r1") == "failed", "요청은 '실패'로 끝남 (거짓 완료 없음)")

# ======================================================== 마스터 쓰기 실패·교체
w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1, 2])
w.failing[("write", A.P_LOCK_TASK + "2.json")] = True          # 잠금 하나를 못 씀
r = w.tick(1)
check(r.failed_at == A.P_LOCK_TASK + "2.json" and r.applied < r.writes, "쓰기가 중간에 실패하면 그 자리에서 멈춤")
w.failing.clear(); w.tick(8)
check(w.results("r1") == [("1", "done"), ("2", "done")], "다음 회차들이 이어서 마침 (빠진 잠금을 채움)")

w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1, 2]); w.tick(2)
st0 = w.lock(1)
w.new_master()                                                   # 마스터 교체 (새 epoch)
w.tick(8)
check(w.results("r1") == [("1", "done"), ("2", "done")] and w.j(A.P_HANDOVER + "2.json") is not None,
      "마스터가 바뀌어도(새 epoch) 실행기가 새 gen으로 다시 보고해 끝까지 마침")
check(h.cvat.count(("import", "1")) == 1 and h.cvat.count(("import", "2")) == 1, "마스터 교체 중에도 CVAT 쓰기는 한 번씩")
old = M.MasterLoop(w.store, "MS1", "fpm", lambda: {"accounts": ACC, "people": PEOPLE}, clock=w.clk)
r = old.run_once()
check(not r.acting and r.writes == 0, "자격을 잃은 옛 마스터는 아무것도 쓰지 않음")

# ======================================================== 못 읽으면 '모름'
w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [5]); w.tick(2)
w.failing[("read", A.P_LOCK_TASK + "5.json")] = True
w.master.cache.items.clear()
r = w.tick(1)
check("file:" + A.P_LOCK_TASK + "5.json" in r.unknown, "파일을 못 읽으면 '없음'이 아니라 '모름'으로 전달")
w.failing.clear(); w.tick(6)
check(w.results("r1") == [("5", "done")], "읽히면 이어서 마침")
w.failing[("list", "arb/")] = True
n0 = w.j(A.P_ARBITER)["round"]
r = w.tick(1)
check("state" in r.unknown and r.writes == 0 and w.j(A.P_ARBITER)["round"] == n0, "arb/ 목록을 못 읽으면 회차 기록도 쓰지 않음 (옛 기록을 덮지 않음)")
w.failing.clear()
bad = M.MasterLoop(w.store, "MS1", "fpm", lambda: (_ for _ in ()).throw(IOError("x")), clock=w.clk)
check(not bad.run_once().acting, "사람 목록·계정 지도를 못 읽으면 판정하지 않음")

# ======================================================== 취소·정지
w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1, 2, 3]); w.tick(1)
w.signal("cancel", rid="r1"); w.tick(8)
res = dict(w.results("r1"))
check(all(v in ("done", "canceled") for v in res.values()) and "canceled" in res.values() and w.req_status("r1") == "canceled",
      "취소: 준비 단계의 TASK는 멈추고 요청은 '취소됨'")
check(len([c for c in h.cvat if c[0] == "import"]) == list(res.values()).count("done"), "취소된 TASK는 CVAT에 쓰지 않음")

w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
w.request("r1", "track", [1, 2]); w.tick(1)
st = w.signal("stop"); w.tick(6)
check(w.j(A.P_HOLD + st + ".json")["active"] and not [a for a in (w.store.root / "arb/assign").glob("*.json")
                                                      if json.loads(a.read_text())["state"] == "active"],
      "정지: 실행기가 묶음을 반납하고 새 배정이 없음")
w.signal("release", stop_id=st); w.tick(10)
check(w.results("r1") == [("1", "done"), ("2", "done")], "해제 뒤 다시 배정받아 마침")

# ======================================================== 확정 중 권한 잃음 → 복원하지 않고 멈춤
w = World(); h = TrackH()
w.executor("E1", ["gpu"], h)
def lose(ctx):                                                   # 첫 CVAT 호출 뒤 실행기가 오래 멈춤 → 심판이 격리
    w.clk.t += 400
    w.master.run_once()
h.between = lose
w.request("r1", "track", [9]); w.tick(5)
check(w.lock(9).get("state") == "quarantine", "확정 중 생존 신호가 끊기면 심판이 '확인 필요'로 격리")
check(("import", "9") not in h.cvat and ("restore", "9") not in h.cvat,
      "깨어난 옛 실행기는 다음 CVAT 호출 전에 권한 확인에서 걸려, 올리기도 복원도 하지 않음")
check(not w.results("r1") and w.req_status("r1") == "pending", "격리된 TASK는 완료로 표시되지 않음")

# ======================================================== 받는 중 일 (백업): 준비 대기 → 게시 잠금 → 게시
class BackupH(X.Handlers):
    def __init__(self): self.asked, self.pub = 0, []
    def fetch(self, ctx):
        self.asked += 1
        return self.asked >= 3                                   # 서버가 세 번째에 준비됨
    def publish(self, ctx):
        ctx.auth("publish").call("publish", lambda: self.pub.append(ctx.task))
        return "done"
w = World(); bh = BackupH()
w.executor("C1", ["cpu"], bh)
w.request("bk", "backup", [4]); w.tick(10)
check(bh.pub == ["4"] and w.results("bk") == [("4", "done")] and w.lock(4).get("state") == "free" and w.req_status("bk") == "done",
      "백업: 받는 동안은 잠금 없이 기다리고, 게시할 때만 잠금 → 결과 → 잠금 풀림")

# ======================================================== 실행형 일: 데이터셋(채택)·FORCE_NEW·처리기 없음
class MgmtH(X.Handlers):
    def run(self, ctx):
        if ctx.kind == "dataset":
            ctx.auth("run").call("publish", lambda: w.store.write_json(
                f"datasets/ds/v/{ctx.run}/_files.json", {"files": {"a": "h"}, "task_keys": ["t1"]}))
            return {"report": "done_run", "type_": "dataset", "name": "ds"}
        if ctx.kind == "force_new":
            return {"report": "done_job", "result": "done", "current_change": {"type": "dataset", "name": "ds", "version": None}}
        raise RuntimeError("모르는 일")
w = World()
w.executor("C1", ["cpu"], MgmtH())
w.request("d1", "dataset", [], name="ds"); w.tick(5)
cur = w.j("datasets/ds/CURRENT.json")
check(cur and cur["version"].startswith("mgmt_") and w.j(A.P_LOCK_MGMT)["state"] == "done" and w.req_status("d1") == "done",
      "관리 일(데이터셋): 버전 경로에 쓰고 완료 보고 → 심판이 채택 → 요청 완료")
w.request("f1", "force_new", [], name="ds"); w.tick(5)
check(w.j("datasets/ds/CURRENT.json")["version"] is None and w.j("datasets/ds/CURRENT.json")["adopted_gen"] == 2,
      "FORCE_NEW: 채택 표시만 바뀜")
w.request("c1", "cleanup34", []); w.tick(5)
check(w.results("c1") == [("run", "failed:RuntimeError")] and w.req_status("c1") == "failed" and w.j(A.P_LOCK_MGMT)["state"] == "done",
      "실행형 일이 실패하면 '실패'로 끝나고 관리 잠금은 풀림")

# ======================================================== worker_cpu
os.environ.pop(access.MODE_VAR, None)
try:
    W.run(IO.LocalStore(TMP / "x"), ACC, ["cpu"], max_steps=1)
    check(False, "분석 모드에서 작업 프로세스 거절")
except access.AccessError:
    check(True, "작업 프로세스는 EGG_ACCESS=exec가 아니면 돌지 않음")
os.environ[access.MODE_VAR] = "exec"
w = World()
ran = []
W.HANDLERS.clear()
W.register("cleanup34", run=lambda ctx: ran.append(ctx.rid) or {"report": "done_job", "result": "done"})
w.request("c1", "cleanup34", []); w.request("c2", "cleanup29", [])
ex = None
for i in range(8):
    w.clk.t += 20; w.master.heartbeat()
    ex = W.run(w.store, ACC, ["cpu"], session="CPU1", max_steps=1, clock=w.clk) if ex is None else ex
    ex.heartbeat(); ex.step(); w.master.run_once()
check(ran == ["c1"] and w.results("c1") == [("run", "done")], "worker_cpu: 등록한 처리기로 관리 일 처리")
check(w.results("c2") == [("run", "failed:NoHandler")], "처리기가 없는 종류는 '실패(처리기 없음)'로 보고 (거짓 완료 없음)")
os.environ.pop(access.MODE_VAR, None)

# ======================================================== rclone 저장소 (가짜 rclone)
calls = []
LS = [{"Path": "ARBITER_GRANT.json", "Name": "ARBITER_GRANT.json", "Size": 30, "ModTime": "2026-11-14T04:06:49.123456789Z",
       "IsDir": False, "Metadata": {"owner": "g@x", "btime": "2026-11-14T04:00:00Z"}}]
def fake_rclone(args, input=None, timeout=60):
    calls.append((args, input))
    if args[0] == "lsjson":
        if "jobs/" in args[1] and "ARBITER_GRANT.json" in args:
            return 0, json.dumps(LS), ""
        if "workers/" in args[1]:
            return 3, "", "Failed to lsjson: directory not found"
        if "requests/" in args[1] and "relabel" not in args[1]:
            return 1, "", "googleapi: Error 500"
        return 0, "[]", ""
    if args[0] == "cat":
        return (0, json.dumps({"epoch": 3, "session": "MS3"}), "") if "GRANT" in args[1] else (1, "", "x")
    if args[0] == "rcat":
        return 0, "", ""
    return 0, "", ""
rs = IO.RcloneStore("gdrive:eggplant_yolo", runner=fake_rclone)
files, unknown, started = IO.snapshot(rs)
g = files.get(A.P_GRANT)
check(g and g.owner == "g@x" and g.obj["epoch"] == 3 and g.created < g.modified, "rclone 목록에서 소유 계정·만든 시각·수정 시각을 읽음")
check("requests" in unknown and "workers" not in unknown, "목록 실패 → 그 종류 '모름' / 폴더가 아직 없는 것은 빈 목록")
check(all(a[0][1].startswith("gdrive:eggplant_yolo/") for a in calls), "원격 경로는 공유 폴더 아래")
rs.write_json("arb/x.json", {"a": 1})
check(calls[-1][0][0] == "rcat" and json.loads(calls[-1][1]) == {"a": 1}, "쓰기는 rcat (내용은 표준 입력으로)")
LS2 = list(LS)
check(rs.write_json(A.P_GRANT, {}, create_only=True) is False, "'없을 때만 만들기'는 있으면 쓰지 않음")
rs2 = IO.RcloneStore("gdrive:", runner=lambda a, i=None, timeout=60: (124, "", "timeout"))
f2, u2, _ = IO.snapshot(rs2)
check({"grant", "requests", "workers", "state", "asks", "signals", "artifacts"} <= u2 and not f2, "rclone이 시간 초과면 전부 '모름'")
check(abs(IO._iso("2026-11-14T04:06:49.123456789Z") - IO._iso("2026-11-14T13:06:49.123456+09:00")) < 1e-3, "시각 해석 (나노초·시간대)")

shutil.rmtree(TMP, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
