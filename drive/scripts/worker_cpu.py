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
from arb_io import Beat, LocalStore, RcloneStore

# kind → {'prepare','commit','fetch','publish','run'} 중 필요한 함수
HANDLERS: Dict[str, Dict[str, Callable]] = {}


def register(kind: str, **fns: Callable):
    HANDLERS.setdefault(kind, {}).update(fns)


class NoHandler(RuntimeError):
    pass


class Dispatch(X.Handlers):
    """요청 종류에 따라 등록된 처리기를 부름."""

    def _fn(self, ctx: X.Ctx, name: str) -> Callable:
        fn = (HANDLERS.get(ctx.kind) or {}).get(name)
        if fn is None:
            raise NoHandler(f"{ctx.kind}.{name}")
        return fn

    def prepare(self, ctx):
        return self._fn(ctx, "prepare")(ctx)

    def commit(self, ctx):
        return self._fn(ctx, "commit")(ctx)

    def fetch(self, ctx):
        return self._fn(ctx, "fetch")(ctx)

    def publish(self, ctx):
        return self._fn(ctx, "publish")(ctx)

    def run(self, ctx):
        return self._fn(ctx, "run")(ctx)


def make_store(base: str):
    return RcloneStore(base) if ":" in base and not base.startswith("/") else LocalStore(base)


def load_accounts(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(store, accounts: Dict[str, str], caps: List[str], session: Optional[str] = None, interval: float = 20,
        hb_every: float = 60, max_steps: Optional[int] = None, stop: Callable[[], bool] = lambda: False,
        sleep=time.sleep, clock=time.time, join_timeout: float = 90) -> X.Executor:
    access_env = access.mode()
    if access_env != "exec":
        raise access.AccessError("작업 프로세스는 EGG_ACCESS=exec에서만 돕니다")
    fp = access.machine_fingerprint()
    ex = X.Executor(store, session or access.new_session_id("cpu", fp), fp, caps, accounts, Dispatch(), clock=clock)
    # 생존 신호는 일하는 줄과 따로 — 긴 처리 중에도 보냄 (Q1). '끝남'도 같은 스레드가 마지막에 씀 (R7)
    beat = Beat(ex.heartbeat, hb_every, final=lambda: ex.heartbeat(stopping=True))
    beat.start()
    n = 0
    try:
        while not stop() and (max_steps is None or n < max_steps):
            ex.step()
            n += 1
            if max_steps is None or n < max_steps:
                sleep(interval)
    finally:
        beat.stop()
        beat.join(timeout=join_timeout)               # 저장소 쓰기 한도보다 길게 기다림
        if beat.is_alive():
            ex.notes.append("beat_join_timeout")    # 다른 줄에서 쓰지 않음 — 생존 신호가 3분 뒤 끊겨 정리됨
    return ex


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="가지 앱 CPU 작업 프로세스")
    ap.add_argument("--base", required=True, help="공유 폴더 경로 또는 rclone 원격 (예: gdrive:eggplant_yolo)")
    ap.add_argument("--accounts", required=True, help="관리자 전용 폴더의 accounts.json (세션 임시 폴더로 받은 사본)")
    ap.add_argument("--caps", default="cpu", help="쉼표로 나눈 능력 (cpu, agg)")
    ap.add_argument("--session", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--stop-file", default=None, help="이 파일이 생기면 지금 단계를 마치고 끝남 (마스터가 만듦)")
    a = ap.parse_args(argv)
    stop = (lambda: Path(a.stop_file).exists()) if a.stop_file else (lambda: False)
    run(make_store(a.base), load_accounts(a.accounts), [c for c in a.caps.split(",") if c], a.session,
        max_steps=1 if a.once else None, stop=stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
