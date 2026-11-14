"""v4.31.13 시험: R14(TASK 기록 받기 실패 시 쓰지 않음) · R15(상태 갱신이 TASK 기록을 통째로 올리지 않음 · '사라짐' 이력은 최신본에 이어 씀) · AA discard"""
import fnmatch, json, os, shutil, sys, time, types
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_43113"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; D = T / "drive"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t43113", KAGGLE_BASE=str(B), CVAT_TOKEN="x")
os.environ.pop("KAGGLE_KERNEL_RUN_TYPE", None)
import web_bridge as wb, relabel_bridge as rb
sys.path.insert(0, str(PKG / "notebooks"))
import kaggle_cpu_master as m
ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)
def jw(p, o):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
def jr(p):
    return json.loads(p.read_text(encoding="utf-8"))
m.BASE = B
m._remote = lambda rel="": str(D / rel)
FAIL = {"down": set(), "up": set(), "lsf": False}; COPIES = []
def _rc(*a, **k):
    a = list(a); out = ""; rc = 0; err = ""
    if a[0] == "lsf":
        if FAIL["lsf"]: rc = 3
        d = Path(a[-1]); inc = a[a.index("--include") + 1] if "--include" in a else "*"
        if not d.is_dir(): rc, err = 3, "directory not found"
        else: out = "\n".join(sorted(f.name for f in d.glob("*") if f.is_file() and fnmatch.fnmatch(f.name, inc)))
    elif a[0] == "copyto":
        src, dst = Path(a[1]), Path(a[2])
        down = str(src).startswith(str(D))
        if src.name in FAIL["down" if down else "up"] or not src.is_file(): rc = 5
        else: dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dst)
    elif a[0] == "copy":
        src, dst = Path(a[1]), Path(a[2]); ex = [a[i + 1] for i, x in enumerate(a) if x == "--exclude"]
        COPIES.append((str(src), str(dst), ex))
        if src.is_dir():
            for f in src.rglob("*"):
                rel = f.relative_to(src).as_posix()
                if f.is_file() and not any(fnmatch.fnmatch(rel, e.replace("/**", "/*")) or fnmatch.fnmatch(f.name, e) for e in ex):
                    (dst / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(f, dst / rel)
    return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)
m.rclone = _rc
REMOTE2 = {"history": [{"note": "a"}, {"note": "b"}], "track_pending": {"xml": "new_track.xml"}}

# ---- R14: 도우미
jw(D / "relabel/tasks/2.json", REMOTE2)
FAIL["down"] = {"2.json"}
r = m.sync_task_record(2, lambda: rb.add_history(B, 2, kind="backup", status="받음"))
check(r is False and jr(D / "relabel/tasks/2.json") == REMOTE2, "받기 실패 → 쓰지 않음 (Drive 기록 그대로)")
FAIL["down"] = set(); FAIL["lsf"] = True
r = m.sync_task_record(2, lambda: rb.add_history(B, 2, kind="backup", status="받음"))
check(r is False and jr(D / "relabel/tasks/2.json") == REMOTE2, "목록 읽기 실패 → '없음'으로 보지 않고 쓰지 않음")
FAIL["lsf"] = False
(D / "relabel/tasks/3.json").write_text("{깨짐")
check(m.sync_task_record(3, lambda: rb.add_history(B, 3, kind="x", status="y")) is False and (D / "relabel/tasks/3.json").read_text() == "{깨짐", "읽을 수 없는 기록 → 쓰지 않음")
FAIL["up"] = {"2.json"}
check(m.sync_task_record(2, lambda: rb.add_history(B, 2, kind="backup", status="받음")) is False, "올리기 실패 → False")
FAIL["up"] = set()
check(m.sync_task_record(2, lambda: rb.add_history(B, 2, kind="backup", status="받음")) is True
      and len(jr(D / "relabel/tasks/2.json")["history"]) == 3 and jr(D / "relabel/tasks/2.json")["track_pending"] == REMOTE2["track_pending"], "정상: 최신본에 이어 씀 (확인 대기 track 보존)")
check(m.sync_task_record(5, lambda: rb.add_history(B, 5, kind="backup", status="받음")) is True and len(jr(D / "relabel/tasks/5.json")["history"]) == 1, "Drive에 없던 TASK는 새 기록")

# ---- R14: 받는 중 확인에서 기록을 못 쓰면 요청을 끝내지 않음 → 다음에 다시 (이력은 한 번만)
jw(D / "relabel/tasks/2.json", REMOTE2)
req = {"id": "B1", "kind": "backup", "status": "waiting", "task_ids": [2], "remaining": [2], "waiting_t": time.time(), "created": "2026-11-13T00:00:00Z", "results": [], "history": []}
jw(B / "relabel/requests/REQ_B1__backup__waiting.json", req); jw(D / "relabel/requests/REQ_B1__backup__waiting.json", req)
(B / "backups/x").mkdir(parents=True); (B / "backups/x/2.zip").write_text("z")
(B / "backups/pending_backups.csv").write_text("request_time,server,task_id,task_name,status\n", encoding="utf-8")
m.run_cpu_backup_and_export = lambda ctt, wb_, rq: m._STATE.update(last_backup_rows=[{"task_id": 2, "backup_state": "최신", "last_file": "backups/x/2.zip"}])
m._peer = lambda rel, sess: None
m.push_req = lambda a, b, sub, **k: (shutil.copy(b["_path"], D / sub / Path(b["_path"]).name), [(D / sub / Path(a["_path"]).name).unlink() for _ in [0] if Path(a["_path"]).name != Path(b["_path"]).name])
m._STATE.update(aa_peer=None, aa_gpu_peer=None, bk_poll_t=0)
FAIL["down"] = {"2.json"}
m.poll_waiting_backups(None, wb, rb)
check(jr(D / "relabel/tasks/2.json") == REMOTE2 and [f.name for f in (D / "relabel/requests").glob("REQ_B1*")] == ["REQ_B1__backup__waiting.json"],
      "기록 받기 실패: Drive 기록 그대로 · 요청은 '받는 중' 그대로")
FAIL["down"] = set(); m._STATE["bk_poll_t"] = 0
m.poll_waiting_backups(None, wb, rb)
d2 = jr(D / "relabel/tasks/2.json")
check(len(d2["history"]) == 3 and d2["track_pending"] and [f.name for f in (D / "relabel/requests").glob("REQ_B1*")] == ["REQ_B1__backup__done.json"], "다음 확인: 이어 쓰고 요청 완료")

# ---- AA discard
jw(D / "relabel/tasks/8.json", {"history": [{"note": "h"}], "track_pending": {"xml": "t.xml"}})
jw(B / "relabel/tasks/9.json", {"history": [{"note": "옛 로컬"}], "track_pending": None})
jw(D / "relabel/tasks/9.json", {"history": [{"note": "옛 로컬"}, {"note": "GPU 새 기록"}], "track_pending": {"xml": "t9.xml"}})
m.claim = lambda wb_, rb_, rq, scope: rq
m.send_heartbeat_once = lambda *a, **k: None
ctt = types.SimpleNamespace(as_task_ids=lambda x: [int(i) for i in x])
rq = {"id": "D1", "kind": "discard", "status": "taken", "task_ids": [8], "created": "x", "history": []}
jw(B / "relabel/requests/REQ_D1__discard__taken.json", rq); rq["_path"] = str(B / "relabel/requests/REQ_D1__discard__taken.json")
shutil.copy(rq["_path"], D / "relabel/requests/REQ_D1__discard__taken.json")
COPIES.clear()
m.handle_aa(ctt, wb, rb, rq, "t")
d8, d9 = jr(D / "relabel/tasks/8.json"), jr(D / "relabel/tasks/9.json")
check(d8["track_pending"] is None and d8["history"] == [{"note": "h"}], "discard: 그 TASK 기록만 최신본에 고침")
check(len(d9["history"]) == 2 and d9["track_pending"], "discard: 다른 TASK(9) 기록은 건드리지 않음")
check(not any(c[0].endswith("relabel/tasks") and c[1].startswith(str(D)) for c in COPIES), "AA 작업: relabel/tasks 폴더를 통째로 올리지 않음")

# ---- R15: 상태 갱신
jw(B / "relabel/tracked.json", {"7": {"first_name": "t7_uld", "name": "t7_uld", "first_seen": "x", "hidden": False}})
jw(D / "relabel/tasks/7.json", {"history": [{"note": "7의 옛 이력"}], "track_pending": None})
wb.gone_tasks = lambda base: {"7": {"name": "t7_uld", "gone_at": "2026-11-13T10:00:00"}}
def _stats(*a, **k):                                       # 통계를 내는 사이 GPU가 9번 기록을 바꿈
    jw(D / "relabel/tasks/9.json", {"history": [{"note": "옛 로컬"}, {"note": "GPU 새 기록"}, {"note": "더 새 기록"}], "track_pending": {"xml": "t9b.xml"}})
    return {}
for n, f in dict(repair_pending=lambda *a, **k: 0, settle=lambda *a, **k: None, media_names=lambda *a, **k: (set(), set()), snapshots=lambda *a, **k: {},
                 compute_stats=_stats, compute_corrections=lambda *a, **k: {}, build_state=lambda *a, **k: {}, write_state=lambda *a, **k: None).items():
    setattr(wb, n, f)
rb.build_state = lambda *a, **k: jw(B / "relabel/state.json", {"ok": 1})
m.uld_info = lambda wb_: {"index": {}, "lineage": {}}
actt = types.SimpleNamespace(compact_shards=lambda *a, **k: 0, connect=lambda *a: object(), set_scope=lambda *a: {}, list_tasks_all=lambda *a, **k: ([], {}),
                             whoami=lambda c: "u", scope_text=lambda s: "", __version__="t")
COPIES.clear()
m.aggregate_and_sync_state(actt, wb, rb)
d9, d7 = jr(D / "relabel/tasks/9.json"), jr(D / "relabel/tasks/7.json")
check(len(d9["history"]) == 3 and d9["track_pending"] == {"xml": "t9b.xml"}, "상태 갱신: 그 사이 바뀐 TASK(9) 기록을 덮지 않음")
check([h.get("note") for h in d7["history"]][0] == "7의 옛 이력" and d7["history"][-1].get("status") == "CVAT에서 사라짐" and len(d7["history"]) == 2, "'사라짐' 이력은 Drive 최신본에 이어 씀")
check((D / "relabel/state.json").exists() and jr(D / "relabel/tracked.json")["7"].get("gone_at"), "state·tracked는 올림")
up = [c for c in COPIES if c[0].endswith("relabel") and c[1].startswith(str(D))]
check(up and all("tasks/**" in c[2] for c in up), "relabel 올리기에서 tasks 제외")
# 못 쓰면 다음에 다시
jw(B / "relabel/tracked.json", {"6": {"first_name": "t6_uld", "name": "t6_uld", "first_seen": "x", "hidden": False}})
jw(D / "relabel/tasks/6.json", {"history": [{"note": "6"}], "track_pending": None})
wb.gone_tasks = lambda base: {"6": {"name": "t6_uld", "gone_at": "2026-11-13T10:00:00"}}
FAIL["down"] = {"6.json"}
m.aggregate_and_sync_state(actt, wb, rb)
check(jr(D / "relabel/tasks/6.json")["history"] == [{"note": "6"}] and not jr(D / "relabel/tracked.json")["6"].get("gone_at"), "'사라짐' 이력을 못 쓰면 표시를 지워 다음에 다시")
FAIL["down"] = set()
m.aggregate_and_sync_state(actt, wb, rb)
check(len(jr(D / "relabel/tasks/6.json")["history"]) == 2 and jr(D / "relabel/tracked.json")["6"].get("gone_at"), "다음 갱신에서 이어 씀")
print("RESULT", ok); sys.exit(0 if ok else 1)
