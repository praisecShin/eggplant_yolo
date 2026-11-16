"""v4.33 무작위 입력 시험 (0i) — 판정 함수가 어떤 입력에도 예외 없이 회차를 마치는지.

1) 기존 시나리오 시험(test_arbiter_433·test_master_433)을 그대로 돌리며 심판이 실제로 받은 입력을 모읍니다.
2) 바깥에서 오는 파일(보고·신호·요청·실행기·산출물 목록·자격 파일·옛 판정 파일)의 칸을 하나씩 이상한 값으로 바꿔
   decide_round를 다시 부릅니다. 객체·목록 칸은 한 단계 안쪽까지 바꿉니다.
3) 매번 예외 없이 끝나야 하고(R1·S1·U1·V1·V2), 뜻도 지켜야 합니다 (b16):
   - 판정 파일이 믿을 수 없게 되면 보호 모드 — 회차 기록·알림 말고는 쓰지 않음 (W1·W2)
   - 보호 모드가 아니면: 살아 있는 정지 보류 아래 새 배정 없음, 살아 있는 배정을 다른 세션으로 덮지 않음
4) 목록 칸은 원소 빼기·중복·바꿔치기·순서 뒤집기도 넣고(b17 X1), 계획의 효과는 구현을 빌리지 않은 독립 정답과 맞춥니다.
5) 칸 두 개를 함께 바꾼 조합도 일부 돌립니다. 씨앗 7에서 나온 사례(계획의 seq 삭제)는 고정 시험으로 둡니다.

실행: python3 tests/test_fuzz_433.py drive        (약 1분)
"""
import contextlib
import copy
import io
import random
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "drive").resolve()
sys.path.insert(0, str(PKG / "scripts"))
import arbiter as A
from arbiter import FileRec, Inputs

ok = True


def check(c, msg):
    global ok
    print(("✅ " if c else "❌ ") + msg)
    ok &= bool(c)


# ---------------------------------------------------------------- 1) 실제 입력 모으기
REC = []
_orig = A.decide_round


def _rec(cfg, inp):
    REC.append((cfg, Inputs(now=inp.now, files=dict(inp.files), list_started_at=inp.list_started_at,
                            unknown=set(inp.unknown), kernel_status=dict(inp.kernel_status),
                            import_pending=dict(inp.import_pending), waiting=dict(inp.waiting))))
    return _orig(cfg, inp)


A.decide_round = _rec
src_ok = True
for t in ("test_arbiter_433.py", "test_master_433.py"):
    argv = sys.argv
    sys.argv = [str(ROOT / t), str(PKG)]
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            runpy.run_path(str(ROOT / t), run_name="__main__")
        except SystemExit as e:
            src_ok &= (e.code in (0, None))
    sys.argv = argv
check(src_ok, "재료로 쓴 시나리오 시험이 모두 통과 (실패한 시험의 입력으로 퍼징하지 않음)")
A.decide_round = _orig
check(len(REC) > 200, f"시나리오 시험에서 심판 입력 {len(REC)}개를 모음")


# ---------------------------------------------------------------- 2) 바꿀 대상
def kind_of(path: str) -> str:
    jk = A.judgement_kind(path)
    if jk:
        return jk
    if path == A.P_GRANT:
        return "grant"
    if path.startswith(A.P_ASK):
        return "ask"
    if path.startswith(A.P_SIGNALS):
        return "signal"
    if path.startswith(A.P_WORKERS):
        return "worker"
    if "/REQ_" in "/" + path:
        return "request"
    if "/v/" in path and path.endswith("/_files.json"):
        return "vfiles"
    return ""


BAD = [None, [], {}, 0, -1, 1.5, True, "", "x", [["a"]], [1], {"a": []}, {"type": []}, "2026-11-14T00:00:00Z", 10 ** 30]


def mutations(obj):
    """(설명, 새 객체) — 칸 하나씩, 한 단계 안쪽까지, 통째로."""
    for b in ([], "x", 3, None):
        yield "whole=" + repr(b), b
    if not isinstance(obj, dict):
        return
    for k in sorted(obj):
        for b in BAD:
            o = copy.deepcopy(obj)
            o[k] = copy.deepcopy(b)
            yield f"{k}={b!r}", o
        o = copy.deepcopy(obj)
        del o[k]
        yield f"-{k}", o
        if isinstance(obj[k], dict):
            for k2 in sorted(obj[k]):
                for b in BAD:
                    o = copy.deepcopy(obj)
                    o[k][k2] = copy.deepcopy(b)
                    yield f"{k}.{k2}={b!r}", o
        if isinstance(obj[k], list) and obj[k]:
            for b in BAD:
                o = copy.deepcopy(obj)
                o[k][0] = copy.deepcopy(b)
                yield f"{k}[0]={b!r}", o
            for j in range(len(obj[k])):                 # 원소 빼기·중복·다른 이름으로 바꿔치기 (b17 X1)
                o = copy.deepcopy(obj); del o[k][j]
                yield f"{k}-[{j}]", o
                o = copy.deepcopy(obj); o[k].insert(j, copy.deepcopy(obj[k][j]))
                yield f"{k}+dup[{j}]", o
                for alt in ("hold", "gpu", "unhold", "mark", "lock", "flag", "zz"):
                    if obj[k][j] != alt:
                        o = copy.deepcopy(obj); o[k][j] = alt
                        yield f"{k}[{j}]={alt}", o
            if len(obj[k]) > 1:
                o = copy.deepcopy(obj); o[k] = list(reversed(o[k]))
                yield f"{k}=reversed", o


# 같은 (종류, 칸 모양)은 입력 몇 개에서만 — 실행 시간 제한
import os
rng = random.Random(int(os.environ.get("FUZZ_SEED", "4330")))
PER_SHAPE = int(os.environ.get("FUZZ_N", "2"))
targets = {}
for i, (cfg, inp) in enumerate(REC):
    for p, r in inp.files.items():
        k = kind_of(p)
        if not k:
            continue
        o = r.obj if isinstance(r.obj, dict) else {}
        shape = (k, tuple(sorted(o)) if isinstance(r.obj, dict) else type(r.obj).__name__,
                 str(o.get("state")), str(o.get("type")), str(o.get("lane")),     # 상태·종류별로 나눠 고름
                 p.startswith(A.P_PLAN) and (A.P_DONE + p[len(A.P_PLAN):]) not in inp.files)   # 끝나지 않은 계획은 따로 (X1)
        targets.setdefault(shape, []).append((i, p))

# 신호 종류별 효과 — 구현(SignalKind.effects)을 빌리지 않은 독립 정답 (b17 X1)
def expected_effects(kind, sig):
    c = sig.get("choice")
    if kind in ("cancel", "approve_night"):
        return ["mark"]
    if kind == "stop":
        return ["hold", "gpu"]
    if kind == "release":
        return ["unhold"]
    if kind == "confirm_choice":
        return ["lock"] if c == "ok" else ["recovery_request", "lock"]
    if kind == "adopt_choice":
        if c != "adopt":
            return ["flag"]
        return ["current", "contam", "flag"] if sig.get("type") == "test_tasks" else ["current", "flag"]
    if kind == "run_choice":
        return ["complete"] if c == "done" else ["redo"]
    return None


def plan_mismatch(p, obj, files):
    """끝나지 않은 계획이 신호와 다른가 (독립 정답). 신호가 없거나 끝났으면 판단하지 않음."""
    if not p.startswith(A.P_PLAN) or not isinstance(obj, dict):
        return False
    sid = p[len(A.P_PLAN):-5]
    if (A.P_DONE + sid + ".json") in files:
        return False
    kind = sid.split("__", 1)[0]
    sr = files.get(A.P_SIGNALS + sid + ".json")
    if obj.get("sid") != sid or obj.get("kind") != kind or expected_effects(kind, {}) is None:
        return True
    if sr is None or not isinstance(sr.obj, dict) or A.input_problem("signal", sr.obj):
        return False
    sig = sr.obj
    tgt = sig.get("rid") or sig.get("task") or sig.get("stop_id") or sig.get("run")
    return obj.get("effects") != expected_effects(kind, sig) or obj.get("target") != tgt


def untrusted_judgement(p, obj, cfg, inp, files=None):
    """판정 파일이 믿을 수 없는가 (보호 모드가 되어야 하는가)."""
    jk = A.judgement_kind(p)
    if not jk:
        return False
    if A.input_problem(jk, obj):
        return True
    if files is not None and plan_mismatch(p, obj, files):
        return True
    g = (inp.files.get(A.P_GRANT).obj or {}) if inp.files.get(A.P_GRANT) else {}
    ep = int(g.get("epoch", 0)) if A._intlike(g.get("epoch", 0)) else 0
    bs, be = obj.get("by_session"), obj.get("by_epoch")
    return not isinstance(bs, str) or not A._intlike(be) or int(be) > ep or (int(be) == ep and bs != cfg.me)


def active_holds(files):
    return [p for p, r in files.items() if p.startswith(A.P_HOLD) and isinstance(r.obj, dict) and r.obj.get("active") is True
            and r.obj.get("by_session") and (r.obj.get("until") is None or A._numlike(r.obj.get("until")))]


def judge(cfg, inp, mi, changed):
    """(예외, 뜻 위반 설명 또는 '')"""
    try:
        res = A.decide_round(cfg, mi)
    except Exception as e:
        return type(e).__name__ + ": " + str(e)[:80], ""
    if not res.acting:
        return "", ""
    writes = [w.path for w in res.writes]
    must_protect = any(untrusted_judgement(p, mi.files[p].obj, cfg, inp, mi.files) for p in changed
                       if isinstance(mi.files[p].obj, dict)) or any(A.judgement_kind(p) and not isinstance(mi.files[p].obj, dict)
                                                                   for p in changed)
    if must_protect:
        bad = [w for w in writes if w != A.P_ARBITER and not w.startswith(A.P_ALERT)]
        if not res.protect:
            return "", "믿을 수 없는 판정 파일인데 보호 모드가 아님"
        if bad:
            return "", "보호 모드인데 판정 파일을 씀: " + bad[0]
        return "", ""
    if res.protect:
        return "", ""
    for w in res.writes:                          # 정지 신호를 '완료'로 쓰면 그 보류가 있어야 함 (b17 X1)
        if w.path.startswith(A.P_DONE) and w.obj.get("result") == "done" and w.obj.get("sid", "").startswith("stop__"):
            hp = A.P_HOLD + w.obj["sid"] + ".json"
            if hp not in mi.files and not any(x.path == hp for x in res.writes):
                return "", "보류 없이 정지 신호를 완료로 씀: " + w.path
    released = {w.path for w in res.writes if w.path.startswith(A.P_HOLD) and not w.obj.get("active")}
    holds = [h for h in active_holds(mi.files) if h not in changed and h not in released]   # 이 회차에 해제·만료된 보류는 뺌
    for w in res.writes:
        if not w.path.startswith(A.P_ASSIGN) or w.obj.get("state") != "active":
            continue
        old = inp.files.get(w.path)
        if holds and not (old and isinstance(old.obj, dict) and old.obj.get("state") == "active"):
            return "", "정지 보류 중 새 배정: " + w.path
        if old and isinstance(old.obj, dict) and old.obj.get("state") == "active" \
                and old.obj.get("session") != w.obj.get("session") and w.path not in changed:
            return "", "살아 있는 배정을 다른 세션으로 덮음: " + w.path
    return "", ""


def run_one(cfg, inp, changes):
    files = dict(inp.files)
    for p, newobj in changes.items():
        r = inp.files[p]
        files[p] = FileRec(newobj, r.owner, r.created, r.modified)
    mi = Inputs(now=inp.now, files=files, list_started_at=inp.list_started_at, unknown=set(inp.unknown),
                kernel_status=inp.kernel_status, import_pending=inp.import_pending, waiting=inp.waiting)
    return judge(cfg, inp, mi, set(changes))


runs, fails, sems = 0, [], []
for shape, lst in sorted(targets.items(), key=lambda kv: str(kv[0])):
    for i, p in rng.sample(lst, min(PER_SHAPE, len(lst))):
        cfg, inp = REC[i]
        for desc, newobj in mutations(inp.files[p].obj):
            runs += 1
            exc, sem = run_one(cfg, inp, {p: newobj})
            if exc:
                fails.append((shape[0], p, desc, exc))
            if sem:
                sems.append((shape[0], p, desc, sem))

# 칸 두 개를 함께 바꾼 조합 (같은 파일 안)
pairs = 0
for shape, lst in sorted(targets.items(), key=lambda kv: str(kv[0])):
    i, p = rng.choice(lst)
    cfg, inp = REC[i]
    obj = inp.files[p].obj
    if not isinstance(obj, dict) or len(obj) < 2:
        continue
    for _ in range(int(os.environ.get("FUZZ_PAIRS", "12"))):
        k1, k2 = rng.sample(sorted(obj), 2)
        o = copy.deepcopy(obj)
        o[k1], o[k2] = copy.deepcopy(rng.choice(BAD)), copy.deepcopy(rng.choice(BAD))
        pairs += 1
        exc, sem = run_one(cfg, inp, {p: o})
        if exc:
            fails.append((shape[0], p, f"{k1}+{k2}", exc))
        if sem:
            sems.append((shape[0], p, f"{k1}+{k2}", sem))

ext = [f for f in fails if not f[0].startswith("judgement")]
jud = [f for f in fails if f[0].startswith("judgement")]
print(f"   바꾼 입력 {runs}개 + 두 칸 조합 {pairs}개 (종류·모양 {len(targets)}가지)")
for f in (ext + jud + sems)[:25]:
    print("   ↳", f)
check(not ext, f"바깥 입력(보고·신호·요청·실행기·산출물 목록·자격 파일)의 칸이 틀려도 회차가 예외 없이 끝남 — 실패 {len(ext)}건")
check(not jud, f"판정 파일이 틀어져도 회차가 예외 없이 끝남 — 실패 {len(jud)}건")
check(not sems, f"뜻 지킴: 판정 파일이 틀어지면 보호 모드(회차 기록·알림만), 정지 보류 아래 새 배정 없음, 살아 있는 배정 안 덮음 — 위반 {len(sems)}건")

# 고정 시험: 씨앗 7에서 나온 사례 (계획의 seq 삭제) — b16 W1
plan_cases = [(i, p) for i, (cfg, inp) in enumerate(REC) for p in inp.files if p.startswith(A.P_PLAN)]
i, p = plan_cases[0]
cfg, inp = REC[i]
o = copy.deepcopy(inp.files[p].obj); o.pop("seq", None)
o2 = copy.deepcopy(inp.files[p].obj); o2.pop("effects", None)
r1, r2 = run_one(cfg, inp, {p: o}), run_one(cfg, inp, {p: o2})
check(r1 == ("", "") and r2 == ("", ""), "고정: 계획의 seq·effects가 빠지면 예외 없이 보호 모드 (씨앗 7 사례, W1)")
# 계획의 메타데이터(admin·requester)는 결과를 바꾸지 못함 — 보호 모드가 되거나 원래와 같은 효과 (b18 Y1)
def effect_writes(res):
    out = {}
    for w in res.writes:
        if w.path == A.P_ARBITER or w.path.startswith(A.P_ALERT) or w.path.startswith(A.P_DONE) or w.path.startswith(A.P_PLAN):
            continue
        out[w.path] = {k: x for k, x in (w.obj or {}).items() if k not in ("by", "at", "seq", "by_session", "by_epoch")} \
            if isinstance(w.obj, dict) else w.obj
    return out
pending_plans = [(i, p) for i, (cfg, inp) in enumerate(REC) for p in inp.files
                 if p.startswith(A.P_PLAN) and (A.P_DONE + p[len(A.P_PLAN):]) not in inp.files]
meta_runs, meta_bad = 0, []
for i, p in pending_plans:
    cfg, inp = REC[i]
    base = A.decide_round(cfg, inp)
    if base.protect:
        continue
    o0 = inp.files[p].obj
    variants = [("admin", not o0.get("admin")), ("admin", True)] + [("requester", x) for x in ("M1", "M2", "system:G", "nobody")
                                                                   if x != o0.get("requester")]
    for k, val in variants:
        o = copy.deepcopy(o0); o[k] = val
        files = dict(inp.files); files[p] = FileRec(o, inp.files[p].owner, inp.files[p].created, inp.files[p].modified)
        res = A.decide_round(cfg, Inputs(now=inp.now, files=files, list_started_at=inp.list_started_at, unknown=set(inp.unknown),
                                         kernel_status=inp.kernel_status, import_pending=inp.import_pending, waiting=inp.waiting))
        meta_runs += 1
        if not res.protect and effect_writes(res) != effect_writes(base):
            meta_bad.append((p, k, val))
print(f"   끝나지 않은 계획 {len(pending_plans)}개 × admin·requester 변형 {meta_runs}회")
for b in meta_bad[:5]:
    print("   ↳", b)
check(meta_runs > 0 and not meta_bad, f"계획의 admin·requester만 바뀌면 보호 모드이거나 효과가 원래와 같음 (Y1) — 위반 {len(meta_bad)}건")

# 고정 시험: 끝나지 않은 정지 계획의 효과 일부 삭제 (b17 X1)
stop_cases = [(i, p) for i, (cfg, inp) in enumerate(REC) for p in inp.files
              if p.startswith(A.P_PLAN + "stop__") and (A.P_DONE + p[len(A.P_PLAN):]) not in inp.files]
check(bool(stop_cases), f"끝나지 않은 정지 계획이 있는 입력 {len(stop_cases)}개를 찾음")
if stop_cases:
    i, p = stop_cases[0]
    cfg, inp = REC[i]
    o = copy.deepcopy(inp.files[p].obj); o["effects"] = ["gpu"]
    files = dict(inp.files); files[p] = FileRec(o, inp.files[p].owner, inp.files[p].created, inp.files[p].modified)
    res = A.decide_round(cfg, Inputs(now=inp.now, files=files, list_started_at=inp.list_started_at, unknown=set(inp.unknown),
                                     kernel_status=inp.kernel_status, import_pending=inp.import_pending, waiting=inp.waiting))
    check(bool(res.protect) and run_one(cfg, inp, {p: o}) == ("", ""), "고정: 정지 계획의 효과가 ['gpu']만 남으면 보호 모드 (X1)")
print("RESULT", ok)
sys.exit(0 if ok else 1)
