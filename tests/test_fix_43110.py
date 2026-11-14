"""v4.31.10 시험: R1(백업 판정 공용 — 열린 요청이 없어진 것만으로 받음 아님) · R2(보안 비밀·설정 파일) · R3(0번 셀 이름 겹침) · R4(마스터가 받는 중 백업 받기) · R5(13번 0건 멈춤)"""
import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest   # v4.31.12 (R13)
import ast, json, os, shutil, stat, sys, types
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_43110"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t43110", KAGGLE_BASE=str(B))
import web_bridge as wb, relabel_bridge as rb
ok = True
def check(c, m):
    global ok; print(("✅ " if c else "❌ ") + m); ok &= bool(c)
def put(rel, text):
    p = B / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8"); return p

# ---- R1: 공용 판정
put("backups/pending_backups.csv", "request_time,server,task_id,task_name,status\n2026-11-13,app.cvat.ai,2,b,준비 중\n2026-11-13,other.cvat,5,e,준비 중\n")
put("backups/x/1.zip", "z")
rows = [{"task_id": 1, "backup_state": "최신", "last_file": "backups/x/1.zip"},
        {"task_id": 3, "backup_state": "백업 필요"},                       # 열린 요청은 없어졌지만 받지 못함
        {"task_id": 4, "backup_state": "최신", "last_file": "backups/x/4.zip"},   # 파일이 없음
        {"task_id": 6, "backup_state": "최신"}]
r = wb.backup_verdict(B, rows, [1, 2, 3, 4, 5, 6, 7], server="app.cvat.ai")
check(r == (["1"], ["2"], ["3", "4", "5", "6", "7"]), f"판정: 받음·받는 중·실패 (다른 서버 요청은 이 서버 것이 아님 · v4.31.11: 경로 없는 최신도 실패) {r}")

# ---- R3: 0번 셀에서 만든 함수 이름을 다른 셀 맨 바깥에서 값으로 덮지 않음
nb = json.load(open(latest(PKG / "notebooks", "eggplant_yolo_colab"), encoding="utf-8"))
def tree(src):
    src = "\n".join("" if l.lstrip().startswith(("!", "%")) else l for l in src.splitlines())
    return ast.parse(src)
code = [("".join(c["source"])) for c in nb["cells"] if c["cell_type"] == "code"]
funcs = {n.name for n in tree(code[0]).body if isinstance(n, ast.FunctionDef)}
def top_assigns(t):
    out = set()
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For)):
            for tg in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                out |= {x.id for x in ast.walk(tg) if isinstance(x, ast.Name)}
    # 함수 안 지역 변수는 빼기
    inner = set()
    for f in [n for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for n in ast.walk(f):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                inner.add(n.id)
    top = {x.id for n in t.body for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)
           and not any(isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)) for p in [n])}
    return out & top
clash = {i: sorted(funcs & top_assigns(tree(s))) for i, s in enumerate(code)}
clash = {i: v for i, v in clash.items() if v}
check(not clash, f"0번 셀 함수 이름이 셀 맨 바깥 값으로 덮이지 않음 {clash}")
check("_need_secret(" in code[0] and "def _need(" not in code[0], "보안 비밀 확인 함수 이름 = _need_secret")

# ---- R5: 13번 사전 검색 0건이면 멈춤
c13 = next(s for s in code if s.startswith("# 13."))
check("if not _bk_ids:" in c13 and "raise SystemExit" in c13 and "] or None\n    BK_QUERY = ''" not in c13, "13번: 검색 0건이면 멈춤 (전체로 넓어지지 않음)")
c30 = next(s for s in code if s.startswith("# 30."))
check("wb.backup_verdict(BASE, _RL.get('bk_rows'), need, server=CVAT_SERVER)" in c30 and "left_all" not in c30, "30번: 받는 중 판정을 공용 기준으로")

# ---- R2: CPU 마스터 보안 비밀
sys.path.insert(0, str(PKG / "notebooks"))
import kaggle_cpu_master as m
m.BASE = B
H = T / "home"; H.mkdir(); os.environ["HOME"] = str(H)
for k in ("RCLONE_CONFIG", "KAGGLE_CONFIG_DIR", "KAGGLE_KERNEL_RUN_TYPE"):
    os.environ.pop(k, None)
fake = types.ModuleType("kaggle_secrets")
SEC = {"RCLONE_CONF": "[gdrive]\ntype = drive\ntoken = {\"a\":1}\n", "CVAT_TOKEN": "sek", "KAGGLE_USERNAME": "u1", "KAGGLE_KEY": "kk"}
class _C:
    def get_secret(self, n):
        if n not in SEC: raise KeyError(n)
        return SEC[n]
fake.UserSecretsClient = _C; sys.modules["kaggle_secrets"] = fake
os.environ.update(KAGGLE_KERNEL_RUN_TYPE="Interactive", RCLONE_CONF="[evil]\ntype = local\n", CVAT_TOKEN="env-should-not-win", KAGGLE_KEY="envkey")
m.setup_credentials()
rc = Path(os.environ["RCLONE_CONFIG"]); kj = Path(os.environ["KAGGLE_CONFIG_DIR"]) / "kaggle.json"
check(rc.is_file() and "[gdrive]" in rc.read_text() and "evil" not in rc.read_text(), "Kaggle: 환경 변수가 아니라 Kaggle 보안 비밀을 읽음")
check(os.environ["CVAT_TOKEN"] == "sek", "CVAT_TOKEN도 보안 비밀 값")
check(stat.S_IMODE(rc.stat().st_mode) == 0o600 and stat.S_IMODE(kj.stat().st_mode) == 0o600, "설정 파일 권한 0600")
check(not (H / ".config/rclone/rclone.conf").exists() and not (H / ".kaggle/kaggle.json").exists() and str(H) not in str(rc), "홈 폴더에 쓰지 않음 (세션 임시 폴더)")
check(json.loads(kj.read_text()) == {"username": "u1", "key": "kk"}, "kaggle.json = 보안 비밀 값")
for k in ("KAGGLE_KERNEL_RUN_TYPE", "RCLONE_CONF", "CVAT_TOKEN", "KAGGLE_KEY"):
    os.environ.pop(k, None)

# ---- R4: 받는 중 AA 백업을 마스터가 받음
def req(rid, kind, rem, wt):
    p = B / "relabel/requests" / f"REQ_{rid}__{kind}__waiting.json"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": rid, "kind": kind, "status": "waiting", "task_ids": rem, "remaining": rem, "waiting_t": wt,
                             "created": "2026-11-13T00:00:00Z", "results": []}, ensure_ascii=False), encoding="utf-8")
import time as _t
req("B1", "backup", [1, 3], _t.time()); req("B2", "backup", [2], _t.time()); req("T1", "track", [1], _t.time())
put("backups/pending_backups.csv", "request_time,server,task_id,task_name,status\n2026-11-13,app.cvat.ai,2,b,준비 중\n")
CALLS = []
import fnmatch
m._remote = lambda rel="": str(B / rel)
def _rc(*a, **k):
    a = list(a); out = ""
    if a[0] == "lsf":
        inc = a[a.index("--include") + 1] if "--include" in a else "*"
        d = Path(a[-1]); out = "\n".join(sorted(f.name for f in d.glob("*") if f.is_file() and fnmatch.fnmatch(f.name, inc))) if d.is_dir() else ""
    elif a[0] == "copyto" and Path(a[1]).is_file() and Path(a[1]) != Path(a[2]):
        Path(a[2]).parent.mkdir(parents=True, exist_ok=True); shutil.copy(a[1], a[2])
    return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
m.rclone = _rc
m._peer = lambda rel, sess: None
def fake_run(ctt, wb_, rq):
    CALLS.append(rq); m._STATE["last_backup_rows"] = rows
m.run_cpu_backup_and_export = fake_run
m._STATE.update(aa_peer=None, bk_poll_t=0)
m.push_req = lambda a, b, sub, **k: None
n = m.poll_waiting_backups(None, wb, rb)
check(CALLS and CALLS[0]["params"]["mode"] == "download" and sorted(CALLS[0]["task_ids"]) == [1, 2, 3], f"받는 중 TASK를 '받기'로 확인 {CALLS[:1]}")
st = {r["id"]: r for r in rb.list_requests(B)}
check(st["B1"]["status"] == "failed" and {x["task_id"]: x["status"] for x in st["B1"]["results"]} == {"1": "받음", "3": "실패"},
      f"B1: 1 받음 · 3 실패 → 끝남 ({st['B1']['status']}, {st['B1'].get('results')})")
check(st["B2"]["status"] == "waiting", "B2: 아직 준비 중 → 받는 중 그대로")
check(st["T1"]["status"] == "waiting", "track 요청은 손대지 않음 (GPU 워커가 마저 함)")
m._STATE["aa_peer"] = {"x": 1}; m._STATE["bk_poll_t"] = 0; CALLS.clear()
m._peer = lambda rel, sess: {"x": 1} if rel == "relabel/WORKER.json" else None
m.poll_waiting_backups(None, wb, rb)
check(not CALLS, "30번 셀 작업자가 살아 있으면 마스터는 받지 않음")
print("RESULT", ok); sys.exit(0 if ok else 1)
