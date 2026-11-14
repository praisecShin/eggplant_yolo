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
req("a1", "discard", [4], "kaggle_cpu", sub="relabel/requests")   # AA — 30번 셀이 살아 있으면 안 받음
req("h1", "hide", [4], "colab", sub="relabel/requests")      # v4.32.0: 숨기기는 취합자(마스터)가 배정과 관계없이 받음
put("jobs/STOP_MASTER.json", {"until": None, "reason": "11/6 hold", "by": "james"})
peer = {"who": "colab-31", "session": "colab_x", "host": "Colab", "heartbeat": now.isoformat(), "stopping": False}
put("web/worker.json", peer); put("relabel/WORKER.json", dict(peer, who="colab-30"))
def _beat():                                   # v4.31.13: 가짜 동료도 생존 신호를 계속 보냄 (느린 환경에서 꺼진 것으로 보이지 않게)
    import time as _t
    while True:
        _t.sleep(15)
        hb = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for rel, who in (("web/worker.json", "colab-31"), ("relabel/WORKER.json", "colab-30")):
            try:
                tmp = D / (rel + ".tmp"); tmp.write_text(json.dumps(dict(peer, who=who, heartbeat=hb))); os.replace(tmp, D / rel)
            except OSError:
                pass
import threading as _th; _th.Thread(target=_beat, daemon=True).start()

sys.path.insert(0, str(PKG / "notebooks")); sys.path.insert(0, str(B / "scripts"))
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
        if task.id == 3 and STOP_AT_3["on"]:
            m._STATE["stop_req"] = {"reason": "시험 정지"}
        Path(dst).write_bytes(b"PK"); EXPORTED.append((task.id, Path(dst).name))
    ctt.export_labels = exp
STOP_AT_3 = {"on": False}
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
print(names)
ok("REQ_e1__export__done.json" in names and "REQ_e1__export__pending.json" not in names, "e1(kaggle_cpu export) 완료, 옛 pending 이름은 Drive에서 지움")
ok({"REQ_c1__export__pending.json", "REQ_n1__export__pending.json", "REQ_u1__upload__pending.json", "REQ_g1__shape__pending.json"} <= set(names), "colab 배정·배정 없음·upload·GPU 요청은 그대로 pending")
ok("REQ_z9__track__pending.json" in names, "처리 중 다른 작업자가 넣은 새 요청이 지워지지 않음 (sync 없음)")
ok(sorted(x[1] for x in EXPORTED) == ["eggplant_G5_261026_1_2_vf.zip", "eggplant_G6_20261013_1_3_vf__1.zip", "eggplant_G6_20261013_1_3_vf__2.zip"], f"같은 이름 TASK는 __ID 붙여 따로: {EXPORTED}")
ok(not (D / "jobs/gpu_queue.json").exists(), "GPU 꺼짐 → gpu_queue.json 안 만듦")
w = json.loads((D / "web/worker.json").read_text()); ok(w["session"] == "colab_x", "31번 셀의 web/worker.json 덮어쓰지 않음")
ok((D / "web/worker_cpu_master.json").exists(), "CPU 마스터는 web/worker_cpu_master.json에 기록")
ok((D / "relabel/requests/REQ_a1__discard__pending.json").exists(), "30번 셀이 살아 있어 AA 요청(버리기) 안 받음")
ok((D / "relabel/requests/REQ_h1__hide__done.json").exists(), "v4.32.0: 숨기기는 취합자인 마스터가 받음 (30번 셀이 살아 있어도)")
ok(json.loads((D / "jobs/STATE_OWNER.json").read_text()).get("role") == "cpu_master", "v4.32.0: 마스터가 취합자 임대를 가짐")
ok(not (D / "jobs/STOP_MASTER.json").exists() and (D / "jobs/STOP_MASTER_released.json").exists(), "수동 시작이 기한 없는 정지 표시를 풀고 기록")
done = json.loads((D / "requests/REQ_e1__export__done.json").read_text()); ok(done.get("taken_host") == "kaggle_cpu", "id로 받은 기록(taken_host)")
print("RESULT", ok_all)

sys.exit(0 if ok_all else 1)   # v4.31.13: 실패하면 종료 코드도 1
