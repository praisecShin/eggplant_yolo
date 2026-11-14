"""v4.31.12 시험: R11(TASK 기록 통째 올리기 없앰) · R12(실패만 남은 track 마무리에 모델 불필요 · 오류도 실패로) · R13(시험 노트북 고르기)"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest
import ast, fnmatch, json, os, shutil, sys, time, traceback, types
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_43112"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; D = T / "drive"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t43112", KAGGLE_BASE=str(B))
for k in ("KAGGLE_KERNEL_RUN_TYPE", "CVAT_TOKEN"):
    os.environ.pop(k, None)
import web_bridge as wb, relabel_bridge as rb
ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

# ---- R13
N = T / "nbs"; N.mkdir(parents=True)
for v in ("4.31.9", "4.31.12", "4.31.10", "4.31.11"):
    (N / f"eggplant_yolo_colab_v{v}.ipynb").write_text("{}")
check(latest(N, "eggplant_yolo_colab").name == "eggplant_yolo_colab_v4.31.12.ipynb", "버전 번호로 가장 새 노트북 (4.31.12 > 4.31.9)")

# ---- R11: Drive(D)와 로컬(B)을 따로 두고, 받는 사이 Drive의 다른 TASK 기록이 바뀌어도 덮지 않음
sys.path.insert(0, str(PKG / "notebooks"))
import kaggle_cpu_master as m
m.BASE = B
m._remote = lambda rel="": str(D / rel)
def _rc(*a, **k):
    a = list(a); out = ""
    if a[0] == "lsf":
        inc = a[a.index("--include") + 1] if "--include" in a else "*"
        d = Path(a[-1]); out = "\n".join(sorted(f.name for f in d.glob("*") if f.is_file() and fnmatch.fnmatch(f.name, inc))) if d.is_dir() else ""
    elif a[0] == "copyto" and Path(a[1]).is_file():
        Path(a[2]).parent.mkdir(parents=True, exist_ok=True); shutil.copy(a[1], a[2])
    elif a[0] == "copy" and Path(a[1]).is_dir():
        shutil.copytree(a[1], a[2], dirs_exist_ok=True)
    return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
m.rclone = _rc
m.push_req = lambda a, b, sub, **k: (_rc("copyto", b["_path"], str(D / sub / Path(b["_path"]).name)),
                                [Path(D / sub / Path(x).name).unlink(missing_ok=True) for x in [a.get("_path")] if x and Path(x).name != Path(b["_path"]).name])
m._peer = lambda rel, sess: None
m._STATE.update(aa_peer=None, aa_gpu_peer=None, bk_poll_t=0)
def jw(p, o):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
req = {"id": "B1", "kind": "backup", "status": "waiting", "task_ids": [2], "remaining": [2], "waiting_t": time.time(),
       "created": "2026-11-13T00:00:00Z", "results": [], "history": []}
jw(B / "relabel/requests/REQ_B1__backup__waiting.json", req); jw(D / "relabel/requests/REQ_B1__backup__waiting.json", req)
jw(B / "relabel/tasks/9.json", {"history": [{"note": "옛 로컬"}], "track_pending": None})          # CPU에 남은 오래된 사본
jw(D / "relabel/tasks/9.json", {"history": [{"note": "옛 로컬"}, {"note": "GPU 새 기록"}], "track_pending": {"xml": "t.xml"}})
jw(D / "relabel/tasks/2.json", {"history": [{"note": "Drive의 2번 기록"}], "track_pending": None})
(B / "backups/x").mkdir(parents=True); (B / "backups/x/2.zip").write_text("z")
(B / "backups/pending_backups.csv").write_text("request_time,server,task_id,task_name,status\n", encoding="utf-8")
def fake_run(ctt, wb_, rq):
    m._STATE["last_backup_rows"] = [{"task_id": 2, "backup_state": "최신", "last_file": "backups/x/2.zip"}]
m.run_cpu_backup_and_export = fake_run
m.poll_waiting_backups(None, wb, rb)
d9 = json.loads((D / "relabel/tasks/9.json").read_text(encoding="utf-8"))
d2 = json.loads((D / "relabel/tasks/2.json").read_text(encoding="utf-8"))
check(len(d9["history"]) == 2 and d9["track_pending"], "다른 TASK(9) 기록은 Drive 최신본 그대로 (통째로 올리지 않음)")
check([h.get("note") for h in d2["history"]][:1] == ["Drive의 2번 기록"] and d2["history"][-1].get("status") == "받음", "받은 TASK(2) 기록은 Drive 최신본에 이어 씀")
check(next((D / "relabel/requests").glob("REQ_B1__*")).name == "REQ_B1__backup__done.json", "요청은 끝남")
# 건너뛸 때는 기록도 올리지 않음
jw(D / "relabel/tasks/2.json", {"history": [{"note": "다시"}], "track_pending": None})
for f in (B / "relabel/requests").glob("*"): f.unlink()
for f in (D / "relabel/requests").glob("*"): f.unlink()
jw(B / "relabel/requests/REQ_B2__backup__waiting.json", {**req, "id": "B2"})
jw(D / "relabel/requests/REQ_B2__backup__waiting.json", {**req, "id": "B2", "history": [{"status": "x"}]})   # Drive 쪽이 바뀜
m._STATE["bk_poll_t"] = 0
m.poll_waiting_backups(None, wb, rb)
check(json.loads((D / "relabel/tasks/2.json").read_text(encoding="utf-8"))["history"] == [{"note": "다시"}], "요청이 바뀌어 건너뛰면 TASK 기록도 올리지 않음")

# ---- R12: 30번 셀 _rl_track_resume을 떼어 내 실행
nb = json.load(open(latest(PKG / "notebooks", "eggplant_yolo_colab"), encoding="utf-8"))
c30 = next("".join(c["source"]) for c in nb["cells"] if "".join(c["source"]).startswith("# 30."))
src = "\n".join("" if l.lstrip().startswith(("!", "%")) else l for l in c30.splitlines())
fns = {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
def run(info, req, model_ok):
    st = {"req": dict(req)}
    ns = {"_RL": {"ready": {"R": info}, "dirty": False}, "traceback": traceback, "AA_CONF": 0.25,
          "ctt": types.SimpleNamespace(now=lambda: "2026-11-13 23:00", api_error=lambda e: str(e)),
          "_rl_req": lambda rid: st["req"], "_rl_ids": lambda r, k="task_ids": [int(x) for x in r.get(k) or []],
          "_rl_lane": lambda *a: None, "_rl_short": lambda x: str(x or "")[:80], "_rl_res": lambda rows: rows,
          "_rl_track_one": lambda t, *a: {"task_id": t, "status": "완료"}}
    def _model(_):
        if not model_ok: raise RuntimeError("모델 없음")
        return "m.pt", "m"
    def _status(r, s, **f):
        st["req"] = {**r, **f, "status": s}
    ns.update(_rl_model=_model, _rl_status=_status)
    exec(fns["_rl_merge"], ns); exec(fns["_rl_track_resume"], ns)
    out = ns["_rl_track_resume"]("R")
    return out, st["req"], ns["_RL"]["ready"]
base = {"id": "R", "status": "waiting", "remaining": [9], "results": [], "result": "", "params": {}}
out, r, ready = run({"got": [], "gave_up": [9]}, base, model_ok=False)
check(r["status"] == "failed" and not ready, f"실패만 남은 track: 모델이 없어도 실패로 끝남 ({r['status']})")
out, r, ready = run({"got": [9], "gave_up": []}, base, model_ok=False)
check(r["status"] == "failed" and "마무리 실패" in r["result"] and not ready, f"마무리 중 오류(모델 없음)도 실패로 기록 ({r['status']})")
out, r, ready = run({"got": [9], "gave_up": []}, base, model_ok=True)
check(r["status"] == "done", "모델이 있으면 정상 완료")
print("RESULT", ok); sys.exit(0 if ok else 1)
