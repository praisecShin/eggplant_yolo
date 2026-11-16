"""가짜 Drive(rclone alias → 로컬 폴더) + 가짜 CVAT로 CPU 마스터 순환 시험"""
import json, os, shutil, sys, time, datetime, threading
from pathlib import Path
T = Path(__file__).resolve().parent / "_work"; T.mkdir(exist_ok=True); D = T / "drive"; B = T / "base"
PKG = Path(sys.argv[1])
shutil.rmtree(D, ignore_errors=True); shutil.rmtree(B, ignore_errors=True)
(T / "rclone.conf").write_text(f"[gdrive]\ntype = alias\nremote = {D}\n")
os.environ.update(RCLONE_CONFIG=str(T / "rclone.conf"), KAGGLE_BASE=str(B), CVAT_TOKEN="x", EGGPLANT_SHARD="kg_test", MASTER_POLL_SEC="1")
shutil.copytree(PKG / "scripts", D / "scripts")
(D / "config").mkdir(parents=True)
(D / "config/routing.json").write_text(json.dumps({"routes": {"export": "kaggle_cpu", "backup": "kaggle_cpu", "upload": "kaggle_cpu", "shape": "kaggle_cpu"}}))
now = datetime.datetime.now(datetime.timezone.utc)
def put(rel, obj): p = D / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, ensure_ascii=False)); return p
def req(rid, kind, ids, route=None, sub="requests", **params):
    put(f"{sub}/REQ_{rid}__{kind}__pending.json", {"id": rid, "kind": kind, "status": "pending", "created": now.isoformat(), "task_ids": ids, "params": params})
    if route: put(f"requests/assign/ASSIGN_{rid}.json", {"req_id": rid, "kind": kind, "route": route, "status": "assigned"})
req("e1", "export", [1, 2, 3], "kaggle_cpu", format="CVAT for images 1.1", images=False, mode="all", org="horti")   # 1·2 같은 이름
req("c1", "export", [4], "colab")             # colab 배정 → 안 받음
req("n1", "export", [4])                      # 배정 없음 → 안 받음
req("u1", "upload", [4], "kaggle_cpu")        # 처리 안 하는 종류
req("g1", "shape", [4], "kaggle_cpu")         # GPU 꺼짐
req("a1", "hide", [4], "kaggle_cpu", sub="relabel/requests")   # AA — 30번 셀이 살아 있으면 안 받음
put("jobs/STOP_MASTER.json", {"until": None, "reason": "11/6 hold", "by": "james"})
peer = {"who": "colab-31", "session": "colab_x", "host": "Colab", "heartbeat": now.isoformat(), "stopping": False}
put("web/worker.json", dict(peer, stopping=True))

sys.path.insert(0, str(PKG / "notebooks" / "K_kaggle")); sys.path.insert(0, str(B / "scripts"))
import kaggle_cpu_master as m
m.ensure_environment = lambda: None; m.setup_credentials = lambda: None
m.is_daytime_kst = lambda: True; m.MAX_RUN_HOURS = float(os.environ.get("MASTER_TEST_SEC", "40")) / 3600   # v4.31.10: 느린 환경은 MASTER_TEST_SEC=90
AGG = []
m.aggregate_and_sync_state = lambda ctt, wb, rb: (AGG.append(time.time()), m._STATE.update(dirty=False, last_refresh=time.time()))
EXPORTED = []
class FakeTasks:
    def retrieve(self, i): return type("T", (), {"id": i, "name": NAMES[i]})()
NAMES = {1: "eggplant_G6_20261013_1_3_vf", 2: "eggplant_G6_20261013_1_3_vf", 3: "eggplant_G5_261026_1_2_vf", 4: "x_AA"}
class FakeClient: tasks = FakeTasks()
def patch_ctt():
    import cvat_task_tools as ctt
    ctt.connect = lambda *a, **k: FakeClient()
    ctt.set_scope = lambda *a, **k: {"org": "horti"}
    ctt.whoami = lambda c: "james"
    ctt.list_tasks = lambda c, **k: [{"task_id": i, "name": n, "updated_utc": "2026-11-07T00:00:00"} for i, n in NAMES.items()]
    def exp(task, dst, fmt=None, include_images=False):
        if task.id == 1 and STOP_AT_3["on"]:
            m._STATE["stop_req"] = {"reason": "시험 정지"}
        Path(dst).write_bytes(b"PK"); EXPORTED.append((task.id, Path(dst).name))
    ctt.export_labels = exp
STOP_AT_3 = {"on": True}
orig_pull = m.initial_pull
def ip():
    orig_pull(); sys.path_importer_cache.clear(); patch_ctt()
m.initial_pull = ip
# 처리 중에 다른 작업자가 새 요청을 Drive에 넣음 → 지워지면 안 됨
def late():
    time.sleep(6); req("z9", "track", [9], "colab")
threading.Thread(target=late, daemon=True).start()
m.main()

ok_all = True
def ok(c, msg):
    global ok_all; print(("✅ " if c else "❌ ") + msg); ok_all &= bool(c)
names = sorted(p.name for p in (D / "requests").glob("REQ_*"))
print(names, EXPORTED)
ok("REQ_e1__export__pending.json" in names and len(EXPORTED) == 1, "정지 표시 → 첫 TASK 뒤 멈추고 e1을 pending으로 되돌림")
r = json.loads((D / "requests/REQ_e1__export__pending.json").read_text()); ok("되돌림" in str(r.get("history")), "되돌린 이유가 이력에 남음")
ok(json.loads((D / "web/worker.json").read_text())["who"] == "kaggle-cpu-master", "31번 셀이 꺼져 있으면 web/worker.json에 씀")
print("RESULT", ok_all)

sys.exit(0 if ok_all else 1)   # v4.31.13: 실패하면 종료 코드도 1
