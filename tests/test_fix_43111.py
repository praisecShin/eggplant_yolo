"""v4.31.11 시험: R6(GPU 워커 생존·쓰기 직전 재확인) · R7(누적 결과로 최종 상태) · R8(CVAT_TOKEN 없으면 멈춤) · R9(실패·기한 초과 track도 GPU 깨움) · R10(경로 없는 최신은 실패)"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest   # v4.31.12 (R13)
import fnmatch, json, os, shutil, sys, time, types
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_43111"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t43111", KAGGLE_BASE=str(B))
for k in ("KAGGLE_KERNEL_RUN_TYPE", "RCLONE_CONF", "CVAT_TOKEN", "KAGGLE_KEY", "RCLONE_CONFIG", "KAGGLE_CONFIG_DIR"):
    os.environ.pop(k, None)
import web_bridge as wb, relabel_bridge as rb
ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)
def put(rel, text):
    p = B / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); return p

# R10
check(wb.backup_verdict(B, [{"task_id": 8, "backup_state": "최신", "last_file": ""}], [8]) == ([], [], ["8"]), "경로가 없는 '최신'은 받음이 아님")
# R7 도우미
check(wb.failed_results([{"task_id": 1, "status": "실패"}, {"task_id": 2, "status": "받음"}, {"task_id": 3, "status": "포기 (준비 안 됨)"}]) == ["1", "3"], "누적 실패·포기 찾기")

sys.path.insert(0, str(PKG / "notebooks" / "K_kaggle"))
import kaggle_cpu_master as m
m.BASE = B
m._remote = lambda rel="": str(B / rel)
WRITES = []
def _rc(*a, **k):
    a = list(a); out = ""
    if a[0] == "lsf":
        inc = a[a.index("--include") + 1] if "--include" in a else "*"
        d = Path(a[-1]); out = "\n".join(sorted(f.name for f in d.glob("*") if f.is_file() and fnmatch.fnmatch(f.name, inc))) if d.is_dir() else ""
    elif a[0] == "copyto" and Path(a[1]).is_file() and Path(a[1]) != Path(a[2]):
        Path(a[2]).parent.mkdir(parents=True, exist_ok=True); shutil.copy(a[1], a[2])
    return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
m.rclone = _rc
m.push_req = lambda a, b, sub, **k: WRITES.append(b["id"])
def req(rid, kind, rem, results=None, wt=None, host=""):
    p = B / "relabel/requests" / f"REQ_{rid}__{kind}__waiting.json"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": rid, "kind": kind, "status": "waiting", "task_ids": rem, "remaining": rem, "waiting_t": wt or time.time(),
                             "created": "2026-11-13T00:00:00Z", "results": results or [], "taken_host": host, "history": []}, ensure_ascii=False), encoding="utf-8")
put("backups/pending_backups.csv", "request_time,server,task_id,task_name,status\n")
put("backups/x/2.zip", "z")
ROWS = [{"task_id": 2, "backup_state": "최신", "last_file": "backups/x/2.zip"}]
def fake_run(ctt, wb_, rq):
    m._STATE["last_backup_rows"] = ROWS
m.run_cpu_backup_and_export = fake_run

# R7: 앞 회차 실패 + 이번 받음 → 실패
req("B7", "backup", [2], results=[{"task_id": "1", "status": "실패"}, {"task_id": "2", "status": "받는 중"}])
m._peer = lambda rel, sess: None
m._STATE.update(aa_peer=None, aa_gpu_peer=None, bk_poll_t=0)
m.poll_waiting_backups(None, wb, rb)
st = {r["id"]: r for r in rb.list_requests(B)}
check(st["B7"]["status"] == "failed", f"앞서 실패한 TASK가 있으면 마지막에 받아도 실패 ({st['B7']['status']})")

# R6-a: GPU 워커가 살아 있으면 손대지 않음
for f in (B / "relabel/requests").glob("*"): f.unlink()
req("B6", "backup", [2]); WRITES.clear()
m._peer = lambda rel, sess: {"x": 1} if rel == "relabel/WORKER_gpu.json" else None
m.send_heartbeat_once.__globals__["_STATE"]["aa_gpu_peer"] = {"x": 1}
m._STATE.update(bk_poll_t=0)
m.poll_waiting_backups(None, wb, rb)
check(not WRITES and {r["id"]: r for r in rb.list_requests(B)}["B6"]["status"] == "waiting", "GPU 워커(WORKER_gpu.json)가 살아 있으면 마스터가 받지 않음")
# R6-b: 받는 사이 다른 작업자가 요청을 바꿈 → 쓰지 않음
m._peer = lambda rel, sess: None
m._STATE.update(aa_peer=None, aa_gpu_peer=None, bk_poll_t=0)
def run_and_change(ctt, wb_, rq):
    m._STATE["last_backup_rows"] = ROWS
    p = next((B / "relabel/requests").glob("REQ_B6__*")); d = json.loads(p.read_text(encoding="utf-8"))
    d["history"] = [{"status": "failed"}]; d["status"] = "failed"; p.unlink()
    (B / "relabel/requests/REQ_B6__backup__failed.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
m.run_cpu_backup_and_export = run_and_change
m.poll_waiting_backups(None, wb, rb)
check(not WRITES and {r["id"]: r for r in rb.list_requests(B)}["B6"]["status"] == "failed", "받는 사이 다른 작업자가 바꾼 요청은 덮어쓰지 않음")
m.run_cpu_backup_and_export = fake_run

# R9: 실패·기한 초과만 남은 GPU track도 깨움
for f in (B / "relabel/requests").glob("*"): f.unlink()
put("backup_status.csv", "task_id,backup_state,last_file\n")
req("T9", "track", [9], host="kaggle_gpu")
check(m.gpu_pending(wb, rb) == 1, "백업이 실패한 TASK만 남은 GPU track → GPU 워커를 깨움")
for f in (B / "relabel/requests").glob("*"): f.unlink()
put("backups/pending_backups.csv", "request_time,server,task_id,task_name,status\n2026-11-13,s,9,b,준비 중\n")
req("T9", "track", [9], host="kaggle_gpu", wt=time.time() - 3600)
check(m.gpu_pending(wb, rb) == 0, "아직 준비 중(기한 안)이면 깨우지 않음")
for f in (B / "relabel/requests").glob("*"): f.unlink()
req("T9", "track", [9], host="kaggle_gpu", wt=time.time() - 7 * 3600)
check(m.gpu_pending(wb, rb) == 1, "기한(6시간)이 지난 준비 중 → 깨워 포기로 마무리")

# R8
fake = types.ModuleType("kaggle_secrets")
class _C:
    def get_secret(self, n):
        if n == "RCLONE_CONF": return "[gdrive]\ntype = drive\n"
        raise KeyError(n)
fake.UserSecretsClient = _C; sys.modules["kaggle_secrets"] = fake
os.environ.update(KAGGLE_KERNEL_RUN_TYPE="Interactive", CVAT_TOKEN="old-env-token", HOME=str(T))
try:
    m.setup_credentials(); raised = False
except RuntimeError:
    raised = True
check(raised and "CVAT_TOKEN" not in os.environ, "Kaggle에서 CVAT_TOKEN 비밀이 없으면 멈추고 환경 값을 쓰지 않음")
os.environ.pop("KAGGLE_KERNEL_RUN_TYPE", None)

# 30번 셀
nb = json.load(open(latest(PKG / "notebooks" / "A0_colab", "eggplant_yolo_colab"), encoding="utf-8"))
c30 = next("".join(c["source"]) for c in nb["cells"] if "".join(c["source"]).startswith("# 30."))
check("_fail = wb.failed_results(res)" in c30 and "'failed' if lost else 'done'" not in c30, "30번: 누적 결과로 최종 상태")
print("RESULT", ok); sys.exit(0 if ok else 1)
