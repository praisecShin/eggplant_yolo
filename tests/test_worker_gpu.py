"""v4.31.6 30번 통합 작업자 시험: 공정 차례 · LC GPU 맡아 두기 · 한 사람 동시 제한 · 두 앱 요청을 한 셀에서
사용: python test_worker30.py <패키지의 drive 폴더>   (가짜 Drive 폴더 + 가짜 CVAT · torch·IPython 없이)"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest   # v4.31.12 (R13)
import json, os, shutil, sys, time, types, datetime, threading, glob
from pathlib import Path
PKG = Path(sys.argv[1]).resolve()
T = Path(__file__).resolve().parent / "_work_wg"; shutil.rmtree(T, ignore_errors=True); B = T / "base"; B.mkdir(parents=True)
shutil.copytree(PKG / "scripts", B / "scripts")
sys.path.insert(0, str(B / "scripts"))
os.environ["EGGPLANT_SHARD"] = "w30_test"
import cvat_task_tools as ctt, web_bridge as wb, relabel_bridge as rb

KST = datetime.timezone(datetime.timedelta(hours=9))
def ago(m): return (datetime.datetime.now(KST) - datetime.timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")   # KST 형식
def ago_utc(m): return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=m)).isoformat(timespec="seconds")
def put(rel, obj):
    p = B / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, ensure_ascii=False)); return p
def req(sub, rid, kind, ids, by, created):
    put(f"{sub}/REQ_{rid}__{kind}__pending.json", {"id": rid, "kind": kind, "status": "pending", "created": created, "task_ids": ids, "by": by, "params": {}})

ok = True
def check(cond, msg):
    global ok
    print(("✅ " if cond else "❌ ") + msg); ok &= bool(cond)

# ---- 1) fair_order 단위 시험
rs = [{"id": "a1", "kind": "shape", "by": "A", "created": ago(300)}, {"id": "a2", "kind": "shape", "by": "A", "created": ago(200)},
      {"id": "a3", "kind": "shape", "by": "A (AA 교체)", "created": ago_utc(100)}, {"id": "b1", "kind": "shape", "by": "B", "created": ago(1)},
      {"id": "b0", "kind": "refresh", "by": "B", "created": ago(0)}, {"id": "c1", "kind": "track", "by": "C", "created": ago_utc(150)}]
o = [r["id"] for r in wb.fair_order(rs, ("refresh",))]
check(o == ["b0", "a1", "c1", "b1", "a2", "a3"], f"공정 차례 (가벼운 일 → 사람마다 한 건씩, 같은 차례는 오래된 것 먼저, KST·UTC 섞여도): {o}")

# ---- 2) GPU 워커 (W_ROLE='gpu'): kaggle_gpu 배정만 받고, 학습은 모든 GPU 줄을 맡고, 할 일이 없으면 스스로 끝남
for sub in ("requests", "relabel/requests", "requests/assign"):
    (B / sub).mkdir(parents=True, exist_ok=True)
def assign(rid, route):
    put(f"requests/assign/ASSIGN_{rid}.json", {"req_id": rid, "route": route, "status": "assigned", "approved": True})
req("relabel/requests", "RG1", "shape", [1], "A", ago(30)); assign("RG1", "kaggle_gpu")
req("relabel/requests", "RG2", "shape", [2], "B", ago(20)); assign("RG2", "kaggle_gpu")
req("relabel/requests", "RC1", "shape", [3], "B", ago(25)); assign("RC1", "colab")       # 30번 셀 몫 → 안 받음
req("relabel/requests", "RN1", "shape", [5], "B", ago(25))                               # 배정 없음 → 안 받음
req("requests", "LT1", "train", [], "A", ago(10)); assign("LT1", "kaggle_gpu")
req("requests", "LB1", "backup", [10], "B", ago(5)); assign("LB1", "kaggle_cpu")           # CPU 마스터 몫
nb = json.load(open(latest(PKG / "notebooks", "eggplant_kaggle_gpu_worker")))
src = "".join(nb["cells"][2]["source"])
assert src.startswith("# 30. 작업자"), src[:40]
cut = src.index("# ---------- 돌기 (v4.31.6)")
partA, partB = src[:cut], src[cut:]
assert "W_ROLE       = 'gpu'" in partA
partA = partA.replace("W_EXIT_IDLE_MIN = None", "W_EXIT_IDLE_MIN = 0.03", 1)
partA = partA.replace("W_POLL_SEC   = None", "W_POLL_SEC   = 0.1", 1).replace("W_USER_MAX   = 2 ", "W_USER_MAX   = 1 ", 1)

sys.modules["torch"] = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False, device_count=lambda: 0))
RUNCELL = []
class _IP:
    def run_cell(self, code, store_history=False):
        RUNCELL.append(code[:20]); return types.SimpleNamespace(error_in_exec=None, error_before_exec=None)
sys.modules["IPython"] = types.SimpleNamespace(get_ipython=lambda: _IP())
(B / "scripts/notebook_cells.json").exists() or put("scripts/notebook_cells.json", {"version": "4.31.6", "cells": {}})
G = dict(__name__="__main__", BASE=str(B), ON_KAGGLE=False, wb=wb, ctt=ctt, os=os, SCRIPTS=str(B / "scripts"),
         APP_VERSION=wb.__version__, SCRIPTS_OK=(wb.__version__,), use_cvat=lambda *a: None, CLIENT=None,
         cvat_client=lambda *a: None, CVAT_LOGIN_MODE="token", who_am_i=lambda: "tester", SESSION_ID="sess1",
         CVAT_SERVER="app.cvat.ai", CVAT_SCOPE={}, AA_CONF=0.25, IMGSZ=1920, NAME="m1",
         drive_pull=lambda *a, **k: None, drive_push=lambda *a, **k: None, kg_file_index=lambda *a: None, uld_index=lambda: {},
         VIDEOS=str(B / "videos"), REGISTRY=str(B / "task_registry.csv"), _KG={}, TASKS_DIR=str(B / "tasks"))
exec(compile(partA, "cell30A", "exec"), G)

LOG, LOCK = [], threading.Lock()
def fake_rl_run(r):
    k = r["kind"]
    with LOCK:
        LOG.append(("AA", r["id"], k, round(time.time(), 2), G["_W"]["lc_gpu"]))
    if k not in G["_RL_LIGHT"]:
        time.sleep(0.6)
    G["_rl_status"](r, "done", done_at=ctt.now())
def fake_lc_do(kind):
    with LOCK:
        LOG.append(("LC", kind, kind, round(time.time(), 2), G["_W"]["lc_gpu"], len(G["_rl_running"]("gpu"))))
    time.sleep(0.3)
    for r in wb.list_requests(str(B)):
        if r["kind"] == kind and r["status"] == "pending":
            wb.set_status(str(B), r, "done", result="시험", done_at=ctt.now(), by="tester")
G.update(_rl_run=fake_rl_run, _lc_do=fake_lc_do, _rl_refresh=lambda force=False: None, _rl_state=lambda force=False: None,
         _lc_state=lambda force=False: None, _lc_waiting=lambda: None)
t0 = time.time()
exec(compile(partB, "cell30B", "exec"), G)
t_loop = time.time() - t0; print(f"(돌기 {t_loop:.1f}초)")
for l in LOG:
    print("   ", l)
aa = sorted(l[1] for l in LOG if l[0] == "AA")
check(aa == ["RG1", "RG2"], f"재처리: kaggle_gpu 배정만 받음 (colab·배정 없음은 안 받음): {aa}")
lc = [l for l in LOG if l[0] == "LC"]
check([l[1] for l in lc] == ["train"], f"LC: 학습만 (backup은 CPU 마스터 몫): {[l[1] for l in lc]}")
check(lc and lc[0][4] == 2 and lc[0][5] == 0, f"학습은 GPU 줄 2개를 모두 맡고, 재처리 GPU 일이 모두 끝난 뒤 시작 (맡은 줄 {lc[0][4] if lc else None}, 돌던 일 {lc[0][5] if lc else None})")
st = {r["id"]: r["status"] for r in rb.list_requests(str(B)) + wb.list_requests(str(B))}
check(st["RC1"] == "pending" and st["RN1"] == "pending" and st["LB1"] == "pending", f"다른 몫은 그대로 대기: {st}")
check((B / "web/worker_gpu.json").exists() and (B / "relabel/WORKER_gpu.json").exists() and not (B / "web/worker.json").exists(),
      "GPU 워커는 worker_gpu.json에 기록 (30번 셀의 worker.json을 건드리지 않음)")
check(list((B / "jobs").glob("DONE_*.json")), "끝날 때 jobs/DONE_<세션>.json (CPU 마스터가 상태를 새로 만듦)")
check(t_loop < 25, f"할 일이 없어 스스로 끝남 ({t_loop:.1f}초)")
check(not (B / "relabel/state.json").exists() and not (B / "relabel/tracked.json").exists() and not (B / "jobs/STATE_OWNER.json").exists(),
      "v4.32.0: GPU 워커는 취합자를 맡지 않고 상태 파일(state·tracked)을 쓰지 않음")
print("통과" if ok else "실패"); sys.exit(0 if ok else 1)
