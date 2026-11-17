"""TASK 쓰기 처리기: track·shape·auto·제출본 올리기 (2b-3).

v4.32의 30번 셀 `_rl_track_one`·`_rl_shape_one`·`_rl_upload_one`, 5·6·10번 셀을 실행기의 두 단계로 나눴습니다.

준비(prepare) — 로컬에서 끝까지, CVAT에 쓰지 않음:
  TASK 정보 → (시험 범위 미리 확인) → 참고용 라벨 받기(track) → 결과 만들기(track XML·shape 목록) 또는 제출본 받기·검증

확정(commit) — 심판의 확정 승인 뒤:
  ① TASK가 준비 때와 같은지(프레임 수·라벨 정의) → ② **업로드 전 백업**: 지금 라벨을 받아 복구 자료로 게시(ctx.auth('recovery_publish')),
  받지 못하면 쓰지 않음 → ③ **사람 라벨 보호**: 기존 라벨이 있고 이름이 uld·AA가 아니면 요청의 `params.allow_replace`가
  참일 때만 → ④ 쓰기(ctx.auth('cvat_write')): 교체면 지우고 가져오기, 가져오기 작업이 끝날 때까지 기다림 →
  실패면 백업으로 되돌림(권한을 잃었으면 되돌리지 않음) · 끝났는지 모르면(시간 초과) 되돌리지 않고 '확인 필요' →
  ⑤ 결과 확인(라벨 수) → ⑥ 이름은 `…_uld` → `…_uld_AA`만 → ⑦ AA TASK를 교체했으면 이전 라벨을 exports/_aa_replaced/에 보관

11/17 결정: track 요청은 한 단계 — 만들고 바로 올림(확인 대기 없음). auto는 shape와 같은 처리기(프레임별 자동 라벨).
결과 문자열: 'done' · 'held:human_labels'(보류, 쓰지 않음) · 'failed:…(restored)'(되돌림). 예외는 실행기가 실패/확인 필요로 보고.

계산(track 만들기·프레임 탐지)은 env.engine이 함: 실제는 `RealEngine`(yolo_track_to_cvat.py·auto_annotate_frames
collect_only), 시험은 가짜. 영상·모델 찾기는 실행 호스트가 넘겨줌(2b-6).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import access
import handlers as H
from arb_io import StoreError

BACKUP_FMT = "CVAT for video 1.1"          # 받기(export) 형식 — v4.32 ctt.EXPORT_FORMAT
IMPORT_FMT = "CVAT 1.1"                    # 가져오기 형식 — v4.32 ctt.IMPORT_FORMAT (track XML·백업 zip 되돌리기, b23 S6)
SHAPES_FMT = "shapes-json"
TARGET_END = ("uld", "AA")
IMPORT_WAIT_SEC = 3600


class TaskChanged(RuntimeError):
    pass


class BackupFailed(RuntimeError):
    pass


class ImportUnknown(RuntimeError):
    """가져오기가 끝났는지 모름 — 되돌리지 않고 '확인 필요'로."""


class ResultMismatch(RuntimeError):
    pass


# 가져오기 호출이 '서버가 받지 않았다'고 분명히 알려 준 실패 (예: 4xx 거절). 이것과 상태 'failed'만 되돌림 대상 (b23 S2)
ImportRejected = H.ImportRejected


TARGET_RE = re.compile(r"_(?:uld|AA(?:_r\d+)?)$", re.I)


def is_target(name: str) -> bool:
    """모델 라벨 TASK인가: 이름이 밑줄까지 맞는 꼬리 `_uld`·`_AA`·`_AA_rN`으로 끝날 때만 (b23 S1 — `humanAA`는 아님).
    AGENTS 3장 3의 사람 라벨 보호를 relabel_bridge.is_target보다 좁게(엄격하게) 적용."""
    return bool(TARGET_RE.search((name or "").strip()))


def is_aa_name(name: str) -> bool:
    return bool(re.search(r"_AA(_r\d+)?$", name or "", re.I))


def aa_name_after_upload(name: str) -> str:
    n = (name or "").strip()
    return n + "_AA" if n.lower().endswith("_uld") else n


def count_labels(ann: dict) -> int:
    """기존 라벨 수 — 박스·track·태그 모두 (b23 S1: 태그만 있는 사람 라벨도 라벨)."""
    return len(ann.get("shapes") or []) + len(ann.get("tracks") or []) + len(ann.get("tags") or [])


def _params(ctx) -> dict:
    p = ctx.intake.get("params")
    return p if isinstance(p, dict) else {}


def _work(ctx) -> Path:
    d = Path(ctx.env.tmp) / f"{ctx.kind}_{ctx.rid}_{ctx.task}_{ctx.job}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_now(env, tid: int, fmt: str, dest: str, progress, wait_sec: float = 900) -> str:
    """지금 라벨을 받아 파일로 (준비 요청 → 끝날 때까지 물음 → 받기)."""
    cv = env.cvat
    job = cv.request_export(tid, fmt, images=False)
    t0 = env.clock()
    while True:
        st = cv.job_status(job)
        if st == "finished":
            with H.ticking(progress, "라벨 받는 중"):
                return cv.download(job, dest)
        if st == "failed":
            raise BackupFailed(f"라벨 받기 실패 ({job})")
        if env.clock() - t0 > wait_sec:
            raise BackupFailed(f"라벨 받기가 {wait_sec:.0f}초 안에 끝나지 않음 ({job})")
        progress("라벨 받는 중")
        getattr(env, "sleep", lambda s: None)(3)


# ---------------------------------------------------------------- 준비
def prepare(ctx) -> dict:
    env, tid = ctx.env, int(ctx.task)
    cv = env.cvat
    info = cv.get_task(tid)
    if hasattr(cv, "check_write"):
        cv.check_write(tid, "prepare")                 # 시험 범위 밖이면 무거운 계산 전에 멈춤
    wd = _work(ctx)
    params = _params(ctx)
    out = {"info": info, "params": params}
    if ctx.kind == "track":
        ref = export_now(env, tid, BACKUP_FMT, str(wd / "reference.zip"), ctx.progress)
        r = env.engine.make_track(info, ref, str(wd), params, ctx.progress)
        out.update(file=r["file"], fmt=r.get("fmt", IMPORT_FMT), count=int(r.get("count", 0)), summary=r.get("summary", {}),
                   mode="replace")
    elif ctx.kind in ("shape", "auto"):
        r = env.engine.make_shapes(info, str(wd), params, ctx.progress)
        f = wd / "shapes.json"
        f.write_text(json.dumps({"shapes": r["shapes"]}, ensure_ascii=False), encoding="utf-8")
        out.update(file=str(f), fmt=SHAPES_FMT, count=len(r["shapes"]), summary=r.get("summary", {}), mode="replace")
    elif ctx.kind == "upload_submission":
        out.update(_get_submission(ctx, info, wd))
    else:
        raise H.NoHandler(f"{ctx.kind}.prepare")
    return out


def _get_submission(ctx, info, wd: Path) -> dict:
    """제출본 받기 → 해시·TASK 일치 검사(access.verify_submission). params.submission = 'submissions/<M>/<제출ID>/'"""
    env = ctx.env
    sub = str(_params(ctx).get("submission") or "").strip("/")
    if not sub.startswith("submissions/") or ".." in sub.split("/"):
        raise access.AccessError("제출본 위치가 없음·잘못됨")
    man = env.store.read_json(sub + "/_submission.json")
    for e in man.get("files", []):
        env.store.get_file(f"{sub}/{e['name']}", str(wd / e["name"]))
    (wd / "_submission.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    size = int(info.get("size") or 0)
    fm = env.frame_map(int(ctx.task)) if hasattr(env, "frame_map") else None
    ok, why = access.verify_submission(wd, {"task_id": str(ctx.task), "server": getattr(env, "server", ""),
                                            "frames": size, "labels": info.get("labels") or [],
                                            "frame_range": [0, size - 1], "frame_map_sha": access.frame_map_sha(fm)})
    if not ok:
        raise access.AccessError("제출본이 TASK와 맞지 않음: " + why)
    data = next((e for e in man.get("files", []) if e["name"] == man.get("data", e["name"])), None)
    if not data:
        raise access.AccessError("제출본에 올릴 파일이 없음")
    return {"file": str(wd / data["name"]), "fmt": man.get("format") or IMPORT_FMT, "count": int(man.get("count", 0)),
            "summary": {"submission": sub}, "mode": man.get("mode")}


def wait_import(env, cv, job, progress) -> str:
    """가져오기 작업이 끝날 때까지 물음 → 'finished' | 'failed'(서버가 그 작업을 실패로 끝냄).
    조회 오류(4xx 포함)·시간 초과·모르는 상태는 ImportUnknown — 진행 중일 수 있으므로 되돌리지 않음 (b24 T1)."""
    t0 = env.clock()
    while True:
        try:
            st = cv.import_status(job)
        except Exception as e:
            raise ImportUnknown(f"가져오기 상태를 모름 ({type(e).__name__})")
        if st in ("finished", "failed"):
            return st
        if env.clock() - t0 > getattr(env, "import_wait", IMPORT_WAIT_SEC) or st not in ("queued", "started"):
            raise ImportUnknown(f"가져오기 작업이 끝났는지 모름 ({job}, {st})")
        progress("가져오는 중")
        getattr(env, "sleep", lambda s: None)(5)


# ---------------------------------------------------------------- 확정
def commit(ctx) -> str:
    env, tid, p = ctx.env, int(ctx.task), ctx.prepared or {}
    cv, store = env.cvat, env.store
    wd = _work(ctx)
    # ① 준비 때와 같은 TASK인가
    now = cv.get_task(tid)
    was = p.get("info") or {}
    if now.get("size") != was.get("size") or sorted(now.get("labels") or []) != sorted(was.get("labels") or []):
        raise TaskChanged("준비 뒤 TASK의 프레임 수·라벨 정의가 바뀜")
    name = now.get("name", "")
    # ② 업로드 전 백업 → 복구 자료로 게시 (받지 못하면 쓰지 않음)
    before = export_now(env, tid, BACKUP_FMT, str(wd / "before_upload.zip"), ctx.progress)
    ann = cv.get_annotations(tid)
    existing = count_labels(ann)
    rdir = ctx.step_log.dir().rstrip("/") + "/" if ctx.step_log else f"recovery/{tid}/{ctx.job}/"
    want = {"before_upload.zip": {"sha256": H.sha256_file(before), "size": os.path.getsize(before)}}
    result_name = "result" + (Path(p["file"]).suffix or ".dat")      # 올릴 결과 파일도 복구 자료에 (DESIGN 확정 5단계, 2c-2)
    want[result_name] = {"sha256": H.sha256_file(p["file"]), "size": os.path.getsize(p["file"])}

    def put_recovery():
        with H.ticking(ctx.progress, "복구 자료 올리는 중"):
            store.put_file(before, rdir + "before_upload.zip")
            store.put_file(p["file"], rdir + result_name)
        bad = H.check_files(store, rdir, want)
        if bad:
            raise BackupFailed("복구 자료가 다름: " + ", ".join(bad))
        store.write_json(rdir + "result_plan.json", {"task": str(tid), "name": name, "kind": ctx.kind, "existing": existing,
                                                     "count": p.get("count"), "fmt": p.get("fmt"), "rid": ctx.rid,
                                                     "before_sha256": want["before_upload.zip"]["sha256"],
                                                     "before_size": want["before_upload.zip"]["size"],
                                                     "result_file": result_name, "result_sha256": want[result_name]["sha256"],
                                                     "model": _params(ctx).get("model"),
                                                     "params": _params(ctx)})
    ctx.auth("recovery_publish").call("recovery", put_recovery)
    # ③ 사람 라벨 보호
    mode = p.get("mode") or "replace"
    allow = _params(ctx).get("allow_replace") is True or p.get("allow_replace") is True   # 복구 일: 원래 동의를 이어받음
    if existing > 0 and not is_target(name) and not allow:
        return "held:human_labels"
    replace = existing > 0 and mode == "replace"
    # ④ 쓰기 — 서버 쓰기마다 권한 확인. 되돌리기는 '분명히 실패'(거절·상태 failed)일 때만 (b23 S2·S3)
    w = ctx.auth("cvat_write")
    each = w.ensure                                     # 한 함수 안에서 여러 번 쓰는 곳(shape 500개씩)도 쓸 때마다 확인
    if replace:
        try:
            w.call("remove", lambda: cv.remove_annotations(tid))
        except (access.AuthorityLost, access.AccessError, H.ScopeError):
            raise
        except Exception as e:
            raise ImportUnknown(f"지우기 결과를 모름 ({type(e).__name__})")
    failed_clearly = False
    try:
        with H.ticking(ctx.progress, "가져오는 중"):
            job = w.call("import", lambda: cv.import_annotations(tid, p["file"], p["fmt"], before_each=each))
    except (access.AuthorityLost, access.AccessError, H.ScopeError):
        raise
    except ImportRejected:
        failed_clearly = True                           # 서버가 받지 않음 — 되돌림
    except Exception as e:
        raise ImportUnknown(f"가져오기 응답을 잃음 — 서버에서 진행 중일 수 있음 ({type(e).__name__})")
    if not failed_clearly:
        failed_clearly = wait_import(env, cv, job, ctx.progress) == "failed"
    if failed_clearly:
        # 되돌리기: 쓰기마다 권한을 다시 확인 — 잃었으면 그 자리에서 멈춤 (b23 S3)
        w.call("restore_remove", lambda: cv.remove_annotations(tid))
        if existing > 0:
            try:
                rj = w.call("restore_import", lambda: cv.import_annotations(tid, before, IMPORT_FMT, before_each=each))
            except (access.AuthorityLost, access.AccessError, H.ScopeError):
                raise
            except Exception as e:
                raise ImportUnknown(f"되돌리기 가져오기 결과를 모름 ({type(e).__name__})")
            if wait_import(env, cv, rj, ctx.progress) != "finished":
                raise ImportUnknown("되돌리기 가져오기가 끝나지 않음")
        return "failed:import(restored)"
    # ⑤ 결과 확인
    after = count_labels(cv.get_annotations(tid))
    expect = (0 if replace else existing) + int(p.get("count") or 0)
    if after < expect or (p.get("exact_count") and after != expect):
        raise ResultMismatch(f"올린 뒤 라벨 수 {after} < 기대 {expect}")
    # ⑥ 이름 규칙
    new = p.get("rename_to") or aa_name_after_upload(name)       # 되돌리기는 원래 이름으로 (2b-5b)
    if new != name:
        w.call("rename", lambda: cv.rename_task(tid, new))
    # ⑦ AA TASK 교체 → 이전 라벨 보관
    if replace and is_aa_name(name) and p.get("archive", True):
        stem = re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", name)
        dst = f"exports/_aa_replaced/{stem}__{tid}__{ctx.rid}.zip"
        try:
            store.put_file(before, dst)
        except StoreError:
            pass                                       # 보관 실패는 복구 자료가 있으므로 결과를 바꾸지 않음
    return "done"


# ---------------------------------------------------------------- 실제 계산 (실행 호스트가 영상·모델을 넘겨줌)
class RealEngine:
    """track: yolo_track_to_cvat.py (5번 셀·30번 셀과 같은 인자), shape: auto_annotate_frames(collect_only).
    model_for(params) → 로컬 모델 경로, video_for(info, ref_zip) → (영상 경로, frame_map 또는 None) 은 호스트가 줌(2b-6)."""

    def __init__(self, scripts_dir, cvat, model_for, video_for, device="0", settings=None):
        self.scripts, self.cvat, self.model_for, self.video_for, self.device = Path(scripts_dir), cvat, model_for, video_for, device
        # v4.32 0번 셀의 TRACK_* 기본값, 자료형·선택값은 yolo_track_to_cvat.py의 인자와 같게 (b23 S5)
        self.s = dict(imgsz=1920, conf=0.3, fill_gaps=3, track_buffer=90, decoder="pyav", frame_offset=0,
                      box_source="detection", near=1)
        self.s.update(settings or {})

    def track_args(self, model, video, ref_zip, out, params, fm=None):
        """yolo_track_to_cvat.py 명령 (시험에서 실제 인자 해석기로 확인)."""
        s = self.s
        conf = float(params.get("conf", s["conf"]))
        args = [sys.executable, str(self.scripts / "yolo_track_to_cvat.py"), "--model", str(model), "--video", str(video),
                "--reference", str(ref_zip), "--imgsz", str(int(s["imgsz"])), "--conf", str(conf),
                "--fill-gaps", str(int(s["fill_gaps"])), "--track-buffer", str(int(s["track_buffer"])),
                "--decoder", "pyav" if fm else str(s["decoder"]), "--frame-offset", "0" if fm else str(int(s["frame_offset"])),
                "--box-source", str(s["box_source"]), "--near", str(int(s["near"])), "--device", self.device, "--out", str(out)]
        if fm:
            args += ["--frame-map", ",".join(map(str, fm))]
        return args

    def make_track(self, info, ref_zip, workdir, params, progress):
        model = self.model_for(params)
        video, fm = self.video_for(info, ref_zip)
        out = Path(workdir) / "track"
        args = self.track_args(model, video, ref_zip, out, params, fm)
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:                       # 줄마다 진행을 알림 (멈춤 한도)
            progress(line.strip()[:80])
        if proc.wait() != 0:
            raise RuntimeError("track 생성 실패")
        xml = next(out.glob("tracks_*.xml"))
        n = len(re.findall(r"<track ", xml.read_text(encoding="utf-8")))
        return {"file": str(xml), "fmt": IMPORT_FMT, "count": n}

    def make_shapes(self, info, workdir, params, progress):
        import cvat_task_tools as ctt
        task = self.cvat.client().tasks.retrieve(int(info["id"]))
        r = ctt.auto_annotate_frames(task, self.scripts / "cvat_yolo_function.py", self.model_for(params),
                                     imgsz=self.s["imgsz"], device=self.device, conf=float(params.get("conf", self.s["conf"])),
                                     log=lambda m: progress(str(m)[:80]), collect_only=True)
        return {"shapes": r["shapes"], "summary": {"per_label": r["per_label"], "frames": r["frames"]}}


for _k in ("track", "shape", "auto", "upload_submission"):
    H.register(_k, prepare=prepare, commit=commit)
