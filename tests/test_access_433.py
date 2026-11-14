"""v4.33 실행 권한·쓰기 제한 시험 (access.py) — 설계 7판.
실행: python3 tests/test_access_433.py drive
"""
import json, os, shutil, sys, tempfile
from pathlib import Path
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
import access as X

ok = True
def check(c, msg):
    global ok; print(("✅ " if c else "❌ ") + msg); ok &= bool(c)

def raises(fn, exc=X.AccessError):
    try:
        fn()
    except exc:
        return True
    except Exception as e:
        print("   (다른 예외)", type(e).__name__, e)
        return False
    return False

T = Path(tempfile.mkdtemp(prefix="acc433_"))
BASE = T / "base"; OUT = BASE / "analysis/M1/20261114_s1"; TMP = T / "tmp"
for d in (BASE, OUT, TMP):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 모드
os.environ.pop(X.MODE_VAR, None)
check(X.mode() == "analysis", "기본 모드는 분석")
os.environ[X.MODE_VAR] = "cli"
check(X.mode() == "invalid", "12번 셀의 RUN_MODE='cli' 같은 모르는 값 → invalid (이름도 EGG_ACCESS로 분리)")
os.environ.pop(X.MODE_VAR)
check(raises(lambda: X.executing(X.ExecContext("r", "s", "d")).__enter__()), "분석 모드에서는 실행 컨텍스트를 받을 수 없음")

# ---------------------------------------------------------------- CVAT 감싸기
class FakeTask:
    id = 7; name = "t_uld"; size = 10
    def get_frames_info(self): return [1, 2]
    def import_annotations(self, *a): raise AssertionError("불리면 안 됨")
    def remove_annotations(self): raise AssertionError("불리면 안 됨")
    def update(self, *a): raise AssertionError("불리면 안 됨")
    def export_dataset(self, *a, **k): return "zip"
class FakeTasks:
    def retrieve(self, i): return FakeTask()
    def list(self): return [FakeTask(), FakeTask()]
    def create_from_data(self, *a): raise AssertionError("불리면 안 됨")
class FakeUsers:
    def retrieve_self(self): return ({"username": "u"}, None)
class FakeApi:
    users_api = FakeUsers()
    def call_api(self, path, method, *a, **k): return "CALLED " + method
class FakeClient:
    tasks = FakeTasks()
    api_client = FakeApi()
    organization_slug = None

made = []
fac = X.CvatFactory(lambda: made.append(1) or FakeClient())
cl = fac.client()
t = cl.tasks.retrieve(7)
check(t.get_frames_info() == [1, 2] and t.name == "t_uld", "분석 모드: 읽기 호출은 통과")
check(t.export_dataset("x") == "zip", "분석 모드: 참조용 export는 허용")
check(len(list(cl.tasks.list())) == 2, "분석 모드: 목록 반복 통과")
elems = cl.tasks.list()
check(all(isinstance(e, X.ReadOnlyProxy) for e in elems), "목록 안의 TASK 객체도 감쌈 (M2)")
check(raises(lambda: elems[0].update({"name": "x"})), "목록 요소로도 TASK 바꾸기 거절 (M2)")
check(raises(lambda: cl.api_client.call_api("/tasks/7", "DELETE")), "범용 call_api(DELETE 등) 거절 (M2)")
check(cl.api_client.users_api.retrieve_self()[0]["username"] == "u", "접속 확인(users_api.retrieve_self)은 허용")
cl.organization_slug = "org1"
check(fac._raw.organization_slug == "org1", "조직 선택(client 로컬 설정)은 허용")
check(raises(lambda: t.import_annotations("a")), "분석 모드: import_annotations 거절")
check(raises(lambda: t.remove_annotations()), "분석 모드: remove_annotations 거절")
check(raises(lambda: t.update({"name": "x"})), "분석 모드: TASK 이름 바꾸기(update) 거절")
check(raises(lambda: cl.tasks.create_from_data()), "분석 모드: 새 TASK 만들기 거절")
check(raises(lambda: setattr(t, "name", "x")), "분석 모드: 객체 속성 바꾸기 거절")
check(not fac.raw_session_allowed(), "분석 모드: 백업 스크립트의 자체 세션 불가")
os.environ[X.MODE_VAR] = "invalid!"
check(raises(lambda: fac.client()), "모드 값이 잘못되면 접속 자체를 거절")
os.environ[X.MODE_VAR] = "exec"
check(isinstance(fac.client(), X.ReadOnlyProxy), "실행기라도 실행 컨텍스트 밖에서는 읽기 전용")
with X.executing(X.ExecContext("r1", "E1", "d1", resources=("tasks/7/",), tasks=("7",))):
    check(isinstance(fac.client(), FakeClient) and fac.raw_session_allowed(), "실행 컨텍스트 안에서만 원시 client")
check(X.current() is None and isinstance(fac.client(), X.ReadOnlyProxy), "컨텍스트가 끝나면(finally) 권한을 거둠")
try:
    with X.executing(X.ExecContext("r1", "E1", "d1")):
        raise ValueError("중간 오류")
except ValueError:
    pass
check(X.current() is None, "예외로 끝나도 권한을 거둠")
os.environ.pop(X.MODE_VAR)

# ---------------------------------------------------------------- 저장 도우미
sv = X.Saver(X.Paths(BASE, OUT, TMP), person="M1")
p = sv.write_json(sv.out("stats/a.json"), {"n": 1})
check(p.exists() and str(p).startswith(str(OUT)), "분석 결과는 분석 폴더에 씀")
check(raises(lambda: sv.write_json(BASE / "web/label_stats.json", {})), "분석 모드: 공유 상태 파일 쓰기 거절 (4번 셀 캐시 같은 경우)")
check(raises(lambda: sv.write_json(BASE / "logs/versions.csv", {})), "분석 모드: 0번 셀 시작 로그 공용 쓰기 거절")
check(raises(lambda: sv.write_json(T / "elsewhere.json", {})), "공유 폴더·분석 폴더 밖 쓰기 거절")
check(sv.write_json(BASE / "requests/REQ_x__track__pending.json", {}, narrow=True).exists(), "좁은 예외: 요청 만들기는 허용")
check(sv.write_json(BASE / "jobs/signals/cancel__M1__1.json", {}, narrow=True).exists(), "좁은 예외: 신호 만들기 허용")
check(raises(lambda: sv.write_json(BASE / "runs/m/CURRENT.json", {}, narrow=True)), "좁은 예외로도 채택 표시는 못 씀")
check(raises(lambda: sv.write_json(BASE / "submissions/M2/s/x.json", {}, narrow=True)), "다른 사람 제출본 폴더에는 못 씀")
check(sv.write_json(TMP / "work.json", {}).exists(), "세션 임시 폴더는 허용")
os.environ[X.MODE_VAR] = "exec"
with X.executing(X.ExecContext("r1", "E1", "d1", resources=("tasks/7/", "recovery/7/"))):
    check(sv.write_json(BASE / "tasks/7/log.json", {}).exists(), "실행 컨텍스트의 허가 경로는 씀")
    check(raises(lambda: sv.write_json(BASE / "tasks/8/log.json", {})), "허가받지 않은 TASK 경로는 거절")
os.environ.pop(X.MODE_VAR)

# ---------------------------------------------------------------- 권한 확인 (H1)
class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
clk = Clock()
state = {"ok": (True, ""), "n": 0}
def chk():
    state["n"] += 1
    return state["ok"]
logs = []
sl = X.StepLog(lambda path, d: logs.append((path, d)), "7", "j1", clock=lambda: 0)
au = X.Authority(chk, clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s), step_log=sl)
calls = []
au.call("import", lambda: calls.append("import"))
check(calls == ["import"] and state["n"] == 1, "호출 직전 권한 확인 후 실행")
check([p.split("/")[-1] for p, _ in logs] == ["001_intent.json", "002_result.json"], "단계 기록: 의도 → 결과 (새 파일)")
check(logs[0][0].startswith("recovery/7/j1/steps/"), "단계 기록 위치 recovery/<TASK>/<작업번호>/steps/")
n0 = state["n"]
au.call("rename", lambda: calls.append("rename"))
check(state["n"] == n0 + 1, "호출마다 다시 확인")
# 틈 재확인: 확인 직후 프로세스가 멈췄다 깸
def slow_check():
    state["n"] += 1
    r = state["ok"]
    clk.t += 10           # 확인을 마친 뒤 10초 멈춤
    return r
au2 = X.Authority(slow_check, clock=clk, sleep=lambda s: None)
n0 = state["n"]
state["ok"] = (True, "")
seq = []
def flip_then_call():
    seq.append("called")
# 첫 확인 뒤 10초 멈춤 → 다시 확인. 두 번째 확인 결과를 '잃음'으로 바꿔 호출이 막히는지 본다
class JumpClock:
    """확인을 마친 '뒤'에 멈췄다 깨는 상황: 확인 직후 읽기 한 번 뒤에 시계가 10초 뜀."""
    def __init__(self): self.t, self.arm = 0.0, None
    def __call__(self):
        if self.arm is not None:
            self.arm -= 1
            if self.arm < 0:
                self.t += 10; self.arm = None
        return self.t
jc = JumpClock()
results = iter([(True, ""), (False, "lost")])
def chk2():
    jc.arm = 1
    return next(results)
au3 = X.Authority(chk2, clock=jc, sleep=lambda s: None)
check(raises(lambda: au3.call("import", flip_then_call), X.AuthorityLost) and not seq,
      "확인과 호출 사이 틈이 5초를 넘으면 다시 확인 → 그사이 잃은 권한이면 호출하지 않음")
state["ok"] = (False, "lost")
logs.clear()
au4 = X.Authority(chk, clock=clk, sleep=lambda s: None, step_log=sl)
check(raises(lambda: au4.call("restore", lambda: calls.append("restore")), X.AuthorityLost) and "restore" not in calls,
      "권한을 잃으면 복원도 호출하지 않고 멈춤")
check(logs and logs[-1][1]["kind"] == "lost", "권한 잃음을 단계 기록에 남김")
seqr = iter([(False, "wait_reissue"), (False, "wait_reissue"), (True, "")])
au5 = X.Authority(lambda: next(seqr), clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s))
done = []
au5.call("import", lambda: done.append(1))
check(done == [1], "다시 발급을 기다렸다가 진행")
seqr = iter([(False, "wait_reissue")] * 1000)
au6 = X.Authority(lambda: next(seqr), clock=clk, sleep=lambda s: setattr(clk, "t", clk.t + s), wait_max=30)
check(raises(lambda: au6.call("import", lambda: None), X.AuthorityLost), "다시 발급이 오지 않으면 멈춤")

# 실패한 호출 직후의 복원도 다시 확인 (M4)
st4 = {"n": 0, "ok": (True, "")}
def chk4():
    st4["n"] += 1
    return st4["ok"]
clk4 = Clock()
au7 = X.Authority(chk4, clock=clk4, sleep=lambda s: None)
def failing_upload():
    st4["ok"] = (False, "lost")          # 업로드 중 다른 소유자에게 넘어감
    raise RuntimeError("업로드 실패")
restored = []
try:
    au7.call("upload", failing_upload)
except RuntimeError:
    pass
check(raises(lambda: au7.call("restore", lambda: restored.append(1)), X.AuthorityLost) and not restored and st4["n"] == 2,
      "업로드 실패 직후 복원 호출도 권한을 다시 확인 → 잃었으면 복원하지 않음 (M4)")
# 의도 기록이 느려 그사이 권한을 잃으면 호출하지 않음
st5 = {"ok": (True, "")}
clk5 = Clock()
def slow_writer(path, d):
    if d.get("kind") == "intent":
        clk5.t += 10
        st5["ok"] = (False, "lost")
sl5 = X.StepLog(slow_writer, "7", "j1", clock=lambda: 0)
au8 = X.Authority(lambda: st5["ok"], clock=clk5, sleep=lambda s: None, step_log=sl5)
called = []
check(raises(lambda: au8.call("import", lambda: called.append(1)), X.AuthorityLost) and not called,
      "의도 기록이 느려 틈이 생기면 다시 확인 → 잃었으면 호출하지 않음 (M4)")

# ---------------------------------------------------------------- 제출본 (G7)
src = OUT / "ann.xml"; src.write_text("<ann/>")
FM = X.frame_map_sha([1, 2, 3])
meta = {"task_id": 7, "server": "cvat1", "frames": 120, "labels": ["bud", "fruit"], "mode": "replace", "model": "m1",
        "frame_range": [0, 119], "frame_map_sha": FM}
d = X.freeze_submission(sv, BASE / "submissions", "sub1", [src], meta)
check((d / "_submission.json").exists(), "제출본 고정: submissions/M1/<ID>/")
check(raises(lambda: X.freeze_submission(sv, BASE / "submissions", "sub1", [src], meta)), "같은 제출 ID로 다시 보내면 거절 (새 ID로)")
src.write_text("<changed/>")
local = TMP / "dl"; shutil.copytree(d, local)
info = {"task_id": 7, "server": "cvat1", "frames": 120, "labels": ["fruit", "bud"], "frame_range": [0, 119], "frame_map_sha": FM}
okv, why = X.verify_submission(local, info)
check(okv, "분석 파일을 나중에 바꿔도 제출본은 그대로 → 검증 통과")
check(X.verify_submission(local, dict(info, task_id=8)) == (False, "task_mismatch"), "다른 TASK에 붙인 제출 → 거절")
check(X.verify_submission(local, dict(info, frames=119))[1] == "frames_mismatch", "프레임 수가 다른 TASK → 거절")
check(X.verify_submission(local, dict(info, labels=["bud"]))[1] == "labels_mismatch", "라벨 정의가 바뀐 TASK → 거절")
check(X.verify_submission(local, dict(info, frame_map_sha=X.frame_map_sha([2, 1, 3])))[1] == "frame_map_mismatch",
      "장수는 같고 프레임 대응이 바뀐 TASK → 거절 (M12)")
check(X.verify_submission(local, dict(info, frame_range=[0, 118]))[1] == "frame_range_mismatch", "프레임 범위가 다르면 거절")
(local / "ann.xml").write_text("<tampered/>")
check(X.verify_submission(local, info)[1].startswith("hash_mismatch"), "받은 제출본 바이트가 다르면 거절")
check(raises(lambda: X.freeze_submission(sv, BASE / "submissions", "sub2", [src], {"task_id": 7})), "제출 정보가 빠지면 거절")
check(raises(lambda: X.freeze_submission(sv, BASE / "submissions", "sub3", [src],
                                         {k: v for k, v in meta.items() if k != "frame_map_sha"})), "프레임맵 지문이 빠지면 거절 (M12)")

# ---------------------------------------------------------------- 배포 목록 (K2)
files = {"scripts/arbiter.py": b"x=1\n", "scripts/access.py": b"y=2\n", "notebook_cells.json": b"{}",
         "gpu_worker.ipynb": b"{gpu}", "master.ipynb": b"PLACEHOLDER"}
# 순서: ① 파일 → ② 목록(마스터 노트북 제외) → ③ 노트북에 목록 해시 → ④ Keeper에 노트북 해시
man = X.make_manifest(files, exclude=["master.ipynb"])
man_sha = X.sha256_bytes(man)
nb = b"MANIFEST_SHA=" + man_sha.encode()
keeper_pin = X.sha256_bytes(nb)
check("master.ipynb" not in json.loads(man)["files"] and "manifest.json" not in json.loads(man)["files"],
      "목록에 마스터 노트북·목록 자신이 없음 (순환 없음)")
check(X.sha256_bytes(nb) == keeper_pin and nb.endswith(man_sha.encode()), "정상 배포 순서로 만든 바이트가 사슬 검증을 통과")
m = X.verify_manifest(man, man_sha)
check(X.verified_bytes(m, "scripts/arbiter.py", b"x=1\n") == b"x=1\n", "목록과 같은 파일 → 그 바이트를 돌려줌")
check(raises(lambda: X.verified_bytes(m, "scripts/arbiter.py", b"x=1\nimport os\n")), "scripts 한 줄 변조 → 실행 거절")
check(raises(lambda: X.verified_bytes(m, "scripts/new.py", b"")), "목록에 없는 파일 → 실행 거절")
check(raises(lambda: X.verify_manifest(man + b" ", man_sha)), "목록 자체가 바뀌면 거절")
g = {}
X.exec_verified(m, "scripts/arbiter.py", b"x=1\n", g)
check(g.get("x") == 1, "검증한 바이트를 그대로 실행")
mod = X.import_verified(m, "scripts/access.py", b"y=2\n", "egg_test_mod")
check(mod.y == 2, "검증한 바이트로 모듈 import")
check(raises(lambda: X.verified_bytes(m, "gpu_worker.ipynb", b"{evil}")), "GPU 노트북 변조 → 거절")

# ---------------------------------------------------------------- 세션 지문 (8판)
f1 = X.machine_fingerprint("host-a", "boot-1"); f2 = X.machine_fingerprint("host-b", "boot-1")
check(len(f1) == 8 and f1 != f2 and f1 == X.machine_fingerprint("host-a", "boot-1"), "기계 지문: 같은 기계는 같고 다른 기계는 다름")
sid1 = X.new_session_id("kgl", fp=f1, now=0); sid2 = X.new_session_id("kgl", fp=f1, now=0)
check(sid1.startswith(f"kgl-{f1}-") and sid1 != sid2, "세션 ID = 환경-지문-시각-난수 (같은 기계에서도 실행마다 다름)")
check(X.worker_record_name(sid1, f1) == f"workers/{sid1}__{f1}.json", "생존 신호 파일 이름에 지문 포함")
check(len(X.machine_fingerprint()) == 8, "이 기계에서도 지문을 만듦")

shutil.rmtree(T, ignore_errors=True)
print("RESULT", ok)
sys.exit(0 if ok else 1)
