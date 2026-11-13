"""
학습 계획 연구 (v4.31.8) — 33번 셀이 씀

1) TASK 지문: 배경(박스 밖 밝기·초록 비율·바닥 색)과 개체(프레임당 박스·가림·작은 박스·겹침)를 숫자로
2) 모델 성적: TASK마다 같은 프레임을 모델로 탐지해 검토 뒤 라벨과 비교 — 클래스별 정밀도·재현율·F1 + 개수 오차
3) 관계: 성적이 지문(어두움·밀도 …)과 '학습에 쓰였는지'에 따라 얼마나 달라지는지 (표준화 회귀 + 부트스트랩 구간)
4) 분할안 시뮬레이션: train/val/시험 TASK를 정하면 시험·val TASK마다 가장 가까운 train TASK와의 거리(덮임)·예상 재현율

박스 형식은 cvat_task_tools.load_annotations와 같음: {frame: [(id, label, occluded, (x1, y1, x2, y2), ...)]}
이미지는 PIL (cvat_task_tools.cvat_frame_getter). numpy만 씀 (scikit-learn 필요 없음).
"""
__version__ = "4.31.8"
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

SIM_DIR = "sim"
FP_FILE = f"{SIM_DIR}/fingerprints.csv"
EVAL_FILE = f"{SIM_DIR}/eval.csv"
FP_IMG_KEYS = ("bg_luma", "bg_dark", "green_ratio", "floor_luma", "floor_sat", "floor_hue_sin", "floor_hue_cos")
FP_BOX_KEYS = ("boxes_per_frame", "occl_ratio", "small_ratio", "overlap_ratio", "box_area_med")
FP_KEYS = FP_IMG_KEYS + FP_BOX_KEYS
FP_KO = {"bg_luma": "배경 밝기", "bg_dark": "어두운 배경 비율", "green_ratio": "초록(잎) 비율", "floor_luma": "바닥 밝기",
         "floor_sat": "바닥 채도", "floor_hue_sin": "바닥 색상(sin)", "floor_hue_cos": "바닥 색상(cos)",
         "boxes_per_frame": "프레임당 박스", "occl_ratio": "가림 비율", "small_ratio": "작은 박스 비율",
         "overlap_ratio": "겹친 박스 비율", "box_area_med": "박스 크기(중앙값, 화면 대비 ‰)", "in_train": "학습에 쓰임"}
# 관계·거리에 쓰는 지문 (서로 거의 같은 것은 하나만)
REL_KEYS = ("bg_luma", "green_ratio", "floor_sat", "floor_hue_sin", "floor_hue_cos", "boxes_per_frame", "occl_ratio", "small_ratio")
SMALL_AREA = 0.0015          # 화면 넓이 대비 이보다 작은 박스 = 작은 박스 (1920×1080에서 약 56×56)
IOU = 0.5


# ---------------------------------------------------------------- 공통
def base_label(lab):
    lab = str(lab or "")
    return lab[:-9] if lab.endswith("_occluded") else lab


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def pick_frames(ann, n=12):
    """TASK 전체에서 고르게 n장 (박스 없는 프레임 포함 — 잘못 그림도 세려고)"""
    fr = list(ann.get("frames") or sorted(ann["boxes"]))
    if n and len(fr) > n:
        step = (len(fr) - 1) / (n - 1)
        fr = sorted({fr[round(i * step)] for i in range(n)})
    return fr


def _rgb_array(img, max_side=640):
    """PIL → 작게 줄인 RGB numpy (float 0..1)와 줄인 비율"""
    im = img.convert("RGB")
    s = min(1.0, max_side / max(im.size))
    if s < 1.0:
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
    return np.asarray(im, dtype=np.float32) / 255.0, s


def _hsv(a):
    """RGB(0..1) → H(0..360), S, V"""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rr = m & (mx == r)
    gg = m & (mx == g) & ~rr
    bb = m & ~rr & ~gg
    h[rr] = (60 * ((g[rr] - b[rr]) / d[rr]) + 360) % 360
    h[gg] = 60 * ((b[gg] - r[gg]) / d[gg]) + 120
    h[bb] = 60 * ((r[bb] - g[bb]) / d[bb]) + 240
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


# ---------------------------------------------------------------- 1) 지문
def box_stats(ann, frames, W, H):
    """박스만으로 재는 개체 지문 (이미지 필요 없음)"""
    area = float((W or 1) * (H or 1))
    n_box, n_occl, n_small, n_ovl, areas, per_label = 0, 0, 0, 0, [], defaultdict(int)
    for f in frames:
        bs = list(ann["boxes"].get(f, []))
        for i, b in enumerate(bs):
            xy = b[3]
            a = max(0.0, (xy[2] - xy[0]) * (xy[3] - xy[1])) / area
            n_box += 1
            per_label[base_label(b[1])] += 1
            areas.append(a)
            n_occl += bool(b[2]) or str(b[1]).endswith("_occluded")
            n_small += a < SMALL_AREA
            if any(iou(xy, c[3]) > 0.1 for j, c in enumerate(bs) if j != i):
                n_ovl += 1
    nf = max(1, len(frames))
    return {"frames": len(frames), "boxes": n_box, "boxes_per_frame": round(n_box / nf, 3),
            "occl_ratio": round(n_occl / n_box, 4) if n_box else 0.0, "small_ratio": round(n_small / n_box, 4) if n_box else 0.0,
            "overlap_ratio": round(n_ovl / n_box, 4) if n_box else 0.0,
            "box_area_med": round(float(np.median(areas)) * 1000, 3) if areas else 0.0,
            "per_label": dict(per_label)}


def image_stats(img, boxes, W, H, floor_frac=0.15):
    """이미지 한 장의 배경 지문: 박스 밖 밝기·어두운 비율·초록 비율 · 아래쪽 floor_frac(바닥)의 밝기·채도·색상"""
    a, s = _rgb_array(img)
    h, w = a.shape[:2]
    sx, sy = w / float(W or img.width), h / float(H or img.height)
    mask = np.ones((h, w), bool)
    for b in boxes:
        x1, y1, x2, y2 = b[3]
        mask[max(0, int(y1 * sy)):max(0, int(math.ceil(y2 * sy))), max(0, int(x1 * sx)):max(0, int(math.ceil(x2 * sx)))] = False
    luma = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    hue, sat, val = _hsv(a)
    bg = mask if mask.any() else np.ones_like(mask)
    green = (hue >= 60) & (hue <= 170) & (sat > 0.2) & (val > 0.12)
    fl = np.zeros_like(mask)
    fl[int(h * (1 - floor_frac)):, :] = True
    fl &= mask if (fl & mask).any() else fl
    fh = hue[fl] * math.pi / 180
    wgt = sat[fl] + 1e-6                                    # 색이 옅은 곳은 색상 평균에서 덜 셈
    return {"bg_luma": float(luma[bg].mean()), "bg_dark": float((luma[bg] < 0.2).mean()), "green_ratio": float(green[bg].mean()),
            "floor_luma": float(luma[fl].mean()), "floor_sat": float(sat[fl].mean()),
            "floor_hue_sin": float((np.sin(fh) * wgt).sum() / wgt.sum()), "floor_hue_cos": float((np.cos(fh) * wgt).sum() / wgt.sum())}


def fingerprint(ann, frames, imgs, W, H):
    """TASK 지문 = 박스 지문 + 이미지 지문 평균 (받은 이미지만)"""
    out = box_stats(ann, frames, W, H)
    vals = defaultdict(list)
    for f in frames:
        im = imgs.get(f)
        if im is None:
            continue
        for k, v in image_stats(im, ann["boxes"].get(f, []), W, H).items():
            vals[k].append(v)
    for k in FP_IMG_KEYS:
        out[k] = round(float(np.mean(vals[k])), 4) if vals.get(k) else None
    out["img_frames"] = len(vals.get("bg_luma", []))
    return out


# ---------------------------------------------------------------- 2) 성적 · 개수 오차
def evaluate(ann, frames, preds, labels=None, iou_thr=IOU):
    """preds = {frame: [(label, occluded, (x1,y1,x2,y2))]} (모델) ↔ ann(검토 뒤 정답).
    라벨별 맞힘·오탐·놓침 + 프레임별 개수 차이 → {라벨: {...}, '_all': {...}}"""
    labs = set(labels) if labels else ({base_label(b[1]) for f in frames for b in ann["boxes"].get(f, [])}
                                       | {base_label(p[0]) for f in frames for p in preds.get(f, [])})
    acc = {l: {"tp": 0, "fp": 0, "fn": 0, "gt": 0, "pred": 0, "abs_err": 0, "signed_err": 0, "frames": 0} for l in labs}
    for f in frames:
        for l in labs:
            G = [b[3] for b in ann["boxes"].get(f, []) if base_label(b[1]) == l]
            P = [p[2] for p in preds.get(f, []) if base_label(p[0]) == l]
            pairs = sorted(((iou(p, g), i, j) for i, p in enumerate(P) for j, g in enumerate(G)), reverse=True)
            up, ug, tp = set(), set(), 0
            for v, i, j in pairs:
                if v < iou_thr:
                    break
                if i in up or j in ug:
                    continue
                up.add(i); ug.add(j); tp += 1
            a = acc[l]
            a["tp"] += tp; a["fp"] += len(P) - tp; a["fn"] += len(G) - tp
            a["gt"] += len(G); a["pred"] += len(P)
            a["abs_err"] += abs(len(P) - len(G)); a["signed_err"] += len(P) - len(G); a["frames"] += 1
    tot = {k: sum(acc[l][k] for l in labs) for k in ("tp", "fp", "fn", "gt", "pred", "abs_err", "signed_err")}
    tot["frames"] = len(frames)
    acc["_all"] = tot
    return {l: _scores(v) for l, v in acc.items()}


def _scores(a):
    p = a["tp"] / (a["tp"] + a["fp"]) if a["tp"] + a["fp"] else None
    r = a["tp"] / (a["tp"] + a["fn"]) if a["tp"] + a["fn"] else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    nf = max(1, a["frames"])
    return dict(a, precision=_r(p), recall=_r(r), f1=_r(f1),
                count_mae=round(a["abs_err"] / nf, 3),                                  # 프레임당 개수 오차 (개)
                count_rel=_r(a["abs_err"] / a["gt"]) if a["gt"] else None,              # 정답 개수 대비 오차 비율
                count_bias=_r(a["signed_err"] / a["gt"]) if a["gt"] else None)          # + = 많이 셈 · − = 덜 셈


def _r(v, n=4):
    return None if v is None else round(float(v), n)


# ---------------------------------------------------------------- 저장 · 읽기
def _read_csv(p):
    p = Path(p)
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _write_csv(p, rows, cols):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    tmp.replace(p)


FP_COLS = ["task_id", "task_name", "gh", "date", "row", "plant", "ref_file", "time", "frames", "img_frames", "boxes", *FP_KEYS, "per_label"]
EVAL_COLS = ["task_id", "task_name", "gh", "date", "model", "label", "in_train", "ref_file", "time", "frames",
             "gt", "pred", "tp", "fp", "fn", "precision", "recall", "f1", "count_mae", "count_rel", "count_bias"]


def read_fingerprints(base):
    """{task_id: 지문 행} (같은 TASK가 여럿이면 나중 것)"""
    out = {}
    for r in _read_csv(Path(base) / FP_FILE):
        out[str(r["task_id"])] = r
    return out


def save_fingerprint(base, row):
    rows = [r for r in _read_csv(Path(base) / FP_FILE) if str(r.get("task_id")) != str(row["task_id"])]
    row = dict(row, per_label=json.dumps(row.get("per_label") or {}, ensure_ascii=False))
    _write_csv(Path(base) / FP_FILE, rows + [row], FP_COLS)


def read_eval(base):
    return _read_csv(Path(base) / EVAL_FILE)


def save_eval(base, rows):
    """같은 (TASK, 모델)의 이전 결과는 바꿈"""
    keys = {(str(r["task_id"]), r["model"]) for r in rows}
    old = [r for r in read_eval(base) if (str(r.get("task_id")), r.get("model")) not in keys]
    _write_csv(Path(base) / EVAL_FILE, old + rows, EVAL_COLS)


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 3) 관계
def relation(fp, ev, model, label="_all", metric="recall", keys=REL_KEYS, n_boot=300, seed=0):
    """성적(metric) ~ 지문(표준화) + 학습에 쓰임 — 계수 = 그 지문이 1 표준편차 늘 때 성적 변화.
    반환 {'n', 'coef': [{key, ko, sd(원래 단위), effect, lo, hi}], 'r2', 'warn'} — n이 적으면 구간이 넓음"""
    X, y = [], []
    for r in ev:
        if r.get("model") != model or r.get("label") != label:
            continue
        f = fp.get(str(r["task_id"]))
        v = _num(r.get(metric))
        if f is None or v is None:
            continue
        x = [_num(f.get(k)) for k in keys]
        if any(t is None for t in x):
            continue
        X.append(x + [1.0 if str(r.get("in_train")).lower() in ("1", "true", "train", "val") else 0.0])
        y.append(v)
    names = list(keys) + ["in_train"]
    n = len(y)
    if n < len(names) + 3:
        return {"n": n, "coef": [], "r2": None, "warn": f"TASK {n}개 — 관계를 재려면 최소 {len(names) + 3}개 필요"}
    X, y = np.array(X), np.array(y)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    Z[:, -1] = X[:, -1]                                    # 학습에 쓰임은 0/1 그대로 (효과 = 쓰였을 때 차이)

    def fit(Zs, ys, lam=1.0):
        A = np.c_[np.ones(len(ys)), Zs]
        I = np.eye(A.shape[1]); I[0, 0] = 0
        return np.linalg.solve(A.T @ A + lam * I, A.T @ ys)   # 작은 능형(ridge) — TASK가 적어도 안정되게
    b = fit(Z, y)
    pred = np.c_[np.ones(n), Z] @ b
    ss = ((y - y.mean()) ** 2).sum()
    r2 = float(1 - ((y - pred) ** 2).sum() / ss) if ss > 0 else None
    rng = np.random.default_rng(seed)
    boots = np.array([fit(Z[i], y[i]) for i in (rng.integers(0, n, n) for _ in range(n_boot))])
    lo, hi = np.percentile(boots, 5, 0), np.percentile(boots, 95, 0)
    coef = [{"key": k, "ko": FP_KO.get(k, k), "sd": round(float(sd[j]), 4) if k != "in_train" else None,
             "effect": round(float(b[j + 1]), 4), "lo": round(float(lo[j + 1]), 4), "hi": round(float(hi[j + 1]), 4),
             "sure": bool(lo[j + 1] > 0 or hi[j + 1] < 0)} for j, k in enumerate(names)]
    coef.sort(key=lambda c: -abs(c["effect"]))
    return {"n": n, "coef": coef, "r2": None if r2 is None else round(r2, 3), "model": model, "label": label, "metric": metric,
            "mean": round(float(y.mean()), 4), "mu": dict(zip(names, map(float, mu))), "sdv": dict(zip(names, map(float, sd))),
            "b": [float(v) for v in b], "keys": names,
            "warn": "" if n >= 30 else f"TASK {n}개 — 구간이 넓습니다 (30개 이상 권장)"}


def group_table(fp, ev, model, label="_all", by="gh"):
    """온실(또는 날짜)별 평균: 지문 몇 가지 + 성적 + 개수 오차 — 관찰(G6 어둡고 조밀 …)이 숫자로 맞는지"""
    g = defaultdict(lambda: defaultdict(list))
    for tid, f in fp.items():
        k = f.get(by) or "?"
        for c in ("bg_luma", "bg_dark", "green_ratio", "floor_sat", "boxes_per_frame", "occl_ratio", "small_ratio"):
            v = _num(f.get(c))
            if v is not None:
                g[k][c].append(v)
        g[k]["_tasks"].append(tid)
    for r in ev:
        if r.get("model") != model or r.get("label") != label:
            continue
        k = (fp.get(str(r["task_id"])) or {}).get(by) or r.get(by) or "?"
        for c in ("recall", "precision", "f1", "count_rel", "count_bias"):
            v = _num(r.get(c))
            if v is not None:
                g[k][c].append(v)
    out = []
    for k in sorted(g):
        row = {by: k, "tasks": len(set(g[k]["_tasks"]))}
        for c, vs in g[k].items():
            if c != "_tasks":
                row[c] = round(float(np.mean(vs)), 3) if vs else None
        out.append(row)
    return out


# ---------------------------------------------------------------- 4) 분할안 시뮬레이션
def _vec(f, keys):
    v = [_num(f.get(k)) for k in keys]
    return None if any(t is None for t in v) else np.array(v)


def simulate(fp, train_ids, eval_ids, rel=None, keys=REL_KEYS, roles=None):
    """train_ids로 학습한다고 할 때 eval_ids(val·시험) TASK마다: 가장 가까운 train TASK · 거리 · 덮임 · 예상 성적.
    덮임 기준 = train TASK끼리의 가장 가까운 거리 90%값보다 멀면 '덮이지 않음' (train에 없는 환경)
    rel = relation() 결과 (있으면 예상 성적 = 학습에 안 쓰인 TASK 기준)"""
    tr = [(t, _vec(fp[t], keys)) for t in map(str, train_ids) if t in fp]
    tr = [(t, v) for t, v in tr if v is not None]
    if len(tr) < 2:
        return {"error": f"지문이 있는 train TASK가 {len(tr)}개 — 먼저 지문을 만드세요", "rows": []}
    M = np.array([v for _, v in tr])
    mu, sd = M.mean(0), M.std(0)
    sd[sd == 0] = 1.0
    Zt = (M - mu) / sd
    nn_tr = [float(np.sort(np.linalg.norm(Zt - Zt[i], axis=1))[1]) for i in range(len(Zt))]
    thr = float(np.percentile(nn_tr, 90))
    rows = []
    for t in map(str, eval_ids):
        f = fp.get(t)
        v = None if f is None else _vec(f, keys)
        if v is None:
            rows.append({"task_id": t, "task_name": (f or {}).get("task_name", ""), "role": (roles or {}).get(t, ""), "note": "지문 없음"})
            continue
        d = np.linalg.norm(Zt - (v - mu) / sd, axis=1)
        j = int(d.argmin())
        row = {"task_id": t, "task_name": f.get("task_name", ""), "gh": f.get("gh", ""), "date": f.get("date", ""),
               "role": (roles or {}).get(t, ""), "nearest": tr[j][0], "nearest_name": fp[tr[j][0]].get("task_name", ""),
               "distance": round(float(d[j]), 3), "covered": bool(d[j] <= thr),
               "far_keys": ", ".join(FP_KO.get(keys[i], keys[i]) for i in np.argsort(-np.abs((v - M[j]) / sd))[:2])}
        if rel and rel.get("b"):
            x = [(_num(f.get(k)) - rel["mu"][k]) / rel["sdv"][k] for k in rel["keys"] if k != "in_train"] + [0.0]
            row["pred_" + rel.get("metric", "recall")] = round(float(np.clip(rel["b"][0] + np.dot(rel["b"][1:], x), 0, 1)), 3)
        rows.append(row)
    by = defaultdict(lambda: {"n": 0, "uncovered": 0})
    for r in rows:
        if "distance" in r:
            by[r["gh"]]["n"] += 1
            by[r["gh"]]["uncovered"] += (not r["covered"])
    comp = defaultdict(lambda: {"tasks": 0, "boxes": 0})
    for t, _ in tr:
        g = fp[t].get("gh") or "?"
        comp[g]["tasks"] += 1
        comp[g]["boxes"] += int(_num(fp[t].get("boxes")) or 0)
    return {"threshold": round(thr, 3), "rows": rows, "by_gh": dict(by), "train_by_gh": dict(comp), "train_n": len(tr)}


def suggest_additions(fp, train_ids, pool_ids, keys=REL_KEYS, k=10):
    """아직 train에 없는 TASK(pool) 중 넣으면 train이 덮는 범위가 가장 넓어지는 것 (가장 먼 것부터, 차례로 하나씩 더하며)"""
    tr = [_vec(fp[t], keys) for t in map(str, train_ids) if t in fp]
    tr = [v for v in tr if v is not None]
    pool = [(t, _vec(fp[t], keys)) for t in map(str, pool_ids) if t in fp and str(t) not in set(map(str, train_ids))]
    pool = [(t, v) for t, v in pool if v is not None]
    if not tr or not pool:
        return []
    allv = np.array(tr + [v for _, v in pool])
    mu, sd = allv.mean(0), allv.std(0)
    sd[sd == 0] = 1.0
    T = [(v - mu) / sd for v in tr]
    out = []
    for _ in range(min(k, len(pool))):
        best = max(pool, key=lambda p: min(np.linalg.norm(((p[1] - mu) / sd) - x) for x in T))
        dist = min(np.linalg.norm(((best[1] - mu) / sd) - x) for x in T)
        out.append({"task_id": best[0], "task_name": fp[best[0]].get("task_name", ""), "gh": fp[best[0]].get("gh", ""),
                    "distance": round(float(dist), 3)})
        T.append((best[1] - mu) / sd)
        pool = [p for p in pool if p[0] != best[0]]
    return out


# ---------------------------------------------------------------- 시험 TASK 후보 표
def test_candidate_table(cands, ledger, model_names=None):
    """시험 TASK 후보(cands = [{'task_id', 'name'}])가 어느 모델 학습(train/val)에 쓰였는지 + 온실·촬영일
    ledger = cvat_task_tools.read_train_tasks(BASE) · model_names = 볼 모델(없으면 대장에 있는 모든 모델)"""
    used = defaultdict(dict)
    for r in ledger:
        used[str(r.get("task_id"))][r.get("model", "")] = r.get("role", "")
    models = list(model_names) if model_names else sorted({r.get("model", "") for r in ledger if r.get("model")})
    rows = []
    for c in cands:
        tid = str(c["task_id"])
        u = used.get(tid, {})
        row = {"task_id": tid, "task_name": c.get("name", ""), "gh": c.get("gh", ""), "date": c.get("date", ""),
               "학습에 쓴 모델": ", ".join(f"{m}({u[m]})" for m in models if m in u) or "없음"}
        rows.append(row)
    return rows, [m for m in models]
