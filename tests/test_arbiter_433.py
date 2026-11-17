"""v4.33 심판 판정 함수 시험 (v4.33.0b) — 설계 8판, 1a 검토 M1~M12 반영.
가짜 저장소에서 장애 순서를 재현하고, 대표 장면의 **모든 쓰기 경계에서 끊어도** 정상 실행과 같은
최종 상태로 돌아오는지 확인합니다.
실행: python3 tests/test_arbiter_433.py drive
"""
import copy, sys
from pathlib import Path
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
import arbiter as A
from arbiter import FileRec, Cfg, Inputs

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

A0, G, X, M2A = "a0@x", "g@x", "stranger@x", "m2@x"
ACC = {"A0": A0, "G": G}
PEOPLE = [{"id": "M1", "account": A0, "role": "admin", "perms": ["request", "wake", "release"], "status": "active"},
          {"id": "M2", "account": M2A, "role": "user", "perms": ["request"], "status": "active"}]
_t0 = 1763000000
DAY0 = _t0 - (_t0 + 9 * 3600) % 86400
DAY = DAY0 + 10 * 3600
NIGHT = DAY0 + 23 * 3600


class Sim:
    """Drive 대신 사전. 실행기·앱·심판은 모두 A0 토큰, 자격 파일만 G 소유."""
    def __init__(self, now=DAY, me="MS1", people=None):
        self.f, self.now, self.me = {}, now, me
        self.people = people or PEOPLE
        self.seq, self.dead = 0, set()

    def put(self, path, obj, owner=A0, t=None):
        t = self.now if t is None else t
        prev = self.f.get(path)
        self.f[path] = FileRec(copy.deepcopy(obj), prev.owner if prev else owner, prev.created if prev else t, t)

    def grant(self, epoch, session=None, owner=G):
        self.me = session or self.me
        self.f[A.P_GRANT] = FileRec({"epoch": epoch, "session": self.me}, owner, self.now, self.now)

    def worker(self, s, caps, fp="fp0", stopping=False):
        self.put(A.P_WORKERS + f"{s}__{fp}.json", {"session": s, "caps": caps, "fp": fp, "hb": self.now,
                                                   "stopping": stopping})

    def kill(self, s):
        self.dead.add(s)

    def request(self, rid, kind, tasks=(), owner=A0, created=None, app="requests/", status="pending", **kw):
        self.put(f"{app}REQ_{rid}__{kind}__{status}.json",
                 dict({"tasks": [str(t) for t in tasks], "created": self.now if created is None else created}, **kw), owner)

    def ask(self, s, typ, **kw):
        self.seq += 1
        self.put(A.P_ASK + f"{s}__{kw.get('task', 'x')}__{self.seq}.json", dict(kw, type=typ, session=s))

    def signal(self, kind, owner=A0, **kw):
        self.seq += 1
        sid = f"{kind}__p__{self.seq}"
        self.put(A.P_SIGNALS + sid + ".json", kw, owner)
        return sid

    def epoch(self):
        return self.f[A.P_GRANT].obj["epoch"]

    def round(self, crash_after=None, unknown=(), **inp):
        cfg = Cfg(me=self.me, accounts=ACC, people=self.people)
        ins = Inputs(now=self.now, files=self.f, list_started_at=self.now - 3, unknown=set(unknown), **inp)
        res = A.decide_round(cfg, ins)
        for i, w in enumerate(res.writes):
            if crash_after is not None and i >= crash_after:
                break
            if w.mode == "create" and w.path in self.f:
                continue
            self.put(w.path, w.obj)
        return res

    def o(self, path):
        r = self.f.get(path)
        return r.obj if r else None

    def lock(self, t):
        return self.o(A.P_LOCK_TASK + f"{t}.json") or {}

    def assigns(self, rid=None, state=None):
        return [r.obj for p, r in sorted(self.f.items()) if p.startswith(A.P_ASSIGN)
                and (rid is None or r.obj.get("rid") == rid) and (state is None or r.obj.get("state") == state)]

    def akey(self, rid, state="active"):
        for p, r in sorted(self.f.items()):
            if p.startswith(A.P_ASSIGN) and r.obj.get("rid") == rid and r.obj.get("state") == state:
                return A._name(p)

    def intake(self, rid):
        return self.o(A.P_INTAKE + rid + ".json") or {}

    def done(self, sid):
        return self.o(A.P_DONE + sid + ".json")

    def results(self, rid=None):
        return [r.obj for p, r in self.f.items() if p.startswith(A.P_RESULTS) and (rid is None or r.obj.get("rid") == rid)]

    def tick(self, sec):
        self.now += sec
        for p, r in self.f.items():
            if p.startswith(A.P_WORKERS) and r.obj.get("session") not in self.dead:
                r.obj["hb"] = self.now

    # ---- 실행기 보고 (완전한 식별 묶음)
    def confirm(self, s, t, job, **over):
        lk = self.lock(t)
        a = dict(rid=lk.get("rid"), chunk=lk.get("chunk"), job=job, epoch=self.epoch(), gen=lk.get("gen"),
                 decision=lk.get("decision"), task=str(t), recovery_dir=f"recovery/{t}/{job}")
        a.update(over)
        self.ask(s, "confirm", **a)

    def end(self, s, t, job, result="done", **over):
        lk = self.lock(t)
        a = dict(rid=lk.get("rid"), chunk=lk.get("chunk"), job=job, epoch=self.epoch(), gen=lk.get("gen"),
                 decision=lk.get("decision"), task=str(t), result=result)
        a.update(over)
        self.ask(s, "end", **a)

    def stop_report(self, s, t, **over):
        lk = self.lock(t)
        a = dict(rid=lk.get("rid"), chunk=lk.get("chunk"), epoch=self.epoch(), decision=lk.get("decision"),
                 task=str(t), reason="lost")
        a.update(over)
        self.ask(s, "stop", **a)

    def release(self, s, rid):
        k = self.akey(rid)
        a = self.o(A.P_ASSIGN + k + ".json")
        self.ask(s, "release", assign=k, rid=rid, chunk=a["chunk"], epoch=self.epoch(), decision=a["decision"])

    def run_report(self, s, lane, typ, **kw):
        self.ask(s, typ, lane=lane, epoch=self.epoch(), **kw)


def basic(now=DAY):
    s = Sim(now)
    s.grant(1)
    s.worker("MS1", ["cpu"])
    return s


def assigned_sim(tasks=(7,)):
    s = basic()
    s.worker("E1", ["gpu"])
    s.request("r1", "track", tasks)
    s.round()
    return s


def approved_sim():
    s = assigned_sim()
    s.confirm("E1", 7, "j1"); s.tick(20); s.round()
    return s


def view(s, **kw):
    return A.View(Cfg(s.me, ACC, s.people), Inputs(kw.pop("now", s.now), s.f, s.now, **kw), A.Result())


# ======================================================== 자격 (M8)
s = basic(); s.f[A.P_GRANT] = FileRec({"epoch": 1, "session": "OTHER"}, G)
r = s.round()
check(not r.acting and not r.writes, "자격이 내 것이 아니면 아무것도 쓰지 않음")
s = basic(); s.grant(1, owner=A0)
check(not s.round().acting, "자격 파일이 G 소유가 아니면 판정하지 않음")
s = basic(); s.grant(1, owner="")
s.worker("E1", ["gpu"]); s.request("g0", "track", [1])
r = s.round()
check(not r.acting and not s.assigns(), "자격 파일의 소유자를 못 읽으면(모름) 판정·배정하지 않음 (M8)")

# ======================================================== 입력 불변 (M7)
s = basic()
s.worker("C1", ["cpu"])
s.request("d1", "dataset", [], name="ds")
s.round()
mg = s.o(A.P_LOCK_MGMT)
s.put(f"datasets/ds/v/{mg['run']}/_files.json", {"files": {"a": "h"}})
s.run_report("C1", "mgmt", "done_run", type_="dataset", name="ds", run=mg["run"], rid="d1", gen=mg["gen"],
             decision=mg["decision"])
before = copy.deepcopy({p: (r.obj, r.owner) for p, r in s.f.items()})
res = A.decide_round(Cfg("MS1", ACC, PEOPLE), Inputs(s.now, s.f, s.now))
after = {p: (r.obj, r.owner) for p, r in s.f.items()}
check(before == after and any(w.path == "datasets/ds/CURRENT.json" for w in res.writes),
      "판정 함수는 입력 파일 사전을 바꾸지 않음 (채택은 쓰기 목록에만) (M7)")

# ======================================================== 접수·신원
s = basic()
s.request("r1", "track", [1], owner=A0)
s.request("r2", "track", [3], owner=X)
s.request("r3", "recovery", [4], owner=A0, by_signal="fake__1", by_session="X", by_epoch=1)
s.request("r4", "track", [5], owner="")
s.request("r5", "backup", [6], owner=G)
s.request("r6", "cleanup34", [], owner=G)
s.round()
check(s.intake("r1").get("requester") == "M1", "A0 소유 요청 → 요청자 M1")
check(s.intake("r2").get("reason") == "not_registered", "미등록 계정 요청 → 거절")
check(s.intake("r3").get("reason") == "recovery_not_by_arbiter", "심판의 신호 계획 없는 복구 요청 → 거절")
check(s.intake("r4") == {}, "소유 계정 모름 → 접수 기록 안 씀 (다음 회)")
check(s.intake("r5").get("requester") == "system:G", "수집기(G) 자동 요청(백업) → 시스템")
check(s.intake("r6").get("reason") == "g_kind_not_allowed", "G가 만든 관리 일 요청 → 거절 (G 입력은 종류 제한)")
s = basic()
s.worker("E1", ["gpu"])
s.request("r1", "track", [1], owner=M2A)
s.round()
o = s.f.pop("requests/REQ_r1__track__pending.json")
s.put("requests/REQ_r1__track__taken.json", o.obj, A0)
s.tick(30); s.round()
check(s.intake("r1").get("requester") == "M2", "상태 이름을 바꿔 다시 게시돼도 요청자는 접수 기록대로")

# ======================================================== 배정·차례
s = basic()
for e in ("E1", "E2", "E3"):
    s.worker(e, ["gpu"])
s.request("a1", "track", list(range(1, 13)), created=DAY - 100)
s.request("a2", "track", [20, 21], created=DAY - 90)
s.request("b1", "track", [2, 30], owner=M2A, created=DAY - 80)
s.round()
a1 = s.assigns("a1", "active")
check(len(a1) == 1, "한 요청에 묶음 하나")
check(a1 and a1[0]["tasks"] == ["1", "2", "3", "4", "5"], "묶음은 5개")
check(not s.assigns("a2", "active"), "같은 사람은 묶음 하나가 끝나야 다음 차례")
b1 = s.assigns("b1", "active")
check(b1 and b1[0]["tasks"] == ["30"], "다른 사람은 함께 받되 앞 요청이 기다리는 TASK 2는 뺌")
check(s.lock(1).get("decision") == a1[0]["decision"], "assign과 잠금의 decision이 같음")

s = basic()
s.worker("C1", ["cpu"]); s.worker("E1", ["gpu"])
s.request("x1", "backup", [1, 2], created=DAY - 100)
s.request("y1", "track", [1], owner=M2A, created=DAY - 50)
s.round()
check(s.assigns("x1", "active") and s.lock(1).get("rid") == "y1", "받는 중(백업)은 잠금을 잡지 않고 순서도 막지 않음")

s = basic(NIGHT)
s.worker("E1", ["gpu"])
s.request("n1", "track", [1])
s.round()
check(not s.assigns("n1"), "밤에는 야간 승인 안 된 요청을 배정하지 않음")
check(s.o(A.P_ARBITER)["wake"]["next_wake_at"] == A.next_morning(NIGHT), "밤 미승인 대기 → next_wake_at = 아침")
s.signal("approve_night", rid="n1"); s.tick(20); s.round()
check(s.assigns("n1", "active"), "야간 승인 신호 뒤 배정")

# TASK 없는 요청도 배정·완료 (M10)
s = basic()
s.worker("C1", ["cpu"]); s.worker("AG", ["agg"])
s.request("c1", "create17", [], name="v_new", server="cvat1")
s.request("f1", "refresh", [])
s.round()
ca = s.assigns("c1", "active"); fa = s.assigns("f1", "active")
check(ca and fa, "TASK 번호가 없는 요청(새 TASK 만들기·전체 새로 고침)도 배정 (M10)")
key = A.create_key("cvat1", "v_new")
cl = s.o(A.P_LOCK_CREATE + key + ".json")
check(cl and cl["state"] == "running", "새 TASK 만들기는 같은 서버·이름 잠금을 잡음")
s.request("c2", "create17", [], name="V_new ", server="cvat1")
s.worker("C2", ["cpu"]); s.tick(20); s.round()
check(not s.assigns("c2", "active"), "같은 서버·정규화한 이름의 다른 만들기는 기다림")
s.run_report("C1", "create", "done_job", run=cl["run"], key=key, rid="c1", gen=cl["gen"], decision=cl["decision"],
             result="done", task_id=901)
ag = s.o(A.P_LOCK_AGG)
s.run_report("AG", "agg", "done_job", run=ag["run"], rid="f1", gen=ag["gen"], decision=ag["decision"], result="done")
s.tick(20); s.round()
check(any(r["task"] == "create" and r.get("task_id") == 901 for r in s.results("c1")), "만들기 완료 → 결과 기록(새 번호 포함)")
check(s.o(A.P_LOCK_AGG)["state"] == "done" and not s.assigns("f1", "active"), "취합 잠금·배정 끝")
check(s.assigns("c2", "active") and s.o(A.P_LOCK_CREATE + key + ".json")["rid"] == "c2",
      "앞 만들기가 끝나면 같은 이름 만들기가 바로 차례를 받음")

# ======================================================== 확정·보고 식별 (M3)
s = assigned_sim()
s.confirm("E1", 7, "j1"); s.tick(20); s.round()
check(s.lock(7).get("state") == "confirm_approved" and s.lock(7).get("job") == "j1", "식별 묶음이 맞는 확정 신청 → 승인")
s.end("E1", 7, "j1", epoch=-99); s.tick(20); s.round()
check(s.lock(7).get("state") == "confirm_approved", "epoch가 다른 끝 보고 → 거절 (M3)")
s.end("E1", 7, "j1", chunk=-99); s.tick(20); s.round()
check(s.lock(7).get("state") == "confirm_approved", "chunk가 다른 끝 보고 → 거절")
s.end("E1", 7, "j1", gen=-99); s.tick(20); s.round()
check(s.lock(7).get("state") == "confirm_approved", "gen이 다른 끝 보고 → 거절")
s.end("E1", 7, "j0"); s.tick(20); s.round()
check(s.lock(7).get("state") == "confirm_approved", "작업번호가 다른 끝 보고 → 거절")
lk = s.lock(7)
s.ask("E1", "end", rid="r1", job="j1", decision=lk["decision"], task="7", result="done")    # epoch·gen·chunk 빠짐
s.tick(20); r = s.round()
check(s.lock(7).get("state") == "confirm_approved" and any("incomplete_report" in str(w.obj) for w in r.writes),
      "식별 항목이 빠진 보고 → 거절·알림")
s.end("E1", 7, "j1"); s.tick(20); s.round()
check(s.lock(7).get("state") == "free" and any(x["task"] == "7" and x["result"] == "done" for x in s.results("r1")),
      "완전한 끝 보고 → 결과 기록 + 잠금 풀림")

s = assigned_sim()
s.confirm("E1", 7, "j1", gen=s.lock(7)["gen"] - 1); s.tick(20); s.round()
check(s.lock(7).get("state") == "held", "gen이 다른 확정 신청 → 승인 안 함")
s.confirm("E1", 7, "j1", epoch=0); s.tick(20); s.round()
check(s.lock(7).get("state") == "held", "epoch가 다른 확정 신청 → 승인 안 함")
s = assigned_sim()
s.signal("cancel", rid="r1")
s.confirm("E1", 7, "j1"); s.tick(20); s.round()
check(s.lock(7).get("state") == "held" and s.intake("r1").get("cancel_signal"), "취소된 요청의 확정 신청 → 승인 안 함")

# ======================================================== 실행기 권한 확인 (M1)
s = assigned_sim()
dec = s.lock(7)["decision"]
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "prepare") == (True, ""), "배정 직후: 준비 단계는 허용")
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "cvat_write", job="j1")[1] == "not_approved",
      "배정 직후(승인 전): CVAT 쓰기는 거절 (M1)")
s.confirm("E1", 7, "j1"); s.tick(20); s.round()
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "cvat_write", job="j1") == (True, ""), "확정 승인 + 작업번호 일치 → CVAT 쓰기 허용")
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "cvat_write", job="j2")[1] == "job_mismatch", "작업번호가 다르면 거절")
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "recovery_publish", job="j1") == (True, ""), "복구 자료 게시는 승인 뒤")
s.kill("E1"); s.tick(200); s.round()
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "cvat_write", job="j1")[1] == "quarantined",
      "'확인 필요'로 격리된 TASK → 옛 실행기의 쓰기 거절 (M1)")
s = assigned_sim()
dec = s.lock(7)["decision"]
s.grant(2);
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "prepare")[1] == "wait_reissue", "자격 바뀌고 다시 발급 전 → 기다림")
s.tick(20); s.round()
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "prepare") == (True, ""), "다시 발급 뒤 → 이어 감 (같은 decision)")
check(A.executor_may_follow(s.f, ACC, "E2", "7", dec, "prepare")[1] == "lost", "다른 세션 → 권한 잃음")
s.f[A.P_LOCK_TASK + "7.json"].obj = {k: x for k, x in s.lock(7).items() if k not in ("by_session", "by_epoch")}
check(A.executor_may_follow(s.f, ACC, "E1", "7", dec, "prepare")[1] == "lock_untrusted", "세션 표시가 없는 잠금 → 따르지 않음")

# ======================================================== 만료·'확인 필요' 선택 (H1)
s = approved_sim()
lk = s.lock(7)
s.kill("E1"); s.tick(200); s.round()
check(s.lock(7).get("state") == "quarantine", "확정 승인 뒤 끊김 → 격리")
check(not A.choice_open(view(s), s.lock(7)), "끊긴 직후 선택 닫힘")
check(A.choice_open(view(s, now=s.now + 1000, import_pending={"7": False}), s.lock(7)), "15분 + 진행 중 가져오기 없음 → 열림")
check(not A.choice_open(view(s, now=s.now + 1000, import_pending={"7": True}), s.lock(7)), "진행 중 가져오기 있으면 닫힘")
check(A.choice_open(view(s, kernel_status={"E1": "ended"}), s.lock(7)), "커널 종료 확인 → 열림")
sid = s.signal("confirm_choice", task="7", decision=lk["decision"], choice="ok")
s.tick(20); s.round()
check(s.lock(7).get("state") == "quarantine" and "choice_not_open" in str(s.done(sid)), "닫힌 동안의 선택 → 무효(이유 기록)")
s3 = copy.deepcopy(s)
s3.signal("confirm_choice", owner=M2A, task="7", decision=lk["decision"], choice="ok", force=True)
s3.tick(20); s3.round()
check(s3.lock(7).get("state") == "quarantine", "관리자가 아닌 사람의 강제 해제 → 무효")
s3.signal("confirm_choice", task="7", decision=lk["decision"], choice="ok", force=True)
s3.tick(20); s3.round()
check(s3.lock(7).get("state") == "free", "관리자 강제 해제 → 풀림")

# ======================================================== 신호 (K1·J4)
s = assigned_sim(tasks=range(1, 8))
sid = s.signal("cancel", rid="r1")
s.tick(20); s.round(crash_after=1)
check(sid in [A._name(p) for p in s.f if p.startswith(A.P_PLAN)] and not s.intake("r1").get("cancel_signal"), "취소 계획만 쓰고 끊김")
s.kill("E1"); s.worker("E2", ["gpu"]); s.tick(200); s.grant(2, session="MS2")
s.round(); s.tick(20); s.round()
check(s.intake("r1").get("cancel_signal") == sid and not s.assigns("r1", "active"), "새 마스터에서 취소 적용, 다시 배정 안 함 (K1)")

s = basic()
s.request("rf", "track", [1]); s.round()
o = s.f.pop("requests/REQ_rf__track__pending.json"); s.put("requests/REQ_rf__track__done.json", o.obj)
sid = s.signal("cancel", rid="rf"); s.tick(20); s.round()
check(s.done(sid)["effects"]["mark"].startswith("invalid:already_done"), "이미 끝난 요청의 취소 → 무효화(이유)")

s = approved_sim()
lk = s.lock(7)
s.kill("E1"); s.tick(1200); s.round()
sid = s.signal("confirm_choice", task="7", decision=lk["decision"], choice="ok")
s.tick(20); s.round(crash_after=1, import_pending={"7": False})
s.grant(2, session="MS2")
s.put(A.P_LOCK_TASK + "7.json", {"task": "7", "state": "held", "session": "E5", "rid": "r9", "decision": "dX",
                                  "epoch": 2, "gen": 99, "chunk": 1, "by_session": "MS2", "by_epoch": 2})
s.put(A.P_HANDOVER + "2.json", {"epoch": 2, "by_session": "MS2", "by_epoch": 2})
s.worker("E5", ["gpu"]); s.tick(20); s.round(import_pending={"7": False})
check(s.lock(7).get("session") == "E5" and "invalid" in str(s.done(sid)), "옛 선택 신호 복구가 새 epoch 잠금을 되돌리지 않음 (J4)")

# G 소유 신호: Keeper의 해제는 원래 관리자 신호가 있어야
s = basic()
st = s.signal("stop")
s.tick(20); s.round()
fake = s.signal("cancel", owner=G, rid="zz")
s.tick(20); s.round()
check(s.done(fake)["result"] == "rejected", "G가 만든 취소 신호 → 거절 (G 입력은 해제만)")
orig = s.signal("wake", stop_id=st)
rl = s.signal("release", owner=G, stop_id=st, origin_signal=orig)
s.tick(20); s.round()
check(s.done(rl)["result"] == "done" and not s.o(A.P_HOLD + st + ".json")["active"], "Keeper(G) 해제 + 원래 관리자 신호 → 해제")
st2 = s.signal("stop"); s.tick(20); s.round()
orig2 = s.signal("wake", owner=M2A, stop_id=st2)
rl2 = s.signal("release", owner=G, stop_id=st2, origin_signal=orig2)
s.tick(20); s.round()
check(s.done(rl2)["result"] == "rejected", "원래 신호가 관리 권한 없는 사람의 것 → 거절")

# ======================================================== 정지 보류·기한 (M11)
s = basic()
s.worker("E1", ["gpu"])
st = s.signal("stop", until=DAY + 300)
s.tick(20); s.round()
s.request("h2", "track", [9]); s.tick(20); s.round()
check(not s.assigns("h2") and s.o(A.P_ARBITER)["wake"]["next_wake_at"] == DAY + 300, "기한 있는 보류 중: 배정 없음, next_wake_at = 기한")
s.tick(400); s.round(); s.tick(20); s.round()
check(not s.o(A.P_HOLD + st + ".json")["active"] and s.assigns("h2", "active"), "기한이 지나면 보류가 풀리고 배정 재개 (M11)")

# ======================================================== 관리 일·학습·채택
s = basic()
s.worker("C1", ["cpu"])
s.request("m1", "restore23", [], created=DAY - 100)
s.request("m2", "cleanup34", [], created=DAY - 50)
s.round()
check(not s.assigns("m1") and s.assigns("m2", "active"), "Colab 실행기 없는 23번은 비켜 두고 34번 진행")
check(s.o(A.P_ARBITER)["check"]["executor_wait"] == ["m1"], "비켜 둔 일은 '실행기 대기'")
mg = s.o(A.P_LOCK_MGMT)
s.run_report("C1", "mgmt", "done_job", run=mg["run"], rid="m2", gen=mg["gen"], decision=mg["decision"], result="done")
s.tick(20); s.round()
check(s.o(A.P_LOCK_MGMT)["state"] == "done" and any(r["task"] == "run" for r in s.results("m2")),
      "산출물 없는 관리 일(청소)도 완료 보고로 끝남 (M10)")
s.tick(20); s.round()
check(not s.assigns("m2", "active") and len(s.assigns("m2")) == 1, "끝난 관리 일은 다시 배정하지 않음")

s = basic()
s.worker("C1", ["cpu"])
s.request("d1", "dataset", [], name="ds")
s.round()
mg = s.o(A.P_LOCK_MGMT)
runA = mg["run"]
s.put(f"datasets/ds/v/{runA}/_files.json", {"files": {"a": "h"}})
s.put(A.P_LOCK_MGMT, dict(mg, run="RUN_B", decision="dB", gen=mg["gen"] + 1))
s.run_report("C1", "mgmt", "done_run", type_="dataset", name="ds", run=runA, rid="d1", gen=mg["gen"], decision=mg["decision"])
s.tick(20); s.round()
check(s.o("datasets/ds/CURRENT.json") is None, "권한 잃은 실행의 늦은 완료 → 채택 안 됨 (J5)")
s.put("datasets/ds/v/RUN_B/_files.json", {"files": {"b": "h"}})
s.run_report("C1", "mgmt", "done_run", type_="dataset", name="ds", run="RUN_B", rid="d1", gen=mg["gen"] + 1, decision="dB")
s.tick(20); s.round()
check((s.o("datasets/ds/CURRENT.json") or {}).get("version") == "RUN_B", "지금 잠금과 맞는 실행 → 채택")

s = basic()
s.worker("C1", ["cpu"])
s.put("runs/m/CURRENT.json", {"version": "VA", "adopted_gen": 1, "by_session": "MS1", "by_epoch": 1})
s.request("fn", "force_new", [], name="m")
s.round()
mg = s.o(A.P_LOCK_MGMT)
s.run_report("C1", "mgmt", "done_job", run=mg["run"], rid="fn", gen=mg["gen"], decision=mg["decision"], result="done",
             current_change={"type": "model", "name": "m", "version": None})
s.tick(20); s.round()
check(s.o("runs/m/CURRENT.json")["version"] is None and s.o("runs/m/CURRENT.json")["adopted_gen"] == 2,
      "FORCE_NEW는 파일을 옮기지 않고 채택 표시만 바꿈")


def train_sim(dataset_keys=("t1", "t2")):
    s = basic()
    s.worker("G1", ["gpu"]); s.worker("C1", ["cpu"])
    st = {"by_session": "MS1", "by_epoch": 1}
    s.put("runs/m/CURRENT.json", dict(st, version="VA", adopted_gen=3))
    s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
    s.put("datasets/default/CURRENT.json", dict(st, version="D0", adopted_gen=1))
    s.put("datasets/default/v/D0/_files.json", {"files": {}, "task_keys": list(dataset_keys)})
    s.request("tr", "train", [], model="m")
    s.round()
    return s, s.o(A.P_LOCK_TRAIN + "m.json")


def train_done(s, tl, keys):
    s.put(f"runs/m/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": keys})
    s.run_report("G1", "train", "done_run", type_="model", name="m", run=tl["run"], rid="tr", gen=tl["gen"],
                 decision=tl["decision"], train_keys=keys)


s, tl = train_sim()
check(tl["start_adopted_gen"] == 3 and tl["start_test_version"] == "T0" and tl["compat"] == "ok", "학습 시작 버전·호환 고정")
s.request("cl", "cleanup34", []); s.tick(20); s.round()
check(s.assigns("cl", "active"), "학습 중에도 관리 일은 기다리지 않음")
s.put("runs/m/CURRENT.json", {"version": "VA", "adopted_gen": 5, "by_session": "MS1", "by_epoch": 1})
train_done(s, tl, ["t1"]); s.tick(20); s.round()
fl = s.o(A.P_FLAGS + f"model__m__{tl['run']}.json")
check(fl and fl["reason"] == "current_changed" and s.o("runs/m/CURRENT.json")["adopted_gen"] == 5, "A→B→A도 채택 gen으로 채택 대기")
s.signal("adopt_choice", type="model", name="m", run=tl["run"], choice="adopt"); s.tick(20); s.round()
check(s.o("runs/m/CURRENT.json")["version"] == tl["run"] and s.o(A.P_FLAGS + f"model__m__{tl['run']}.json")["state"] == "adopted",
      "관리자 채택 선택 → 채택 표시·플래그 모두 반영")

s, tl = train_sim()
s.put("sets/test_tasks/CURRENT.json", {"version": "T1", "keys": ["t9", "t1"], "adopted_gen": 2, "by_session": "MS1", "by_epoch": 1})
train_done(s, tl, ["t1", "t2"]); s.tick(20); s.round()
check((s.o(A.P_FLAGS + f"model__m__{tl['run']}.json") or {}).get("reason") == "contaminated", "학습 중 시험 설정과 겹침 → 오염·채택 대기")


def same_round(order):
    s = basic()
    s.worker("G1", ["gpu"]); s.worker("C1", ["cpu"])
    st = {"by_session": "MS1", "by_epoch": 1}
    s.put("runs/m/CURRENT.json", dict(st, version="VA", adopted_gen=1))
    s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
    s.put("datasets/default/CURRENT.json", dict(st, version="D0", adopted_gen=1))
    s.put("datasets/default/v/D0/_files.json", {"files": {}, "task_keys": ["t1"]})
    s.request("tr", "train", [], model="m"); s.request("tt", "test_tasks33", [])
    s.round()
    tl = s.o(A.P_LOCK_TRAIN + "m.json"); mg = s.o(A.P_LOCK_MGMT)
    s.put(f"runs/m/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
    s.put(f"sets/test_tasks/v/{mg['run']}/_files.json", {"files": {"x": "h"}, "keys": ["t1"]})
    for k in order:
        if k == "m":
            s.run_report("G1", "train", "done_run", type_="model", name="m", run=tl["run"], rid="tr", gen=tl["gen"],
                         decision=tl["decision"], train_keys=["t1"])
        else:
            s.run_report("C1", "mgmt", "done_run", type_="test_tasks", name="", run=mg["run"], rid="tt", gen=mg["gen"],
                         decision=mg["decision"])
    s.tick(20); s.round()
    fl = s.o(A.P_FLAGS + f"model__m__{tl['run']}.json") or {}
    return s.o("runs/m/CURRENT.json")["version"], fl.get("state"), fl.get("reason")
r1, r2 = same_round("mt"), same_round("tm")
check(r1 == r2 == ("VA", "adopt_wait", "contaminated"), f"같은 회차 도착 순서와 상관없이 같은 결과 {r1} {r2}")

s, tl = train_sim(dataset_keys=("t9",))
check(tl is None or tl.get("rid") != "tr", "옛 데이터셋이 지금 시험 TASK와 겹치면 학습을 시작하지 않음")

# 관리 일·학습 실종 → 사람 선택 (M10)
s, tl = train_sim()
s.kill("G1"); s.tick(200); s.round()
check(s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "needs_check", "학습 실행기 끊김 → 확인 필요")
sid = s.signal("run_choice", lane="train", model="m", run=tl["run"], choice="redo")
s.tick(20); s.round()
check("choice_not_open" in str(s.done(sid)), "끊긴 직후의 실행 선택 → 무효 (TASK와 같은 선택 조건)")
s.tick(1000)
sid = s.signal("run_choice", lane="train", model="m", run=tl["run"], choice="done")
s.tick(20); s.round()
check("version_files_not_verified" in str(s.done(sid)), "버전 목록 검증 없이 '끝난 것으로' → 무효")
sid = s.signal("run_choice", lane="train", model="m", run=tl["run"], choice="redo")
s.worker("G2", ["gpu"]); s.tick(20); s.round(); s.tick(20); s.round()
tl2 = s.o(A.P_LOCK_TRAIN + "m.json")
check(tl2["state"] == "running" and tl2["run"] != tl["run"] and tl2["session"] == "G2", "'다시 하기' → 새 실행 ID로 다시 배정")

# ======================================================== '모름' (M8)
s = basic()
s.worker("E1", ["gpu"])
s.request("u1", "track", [7])
s.round(unknown={"file:" + A.P_LOCK_TASK + "7.json"})
check(not s.assigns("u1"), "잠금 파일을 못 읽은 TASK는 배정하지 않음")
s = assigned_sim()
s.kill("E1"); s.tick(200); s.round(unknown={"requests"})
check(s.lock(7).get("state") == "held", "요청 목록을 못 읽으면 만료·회수 안 함")
s = assigned_sim()
s.grant(2, session="MS2"); s.tick(20)
s.round(unknown={"workers"})
check(s.lock(7).get("epoch") == 1 and s.o(A.P_HANDOVER + "2.json") is None, "새 epoch 첫 회에 '모름'이면 인계를 미룸 (인계 기록 없음)")
s.tick(20); s.round()
check(s.lock(7).get("epoch") == 2 and s.o(A.P_HANDOVER + "2.json"), "다음 정상 회차에서 인계를 마침 (M8)")
s = assigned_sim()
s.confirm("E1", 7, "j1"); s.tick(20); s.round()
s.end("E1", 7, "j1"); s.tick(20); s.round(unknown={"asks"})
check(s.lock(7).get("state") == "confirm_approved", "신청 목록을 모르면 보고를 반영하지 않음")
s.tick(20); s.round()
check(s.lock(7).get("state") == "free", "다음 회에 반영")

# ======================================================== 세션 지문 (M9)
s = basic()
s.worker("G1", ["gpu"])
s.put("runs/m/CURRENT.json", {"version": "UNSTAMPED", "adopted_gen": 9})
s.request("tr", "train", [], model="m")
s.round()
check((s.o(A.P_LOCK_TRAIN + "m.json") or {}).get("start_version") is None, "표시 없는 채택 표시는 믿지 않음 (M9)")
s = assigned_sim()
s.put(A.P_RESULTS + "r1__7__fake.json", {"rid": "r1", "task": "7", "result": "done"})
s.tick(20)
v = view(s)
check("7" not in v.done_tasks("r1"), "표시 없는 결과 기록은 진행으로 세지 않음")
s = basic()
s.worker("E1", ["gpu"], fp="aaaa"); s.worker("E1", ["gpu"], fp="bbbb")
s.request("dup", "track", [1])
r = s.round()
check(not s.assigns("dup") and any("duplicate_session" in str(w.obj) for w in r.writes), "같은 세션 두 지문 → 배정 안 함·알림")
s = assigned_sim()
check(all(r.obj.get("by_session") == "MS1" and r.obj.get("by_epoch") == 1 for p, r in s.f.items() if p.startswith("arb/")),
      "심판이 쓴 arb/ 파일에는 모두 세션 지문")

# ======================================================== 접수 뒤 권한·실행기 능력
s = basic()
s.request("pq", "track", [1], owner=M2A); s.round()
s.people = [PEOPLE[0], dict(PEOPLE[1], status="stopped")]
s.worker("E1", ["gpu"]); s.tick(20); s.round()
check(s.intake("pq").get("ok") and not s.assigns("pq"), "배정 때 지금 people에서 stopped면 배정 안 함")
s = basic()
s.worker("A0K", ["gpu", "cpu"]); s.request("rs", "restore23", []); s.round()
check(not s.assigns("rs"), "A0 Kaggle(gpu·cpu)은 23번(colab_oauth)을 받지 않음")

# ======================================================== 깨우기 정보 (K4)
s = basic(NIGHT)
s.round(waiting={"bk1": NIGHT + 600})
w = s.o(A.P_ARBITER)["wake"]
check(w["runnable"] == 0 and w["next_wake_at"] == NIGHT + 600 and w["observed_from"] == NIGHT - 3, "할 일 0이어도 다음 확인 시각을 남김")
s = basic()
s.request("w1", "restore23", [])
s.round()
check(s.o(A.P_ARBITER)["wake"]["runnable"] == 0, "맞는 실행기가 없는 일은 '실행 가능'으로 세지 않음")
s = basic(); s.round()
s.request("w2", "track", [1]); s.round()
check(s.o(A.P_ARBITER)["wake"]["runnable"] == 1, "GPU 일은 마스터가 GPU 작업자를 켤 수 있으므로 실행 가능")

# ======================================================== 새 TASK 후보 판정 (L3)
it = {"name": "v1_uld", "created_at": 100, "source_sha": "S", "frames": 300}
check(A.judge_create_candidates(it, [{"id": 9, "created": 120, "has_media": False}], None)[1] == "empty_candidate_without_evidence",
      "빈 후보는 증거 없으면 확인 필요 (L3)")
check(A.judge_create_candidates(dict(it, server_job="J1"), [{"id": 9, "created": 120, "server_job": "J1"}], None) == ("adopt", 9),
      "서버 작업 ID가 맞으면 이어받음")
check(A.judge_create_candidates(it, [{"id": 9, "created": 120, "has_media": True, "source_sha": "S", "frames": 300}], None) == ("adopt", 9),
      "미디어 후보 + 원본·프레임 수 일치 → 이어받음")
check(A.judge_create_candidates(it, [], True) == ("retry_ok", None), "후보 없음 + 서버 작업 끝남 → 다시 만들기 허용")


# 1b 통합 시험이 찾은 것: '확인 필요'로 격리된 TASK는 같은 요청에도 다시 배정하지 않음
s = approved_sim()
s.kill("E1"); s.worker("E2", ["gpu"]); s.tick(200); s.round(); s.tick(20); s.round()
check(s.lock(7).get("state") == "quarantine" and not s.assigns("r1", "active"),
      "격리된 TASK는 같은 요청의 새 묶음으로도 다시 배정하지 않음 (사람의 선택을 기다림)")

# ======================================================== b9 회귀 (N1~N4)
# N1: 학습 결과 기록 뒤 끊김 → 그사이 FORCE_NEW → 옛 학습 결과가 최신 채택을 덮지 않음
s, tl = train_sim()
s.put(f"runs/m/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
s.run_report("G1", "train", "done_run", type_="model", name="m", run=tl["run"], rid="tr", gen=tl["gen"],
             decision=tl["decision"], train_keys=["t1"])
ask_p = [p for p in s.f if p.startswith(A.P_ASK)][-1]
s.tick(20)
dry = A.decide_round(Cfg(s.me, ACC, s.people), Inputs(s.now, s.f, s.now - 3))
i_res = [w.why for w in dry.writes].index("result")
s.round(crash_after=i_res + 1)                       # 결과 기록까지만
check(any(r.get("job") == tl["run"] for r in s.results("tr")) and s.o("runs/m/CURRENT.json")["version"] == "VA",
      "학습 결과 기록만 쓰고 끊김 (채택 표시는 그대로)")
s.request("fn", "force_new", [], name="m")
hid = s.f.pop(ask_p)                                 # 옛 보고는 잠시 목록에 안 보임 (0o: '모름'이면 그 회차는 판정하지 않으므로 '안 보임'으로)
s.tick(20); s.round()
mg = s.o(A.P_LOCK_MGMT)
s.run_report("C1", "mgmt", "done_job", run=mg["run"], rid="fn", gen=mg["gen"], decision=mg["decision"], result="done",
             current_change={"type": "model", "name": "m", "version": None})
s.tick(20); s.round()
check(s.o("runs/m/CURRENT.json")["version"] is None, "그사이 FORCE_NEW가 채택 표시를 바꿈")
s.f[ask_p] = hid
s.tick(20); s.round()                                # 옛 보고가 다시 보임 → 이어 하기
fl = s.o(A.P_FLAGS + f"model__m__{tl['run']}.json") or {}
check(s.o("runs/m/CURRENT.json")["version"] is None and fl.get("reason") == "superseded"
      and s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "done",
      "이어 할 때 전제가 바뀌었으면 덮지 않고 채택 대기(superseded) (N1)")

# N2: 사람의 '끝난 것으로'도 정상 완료와 같은 채택 판정 / 만들기는 확인한 TASK 번호로 닫음
s, tl = train_sim()
s.put(f"runs/m/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"], "verified": True})
s.kill("G1"); s.tick(1200); s.round()
sid = s.signal("run_choice", lane="train", model="m", run=tl["run"], choice="done")
s.tick(20); s.round()
check(s.o("runs/m/CURRENT.json")["version"] == tl["run"] and s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "done",
      "학습 '끝난 것으로'(검증된 버전 목록) → 채택까지 (N2)")
s = basic()
s.worker("C1", ["cpu"])
s.request("c1", "create17", [], name="v9", server="cvat1")
s.round()
key = A.create_key("cvat1", "v9")
cl = s.o(A.P_LOCK_CREATE + key + ".json")
s.kill("C1"); s.worker("C2", ["cpu"]); s.tick(1200); s.round()
check(s.o(A.P_LOCK_CREATE + key + ".json")["state"] == "needs_check", "만들기 실행기 끊김 → 확인 필요")
sid = s.signal("run_choice", lane="create", key=key, run=cl["run"], choice="done")
s.tick(20); s.round()
check("create_needs_task_id" in str(s.done(sid)), "만들기 '끝난 것으로'는 확인한 TASK 번호가 있어야 함")
sid = s.signal("run_choice", lane="create", key=key, run=cl["run"], choice="done", task_id=777)
s.tick(20); s.round(); s.tick(20); s.round()
check(any(r["task"] == "create" and r.get("task_id") == 777 for r in s.results("c1")) and len(s.assigns("c1")) == 1,
      "만들기 '끝난 것으로' → 만들기 결과(TASK 번호)로 닫고 다시 배정하지 않음 (N2)")

# N3: 개별 파일 모름 → 인계를 미뤄 두었다가 읽히면 마저 함 / 보고는 처리됨으로 두지 않음
s = assigned_sim()
s.grant(2, session="MS2"); s.tick(20)
r = s.round(unknown={"file:" + A.P_LOCK_TASK + "7.json"})
check(s.o(A.P_HANDOVER + "2.json") is None and s.lock(7)["epoch"] == 1 and "hold_on_unknown" in r.notes,
      "첫 회에 잠금 하나를 못 읽음 → 인계를 하지 않고 판정 보류 (0o)")
s.tick(20); s.round()
check(s.lock(7)["epoch"] == 2 and s.o(A.P_HANDOVER + "2.json")["pending"] == [], "읽히는 회차에 인계를 마침 (N3 → 0o)")
s, tl = train_sim()
s.put(f"runs/m/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
s.run_report("G1", "train", "done_run", type_="model", name="m", run=tl["run"], rid="tr", gen=tl["gen"],
             decision=tl["decision"], train_keys=["t1"])
s.tick(20); s.round(unknown={"file:" + A.P_LOCK_TRAIN + "m.json"})
check(s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "running" and s.o(A.P_LOCK_TRAIN + "m.json")["run"] == tl["run"]
      and len(s.assigns("tr")) == 1, "학습 잠금을 못 읽은 회차: 보고를 미루고, 배정을 거두거나 새 학습을 잡지 않음")
s.tick(20); s.round()
check(s.o("runs/m/CURRENT.json")["version"] == tl["run"], "다음 회차에 그 보고를 처리 (처리됨으로 굳히지 않음) (N3)")

# N4: 게시 잠금은 받는 중 배정의 TASK에만
s = basic()
s.worker("C1", ["cpu"]); s.worker("E1", ["gpu"])
s.request("bk", "backup", [7]); s.request("tk", "track", [8], owner=M2A)
s.round()
asg = s.assigns("bk", "active")[0]
s.ask("C1", "publish_lock", rid="bk", chunk=asg["chunk"], epoch=1, decision=asg["decision"], task="999")
s.tick(20); s.round()
check(not s.lock(999), "배정 밖 TASK의 게시 잠금 → 거절 (N4)")
ta = s.assigns("tk", "active")[0]
s.ask("E1", "publish_lock", rid="tk", chunk=ta["chunk"], epoch=1, decision=ta["decision"], task="8")
s.tick(20); s.round()
check(not s.lock(8).get("publish"), "받는 중이 아닌 배정(GPU)의 게시 잠금 → 거절")
s.ask("C1", "publish_lock", rid="bk", chunk=asg["chunk"], epoch=1, decision=asg["decision"], task="7")
s.tick(20); s.round()
check(s.lock(7).get("publish") and s.lock(7).get("session") == "C1", "배정된 TASK의 게시 잠금 → 발급")


# ======================================================== b10 회귀 (P1~P3)
# P1: 사람이 시험 설정을 채택해도 시험 키·오염 대조까지
s = basic()
st = {"by_session": "MS1", "by_epoch": 1}
s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
s.put("runs/m/CURRENT.json", dict(st, version="VA", adopted_gen=1))
s.put("runs/m/v/VA/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
s.put("sets/test_tasks/v/WAIT/_files.json", {"files": {"x": "h"}, "keys": ["t1"]})
s.put(A.P_FLAGS + "test_tasks____WAIT.json", dict(st, type="test_tasks", name="", run="WAIT", state="adopt_wait"))
sid = s.signal("adopt_choice", type="test_tasks", name="", run="WAIT", choice="adopt")
s.tick(20)
dry = A.decide_round(Cfg(s.me, ACC, s.people), Inputs(s.now, s.f, s.now - 3))
i_cur = [w.why for w in dry.writes].index("adopt_choice")
s.round(crash_after=i_cur + 1)                       # 채택 표시까지만 쓰고 끊김
s.tick(20); s.round()
tc = s.o("sets/test_tasks/CURRENT.json")
fl = s.o(A.P_FLAGS + "model__m__VA.json") or {}
check(tc["version"] == "WAIT" and tc["keys"] == ["t1"], "사람의 시험 설정 채택 → 채택 표시에 시험 키 (P1)")
check(fl.get("contaminated_for") == "WAIT" and s.done(sid)["result"] == "done",
      "채택 표시만 쓰고 끊겨도 다음 회차에 오염 표시를 마저 만듦 (P1)")

# P2: 완료가 읽는 파일을 모르면 미룸 — 정상 보고와 사람의 선택 모두
s, tl = train_sim()
s.put("sets/test_tasks/CURRENT.json", {"version": "T1", "keys": ["t9", "t1"], "adopted_gen": 2, "by_session": "MS1", "by_epoch": 1})
train_done(s, tl, ["t1"])
s.tick(20); s.round(unknown={"file:sets/test_tasks/CURRENT.json"})
check(s.o("runs/m/CURRENT.json")["version"] == "VA" and s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "running",
      "시험 설정 채택 표시를 못 읽은 회차에는 학습 완료를 미룸 (오염 검사 없이 채택하지 않음) (P2)")
s.tick(20); s.round()
check((s.o(A.P_FLAGS + f"model__m__{tl['run']}.json") or {}).get("reason") == "contaminated"
      and s.o("runs/m/CURRENT.json")["version"] == "VA", "읽히는 회차에 오염으로 판정 → 채택 대기")
s = basic()
s.worker("C1", ["cpu"])
s.put("datasets/ds/CURRENT.json", {"version": "OLD", "adopted_gen": 9, "by_session": "MS1", "by_epoch": 1})
s.request("d1", "dataset", [], name="ds"); s.round()
mg = s.o(A.P_LOCK_MGMT)
s.put(f"datasets/ds/v/{mg['run']}/_files.json", {"files": {"a": "h"}, "verified": True})
s.kill("C1"); s.tick(1200); s.round()
sid = s.signal("run_choice", lane="mgmt", run=mg["run"], choice="done")
s.tick(20); s.round(unknown={"file:datasets/ds/CURRENT.json"})
check(s.done(sid) is None and s.o("datasets/ds/CURRENT.json")["version"] == "OLD",
      "사람의 '끝난 것으로'도 채택 표시를 못 읽은 회차에는 미룸 (모르는 표시를 덮지 않음) (P2)")
s.tick(20); s.round()
cur = s.o("datasets/ds/CURRENT.json")
check(cur["version"] == mg["run"] and cur["adopted_gen"] == 10, "읽히는 회차에 채택 (gen은 이어서)")

# P3: 채택 대기 → 사람이 채택 → 옛 완료를 이어 처리해도 되돌리지 않음
for choice, want_state in (("adopt", "adopted"), ("discard", "discarded")):
    s, tl = train_sim()
    s.put("runs/m/CURRENT.json", {"version": "VB", "adopted_gen": 5, "by_session": "MS1", "by_epoch": 1})
    train_done(s, tl, ["t1"])
    ask_p = [p for p in s.f if p.startswith(A.P_ASK)][-1]
    s.tick(20)
    dry = A.decide_round(Cfg(s.me, ACC, s.people), Inputs(s.now, s.f, s.now - 3))
    i_fl = [w.why for w in dry.writes].index("adopt_wait")
    s.round(crash_after=i_fl + 1)                    # 결과·채택 대기 표시까지만
    sid = s.signal("adopt_choice", type="model", name="m", run=tl["run"], choice=choice)
    hid = s.f.pop(ask_p)                             # 옛 완료 보고는 잠시 안 보임
    s.tick(20); s.round()
    s.f[ask_p] = hid
    s.tick(20); s.round()                            # 옛 완료 보고를 이어 처리
    fl = s.o(A.P_FLAGS + f"model__m__{tl['run']}.json")
    want_ver = tl["run"] if choice == "adopt" else "VB"
    check(fl["state"] == want_state and fl.get("by_signal") == sid and s.o("runs/m/CURRENT.json")["version"] == want_ver
          and s.o(A.P_LOCK_TRAIN + "m.json")["state"] == "done",
          f"사람이 '{choice}'로 해소한 뒤 옛 완료를 이어 처리해도 표시를 되살리지 않고 잠금만 닫음 (P3)")

# 반대 방향: 정상 채택이 잘못 막히지 않음 / 같은 회차 서로 다른 모델은 각각 채택
s = basic()
s.worker("G1", ["gpu"]); s.worker("G2", ["gpu"])
st = {"by_session": "MS1", "by_epoch": 1}
s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
s.put("datasets/default/CURRENT.json", dict(st, version="D0", adopted_gen=1))
s.put("datasets/default/v/D0/_files.json", {"files": {}, "task_keys": ["t1"]})
s.request("ta", "train", [], model="ma"); s.request("tb", "train", [], model="mb", owner=M2A)
s.round()
for m, rid in (("ma", "ta"), ("mb", "tb")):
    tl = s.o(A.P_LOCK_TRAIN + f"{m}.json")
    s.put(f"runs/{m}/v/{tl['run']}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
    s.run_report(tl["session"], "train", "done_run", type_="model", name=m, run=tl["run"], rid=rid, gen=tl["gen"],
                 decision=tl["decision"], train_keys=["t1"])
s.tick(20); s.round()
check(all(s.o(f"runs/{m}/CURRENT.json")["version"] == s.o(A.P_LOCK_TRAIN + f"{m}.json")["run"] for m in ("ma", "mb"))
      and not [p for p in s.f if p.startswith(A.P_FLAGS)],
      "같은 회차에 끝난 서로 다른 모델은 각각 채택되고, 전제가 그대로면 superseded로 막히지 않음")


# ======================================================== 쓰기 경계마다 끊어 보기
class FakeExec:
    """실제 실행기처럼 매 회차 파일을 보고 다음 보고를 냄 (같은 보고를 두 번 내지 않음)."""
    def __init__(self, s, name):
        self.s, self.n, self.sent = s, name, set()

    def _send(self, key, fn):
        if key not in self.sent:
            fn(); self.sent.add(key)

    def step(self):
        s = self.s
        for p, r in sorted(s.f.items()):
            a = r.obj
            if not p.startswith(A.P_ASSIGN) or a.get("session") != self.n or a.get("state") != "active":
                continue
            lane = a.get("lane")
            if lane in ("mgmt", "train"):
                lp = A.P_LOCK_MGMT if lane == "mgmt" else next(
                    (q for q, rr in s.f.items() if q.startswith(A.P_LOCK_TRAIN) and rr.obj.get("run") == a.get("run")), "")
                lk = s.o(lp) or {}
                if lk.get("state") != "running" or lk.get("session") != self.n or lk.get("epoch") != s.epoch():
                    continue
                art = lk.get("artifact")
                key = ("run", lk["run"], lk["gen"], s.epoch())
                if art:
                    vf = A.VERSION_FILES_OF[art["type"]].format(n=art["name"], run=lk["run"])
                    def go(lk=lk, art=art, vf=vf):
                        s.put(vf, {"files": {"w": "h"}, "train_keys": ["t1"], "keys": ["t1"], "verified": True})
                        s.run_report(self.n, lane, "done_run", type_=art["type"], name=art["name"], run=lk["run"],
                                     rid=lk["rid"], gen=lk["gen"], decision=lk["decision"], train_keys=["t1"])
                    self._send(key, go)
                else:
                    self._send(key, lambda lk=lk: s.run_report(self.n, lane, "done_job", run=lk["run"], rid=lk["rid"],
                                                               gen=lk["gen"], decision=lk["decision"], result="done"))
                continue
            all_done = True
            for t in a.get("tasks", []):
                lk = s.lock(t)
                if any(x["task"] == str(t) for x in s.results(a["rid"])):
                    continue
                all_done = False
                if lane == "read":                      # 받는 중 일: 게시 잠금 → 결과
                    if lk.get("session") == self.n and lk.get("decision") == a["decision"] and lk.get("publish") \
                            and lk.get("state") == "held" and lk.get("epoch") == s.epoch():
                        self._send(("res", t, lk["gen"]), lambda t=t, lk=lk: s.ask(
                            self.n, "result", rid=a["rid"], chunk=a["chunk"], epoch=s.epoch(), gen=lk["gen"],
                            decision=a["decision"], task=str(t), result="done"))
                    elif lk.get("state") in (None, "free"):
                        self._send(("pub", t, s.epoch(), a["decision"]), lambda t=t: s.ask(
                            self.n, "publish_lock", rid=a["rid"], chunk=a["chunk"], epoch=s.epoch(),
                            decision=a["decision"], task=str(t)))
                    continue
                job = f"j{t}c{a['chunk']}"
                if lk.get("session") != self.n or lk.get("decision") != a["decision"] or lk.get("epoch") != s.epoch():
                    continue
                if (s.intake(a["rid"]) or {}).get("cancel_signal") and lk.get("state") == "held":
                    self._send(("result", t, lk["gen"]), lambda t=t, lk=lk: s.ask(
                        self.n, "result", rid=a["rid"], chunk=a["chunk"], epoch=s.epoch(), gen=lk["gen"],
                        decision=a["decision"], task=str(t), result="canceled"))
                    continue
                if lk.get("state") == "held":
                    self._send(("confirm", t, lk["gen"]), lambda t=t: s.confirm(self.n, t, job))
                elif lk.get("state") == "confirm_approved" and lk.get("job") == job:
                    self._send(("end", t, lk["gen"]), lambda t=t: s.end(self.n, t, job))
            if all_done:
                self._send(("release", a["rid"], a["chunk"], s.epoch()), lambda: s.release(self.n, a["rid"]))


def logical(s, version):
    """실행 ID(매번 다름)를 그 실행의 요청 ID로 바꿔 비교."""
    if version is None:
        return None
    for r in s.results():
        if r.get("job") == version:
            return "run_of:" + r["rid"]
    return version


def signature(s):
    locks = {A._name(p): (r.obj.get("state"), r.obj.get("rid")) for p, r in s.f.items() if p.startswith(A.P_LOCK_TASK)}
    runlocks = {p: (r.obj.get("state"), r.obj.get("rid")) for p, r in s.f.items()
                if p in (A.P_LOCK_MGMT, A.P_LOCK_AGG) or p.startswith(A.P_LOCK_TRAIN) or p.startswith(A.P_LOCK_CREATE)}
    res = sorted((r["rid"], r["task"], r["result"], str(r.get("reason")), str(r.get("task_id"))) for r in s.results())
    cancel = sorted(rid for rid in [A._name(p) for p in s.f if p.startswith(A.P_INTAKE)] if s.intake(rid).get("cancel_signal"))
    cur = {p: (logical(s, (r.obj or {}).get("version")), tuple((r.obj or {}).get("keys") or []))
           for p, r in s.f.items() if p.endswith("CURRENT.json")}
    flags = sorted((str(o.get("type")), str(o.get("name")), str(logical(s, o.get("run"))), str(o.get("state")),
                    str(o.get("reason")), str(logical(s, o.get("contaminated_for"))))
                   for p, r in s.f.items() if p.startswith(A.P_FLAGS) for o in [r.obj])
    holds = {A._name(p): r.obj.get("active") for p, r in s.f.items() if p.startswith(A.P_HOLD)}
    active = len(s.assigns(state="active"))
    rcv = sorted((r.obj.get("origin_rid"), tuple(r.obj.get("tasks") or []), r.obj.get("mode"))
                 for p, r in s.f.items() if p.startswith("requests/REQ_rcv"))
    return {"locks": locks, "runlocks": runlocks, "results": res, "cancel": cancel, "current": cur,
            "flags": flags, "holds": holds, "active": active, "rcv": rcv}


def run_scene(scene, crash=None, new_master=True):
    """scene(s, execs, i): i번째 회차 전에 하는 일. crash=(회차, 몇 번째 쓰기에서) → 그 회차에서 끊기고 새 마스터(새 epoch)."""
    s, execs = scene_setup[scene]()
    n_rounds = scene_rounds[scene]
    epoch = 1
    for i in range(n_rounds + 6):
        if i < n_rounds:
            scene_steps[scene](s, i)
        for e in execs:
            e.step()
        s.tick(20)
        if crash and crash[0] == i:
            s.round(crash_after=crash[1], **scene_inp.get(scene, {}))
            if new_master:                       # 마스터가 죽고 새 마스터(새 epoch)가 이어 감
                epoch += 1
                s.grant(epoch, session=f"MS{epoch}")
                s.worker(f"MS{epoch}", ["cpu"])
                                                 # 아니면 같은 마스터가 다음 회차에 이어 감 (쓰기 일부 실패)
        else:
            s.round(**scene_inp.get(scene, {}))
    return s


def setup_track():
    s = basic(); s.worker("E1", ["gpu"])
    return s, [FakeExec(s, "E1")]


def steps_track(s, i):
    if i == 0:
        s.request("r1", "track", [1, 2])


def setup_cancel():
    s = basic(); s.worker("E1", ["gpu"])
    return s, [FakeExec(s, "E1")]


def steps_cancel(s, i):
    if i == 0:
        s.request("r1", "track", [1, 2, 3])     # 접수와 같은 회차에 취소 → 일하지 않음
        s.signal("cancel", rid="r1")
        s.request("r2", "track", [4, 5], owner=M2A)


def setup_choice():
    s = approved_sim()
    s.kill("E1"); s.tick(200); s.round(); s.tick(1000); s.round()
    s.worker("E9", ["gpu"])
    return s, [FakeExec(s, "E9")]


def steps_choice(s, i):
    if i == 0:
        s.signal("confirm_choice", task="7", decision=s.lock(7)["decision"], choice="redo")


def setup_mgmt():
    s = basic(); s.worker("C1", ["cpu"])
    return s, [FakeExec(s, "C1")]


def steps_mgmt(s, i):
    if i == 0:
        s.request("d1", "dataset", [], name="ds")


def setup_train():
    s = basic(); s.worker("G1", ["gpu"])
    st = {"by_session": "MS1", "by_epoch": 1}
    s.put("runs/m/CURRENT.json", dict(st, version="VA", adopted_gen=3))
    s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
    s.put("datasets/default/CURRENT.json", dict(st, version="D0", adopted_gen=1))
    s.put("datasets/default/v/D0/_files.json", {"files": {}, "task_keys": ["t1"]})
    return s, [FakeExec(s, "G1")]


def steps_train(s, i):
    if i == 0:
        s.request("tr", "train", [], model="m")


def setup_testset():
    s = basic(); s.worker("C1", ["cpu"])
    st = {"by_session": "MS1", "by_epoch": 1}
    s.put("sets/test_tasks/CURRENT.json", dict(st, version="T0", keys=["t9"], adopted_gen=1))
    for m, ver in (("m", "VA"), ("m2", "VB")):                 # 새 시험 설정(t1)과 겹치는 모델 둘
        s.put(f"runs/{m}/CURRENT.json", dict(st, version=ver, adopted_gen=1))
        s.put(f"runs/{m}/v/{ver}/_files.json", {"files": {"w": "h"}, "train_keys": ["t1"]})
    return s, [FakeExec(s, "C1")]


def steps_testset(s, i):
    if i == 0:
        s.request("tt", "test_tasks33", [])


def setup_publish():
    s = basic(); s.worker("C1", ["cpu"])
    return s, [FakeExec(s, "C1")]


def steps_publish(s, i):
    if i == 0:
        s.request("bk", "backup", [3, 4])


def setup_stop():
    s = basic(); s.worker("E1", ["gpu"])
    return s, [FakeExec(s, "E1")]


def steps_stop(s, i):
    if i == 0:
        s.request("r1", "track", [1, 2])
        s.request("r2", "track", [5], owner=M2A)
    if i == 1:
        s.signal("stop")
    if i == 4:
        st = sorted(A._name(p) for p in s.f if p.startswith(A.P_SIGNALS + "stop__"))[0]
        s.signal("release", stop_id=st)


scene_setup = {"track": setup_track, "cancel": setup_cancel, "choice": setup_choice, "mgmt": setup_mgmt,
               "train": setup_train, "publish": setup_publish, "stop": setup_stop, "testset": setup_testset}
scene_steps = {"track": steps_track, "cancel": steps_cancel, "choice": steps_choice, "mgmt": steps_mgmt,
               "train": steps_train, "publish": steps_publish, "stop": steps_stop, "testset": steps_testset}
scene_rounds = {"track": 8, "cancel": 8, "choice": 8, "mgmt": 5, "train": 5, "publish": 8, "stop": 10, "testset": 5}
scene_inp = {"choice": {"import_pending": {"7": False}}}

for scene in ("track", "cancel", "choice", "mgmt", "train", "publish", "stop", "testset"):
    base = run_scene(scene)
    sig0 = signature(base)
    # 회차마다 쓰기 수를 재어 모든 경계에서 끊어 봄
    counts = []
    s, execs = scene_setup[scene]()
    for i in range(scene_rounds[scene]):
        scene_steps[scene](s, i)
        for e in execs:
            e.step()
        s.tick(20)
        counts.append(len(s.round(**scene_inp.get(scene, {})).writes))
    for nm, label in ((True, "새 마스터(새 epoch)"), (False, "같은 마스터")):
        bad, total = [], 0
        for i, n in enumerate(counts):
            for k in range(n):
                total += 1
                sg = signature(run_scene(scene, crash=(i, k), new_master=nm))
                if sg != sig0:
                    bad.append((i, k, {kk: (sg[kk], sig0[kk]) for kk in sg if sg[kk] != sig0[kk]}))
        check(not bad, f"[{scene}] 모든 쓰기 경계 {total}곳에서 끊고 {label}로 이어 가도 정상 실행과 같은 최종 상태"
              + ("" if not bad else f" — 다름 {len(bad)}곳, 첫 예: {bad[0]}"))
check([x[:3] for x in signature(run_scene("track"))["results"]] == [("r1", "1", "done"), ("r1", "2", "done")], "[track] 정상 실행: 두 TASK 완료")
sc = signature(run_scene("cancel"))
check(sc["cancel"] == ["r1"] and [x[:3] for x in sc["results"]] == [("r2", "4", "done"), ("r2", "5", "done")], "[cancel] 정상 실행: r1 취소, r2 완료")
check(signature(run_scene("choice"))["rcv"] == [("r1", ("7",), "redo")], "[choice] 정상 실행: 원요청·TASK가 맞는 복구 요청 하나")
check([x[0] for x in signature(run_scene("mgmt"))["current"].values()] == ["run_of:d1"], "[mgmt] 정상 실행: 그 관리 일의 버전 채택")
st_ = signature(run_scene("train"))
check(st_["current"]["runs/m/CURRENT.json"][0] == "run_of:tr" and st_["runlocks"]["arb/locks/train/m.json"][0] == "done",
      "[train] 정상 실행: 학습 버전 채택, 학습 잠금 끝")
sp_ = signature(run_scene("publish"))
check(sorted((x[0], x[1]) for x in sp_["results"]) == [("bk", "3"), ("bk", "4")] and sp_["locks"]["3"][0] == "free",
      "[publish] 정상 실행: 게시 잠금 → 결과 → 잠금 풀림")
ss_ = signature(run_scene("stop"))
check(list(ss_["holds"].values()) == [False] and len(ss_["results"]) == 3, "[stop] 정상 실행: 보류 뒤 해제, 일은 모두 끝남")
sx_ = signature(run_scene("testset"))
check(sx_["current"]["sets/test_tasks/CURRENT.json"] == ("run_of:tt", ("t1",))
      and sorted(f[1] for f in sx_["flags"] if f[5] == "run_of:tt") == ["m", "m2"],
      "[testset] 정상 실행: 시험 설정 채택(시험 키 포함) + 겹치는 모델 둘에 오염 표시")
# 음성 시험: 비교가 틀린 상태를 반드시 잡는가 (N5)
b_ = run_scene("train"); g0 = signature(b_)
b2 = copy.deepcopy(b_); b2.f["runs/m/CURRENT.json"].obj["version"] = "WRONG"
b3 = copy.deepcopy(b_); b3.put(A.P_FLAGS + "model__m__x.json", {"type": "model", "name": "m", "run": "x", "state": "adopt_wait"})
b4 = copy.deepcopy(b_); b4.f["arb/locks/train/m.json"].obj["state"] = "running"
check(signature(b2) != g0 and signature(b3) != g0 and signature(b4) != g0,
      "비교 함수는 틀린 채택 버전·남은 채택 대기·남은 실행 잠금을 모두 잡음 (N5)")


# ---------------------------------------------------------------- b11 회귀 (0e)
check(A.to_ts("2026-11-14T01:00:00.000Z") == 1794618000.0 and A.to_ts(5) == 5.0 and A.to_ts("x", 7) == 7.0 and A.to_ts(None, 3) == 3.0,
      "시각: 숫자·ISO 문자열 모두 초로, 해석 못 하면 기본값")
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"])
s.round(); s.round()
s.request("r1", "track", [1]); s.request("r2", "track", [2], created="2026-11-14T01:00:00Z")
s.put(A.P_WORKERS + "bad__x.json", {"session": "B", "caps": "gpu", "hb": "zz"})
s.round(unknown={"config"})
check(A.P_INTAKE + "r1.json" not in s.f, "사람 목록이 오래됨('config' 모름) → 새 요청을 접수하지 않음 (Q3)")
s.round(); s.round()
check(A.P_INTAKE + "r1.json" in s.f and A.P_INTAKE + "r2.json" in s.f, "다시 읽히면 접수 — 만든 시각이 숫자·문자열로 섞여 있어도 정렬에서 죽지 않음 (Q7)")
wk = s.f[A.P_ARBITER].obj["wake"]
check("G1" in wk["workers"] and "B" not in wk["workers"] and "executor_wait" in wk,
      "회차 기록의 깨우기 요약에 살아 있는 실행기 목록·실행기 대기 수 (Q9), 형태가 틀린 실행기 파일은 버림")

# ---------------------------------------------------------------- b12 회귀 (0f)
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"])
s.round(); s.round()
s.put(A.P_WORKERS + "bad__x.json", {"session": "bad", "fp": [], "caps": ["cpu"], "hb": s.now})
s.put(A.P_WORKERS + "bad2__x.json", {"session": "bad2", "fp": "f", "caps": [1], "hb": s.now})
s.put("requests/REQ_badt__track__pending.json", {"tasks": [[1]], "created": s.now})
s.put(A.P_SIGNALS + "cancel__p__900.json", {"rid": {"x": 1}})
s.put(A.P_ASK + "G1__x__900.json", {"type": "end", "epoch": "abc", "rid": "r", "task": "1"})
s.request("r1", "track", [1])
r = s.round(); s.round()
bad = sorted(a["path"] for a in r.alerts if a.get("kind") == "bad_input") if hasattr(r, "alerts") else None
check(A.P_INTAKE + "r1.json" in s.f, "내부 필드 형태가 틀린 실행기·요청·신호·보고가 있어도 정상 요청은 접수됨 (R1)")
alerts = [p for p in s.f if p.startswith(A.P_ALERT)]
check((s.f.get(A.P_INTAKE + "badt.json") or FileRec({})).obj.get("ok") is False
      and s.f[A.P_INTAKE + "badt.json"].obj["reason"] == "bad_input:tasks",
      "형태가 틀린 요청은 '거절' 접수 기록(이유: bad_input)을 남기고 처리하지 않음 (앱에 이유가 보임)")
for kind, o, want in [("worker", {"fp": []}, "fp"), ("worker", {"caps": [1]}, "caps"), ("worker", {"stopping": "yes"}, "stopping"),
                      ("request", {"tasks": [None]}, "tasks"), ("request", {"name": ["a"]}, "name"),
                      ("signal", {"until": "soon"}, "until"), ("signal", {"stop_id": []}, "stop_id"),
                      ("ask", {"type": "end", "gen": "x"}, "gen"), ("ask", {"type": 3}, "type"),
                      ("worker", {"fp": "a", "caps": ["cpu"], "hb": 1}, ""), ("request", {"tasks": ["1", 2]}, "")]:
    check(A.input_problem(kind, o) == want, f"형태 확인 {kind} {o} → {want or '정상'}")
# R6: 낮에 야간 승인된 일이 실행기를 기다리면 '밤에도 할 수 있는 대기'로 적음
s = Sim(now=DAY0 + 18 * 3600 + 59 * 60); s.grant(1); s.worker("MS1", ["master"])
s.round(); s.round()
s.request("d1", "dataset", [], name="ds"); s.request("d2", "dataset", [], name="ds2")
s.round()
s.signal("approve_night", rid="d1"); s.round(); s.round()
wk = s.f[A.P_ARBITER].obj["wake"]
check(wk["executor_wait"] == 2 and wk["executor_wait_night"] == 1, "실행기 대기 2건 중 야간 승인된 1건만 '밤에도 할 수 있는 대기' (R6)")

# R4: 옛 방식에서 남은 요청은 새 심판이 접수하지 않음
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"])
s.round(); s.round()
s.request("o1", "track", [1], status="taken"); s.request("o2", "track", [2], status="transition"); s.request("n1", "track", [3])
s.round(); s.round()
check(A.P_INTAKE + "n1.json" in s.f and A.P_INTAKE + "o1.json" not in s.f and A.P_INTAKE + "o2.json" not in s.f,
      "옛 '받음'·'전환 확인 필요' 요청은 접수하지 않고 새 '대기' 요청만 접수 (R4)")
check(sorted(s.f[A.P_ARBITER].obj["check"]["orphans"]) == ["o1", "o2"], "남은 옛 요청은 회차 기록의 점검 목록(orphans)에 보임 → CTRL앱")

# ---------------------------------------------------------------- b13 회귀 (0g)
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("C1", ["cpu"]); s.worker("G1", ["gpu"])
s.round(); s.round()
s.request("bn", "create16", [], name=123, server="cvat")
s.request("ok1", "track", [1])
s.round(); s.round()
check(A.P_INTAKE + "ok1.json" in s.f and s.f[A.P_INTAKE + "bn.json"].obj["ok"] is False and s.assigns("ok1", "active"),
      "이름이 숫자인 만들기 요청은 '거절'로 접수하고 옆의 정상 요청은 접수·배정 (S1)")
for kind, o, want in [("request", {"name": 123}, "name"), ("request", {"server": True}, "server"),
                      ("signal", {"stop_id": 5}, "stop_id"), ("signal", {"origin_signal": 1}, "origin_signal"),
                      ("signal", {"force": "yes"}, "force"), ("signal", {"until": "2026-11-14T01:00:00Z"}, ""),
                      ("ask", {"type": "end", "decision": 7}, "decision"), ("ask", {"type": "release", "assign": 3}, "assign"),
                      ("ask", {"type": "end", "task": 12, "epoch": "3"}, ""), ("ask", {"rid": "r"}, "type"),
                      ("request", {"tasks": [1, "2"], "name": "a"}, "")]:
    check(A.input_problem(kind, o) == want, f"형태 표 {kind} {o} → {want or '정상'}")

# ---------------------------------------------------------------- b14 회귀 (0h)
for kind, o, want in [("ask", {"type": "done_job", "current_change": 1}, "current_change"),
                      ("ask", {"type": "done_job", "current_change": {"type": "model", "name": 3}}, "current_change"),
                      ("ask", {"type": "done_job", "current_change": {"type": "nope", "name": "m"}}, "current_change"),
                      ("ask", {"type": "done_job", "current_change": {"type": "model", "name": "m", "version": "v1"}}, ""),
                      ("ask", {"type": "done_run", "train_keys": [["a"]]}, "train_keys"),
                      ("vfiles", {"files": [], "verified": True}, "files"), ("vfiles", {"files": {}, "keys": "a"}, "keys"),
                      ("grant", {"epoch": "x", "session": "s"}, "epoch"), ("person", {"id": "M1", "account": "a", "perms": "wake"}, "perms")]:
    check(A.input_problem(kind, o) == want, f"형태 표 {kind} {o} → {want or '정상'}")
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"])
s.f[A.P_GRANT] = FileRec({"epoch": "x", "session": "MS1"}, G, s.now, s.now)
r = s.round()
check("not_arbiter" in r.notes, "자격 파일의 epoch가 숫자가 아니면 자격 없음으로 보고 판정하지 않음 (예외 없이)")
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.round(); s.round()
s.signal("stop", until="2026-11-14T15:00:00Z"); s.round(); s.round()
h = [x.obj for p, x in s.f.items() if p.startswith(A.P_HOLD)]
check(h and isinstance(h[0]["until"], float), "정지 기한이 ISO 문자열이어도 초로 바꿔 둠 (만료 계산에서 죽지 않음)")

# ---------------------------------------------------------------- b15 회귀 (0i)
for kind, o, want in [("ask", {"type": "done_job", "current_change": {"type": []}}, "current_change"),
                      ("ask", {"type": "done_job", "current_change": {"type": {"a": 1}}}, "current_change"),
                      ("person", {"account": "a0@x", "perms": ["request"], "status": "active"}, "id"),
                      ("person", {"id": "M1", "perms": []}, "account"), ("person", {"id": "M1", "account": "a"}, "perms"),
                      ("vfiles", {"files": {}, "task_keys": 1}, "task_keys"), ("vfiles", {"files": {}, "task_keys": ["a"]}, "")]:
    check(A.input_problem(kind, o) == want, f"형태 표 {kind} {o} → {want or '정상'} (V1·V2)")
class Weird(dict):
    def get(self, *a):
        raise RuntimeError("boom")
check(A.input_problem("ask", Weird(type="x")) == "unreadable", "형태 확인은 어떤 입력에도 예외를 내지 않음 (V1)")
s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"])
s.round(); s.round()
s.put("datasets/ds/CURRENT.json", {"type": "dataset", "name": "ds", "version": "v1", "adopted_gen": 1, "by_session": "MS1", "by_epoch": 1})
s.put("datasets/ds/v/v1/_files.json", {"files": {}, "task_keys": 1})
s.request("t1", "train", [], model="m", dataset="ds")
s.request("ok1", "track", [1])
r = s.round(); s.round()
check(A.P_INTAKE + "ok1.json" in s.f and s.assigns("ok1", "active"),
      "데이터셋 목록의 task_keys가 숫자여도 판정이 죽지 않고 정상 요청은 배정 (V2)")
check(not s.assigns("t1", "active"), "형태가 틀린 데이터셋 목록으로는 학습을 시작하지 않음 ('모름')")

# ---------------------------------------------------------------- b17 회귀 (0k)
def x1_case(edit):
    s = Sim(); s.grant(1); s.worker("MS1", ["master"]); s.worker("G1", ["gpu"]); s.round(); s.round()
    sid = s.signal("stop")
    r = s.round(crash_after=1)                     # 계획만 쓰고 멈춤
    pp = A.P_PLAN + sid + ".json"
    assert pp in s.f and s.done(sid) is None, r.writes[:2]
    if edit:
        o = copy.deepcopy(s.o(pp)); edit(o); s.f[pp] = FileRec(o, A0, s.now, s.now)
    s.tick(30)
    r = s.round()
    return s, sid, r
s, sid, r = x1_case(None)
check(not r.protect and (s.done(sid) or {}).get("result") == "done" and any(p.startswith(A.P_HOLD) for p in s.f),
      "정지 계획을 쓰고 멈춘 뒤 이어서 하면 보류까지 만들고 끝냄 (정상 계획은 보호 모드 아님)")
for desc, ed in [("효과 일부 삭제 ['gpu']", lambda o: o.update(effects=["gpu"])),
                 ("효과 중복", lambda o: o.update(effects=["hold", "hold", "gpu"])),
                 ("효과 바꿔치기", lambda o: o.update(effects=["unhold", "gpu"])),
                 ("효과 순서 바뀜", lambda o: o.update(effects=["gpu", "hold"])),
                 ("sid 다름", lambda o: o.update(sid="stop__p__99")),
                 ("종류 다름", lambda o: o.update(kind="release")),
                 ("대상 다름", lambda o: o.update(target="x"))]:
    s, sid, r = x1_case(ed)
    bad = [w.path for w in r.writes if w.path != A.P_ARBITER and not w.path.startswith(A.P_ALERT)]
    check(r.protect and not bad and s.done(sid) is None and not any(p.startswith(A.P_HOLD) for p in s.f),
          f"정지 계획의 {desc} → 보호 모드, 완료·보류·배정을 쓰지 않음 (X1)")
s, sid, r = x1_case(lambda o: o.update(effects=["gpu"]))
s.request("t99", "track", [99]); s.tick(30); r = s.round()
check(r.protect and not s.assigns("t99", "active"), "효과가 빠진 정지 계획이 남아 있는 동안 새 배정 없음 (X1 재현 조건)")

# ---------------------------------------------------------------- b18 회귀 (0l)
def y1_case(edit, owner=M2A, people=None):
    s = approved_sim()
    lk = s.lock(7)
    s.kill("E1"); s.tick(200); s.round()                    # 격리, 선택은 아직 닫힘
    sid = s.signal("confirm_choice", owner=owner, task="7", decision=lk["decision"], choice="ok", force=True)
    s.tick(20); s.round(crash_after=1)                      # 계획만 쓰고 멈춤
    pp = A.P_PLAN + sid + ".json"
    assert pp in s.f and s.done(sid) is None
    if edit:
        o = copy.deepcopy(s.o(pp)); edit(o); s.f[pp] = FileRec(o, A0, s.now, s.now)
    if people is not None:
        s.people = people
    s.tick(20)
    return s, sid, s.round()
s, sid, r = y1_case(None)
check(not r.protect and s.lock(7).get("state") == "quarantine" and "choice_not_open" in str(s.done(sid)),
      "일반 사용자의 강제 해제 계획을 이어 해도 무효 (정상 계획)")
s, sid, r = y1_case(lambda o: o.update(admin=True))
check(s.lock(7).get("state") == "quarantine" and "choice_not_open" in str(s.done(sid)) and not r.protect,
      "계획의 admin만 true로 바뀌어도 지금 신호 소유자가 관리자가 아니면 강제 해제 무효 (Y1)")
s, sid, r = y1_case(lambda o: o.update(requester="M1", admin=True))
check(r.protect and any(x["why"] == "plan_requester_mismatch" for x in r.protect) and s.lock(7).get("state") == "quarantine",
      "계획의 요청자가 신호 소유자와 다르면 보호 모드 (Y1)")
s, sid, r = y1_case(lambda o: o.update(admin="yes"))
check(r.protect and any(x["why"] in ("admin", "plan_admin_bad") for x in r.protect), "계획의 admin이 참·거짓이 아니면 보호 모드 (Y1)")
demoted = [dict(PEOPLE[0], role="user"), PEOPLE[1]]
s, sid, r = y1_case(None, owner=A0, people=demoted)
check(not r.protect and s.lock(7).get("state") == "quarantine",
      "계획 뒤 관리자에서 내려간 사람의 강제 해제 → 무효 (계획과 지금 권한 둘 다 관리자여야)")
s, sid, r = y1_case(None, owner=A0)
check(not r.protect and s.lock(7).get("state") == "free", "관리자의 강제 해제 계획을 이어 하면 풀림 (정상)")

s = basic(); s.worker("E1", ["gpu"])
s.request("dup1", "track", [41]); s.tick(5); s.request("dup1", "track", [41], app="relabel/requests/")
r = s.round(); s.tick(20); r2 = s.round()
check(len(s.assigns("dup1")) == 1 and s.intake("dup1").get("ok") is not None
      and any(isinstance(x.obj, dict) and x.obj.get("kind") == "duplicate_request" for p_, x in s.f.items() if p_.startswith(A.P_ALERT)),
      "같은 요청 ID 파일이 둘이어도 접수·배정은 하나, 알림을 남김 (Y4)")

# ---------------------------------------------------------------- b19 회귀 (0m)
s = approved_sim(); lk = s.lock(7); s.kill("E1"); s.tick(200); s.round()
sid = s.signal("confirm_choice", task="7", decision=lk["decision"], choice="ok", force=True)
s.tick(20); s.round(crash_after=1)
sp = A.P_SIGNALS + sid + ".json"; real = s.f[sp]
s.f[sp] = FileRec(real.obj, "", real.created, real.modified)
s.tick(20); r = s.round()
check(s.done(sid) is None and s.lock(7).get("state") == "quarantine" and not r.protect,
      "계획을 이어 할 때 신호 소유 계정을 모르면 끝내지 않고 미룸 (Z1)")
s.f[sp] = real; s.tick(20); s.round()
check(s.lock(7).get("state") == "free" and "applied" in str(s.done(sid)), "다시 읽히면 관리자 강제 해제를 마침 (Z1)")
# G의 해제(원래 관리자 신호 연결) 계획 뒤 그 관리자의 해제 권한이 철회됨 → 거절
s = basic()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
orig = s.signal("wake", stop_id=st)
rl = s.signal("release", owner=G, stop_id=st, origin_signal=orig)
s.tick(20); s.round(crash_after=1)
assert A.P_PLAN + rl + ".json" in s.f and s.done(rl) is None
s.people = [dict(PEOPLE[0], perms=["request", "wake"]), PEOPLE[1]]
s.tick(20); r = s.round()
check(s.o(A.P_HOLD + st + ".json")["active"] and "invalid:revoked" in str(s.done(rl)) and not r.protect,
      "해제 계획 뒤 원래 관리자의 해제 권한이 철회되면 아직 적용하지 않은 해제는 거절 (Z1)")
s2 = basic()
st = s2.signal("stop"); s2.tick(20); s2.round(); s2.tick(20); s2.round()
orig = s2.signal("wake", stop_id=st)
rl = s2.signal("release", owner=G, stop_id=st, origin_signal=orig)
s2.tick(20); s2.round(crash_after=1)
o_ = s2.f[A.P_SIGNALS + orig + ".json"]; s2.f[A.P_SIGNALS + orig + ".json"] = FileRec(o_.obj, "", o_.created, o_.modified)
s2.tick(20); s2.round()
check(s2.done(rl) is None and s2.o(A.P_HOLD + st + ".json")["active"], "원래 신호의 소유 계정을 모르면 G의 해제도 미룸 (Z1)")

# ---------------------------------------------------------------- b20 회귀 (0n)
def round_hidden(s, paths, dup=True, **inp):
    """snapshot이 같은 이름 파일(또는 읽기 실패)로 그 경로를 빼고 '모름'으로 넘긴 회차를 흉내."""
    files = {p_: r_ for p_, r_ in s.f.items() if p_ not in paths}
    unk = {"file:" + p_ for p_ in paths} | ({"dup:" + p_ for p_ in paths} if dup else set())
    cfg = Cfg(me=s.me, accounts=ACC, people=s.people)
    res = A.decide_round(cfg, Inputs(now=s.now, files=files, list_started_at=s.now - 3, unknown=unk, **inp))
    for w in res.writes:
        if w.mode == "create" and w.path in s.f:
            continue
        s.put(w.path, w.obj)
    return res
# ① 정지 보류가 같은 이름 둘 → 모름: 새 배정·GPU 필요 없음, 그 경로에 쓰지 않음
s = basic(); s.worker("G2", ["gpu"])
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
hp = A.P_HOLD + st + ".json"
s.request("t99", "track", [99]); s.tick(20)
r = round_hidden(s, {hp})
check(not s.assigns("t99", "active") and "hold_on_unknown" in r.notes and not any(w.path == hp for w in r.writes)
      and s.o(A.P_ARBITER)["wake"]["holds_unknown"] is True and "(모름)" in s.o(A.P_ARBITER)["wake"]["holds"]
      and s.o(A.P_ARBITER)["wake"]["gpu_needed"] == 0,
      "정지 보류 파일이 같은 이름 둘(모름)이면 보류가 있는 것으로 보고 새 배정·GPU 기동 없음, 그 경로에 쓰지 않음 (Q1)")
check(any(isinstance(x.obj, dict) and x.obj.get("kind") == "duplicate_path" for p_, x in s.f.items() if p_.startswith(A.P_ALERT)),
      "같은 이름 파일 알림이 남음")
# ② 계획이 같은 이름 둘 → 그 신호를 미루고 계획·보류·완료를 쓰지 않음
s = basic(); s.worker("G2", ["gpu"]); s.round(); s.round()
st = s.signal("stop"); s.tick(20); s.round(crash_after=1)
pp = A.P_PLAN + st + ".json"; assert pp in s.f
s.tick(20); r = round_hidden(s, {pp})
check(not any(w.path in (pp, A.P_HOLD + st + ".json", A.P_DONE + st + ".json") for w in r.writes) and s.done(st) is None,
      "신호 계획이 같은 이름 둘이면 그 신호를 미루고 계획·보류·완료를 다시 쓰지 않음 (Q1)")
s.tick(20); s.round()
check((s.done(st) or {}).get("result") == "done" and s.o(A.P_HOLD + st + ".json")["active"], "하나만 남으면 이어서 마침")
# ③ 완료 기록이 같은 이름 둘 → 다시 쓰지 않음
s = basic()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
dp = A.P_DONE + st + ".json"; assert dp in s.f
s.tick(20); r = round_hidden(s, {dp})
check(not any(w.path == dp or w.path == A.P_PLAN + st + ".json" for w in r.writes), "완료 기록이 같은 이름 둘이면 다시 계획·완료를 쓰지 않음 (Q1)")
# ④ 효과를 쓸 경로가 모름(보류 경로만 같은 이름 둘)이면 완료로 적지 않음
s = basic(); s.round(); s.round()
st = s.signal("stop"); s.tick(20); s.round(crash_after=1)
r = round_hidden(s, {A.P_HOLD + st + ".json"})
check(s.done(st) is None and not any(w.path == A.P_HOLD + st + ".json" for w in r.writes) and "hold_on_unknown" in r.notes,
      "효과를 쓸 경로를 모르면 그 회차는 판정 보류 — 쓰지 않고 완료로도 적지 않음 (Q1 → 0o)")

# ⑤ 인계 기록이 같은 이름 둘 → 인계를 되풀이하지 않음
s = basic(); s.round(); s.round()
hp_ = A.P_HANDOVER + "1.json"; assert hp_ in s.f
s.grant(1); s.tick(20); r = round_hidden(s, {hp_})
check("hold_on_unknown" in r.notes and not any(w.path.startswith(A.P_RECOVERY) or w.path == hp_ for w in r.writes),
      "인계 기록을 모르면 인계(다시 발급)를 되풀이하지 않고 기다림 (Q1)")

# Q2: G 해제의 원래 신호를 못 읽음 → 미룸, 다시 읽히면 해제
for dup_ in (False, True):
    s = basic()
    st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
    orig = s.signal("wake", stop_id=st)
    rl = s.signal("release", owner=G, stop_id=st, origin_signal=orig)
    s.tick(20); s.round(crash_after=1)
    op = A.P_SIGNALS + orig + ".json"
    s.tick(20); round_hidden(s, {op}, dup=dup_)
    check(s.done(rl) is None and s.o(A.P_HOLD + st + ".json")["active"],
          f"원래 신호를 {'같은 이름 둘이라' if dup_ else '읽지 못해'} 모르면 해제를 거절하지 않고 미룸 (Q2)")
    s.tick(20); s.round()
    check((s.done(rl) or {}).get("result") == "done" and not s.o(A.P_HOLD + st + ".json")["active"], "다시 읽히면 해제를 마침 (Q2)")
# 계획을 처음 세울 때도 같은 규칙
s = basic()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
orig = s.signal("wake", stop_id=st)
rl = s.signal("release", owner=G, stop_id=st, origin_signal=orig)
s.tick(20); round_hidden(s, {A.P_SIGNALS + orig + ".json"}, dup=False)
check(s.done(rl) is None and A.P_PLAN + rl + ".json" not in s.f, "새 해제 신호도 원래 신호를 모르면 거절하지 않고 미룸 (Q2)")
s.tick(20); s.round(); s.tick(20); s.round()
check((s.done(rl) or {}).get("result") == "done", "다시 읽히면 계획부터 세워 마침")
# 원래 신호가 정말 없으면 거절 (그대로)
s = basic()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
rl = s.signal("release", owner=G, stop_id=st, origin_signal="wake__p__999")
s.tick(20); s.round()
check((s.done(rl) or {}).get("result") == "rejected" and "origin_missing" in str(s.done(rl)), "원래 신호가 정말 없으면 거절 (그대로)")

# ---------------------------------------------------------------- b21 회귀 (0o: 읽지 못한 것이 있으면 그 회차는 판정 보류)
def only_round_writes(r):
    return [w.path for w in r.writes if w.path != A.P_ARBITER and not w.path.startswith(A.P_ALERT)]
# P1: 반환된 배정 파일을 못 읽는 회차 → 잠금·배정을 만들지 않음, 다시 읽히면 정상 재배정
s = assigned_sim()
s.release("E1", "r1"); s.tick(20); s.round()
k1 = [p_ for p_ in s.f if p_.startswith(A.P_ASSIGN)][0]
s.worker("E2", ["gpu"]); s.tick(20)
r = round_hidden(s, {k1}, dup=False)
check("hold_on_unknown" in r.notes and not only_round_writes(r), "배정 파일을 못 읽는 회차는 잠금·배정을 쓰지 않음 (P1 → 0o)")
s.tick(20); s.round(); s.tick(20); s.round()
act = s.assigns("r1", "active")
check(len(act) == 1 and s.lock(act[0]["tasks"][0]).get("session") == act[0]["session"],
      "다시 읽히면 배정과 잠금이 서로 맞게 다시 배정됨 (P1)")
# P1②: 복구 요청 파일을 못 읽는 회차 → 접수·배정 없음
s = approved_sim(); lk = s.lock(7); s.kill("E1"); s.tick(1200); s.round()
sid = s.signal("confirm_choice", task="7", decision=lk["decision"], choice="redo")
s.tick(20); s.round(crash_after=2)
rq = [p_ for p_ in s.f if "__recovery__" in p_]
if rq:
    s.tick(20); r = round_hidden(s, set(rq), dup=False)
    check("hold_on_unknown" in r.notes and not only_round_writes(r), "복구 요청 파일을 못 읽는 회차는 접수·배정을 하지 않음 (P1 → 0o)")
s.worker("E3", ["gpu"]); s.tick(20); s.round(); s.tick(20); s.round()
check((s.done(sid) or {}).get("result") == "done" and len([x for x in s.f if "__recovery__" in x]) == 1,
      "다시 읽히면 복구 요청 하나로 이어 감 (P1)")
# P2: 반환 보고를 처리할 회차에 TASK 잠금을 못 읽음 → 보고를 처리하지 않음, 다시 읽히면 잠금 해제
s = assigned_sim()
d0 = s.lock(7).get("decision")
s.release("E1", "r1"); s.tick(20)
r = round_hidden(s, {A.P_LOCK_TASK + "7.json"}, dup=False)
check(not only_round_writes(r) and s.lock(7).get("state") == "held", "반환 보고 회차에 잠금을 못 읽으면 보고를 처리하지 않음 (P2 → 0o)")
s.tick(20); s.round()
check(s.lock(7).get("decision") != d0 and not any(a.get("decision") == d0 and a.get("state") == "active" for a in s.assigns("r1")),
      "다시 읽히면 반환을 처리해 옛 잠금이 남지 않음 (새 배정으로 바뀜) (P2)")
# P3: 해제 대상 보류를 못 읽음 → 해제 신호를 끝내지 않음, 다시 읽히면 해제
s = basic(); s.round(); s.round()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
rl = s.signal("release", stop_id=st); s.tick(20)
r = round_hidden(s, {A.P_HOLD + st + ".json"}, dup=False)
check(s.done(rl) is None and not only_round_writes(r), "해제할 보류를 못 읽으면 해제 신호를 끝내지 않음 (P3 → 0o)")
s.tick(20); s.round()
check((s.done(rl) or {}).get("result") == "done" and not s.o(A.P_HOLD + st + ".json")["active"], "다시 읽히면 해제 (P3)")
# P4: 판정 보류가 30분 넘게 이어지면 알림 한 번, 시작 시각은 그대로
s = basic(); s.round(); s.round()
st = s.signal("stop"); s.tick(20); s.round(); s.tick(20); s.round()
hp4 = A.P_HOLD + st + ".json"
r = round_hidden(s, {hp4}, dup=False); since = s.o(A.P_ARBITER)["hold_on_since"]
for _ in range(31):
    s.tick(60); round_hidden(s, {hp4}, dup=False)
al = [x.obj for p_, x in s.f.items() if p_.startswith(A.P_ALERT) and isinstance(x.obj, dict) and x.obj.get("kind") == "hold_on_long"]
check(s.o(A.P_ARBITER)["hold_on_since"] == since and len(al) == 1 and al[0]["unknown"] == ["file:" + hp4],
      "판정 보류가 30분 넘으면 'hold_on_long' 알림 하나 (Keeper가 메일), 시작 시각 유지 (P4)")
s.tick(20); s.round()
check(not s.o(A.P_ARBITER).get("hold_on") and "hold_on_since" not in s.o(A.P_ARBITER), "다시 읽히면 판정 보류 끝")
w_ = s.o(A.P_ARBITER)
s.tick(20); round_hidden(s, {hp4}, dup=False)
check(s.o(A.P_ARBITER)["hold_on_since"] == s.now, "다시 못 읽으면 새 구간으로 시작")

print("RESULT", ok)
sys.exit(0 if ok else 1)
