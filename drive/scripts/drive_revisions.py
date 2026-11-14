"""Google Drive 버전 기록에서 사용자별 마지막 버전을 찾아 다른 이름으로 복원 (23번 셀)

두 사람이 같은 학습 이름(runs/<이름>)으로 동시에 학습해 파일이 서로 덮어써졌을 때,
Drive가 파일마다 보관하는 이전 버전(revision) 중 '각 사용자가 마지막으로 저장한 버전'을 골라
runs/<이름>_A/, runs/<이름>_B/ 처럼 따로 내려받는다. 원본 파일은 건드리지 않는다.

한계
- Drive는 파일마다 이전 버전을 약 30일 / 100개까지만 보관한다 (영구 보관 표시한 것 제외).
  last.pt처럼 에폭마다 다시 쓰는 파일은 100개를 넘으면 오래된 버전부터 사라진다 → 빨리 실행.
- 사용자는 '마지막으로 수정한 Google 계정'으로 구분한다. 두 사람이 같은 계정으로 Drive를 연결했다면 나눌 수 없다.
- revisions.list가 버전이 아주 많은 파일에서는 일부만 돌려줄 수 있다 (Drive API 문서).
"""
__version__ = "4.32.0"

import csv
import datetime as _dt
import io
import json
import os
import re
from collections import defaultdict
from pathlib import Path

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
REV_FIELDS = ("nextPageToken,revisions(id,modifiedTime,size,keepForever,md5Checksum,"
              "lastModifyingUser(displayName,emailAddress,me))")
KST = _dt.timezone(_dt.timedelta(hours=9))


# ---------------- 접속 ----------------
def drive_service():
    """Colab에서 Google 계정 인증 후 Drive API v3 (처음 한 번 팝업으로 허용)"""
    try:
        from google.colab import auth
        auth.authenticate_user()
    except ImportError:
        pass
    from googleapiclient.discovery import build
    return build("drive", "v3", cache_discovery=False)


def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _list(svc, q, fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,shortcutDetails)"):
    out, tok = [], None
    while True:
        r = svc.files().list(q=q, fields=fields, pageSize=1000, pageToken=tok, supportsAllDrives=True,
                             includeItemsFromAllDrives=True, corpora="allDrives").execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def _resolve(f):
    """바로가기면 대상 (id, mimeType)"""
    if f.get("mimeType") == SHORTCUT and f.get("shortcutDetails"):
        return f["shortcutDetails"]["targetId"], f["shortcutDetails"].get("targetMimeType", "")
    return f["id"], f.get("mimeType", "")


def path_to_id(svc, path):
    """Colab의 Drive 경로 → 파일/폴더 id. 먼저 FUSE 속성(user.drive.id), 안 되면 API로 경로를 따라감"""
    try:
        v = os.getxattr(path, "user.drive.id")
        if v:
            return v.decode() if isinstance(v, bytes) else v
    except Exception:
        pass
    p = str(path).rstrip("/")
    m = re.match(r"^/content/drive/(MyDrive|My Drive)(/.*)?$", p)
    m2 = re.match(r"^/content/drive/\.shortcut-targets-by-id/([^/]+)(/.*)?$", p)
    m3 = re.match(r"^/content/drive/Shareddrives/([^/]+)(/.*)?$", p)
    if m:
        cur, rest = "root", m.group(2) or ""
    elif m2:
        cur, rest = m2.group(1), m2.group(2) or ""
        rest = "/".join(rest.split("/")[2:]) if rest.count("/") >= 1 else ""   # 첫 칸은 공유 폴더 자신의 이름
    elif m3:
        drives = svc.drives().list(pageSize=100, q=f"name = '{_q(m3.group(1))}'").execute().get("drives", [])
        if not drives:
            raise FileNotFoundError(f"공유 드라이브 없음: {m3.group(1)}")
        cur, rest = drives[0]["id"], m3.group(2) or ""
    else:
        raise ValueError(f"Drive 경로가 아님: {path}")
    for part in [x for x in rest.split("/") if x]:
        hits = _list(svc, f"'{cur}' in parents and name = '{_q(part)}' and trashed = false")
        if not hits:
            raise FileNotFoundError(f"Drive에서 찾지 못함: {part} (경로 {path})")
        cur, _ = _resolve(hits[0])
    return cur


def walk(svc, folder_id, rel=""):
    """폴더 아래 모든 파일 [(상대경로, id, size)] (하위 폴더 포함)"""
    out = []
    for f in _list(svc, f"'{folder_id}' in parents and trashed = false"):
        fid, mt = _resolve(f)
        r = f"{rel}/{f['name']}" if rel else f["name"]
        if mt == FOLDER:
            out += walk(svc, fid, r)
        else:
            out.append((r, fid, int(f.get("size") or 0)))
    return out


# ---------------- 버전 목록 ----------------
def revisions(svc, file_id):
    out, tok = [], None
    while True:
        r = svc.revisions().list(fileId=file_id, fields=REV_FIELDS, pageSize=200, pageToken=tok).execute()
        out += r.get("revisions", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    for v in out:
        u = v.get("lastModifyingUser") or {}
        v["user"] = u.get("emailAddress") or u.get("displayName") or "(알 수 없음)"
        v["user_name"] = u.get("displayName") or v["user"]
        v["t"] = _dt.datetime.fromisoformat(v["modifiedTime"].replace("Z", "+00:00"))
    return sorted(out, key=lambda v: v["t"])


def _kst(t):
    return t.astimezone(KST).strftime("%m-%d %H:%M:%S") if t else ""


def _parse_until(until):
    if not until:
        return None
    if isinstance(until, _dt.datetime):
        return until if until.tzinfo else until.replace(tzinfo=KST)
    return _dt.datetime.fromisoformat(str(until).strip()).replace(tzinfo=KST)   # 한국 시각으로 적음


def collect(svc, base, name, extra=("datasets/{name}.zip", "datasets/{name}.sig", "datasets/{name}_report.html"),
            log=print):
    """runs/<name>/ 아래 파일 + 추가 파일들의 버전 기록 → [{'rel','dest_kind','id','revs'}]"""
    items = []
    run_path = f"{base}/runs/{name}"
    try:
        rid = path_to_id(svc, run_path)
        files = walk(svc, rid)
        log(f"runs/{name}: 파일 {len(files)}개")
        for rel, fid, _ in files:
            items.append({"rel": f"runs/{name}/{rel}", "sub": rel, "kind": "run", "id": fid})
    except FileNotFoundError:
        log(f"⚠️ runs/{name} 폴더를 찾지 못했습니다")
    for e in extra:
        rel = e.format(name=name)
        try:
            items.append({"rel": rel, "sub": rel, "kind": "extra", "id": path_to_id(svc, f"{base}/{rel}")})
        except FileNotFoundError:
            pass
    for k, it in enumerate(items, 1):
        try:
            it["revs"] = revisions(svc, it["id"])
        except Exception as ex:          # 권한 없음 등
            it["revs"], it["error"] = [], str(ex)[:120]
        if k % 10 == 0:
            log(f"  버전 기록 읽는 중 {k}/{len(items)}")
    return items


def users_of(items):
    """사용자 → 처음 저장 시각 (먼저 시작한 사람이 A)"""
    first = {}
    for it in items:
        for v in it["revs"]:
            if v["user"] not in first or v["t"] < first[v["user"]]:
                first[v["user"]] = v["t"]
    return dict(sorted(first.items(), key=lambda kv: kv[1]))


def auto_suffixes(items):
    return {u: chr(ord("A") + i) for i, u in enumerate(users_of(items))}


def pick(items, until=None):
    """파일마다 사용자별 마지막 버전 → rows (표)"""
    cut = _parse_until(until)
    rows = []
    for it in items:
        by = defaultdict(list)
        for v in it["revs"]:
            if cut is None or v["t"] <= cut:
                by[v["user"]].append(v)
        newest = it["revs"][-1]["user"] if it["revs"] else ""
        for u, vs in by.items():
            v = vs[-1]
            rows.append({"파일": it["rel"], "사용자": u, "이름": v["user_name"], "마지막 저장(KST)": _kst(v["t"]),
                         "크기": int(v.get("size") or 0), "그 사용자 버전 수": len(vs),
                         "지금 파일": "← 지금 이것" if (u == newest and v is it["revs"][-1]) else "",
                         "영구보관": bool(v.get("keepForever")), "_it": it, "_rev": v})
        if not by:
            rows.append({"파일": it["rel"], "사용자": "", "이름": "", "마지막 저장(KST)": "",
                         "크기": 0, "그 사용자 버전 수": 0, "지금 파일": "",
                         "영구보관": False, "_it": it, "_rev": None,
                         "비고": it.get("error", "남은 버전 없음")})
    return rows


def pin(svc, rows, log=print):
    """찾은 버전을 영구 보관(keepForever)으로 → 30일/100개 자동 삭제에서 제외 (파일 편집 권한 필요)"""
    n = 0
    for r in rows:
        v = r["_rev"]
        if v is None or v.get("keepForever"):
            continue
        try:
            svc.revisions().update(fileId=r["_it"]["id"], revisionId=v["id"], body={"keepForever": True}).execute()
            v["keepForever"] = r["영구보관"] = True
            n += 1
        except Exception as ex:
            log(f"  영구 보관 실패 {r['파일']} ({str(ex)[:80]})")
    return n


def download_rev(svc, file_id, rev_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with open(tmp, "wb") as fh:
        dl = MediaIoBaseDownload(fh, svc.revisions().get_media(fileId=file_id, revisionId=rev_id),
                                 chunksize=64 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
    tmp.replace(dest)
    return dest


def restore(svc, base, name, rows, suffixes, overwrite=False, log=print, downloader=None):
    """사용자별 마지막 버전을 runs/<name>_<접미사>/ · datasets/<name>_<접미사>.* 로 내려받음"""
    downloader = downloader or download_rev
    done = defaultdict(list)
    for r in rows:
        v, u = r["_rev"], r["사용자"]
        if v is None or u not in suffixes:
            continue
        new = f"{name}_{suffixes[u]}"
        it = r["_it"]
        if it["kind"] == "run":
            dest = Path(base) / "runs" / new / it["sub"]
        else:
            d, b = os.path.split(it["sub"])
            b = new + b[len(name):] if b.startswith(name) else f"{new}__{b}"
            dest = Path(base) / d / b
        if dest.exists() and not overwrite:
            log(f"  있음 → 건너뜀: {dest.relative_to(base)}")
            done[u].append((it["rel"], str(dest), "있음"))
            continue
        downloader(svc, it["id"], v["id"], dest)
        log(f"  {suffixes[u]} ← {it['rel']} ({_kst(v['t'])}, {r['이름']}) → {dest.relative_to(base)}")
        done[u].append((it["rel"], str(dest), _kst(v["t"])))
    for u, files in done.items():
        new = f"{name}_{suffixes[u]}"
        rd = Path(base) / "runs" / new
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "RESTORED_FROM.json").write_text(json.dumps(
            {"from": f"runs/{name}", "user": u, "suffix": suffixes[u],
             "restored_at": _dt.datetime.now(KST).isoformat(timespec="seconds"),
             "files": [{"src": a, "dest": os.path.relpath(b, base), "revision_time_kst": c} for a, b, c in files]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        if (rd / "weights" / "best.pt").exists() and not (rd / "TRAINING_DONE").exists():
            (rd / "TRAINING_DONE").write_text(f"복원본 (Drive 버전 기록, {u}) — 이어서 학습하지 마세요", encoding="utf-8")
        split_results_csv(rd / "results.csv", log=log)
    return done


# ---------------- results.csv 정리 ----------------
def split_results_csv(path, log=print):
    """두 학습이 한 results.csv에 섞여 쓴 경우: (epoch가 1씩 늘고 time이 커지는) 줄끼리 묶어 나눔 — 추정
    나뉘면 results_part1.csv, results_part2.csv … 로 저장하고 개수를 돌려줌"""
    path = Path(path)
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        return 0
    head = [h.strip() for h in lines[0].split(",")]
    try:
        ie, it = head.index("epoch"), head.index("time") if "time" in head else None
    except ValueError:
        return 0
    seqs = []                                  # [[줄...], 마지막 epoch, 마지막 time]
    for ln in lines[1:]:
        if not ln.strip() or ln.strip().startswith("epoch"):
            continue
        c = [x.strip() for x in ln.split(",")]
        try:
            e = int(float(c[ie]))
            t = float(c[it]) if it is not None else None
        except (ValueError, IndexError):
            continue
        tgt = None
        for s in seqs:
            if e == s[1] + 1 and (t is None or s[2] is None or t >= s[2]):
                tgt = s
                break
        if tgt is None:
            tgt = [[], 0, None]
            seqs.append(tgt)
        tgt[0].append(ln)
        tgt[1], tgt[2] = e, t
    seqs = [s for s in seqs if s[0]]
    if len(seqs) <= 1:
        return 1
    for k, s in enumerate(seqs, 1):
        (path.parent / f"results_part{k}.csv").write_text("\n".join([lines[0]] + s[0]) + "\n", encoding="utf-8")
    log(f"  ⚠️ {path.parent.name}/results.csv에 학습 {len(seqs)}개가 섞여 있어 나눴습니다 (추정): "
        + ", ".join(f"part{k} 에폭 {len(s[0])}개" for k, s in enumerate(seqs, 1)))
    return len(seqs)


# ---------------- 체크포인트 확인 ----------------
def ckpt_info(path):
    """best.pt/last.pt 안의 기록: 저장 시각, 에폭, best_fitness, 학습 설정(data·name), 기록된 에폭 수"""
    import torch
    try:
        ck = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        ck = torch.load(path, map_location="cpu")
    ta = ck.get("train_args") or {}
    tr = ck.get("train_results") or {}
    ep_list = tr.get("epoch") if isinstance(tr, dict) else None
    tm = ck.get("train_metrics") or {}
    return {"파일": str(path), "저장 시각": ck.get("date", ""), "epoch(-1=학습 끝)": ck.get("epoch"),
            "best_fitness": None if ck.get("best_fitness") is None else round(float(ck["best_fitness"]), 4),
            "mAP50-95": round(float(tm["metrics/mAP50-95(B)"]), 4) if "metrics/mAP50-95(B)" in tm else None,
            "기록 에폭 수": len(ep_list) if ep_list else None,
            "data": ta.get("data", ""), "name": ta.get("name", ""), "epochs": ta.get("epochs"),
            "imgsz": ta.get("imgsz"), "model": ta.get("model", "")}


def save_table(rows, path):
    keys = [k for k in rows[0] if not k.startswith("_")] if rows else []
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
