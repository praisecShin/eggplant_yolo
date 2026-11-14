"""v4.33 1b — 마스터 판정 루프 (설계 8판 '심판: CPU 마스터').

판정 루프는 CVAT를 부르지 않습니다. 한 회 = 읽기(snapshot) → 판정(arbiter.decide_round) → 쓰기(apply_writes).
쓰기가 중간에 실패하면 거기서 멈추고, 다음 회차가 파일만 보고 이어 갑니다.
`jobs/…`·`arb/ARBITER.json`은 이 루프만 씁니다. 생존 신호는 `heartbeat()`가 `workers/<세션>__<지문>.json`에 씁니다.

Kaggle 마스터 노트북에 연결하는 일(자격 신청, 작업 프로세스 띄우기, GPU 기동)은 2단계입니다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import access
import arbiter as A
from arb_io import ARBITER_SPEC, Cache, StoreError, apply_writes, snapshot

P_ARB_ASK = "jobs/arbiter_ask/"


@dataclass
class Probes:
    """판정에 필요한 바깥 조회 — 판정 루프를 막지 않게 작업 프로세스가 채워 둔 값을 읽음."""
    kernel_status: Callable[[], Dict[str, str]] = lambda: {}
    import_pending: Callable[[], Dict[str, Optional[bool]]] = lambda: {}
    waiting: Callable[[], Dict[str, float]] = lambda: {}


@dataclass
class RoundSummary:
    acting: bool
    writes: int
    applied: int
    failed_at: Optional[str]
    unknown: List[str]
    notes: List[str] = field(default_factory=list)


class MasterLoop:
    def __init__(self, store, me: str, fp: str, config: Callable[[], dict], probes: Optional[Probes] = None,
                 clock=time.time, owner: Optional[str] = None):
        """config(): {'accounts': {...}, 'people': [...]} — 관리자 전용 폴더에서 읽음. 못 읽으면 예외."""
        self.store, self.me, self.fp, self.config = store, me, fp, config
        self.probes, self.clock, self.owner = probes or Probes(), clock, owner
        self.cache = Cache()
        self.cfg_cache, self.cfg_at = None, 0.0
        self.last_round = 0

    def _cfg(self) -> Optional[dict]:
        now = self.clock()
        if self.cfg_cache is None or now - self.cfg_at >= 600:      # 10분마다 다시 읽음
            try:
                c = self.config()
                if not (c.get("accounts") or {}).get("G") or not isinstance(c.get("people"), list):
                    raise ValueError("config")
                self.cfg_cache, self.cfg_at = c, now
            except Exception:
                if self.cfg_cache is None:
                    return None                     # 한 번도 못 읽었으면 판정하지 않음
        return self.cfg_cache

    def ask_grant(self):
        """켜질 때 한 번: 심판 자격 신청 (Keeper가 보고 자격을 줌)."""
        self.store.write_json(P_ARB_ASK + self.me + ".json", {"session": self.me, "fp": self.fp, "at": self.clock()},
                              owner=self.owner)

    def heartbeat(self, caps=("master",)):
        """생존 신호 스레드가 60초마다 부름. ARBITER.json은 건드리지 않음."""
        self.store.write_json(access.worker_record_name(self.me, self.fp),
                              {"session": self.me, "fp": self.fp, "caps": list(caps), "hb": self.clock(),
                               "last_round": self.last_round}, owner=self.owner)

    def run_once(self) -> RoundSummary:
        cfg = self._cfg()
        if cfg is None:
            return RoundSummary(False, 0, 0, None, ["config"], ["config_unreadable"])
        files, unknown, started = snapshot(self.store, ARBITER_SPEC, self.cache, self.clock)
        inp = A.Inputs(now=self.clock(), files=files, list_started_at=started, unknown=unknown,
                       kernel_status=self.probes.kernel_status(), import_pending=self.probes.import_pending(),
                       waiting=self.probes.waiting())
        res = A.decide_round(A.Cfg(me=self.me, accounts=cfg["accounts"], people=cfg["people"]), inp)
        n, failed = apply_writes(self.store, res.writes, owner=self.owner)
        if failed is None and res.writes and res.writes[-1].path == A.P_ARBITER:
            self.last_round = int(res.writes[-1].obj.get("round", self.last_round))
        return RoundSummary(res.acting, len(res.writes), n, failed, sorted(unknown), list(res.notes))

    def run_forever(self, interval: float = 25, stop: Callable[[], bool] = lambda: False, sleep=time.sleep,
                    on_round: Optional[Callable[[RoundSummary], None]] = None):
        while not stop():
            try:
                r = self.run_once()
            except StoreError:
                r = RoundSummary(False, 0, 0, None, ["store"], ["store_error"])
            if on_round:
                on_round(r)
            sleep(interval)
