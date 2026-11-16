"""v4.32.0 (2차-1 F3·F14) 시험: 취합자 임대 · 요청은 받은 세션만 · '받는 중' 넘겨받기 · TASK 기록 최신본(줄·다시) · 마스터 받기 확인 · 셀 정적 확인"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest
import datetime, fnmatch, json, os, shutil, sys, time, types
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_4320"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; D = T / "drive"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t4320", KAGGLE_BASE=str(B), CVAT_TOKEN="x")
os.environ.pop("KAGGLE_KERNEL_RUN_TYPE", None)
import web_bridge as wb, relabel_bridge as rb
ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)
def iso(sec_ago=0):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=sec_ago)).isoformat()
def jw(p, o):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
def jr(p):
    return json.loads(p.read_text(encoding="utf-8"))

# ---- 취합자 임대
L = lambda sess, prio, ago=0, stop=False: {"session": sess, "prio": prio, "heartbeat": iso(ago), "stopping": stop}
check(wb.lease_should_take(None, "me", 2), "주인이 없으면 맡음")
check(wb.lease_should_take(L("me", 2), "me", 2), "내 것이면 계속")
check(not wb.lease_should_take(L("m", 3), "me", 2), "살아 있는 더 높은 순위(마스터)면 맡지 않음")
check(wb.lease_should_take(L("w", 2), "me", 3), "더 낮은 순위면 넘겨받음 (마스터가 켜지면)")
check(not wb.lease_should_take(L("w", 2), "me", 2), "같은 순위가 살아 있으면 맡지 않음")
check(wb.lease_should_take(L("m", 3, ago=400), "me", 2), "주인이 꺼짐(생존 신호 오래됨) → 이어받음")
check(wb.lease_should_take(L("m", 3, stop=True), "me", 2), "주인이 내려놓음 → 이어받음")
check(not wb.lease_should_take(None, "gpu", 0), "GPU 워커(순위 0)는 맡지 않음")

# ---- 요청 소유
mine = {"status": "taken", "taken_session": "me"}
check(wb.request_owned({"status": "taken", "taken_session": "me"}, mine, "me"), "진행 중 · 내 세션 → 씀")
check(not wb.request_owned({"status": "taken", "taken_session": "other"}, mine, "me"), "다른 세션이 받음 → 쓰지 않음")
check(not wb.request_owned({"status": "canceled", "taken_session": "me"}, mine, "me"), "앱이 취소함 → 쓰지 않음")
check(not wb.request_owned(None, mine, "me"), "Drive에서 못 찾음 → 쓰지 않음")
check(wb.request_owned({"status": "pending"}, {"status": "pending"}, "me"), "대기 → 받기는 씀")
check(not wb.request_owned({"status": "taken", "taken_session": "other"}, {"status": "pending"}, "me"), "이미 다른 세션이 받음 → 받지 않음")
jw(B / "web/worker.json", {"session": "w1", "heartbeat": iso(10)})
jw(B / "relabel/WORKER_gpu.json", {"session": "g1", "heartbeat": iso(10)})
jw(B / "relabel/WORKER.json", {"session": "old", "heartbeat": iso(900)})
alive = wb.live_sessions(B)
check(alive == {"w1", "g1"}, f"살아 있는 세션 {alive}")
check(wb.may_adopt({"taken_session": "old"}, "me", alive) and not wb.may_adopt({"taken_session": "g1"}, "me", alive), "받는 중: 꺼진 세션 것만 넘겨받음")

# ---- wb.finish: 이 세션이 받은 것만
for rid, sess in (("f1", "me"), ("f2", "other")):
    jw(B / f"requests/REQ_{rid}__track__taken.json", {"id": rid, "kind": "track", "status": "taken", "taken_session": sess, "task_ids": [1], "created": "x"})
done = wb.finish(B, ["f1", "f2"], ok=False, summary="t", session="me")
check([d["id"] for d in done] == ["f1"], f"끝내기: 다른 세션이 받은 요청은 건드리지 않음 {[d['id'] for d in done]}")

# ---- TASK 기록: 원격(Kaggle) — 실패하면 줄에 남기고 같은 순서로 다시, 같은 이력은 한 번
FAIL = {"on": False}
def fetch(rel, dest):
    if FAIL["on"]:
        return "fail"
    src = D / rel
    if not src.exists():
        return "missing"
    Path(dest).parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dest); return "ok"
def put(rel, src):
    if FAIL["on"]:
        return False
    (D / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, D / rel); return True
jw(D / "relabel/tasks/5.json", {"history": [{"note": "GPU가 쓴 것"}], "track_pending": {"xml": "a.xml"}})
jw(B / "relabel/tasks/5.json", {"history": [], "track_pending": None})                  # 오래된 로컬 사본
rb.use_remote(fetch, put)
rb.add_history(B, 5, kind="upload", status="완료")
d5 = jr(D / "relabel/tasks/5.json")
check(len(d5["history"]) == 2 and d5["track_pending"] == {"xml": "a.xml"}, "Kaggle: 최신본에 이어 써 그 파일만 올림 (오래된 로컬로 덮지 않음)")
FAIL["on"] = True
rb.add_history(B, 5, kind="track", status="완료")
rb.set_pending_track(B, 5, {"xml": "b.xml"})
check(len(rb._REMOTE["queue"]) == 2 and jr(D / "relabel/tasks/5.json") == d5, "Drive 실패: 고치기를 줄에 남김 (Drive 그대로)")
check(rb.flush_remote() == 2, "아직 실패 → 그대로 남음")
jw(D / "relabel/tasks/5.json", dict(d5, history=d5["history"] + [{"note": "그 사이 다른 작업자"}]))
FAIL["on"] = False
check(rb.flush_remote() == 0, "다시: 모두 올림")
d5 = jr(D / "relabel/tasks/5.json")
check([h.get("note") or h.get("kind") for h in d5["history"]] == ["GPU가 쓴 것", "upload", "그 사이 다른 작업자", "track"] and d5["track_pending"] == {"xml": "b.xml"},
      f"순서대로 최신본에 이어 씀 {[h.get('note') or h.get('kind') for h in d5['history']]}")
rb.flush_remote()
check(len(jr(D / "relabel/tasks/5.json")["history"]) == 4, "같은 이력은 두 번 적히지 않음")
rb._REMOTE.update(fetch=None, put=None)

# ---- CPU 마스터: 올리기 전 소유 확인 · 받은 뒤 확인 · 임대
sys.path.insert(0, str(PKG / "notebooks" / "K_kaggle"))
import kaggle_cpu_master as m
m.BASE = B
m._remote = lambda rel="": str(D / rel)
SWAP = {"after_push": None}
def _rc(*a, **k):
    a = list(a); out = ""; rc = 0; err = ""
    if a[0] == "lsf":
        d = Path(a[-1]); inc = a[a.index("--include") + 1] if "--include" in a else "*"
        if not d.is_dir(): rc, err = 3, "directory not found"
        else: out = "\n".join(sorted(f.name for f in d.glob("*") if f.is_file() and fnmatch.fnmatch(f.name, inc)))
    elif a[0] == "copyto":
        src, dst = Path(a[1]), Path(a[2])
        if not src.is_file(): rc = 3
        else: dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dst)
    elif a[0] == "deletefile":
        Path(a[1]).unlink(missing_ok=True)
    elif a[0] == "copy":
        src, dst = Path(a[1]), Path(a[2])
        if src.is_dir():
            inc = [a[i + 1] for i, x in enumerate(a) if x == "--include"]
            for f in src.glob("*"):
                if f.is_file() and (not inc or any(fnmatch.fnmatch(f.name, p) for p in inc)):
                    dst.mkdir(parents=True, exist_ok=True); shutil.copy(f, dst / f.name)
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)
m.rclone = _rc
m.CLAIM_CONFIRM_SEC = 0
def mkreq(rid, status="pending", sess=None, kind="discard"):
    o = {"id": rid, "kind": kind, "status": status, "task_ids": [4], "created": "x", "history": []}
    if sess: o["taken_session"] = sess
    for root in (B, D):
        jw(root / f"relabel/requests/REQ_{rid}__{kind}__{status}.json", o)
    return dict(o, _path=str(B / f"relabel/requests/REQ_{rid}__{kind}__{status}.json"))
r = mkreq("c1")
got = m.claim(wb, rb, r, "aa")
check(got and jr(D / "relabel/requests/REQ_c1__discard__taken.json")["taken_session"] == m.SESSION_ID, "마스터 받기: Drive에 올리고 확인")
r = mkreq("c2")
jw(D / "relabel/requests/REQ_c2__discard__taken.json", {"id": "c2", "kind": "discard", "status": "taken", "taken_session": "other", "history": []})
(D / "relabel/requests/REQ_c2__discard__pending.json").unlink()
check(m.claim(wb, rb, r, "aa") is None, "마스터 받기: 다른 작업자가 먼저 받았으면 물러남")
r = mkreq("c3")
_orig_sleep = m.time.sleep
def _swap(sec):                                          # 받은 직후 다른 작업자가 같은 요청을 받아 덮음
    p = D / "relabel/requests/REQ_c3__discard__taken.json"
    if p.exists():
        jw(p, dict(jr(p), taken_session="other"))
m.time.sleep = _swap
check(m.claim(wb, rb, r, "aa") is None, "마스터 받기: 거의 동시에 받은 다른 작업자가 있으면 다시 읽어 물러남")
m.time.sleep = _orig_sleep
r = mkreq("p1", status="taken", sess="other")
fin = rb.set_status(B, r, "done")
check(m.push_req(r, fin, "relabel/requests") is False and (D / "relabel/requests/REQ_p1__discard__taken.json").exists(), "마스터 올리기: 다른 세션 것이면 올리지 않음")
# 임대
(D / "jobs").mkdir(parents=True, exist_ok=True)
check(m.lease_tick(wb) and jr(D / "jobs/STATE_OWNER.json")["session"] == m.SESSION_ID, "마스터: 주인이 없으면 취합자를 맡음")
jw(D / "jobs/STATE_OWNER.json", L("m2", 3))
check(not m.lease_tick(wb), "다른 살아 있는 마스터(같은 순위)가 맡고 있으면 맡지 않음")
jw(D / "jobs/STATE_OWNER.json", L("w", 2))
check(m.lease_tick(wb), "30번 셀(순위 2)이 맡고 있으면 마스터가 넘겨받음")
m.lease_tick(wb, stopping=True)
check(jr(D / "jobs/STATE_OWNER.json")["stopping"] is True and not m._STATE["owner"], "마스터가 멈출 때 내려놓음")
jw(D / "jobs/DIRTY_s9.json", {"session": "s9"})
check([p.name for p in m.dirty_markers()] == ["DIRTY_s9.json"], "취합자: 다른 작업자의 표시를 받음")

# ---- 30번 셀 정적 확인
nb = json.load(open(latest(PKG / "notebooks" / "A0_colab", "eggplant_yolo_colab"), encoding="utf-8"))
code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
c30 = next(s for s in code if s.startswith("# 30.")); c28 = next(s for s in code if s.startswith("# 28."))
check("'relabel/**'" not in c30.split("def _rl_push")[1] and "relabel/tasks/{tid}.json" not in c30, "30번: relabel/**·TASK 기록 파일을 통째로 올리지 않음")
check(c30.count("if not _own_state():") >= 3 and "rb.use_remote(_kg_fetch, _kg_put)" in c30, "30번: 상태 파일은 취합자만 · Kaggle은 TASK 기록을 최신본에")
check("_rl_claim(r)" in c30 and "_lc_claim(ids)" in c30 and "wb.request_owned(cur, req, SESSION_ID)" in c30, "30번: 받기 확인 · 쓰기 전 소유 확인")
check("wb.may_adopt(r, SESSION_ID, _alive)" in c30 and "_own_state(stopping=True)" in c30, "30번: 꺼진 세션 것만 넘겨받음 · 멈출 때 내려놓음")
check("_own28 = False" in c28 and "if _own28 and wb is not None and hasattr(wb, 'settle')" in c28, "28번: 다른 작업자가 취합자면 상태 파일·받는 중 정리를 하지 않음")
gpu = json.load(open(latest(PKG / "notebooks" / "K_kaggle", "eggplant_kaggle_gpu_worker"), encoding="utf-8"))
g30 = "".join(gpu["cells"][2]["source"])
check(g30.replace("W_ROLE       = 'gpu'", "W_ROLE       = 'all'", 1) == c30, "GPU 워커 30번 셀 = Colab 30번 셀 (W_ROLE만 다름)")
print("RESULT", ok); sys.exit(0 if ok else 1)
