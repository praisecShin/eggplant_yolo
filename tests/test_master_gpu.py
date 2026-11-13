"""가짜 Drive(rclone alias → 로컬 폴더) + 가짜 CVAT로 CPU 마스터 순환 시험"""
import json, os, shutil, sys, time, datetime, threading
from pathlib import Path
T = Path(__file__).resolve().parent / "_work_mg"; T.mkdir(exist_ok=True); D = T / "drive"; B = T / "base"
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

# v4.31.7: GPU 워커 시작 시험 — kaggle_gpu 배정 요청이 있으면 GPU 워커 노트북을 Kaggle API로 올림 (한 번만)
(D / "config/routing.json").write_text(json.dumps({"gpu_worker_enabled": True, "routes": {"shape": "kaggle_gpu", "train": "kaggle_gpu"},
                                                   "kaggle_kernels": {"gpu_worker_slug": "eggplant-gpu-worker"}}))
req("g1", "shape", [4], "kaggle_gpu", sub="relabel/requests")
req("t1", "train", [], "kaggle_gpu")
req("c1", "export", [4], "colab")
shutil.copy(next((PKG / "notebooks").glob("eggplant_kaggle_gpu_worker_v*.ipynb")), (D / "notebooks").mkdir(parents=True, exist_ok=True) or D / "notebooks" / "eggplant_kaggle_gpu_worker_v4.31.7.ipynb")
(D / "notebooks" / "eggplant_kaggle_gpu_worker_v4.31.2.ipynb").write_text("{}")   # 옛 버전 — 새 것을 골라야 함
BIN = T / "bin"; BIN.mkdir(exist_ok=True); LOG = T / "kaggle_calls.log"
(BIN / "kaggle").write_text(f"""#!/bin/sh
echo "$@" >> {LOG}
if [ "$1 $2" = "kernels push" ]; then cp "$4/kernel-metadata.json" {T}/pushed_meta.json; ls "$4" > {T}/pushed_files.txt; fi
if [ "$1 $2" = "kernels status" ]; then echo 'status "complete"'; fi
""")
os.chmod(BIN / "kaggle", 0o755); os.environ["PATH"] = f"{BIN}:" + os.environ["PATH"]
os.environ.update(KAGGLE_USERNAME="tester", KAGGLE_KEY="k")
sys.path.insert(0, str(PKG / "notebooks")); sys.path.insert(0, str(B / "scripts"))
import kaggle_cpu_master as m
m.ensure_environment = lambda: None; m.setup_credentials = lambda: None
m.is_daytime_kst = lambda: True; m.MAX_RUN_HOURS = 25 / 3600
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
m.main()
ok_all = True
def ok(c, msg):
    global ok_all; print(("✅ " if c else "❌ ") + msg); ok_all &= bool(c)
calls = LOG.read_text().splitlines() if LOG.exists() else []
pushes = [c for c in calls if c.startswith("kernels push")]
ok(len(pushes) == 1, f"GPU 워커를 한 번만 올림 (10분 안에 다시 올리지 않음): {len(pushes)}번")
meta = json.loads((T / "pushed_meta.json").read_text()) if (T / "pushed_meta.json").exists() else {}
ok(meta.get("kernel_type") == "notebook" and meta.get("enable_gpu") == "true" and meta.get("id") == "tester/eggplant-gpu-worker", f"GPU 켠 노트북으로: {meta}")
ok(meta.get("code_file") == "eggplant_kaggle_gpu_worker_v4.31.7.ipynb", f"Drive의 가장 새 워커 노트북: {meta.get('code_file')}")
files = (T / "pushed_files.txt").read_text().split() if (T / "pushed_files.txt").exists() else []
ok(sorted(files) == ["eggplant_kaggle_gpu_worker_v4.31.7.ipynb", "kernel-metadata.json"], f"올린 파일: {files}")
names = sorted(p.name for p in (D / "requests").glob("REQ_*")) + sorted(p.name for p in (D / "relabel/requests").glob("REQ_*"))
ok("REQ_t1__train__pending.json" in names and "REQ_g1__shape__pending.json" in names, "GPU 요청은 마스터가 받지 않고 pending 그대로 (워커가 받음)")
print("RESULT", ok_all)
