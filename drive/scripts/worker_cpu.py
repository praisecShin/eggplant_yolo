"""v4.33 1b — CPU 작업 프로세스 (설계 8판 '심판: CPU 마스터'의 CPU 작업 프로세스).

마스터가 `python -m worker_cpu --base <공유 폴더 또는 rclone 원격> …`로 띄우는 **별도 프로세스**입니다.
마스터와 전역 설정·rclone 잠금을 함께 쓰지 않고, 다른 실행기와 같은 규칙(`executor.Executor`)을 따릅니다.

일 종류별 처리기는 `register()`로 붙입니다. 백업·export·취합·청소 같은 기존 코드의 전환은 2단계이고,
여기에는 뼈대와 등록 틀만 있습니다. 처리기가 없는 종류는 'failed:no_handler'로 보고합니다(거짓 완료 금지).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import time
from typing import Callable, Dict, List, Optional

import access
import executor as X
from arb_io import LocalStore, RcloneStore

# 처리기 등록부는 handlers.py (CPU 작업 프로세스·GPU 작업자·Colab 30번 셀이 함께 씀, 2b-1). 옛 이름도 그대로 둠
from handlers import REGISTRY as HANDLERS, Dispatch, NoHandler, register   # noqa: E402,F401


def make_store(base: str):
    return RcloneStore(base) if ":" in base and not base.startswith("/") else LocalStore(base)


def load_accounts(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(store, accounts: Dict[str, str], caps: List[str], session: Optional[str] = None, interval: float = 20,
        hb_every: float = 60, max_steps: Optional[int] = None, stop: Callable[[], bool] = lambda: False,
        sleep=time.sleep, clock=time.time, join_timeout: float = 90, env=None, test: bool = False,
        exec_cfg: Optional[dict] = None, work: Optional[str] = None) -> X.Executor:
    """env를 주지 않으면 exec_host.build_env로 꾸밈 (2b-6: 시험 범위·데이터셋 만들기 엔진)."""
    import exec_host as EH
    if access.mode() != "exec":
        raise access.AccessError("작업 프로세스는 EGG_ACCESS=exec에서만 돕니다")
    fp = access.machine_fingerprint()
    session = session or access.new_session_id("cpu", fp)
    if env is None:
        cfg = EH.HostConfig(test=test, caps=list(caps), exec_cfg=dict(EH.DEFAULT_EXEC, **(exec_cfg or {})),
                            scripts_dir=str(Path(__file__).resolve().parent), work=work)
        env = EH.build_env(cfg, store)
    return EH.run_loop(store, accounts, caps, env, session, fp, interval=interval, hb_every=hb_every, stop=stop,
                       max_steps=max_steps, sleep=sleep, clock=clock, join_timeout=join_timeout)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="가지 앱 CPU 작업 프로세스")
    ap.add_argument("--base", required=True, help="공유 폴더 경로 또는 rclone 원격 (예: gdrive:eggplant_yolo)")
    ap.add_argument("--accounts", required=True, help="관리자 전용 폴더의 accounts.json (세션 임시 폴더로 받은 사본)")
    ap.add_argument("--caps", default="cpu", help="쉼표로 나눈 능력 (cpu, agg)")
    ap.add_argument("--session", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--stop-file", default=None, help="이 파일이 생기면 지금 단계를 마치고 끝남 (마스터가 만듦)")
    ap.add_argument("--test", action="store_true", help="시험 실행 — 시험 프로젝트의 REH_ TASK에만 씀")
    ap.add_argument("--exec-config", default=None, help="관리자 폴더 config/exec.json의 사본 (비밀 아님)")
    a = ap.parse_args(argv)
    import handlers as H
    H.load_all()                                       # 처리기 모듈 등록 (시험은 run()에 직접 등록)
    stop = (lambda: Path(a.stop_file).exists()) if a.stop_file else (lambda: False)
    run(make_store(a.base), load_accounts(a.accounts), [c for c in a.caps.split(",") if c], a.session,
        max_steps=1 if a.once else None, stop=stop, test=a.test,
        exec_cfg=load_accounts(a.exec_config) if a.exec_config else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
