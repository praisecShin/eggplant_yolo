"""v4.31.6 30번 통합 작업자 시험: 공정 차례 · LC GPU 맡아 두기 · 한 사람 동시 제한 · 두 앱 요청을 한 셀에서
사용: python test_worker30.py <패키지의 drive 폴더>   (가짜 Drive 폴더 + 가짜 CVAT · torch·IPython 없이)"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest   # v4.31.12 (R13)
import json, os, shutil, sys, time, types, datetime, threading, glob
from pathlib import Path
PKG = Path(sys.argv[1]).resolve()
T = Path(__file__).resolve().parent / "_work_w30"; shutil.rmtree(T, ignore_errors=True); B = T / "base"; B.mkdir(parents=True)
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

# ---- 2) 30번 셀 실행
for sub in ("requests", "relabel/requests"):
    (B / sub).mkdir(parents=True, exist_ok=True)
req("relabel/requests", "RA1", "shape", [1], "A", ago(300))     # A의 밀린 재처리 3건
req("relabel/requests", "RA2", "shape", [2], "A", ago(290))
req("relabel/requests", "RA3", "shape", [3], "A", ago(280))
req("relabel/requests", "RB1", "shape", [4], "B", ago(1))       # B의 새 요청 → A의 두 번째보다 먼저
req("relabel/requests", "RB0", "refresh", [], "B", ago(0))
req("requests", "LB1", "backup", [10], "B", ago(2))             # LC
req("requests", "LA1", "track", [11], "A", ago(30))             # LC GPU 일

nb = json.load(open(latest(PKG / "notebooks" / "A0_colab", "eggplant_yolo_colab")))
src = "".join(nb["cells"][54]["source"])
assert src.startswith("# 30. 작업자"), src[:40]
cut = src.index("# ---------- 돌기 (v4.31.6)")
partA, partB = src[:cut], src[cut:]
partA = partA.replace("RL_GPU_WORKERS = 2 ", "RL_GPU_WORKERS = 1 ", 1).replace("W_MAX_LOOPS  = None", "W_MAX_LOOPS  = 150", 1)
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
print(f"(돌기 {time.time() - t0:.1f}초)")
for l in LOG:
    print("   ", l)
aa = [l[1] for l in LOG if l[0] == "AA"]
check(aa[:1] == ["RB0"], f"가벼운 일(새로 고침) 먼저: {aa[:1]}")
check("RB1" in aa and aa.index("RB1") < aa.index("RA2"), f"B의 새 요청이 A의 밀린 두 번째보다 먼저: {aa}")
check(set(aa) == {"RB0", "RA1", "RA2", "RA3", "RB1"}, "재처리 요청 모두 처리")
lc = [l for l in LOG if l[0] == "LC"]
check([l[1] for l in lc] == ["track", "backup"] or [l[1] for l in lc] == ["backup", "track"], f"LC 요청 두 종류 모두 실행: {[l[1] for l in lc]}")
tr = [l for l in lc if l[1] == "track"]
check(tr and tr[0][4] == 1 and tr[0][5] == 0, f"LC track은 GPU 줄을 맡아 두고 빈 뒤에 시작 (lc_gpu={tr[0][4] if tr else None}, 재처리 GPU 일 {tr[0][5] if tr else None})")
bk = [l for l in lc if l[1] == "backup"]
check(bk and not bk[0][4], "LC backup은 GPU를 맡지 않음")
# LC track 실행 중에 재처리 GPU 일이 새로 시작되지 않음
if tr:
    t_tr = tr[0][3]
    started = [l for l in LOG if l[0] == "AA" and l[2] == "shape" and t_tr <= l[3] < t_tr + 0.3]
    check(not started, f"LC GPU 일 동안 재처리 shape는 새로 시작하지 않음: {started}")
left = [r["id"] for r in rb.list_requests(str(B)) + wb.list_requests(str(B)) if r["status"] != "done"]
check(not left, f"남은 요청 없음: {left}")
check(json.loads((B / "web/worker.json").read_text()).get("stopping") is True, "LC 작업자 '꺼짐' 기록 (web/worker.json)")
check(json.loads((B / "relabel/WORKER.json").read_text()).get("stopping") is True, "재처리 작업자 '꺼짐' 기록 (relabel/WORKER.json)")
print("통과" if ok else "실패"); sys.exit(0 if ok else 1)
