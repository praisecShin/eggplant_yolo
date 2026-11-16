"""v4.33 1b — 마스터 판정 루프 (설계 8판 '심판: CPU 마스터').

판정 루프는 CVAT를 부르지 않습니다. 한 회 = 읽기(snapshot) → 판정(arbiter.decide_round) → 쓰기(apply_writes).
쓰기가 중간에 실패하면 거기서 멈추고, 다음 회차가 파일만 보고 이어 갑니다.
`jobs/…`·`arb/ARBITER.json`은 이 루프만 씁니다. 생존 신호는 `heartbeat()`가 `workers/<세션>__<지문>.json`에 씁니다.

Kaggle 마스터 노트북에 연결하는 일(자격 신청, 작업 프로세스 띄우기, GPU 기동)은 `master_main.py`(2a)가 합니다.
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
        self.cfg_cache, self.cfg_at, self.cfg_tried, self.cfg_failed = None, 0.0, 0.0, False
        self.last_round = 0
        self.decide_errors = 0
        self.last_arbiter: Optional[dict] = None       # 마지막으로 쓴 회차 기록 (깨우기 요약 포함) — master_main이 읽음
        self.last_acting_at = 0.0
        self.last_clean_at = 0.0                       # 모름 없이 읽고 모두 쓴 마지막 회차 (master_main 밤 끝내기, U6)
        self.last_run_at = 0.0                         # 마지막 회차 시작 시각 (성공·실패와 무관)
        self.cfg_reject: Optional[str] = None          # 마지막으로 새 설정을 받지 않은 이유 (CTRL앱에 보임)
        self.status_extra: dict = {}                   # master_main이 채우는 상태 (GPU 상태 모름 등) — 생존 신호에 실음

    CFG_REFRESH, CFG_MAX_AGE = 600, 1200

    def _cfg(self) -> Optional[dict]:
        """10분마다 다시 읽음. 못 읽은 채 20분이 지나면 '오래됨' — 새 접수·신호·배정을 멈춤 (Q3)."""
        now = self.clock()
        if self.cfg_cache is None or now - self.cfg_tried >= min(self.CFG_REFRESH, 60 if self.cfg_failed else self.CFG_REFRESH):
            self.cfg_tried = now
            try:
                c = self.config()
                why = self._cfg_problem(c)
                if why:
                    raise ValueError(why)                 # 사람 목록 형태가 틀리면 새 값을 쓰지 않음 (U1·V1)
                self.cfg_cache, self.cfg_at, self.cfg_failed, self.cfg_reject = c, now, False, None
            except Exception as e:
                self.cfg_reject = str(e) if isinstance(e, ValueError) else "unreadable:" + type(e).__name__
                self.cfg_failed = True
                if self.cfg_cache is None:
                    return None                     # 한 번도 못 읽었으면 판정하지 않음
        return self.cfg_cache

    @staticmethod
    def _cfg_problem(c) -> str:
        if not isinstance(c, dict) or not isinstance(c.get("accounts"), dict) or not c["accounts"].get("G") \
                or not all(isinstance(x, str) for x in c["accounts"].values()):
            return "accounts"
        if not isinstance(c.get("people"), list):
            return "people"
        for i, p in enumerate(c["people"]):
            why = A.input_problem("person", p)
            if why:
                return f"people[{i}].{why}"
        ids = [p["id"] for p in c["people"]]
        accts = [p["account"] for p in c["people"]]
        if len(set(ids)) != len(ids) or len(set(accts)) != len(accts):
            return "people.duplicate"
        return ""

    def config_status(self) -> dict:
        return {"ok_at": self.cfg_at or None, "rejected": self.cfg_reject, "stale": self.cfg_stale()}

    def cfg_stale(self) -> bool:
        return self.cfg_cache is not None and self.clock() - self.cfg_at > self.CFG_MAX_AGE

    def ask_grant(self):
        """켜질 때 한 번: 심판 자격 신청 (Keeper가 보고 자격을 줌)."""
        self.store.write_json(P_ARB_ASK + self.me + ".json", {"session": self.me, "fp": self.fp, "at": self.clock()},
                              owner=self.owner)

    def heartbeat(self, caps=("master",), stopping: bool = False, extra: Optional[dict] = None):
        """생존 신호 스레드가 60초마다 부름. ARBITER.json은 건드리지 않음."""
        self.store.write_json(access.worker_record_name(self.me, self.fp),
                              dict({"session": self.me, "fp": self.fp, "caps": list(caps), "hb": self.clock(),
                                    "last_round": self.last_round, "stopping": stopping},
                                   **{"status": dict(self.status_extra)}, **(extra or {})),
                              owner=self.owner)

    def run_once(self) -> RoundSummary:
        self.last_run_at = self.clock()
        cfg = self._cfg()
        if cfg is None:
            return RoundSummary(False, 0, 0, None, ["config"], ["config_unreadable"])
        files, unknown, started = snapshot(self.store, ARBITER_SPEC, self.cache, self.clock)
        if self.cfg_stale():
            unknown.add("config")
        inp = A.Inputs(now=self.clock(), files=files, list_started_at=started, unknown=unknown,
                       kernel_status=self.probes.kernel_status(), import_pending=self.probes.import_pending(),
                       waiting=self.probes.waiting())
        try:
            res = A.decide_round(A.Cfg(me=self.me, accounts=cfg["accounts"], people=cfg["people"]), inp)
        except Exception as e:                       # 예상 못 한 입력으로 판정이 실패해도 루프는 죽지 않음 (Q7)
            self.decide_errors += 1
            return RoundSummary(False, 0, 0, None, sorted(unknown), ["decide_error:" + type(e).__name__])
        n, failed = apply_writes(self.store, res.writes, owner=self.owner)
        notes = list(res.notes)
        if getattr(self.store, "no_btime", 0):
            notes.append("no_btime")                # rclone이 만든 시각을 주지 않음 — 버전·설정 확인
        if failed is None and res.writes and res.writes[-1].path == A.P_ARBITER:
            self.last_round = int(res.writes[-1].obj.get("round", self.last_round))
            self.last_arbiter = res.writes[-1].obj
        if res.acting:
            self.last_acting_at = self.clock()
            if not unknown and failed is None and self.last_arbiter is not None and n == len(res.writes) \
                    and not res.protect and not res.internal_unknown:   # 보호 모드·안쪽 '모름'은 빠짐없는 회차가 아님 (W2)
                self.last_clean_at = self.last_run_at
        return RoundSummary(res.acting, len(res.writes), n, failed, sorted(set(unknown) | set(res.internal_unknown)), notes)

    def run_forever(self, interval: float = 25, stop: Callable[[], bool] = lambda: False, sleep=time.sleep,
                    on_round: Optional[Callable[[RoundSummary], None]] = None):
        while not stop():
            try:
                r = self.run_once()
            except StoreError:
                r = RoundSummary(False, 0, 0, None, ["store"], ["store_error"])
            except Exception as e:
                r = RoundSummary(False, 0, 0, None, ["error"], ["round_error:" + type(e).__name__])
            if on_round:
                on_round(r)
            sleep(interval)
