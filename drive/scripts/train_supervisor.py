"""v4.33 학습 감독 프로세스 (b27 F1).

실행기(부모)는 이 감독만 띄우고 지켜봅니다. 감독은
1) 자기를 '고아 프로세스의 새 부모'(PR_SET_CHILD_SUBREAPER)로 정한 뒤 학습 자식(`train_child.py`)을 띄웁니다.
   → 학습 자식이나 DDP launcher가 먼저 끝나도, 그 아래 프로세스(새 세션으로 나간 작업자 포함)는 **언제나 감독 아래**로
   넘어옵니다. 실행기의 다른 subprocess와 섞이지 않습니다 (학습만 소유하는 경계).
2) 학습 자식이 끝나도 **자기 아래에 살아 있는 프로세스가 하나도 없을 때까지** 끝나지 않습니다. 남은 것은 유예 뒤
   TERM → KILL. 좀비는 거둡니다.
3) TERM을 받으면 자기 아래 전부에 TERM → 유예 → KILL → 모두 없어진 뒤 끝냅니다.
0) 먼저 subreaper 설정을 다시 읽어 확인하고 /proc 관측이 되는지 봅니다. 하나라도 안 되면 학습 자식을 띄우지 않고
   {"setup_failed": 이유, "child_started": false}를 남기고 끝냅니다 (b28 V4 — 경계 없이 돌려 거짓 '깨끗함'을 남기지 않음).
4) 끝날 때 `status` 파일에 {"child_rc", "clean": true}를 씁니다. 이 파일이 없거나 clean이 아니면 실행기는
   '정리 확인 불가'(확인 필요)로 봅니다 — 예: 감독이 KILL로 죽은 경우.

우리 모듈을 불러오지 않습니다 (경로로 실행, 표준 라이브러리만). 사용:
    python train_supervisor.py <train_child.py> <spec.json> <status.json> <유예 초>
"""
import ctypes
import json
import os
import signal
import subprocess
import sys
import time


def _stat(pid):
    try:
        raw = open(f"/proc/{pid}/stat", "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    rest = raw[raw.rfind(")") + 2:].split()
    try:
        return int(rest[1]), rest[0]                  # (ppid, 상태)
    except (IndexError, ValueError):
        return None


def descendants(root):
    """root 아래의 모든 프로세스 {pid: 상태} (부모 사슬)."""
    procs = {}
    for n in os.listdir("/proc"):
        if n.isdigit():
            st = _stat(int(n))
            if st:
                procs[int(n)] = st
    out, frontier = {}, {root}
    while frontier:
        nxt = set()
        for pid, (ppid, state) in procs.items():
            if ppid in frontier and pid not in out:
                out[pid] = state
                nxt.add(pid)
        frontier = nxt
    return out


def live(root):
    return {p for p, s in descendants(root).items() if s != "Z"}


def reap(child, rc):
    """자기 자식이 된 좀비를 거둠. 학습 자식의 종료 코드를 기억."""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return rc
        if pid == 0:
            return rc
        if pid == child.pid:
            rc = os.waitstatus_to_exitcode(status)
            child.returncode = rc


def signal_all(root, sig):
    for p in live(root):
        try:
            os.kill(p, sig)
        except (ProcessLookupError, PermissionError):
            pass


def set_subreaper():
    """PR_SET_CHILD_SUBREAPER를 켜고 PR_GET으로 다시 읽어 확인. 성공이면 None, 실패면 이유 (b28 V4)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:                         # PR_SET_CHILD_SUBREAPER
            return f"prctl(SET_CHILD_SUBREAPER) 실패 errno={ctypes.get_errno()}"
        v = ctypes.c_int(0)
        if libc.prctl(37, ctypes.byref(v), 0, 0, 0) != 0 or v.value != 1:   # PR_GET_CHILD_SUBREAPER
            return f"subreaper 확인 실패 (값 {v.value}, errno={ctypes.get_errno()})"
    except (OSError, AttributeError) as e:
        return f"prctl을 부를 수 없음: {e}"
    return None


def can_observe(me):
    """/proc으로 자기와 자기 아래를 볼 수 있는지 (못 보면 '아래에 아무것도 없음'을 믿을 수 없음)."""
    try:
        if _stat(me) is None or not any(n.isdigit() for n in os.listdir("/proc")):
            return "/proc에서 자기 프로세스를 읽을 수 없음"
    except OSError as e:
        return f"/proc을 읽을 수 없음: {e}"
    return None


def write_status(status_path, data):
    tmp = status_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, status_path)


def main(child_script, spec, status_path, grace):
    me = os.getpid()
    why = set_subreaper() or can_observe(me)
    if why:
        # 소유 경계를 만들 수 없으면 학습 자식을 띄우지 않음. 띄운 것이 없으므로 남은 것도 없음 —
        # 실행기는 'setup_failed'를 보고 정리 확인 불가가 아니라 '학습 준비 실패'로 끝냄 (b28 V4)
        write_status(status_path, {"child_rc": None, "child_started": False, "setup_failed": why, "clean": True,
                                   "left": [], "stopped": False})
        return 4
    term = {"at": None}
    signal.signal(signal.SIGTERM, lambda *a: term.__setitem__("at", term["at"] or time.monotonic()))
    child = subprocess.Popen([sys.executable, child_script, spec])
    rc, child_done_at, termed, killed = None, None, False, False
    while True:
        rc = reap(child, rc)
        if rc is not None and child_done_at is None:
            child_done_at = time.monotonic()
        alive_set = live(me)
        if rc is not None and not alive_set:
            break                                           # 학습 자식이 끝났고 아래에 아무것도 없음
        # 멈추라는 신호를 받았거나, 학습 자식이 끝났는데 아래에 남은 것이 유예를 넘김 → TERM → KILL
        start = term["at"] if term["at"] is not None else (child_done_at if rc is not None else None)
        if start is not None:
            if not termed:
                signal_all(me, signal.SIGTERM)
                termed = True
            elif time.monotonic() - start > grace and not killed:
                signal_all(me, signal.SIGKILL)
                killed = True
            elif killed and time.monotonic() - start > grace + 10:
                break                                       # KILL로도 남음 — clean 아님
        time.sleep(0.1)
    left = live(me)
    write_status(status_path, {"child_rc": rc, "child_started": True, "clean": not left, "left": sorted(left)[:20],
                               "stopped": term["at"] is not None})
    return 0 if (rc == 0 and not left) else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])))
