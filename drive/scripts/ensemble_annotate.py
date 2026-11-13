"""여러 모델 앙상블 자동 라벨링 (27번 셀) — 프레임마다 모델 N개가 탐지 → 같은 열매끼리 묶어(WBF) 한 박스로

- 묶기: 같은 라벨(가림 클래스는 기본 라벨로) 박스끼리 IoU ≥ iou_thr면 같은 열매. 한 묶음에 모델마다 최대 1개.
- 합친 박스: 신뢰도 가중 평균 위치, 가림 표시는 다수결, 신뢰도 = (묶음 신뢰도 합) / (그 라벨을 아는 모델 수).
- 채택: 표(찾은 모델 수) ≥ min(min_votes, 그 라벨을 아는 모델 수). 나머지는 '검토 목록'(한 모델만 찾은 것 등).
  예: bud를 아는 모델이 2개뿐이면 bud는 2개 중 2표가 필요 (bud를 모르는 모델 때문에 지워지지 않음).
"""
__version__ = "4.31.9"

from collections import Counter, defaultdict
from pathlib import Path


def base_label(name):
    return (name[:-9], True) if name.endswith("_occluded") else (name, False)


class ModelInfo:
    """YOLO 모델 하나: 이름, 아는 기본 라벨, 클래스 → (기본 라벨, 가림)"""

    def __init__(self, name, weights, model=None):
        self.name, self.weights = name, str(weights)
        if model is None:
            from ultralytics import YOLO
            model = YOLO(self.weights)
        self.model = model
        names = model.names if isinstance(model.names, dict) else dict(enumerate(model.names))
        self.cls = {int(i): base_label(n) for i, n in names.items()}
        self.labels = sorted({b for b, _ in self.cls.values()})
        self.split = any(o for _, o in self.cls.values())

    def detect(self, img, imgsz=1920, conf=0.25, device=None):
        """→ [(기본 라벨, 가림, (x1,y1,x2,y2), 신뢰도)]  (이미지 픽셀 좌표)"""
        kw = dict(imgsz=imgsz, conf=conf, verbose=False, agnostic_nms=self.split)
        if device is not None:
            kw["device"] = device
        r = self.model.predict(img, **kw)[0]
        out = []
        if r.boxes is None:
            return out
        for (x1, y1, x2, y2), c, cf in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            lab, occ = self.cls[int(c)]
            out.append((lab, occ, (x1, y1, x2, y2), float(cf)))
        return out


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def fuse(dets, knows, iou_thr=0.55, min_votes=2, weights=None):
    """dets = {모델 이름: [(라벨, 가림, box, conf)]}, knows = {라벨: [그 라벨을 아는 모델 이름]}
    → (채택 [dict], 검토 [dict]). dict: label, occluded, box, conf, votes, need, voters{모델: conf}, boxes{모델: box}"""
    weights = weights or {}
    by_label = defaultdict(list)
    for m, lst in dets.items():
        for lab, occ, box, cf in lst:
            by_label[lab].append((cf * weights.get(m, 1.0), m, occ, box, cf))
    accepted, review = [], []
    for lab, items in by_label.items():
        items.sort(key=lambda x: -x[0])
        clusters = []                                   # {'members': [(w, m, occ, box, cf)], 'box': fused}
        for it in items:
            best, bv = None, iou_thr
            for c in clusters:
                if any(mm[1] == it[1] for mm in c["members"]):
                    continue                           # 한 묶음에 같은 모델은 하나만
                v = iou(c["box"], it[3])
                if v >= bv:
                    best, bv = c, v
            if best is None:
                clusters.append({"members": [it], "box": it[3]})
            else:
                best["members"].append(it)
                ws = sum(m[0] for m in best["members"])
                best["box"] = tuple(sum(m[0] * m[3][j] for m in best["members"]) / ws for j in range(4))
        n_know = max(1, len(knows.get(lab, [])))
        need = min(int(min_votes), n_know)
        for c in clusters:
            mem = c["members"]
            occ_votes = sum(1 for m in mem if m[2])
            d = {"label": lab, "occluded": occ_votes * 2 > len(mem), "box": c["box"],
                 "conf": sum(m[4] for m in mem) / n_know, "votes": len(mem), "need": need, "n_know": n_know,
                 "voters": {m[1]: round(m[4], 3) for m in mem}, "boxes": {m[1]: m[3] for m in mem}}
            (accepted if len(mem) >= need else review).append(d)
    return accepted, review


def contribution(frames_result, model_names):
    """모델별 기여: 찾은 박스, 채택된 묶음에 들어간 수, 혼자만 찾은 것(검토 목록) 수"""
    st = {m: Counter() for m in model_names}
    for fr in frames_result.values():
        for d in fr["accepted"]:
            for m in d["voters"]:
                st[m]["채택에 참여"] += 1
                st[m]["찾은 박스"] += 1
        for d in fr["review"]:
            for m in d["voters"]:
                st[m]["찾은 박스"] += 1
                if d["votes"] == 1:
                    st[m]["혼자만 찾음(검토)"] += 1
                else:
                    st[m]["검토(표 부족)"] += 1
    rows = []
    for m in model_names:
        c = st[m]
        rows.append({"모델": m, "찾은 박스": c["찾은 박스"], "채택에 참여": c["채택에 참여"],
                     "혼자만 찾음(검토)": c["혼자만 찾음(검토)"], "검토(표 부족)": c["검토(표 부족)"],
                     "참여율": f"{c['채택에 참여'] / c['찾은 박스']:.0%}" if c["찾은 박스"] else ""})
    return rows


def run_ensemble(task, models, frames_iter, W0=None, H0=None, imgsz=1920, conf=0.25, iou_thr=0.55,
                 min_votes=2, weights=None, device=None, log=print, every=25):
    """frames_iter: (TASK 프레임 순번 k, PIL 이미지) 반복자. 좌표는 CVAT 원본 크기(W0,H0)로 환산.
    → {k: {'accepted': [...], 'review': [...]}}"""
    knows = defaultdict(list)
    for m in models:
        for lab in m.labels:
            knows[lab].append(m.name)
    res, n = {}, 0
    import time
    t0 = time.time()
    for k, img in frames_iter:
        img = img.convert("RGB")
        sx = (W0 / img.width) if W0 else 1.0
        sy = (H0 / img.height) if H0 else 1.0
        dets = {}
        for m in models:
            dets[m.name] = [(lab, occ, (b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy), cf)
                            for lab, occ, b, cf in m.detect(img, imgsz=imgsz, conf=conf, device=device)]
        acc, rev = fuse(dets, knows, iou_thr, min_votes, weights)
        res[k] = {"accepted": acc, "review": rev, "raw": {m: len(v) for m, v in dets.items()}}
        n += 1
        if every and n % every == 0:
            log(f"  {n}프레임 · 채택 {sum(len(r['accepted']) for r in res.values())} · "
                f"검토 {sum(len(r['review']) for r in res.values())} · {time.time() - t0:.0f}초")
    return res


def frames_from_cvat(task, todo, log=print):
    """CVAT에서 프레임 받기 (원본 → 고해상도라 안 되면 압축)"""
    import PIL.Image
    q = {"q": "original"}
    for k in todo:
        try:
            img = PIL.Image.open(task.get_frame(k, quality=q["q"]))
        except Exception as e:
            if q["q"] == "original" and "resolution" in str(e):
                q["q"] = "compressed"
                log("  참고: 원본 프레임 불가(고해상도) → 압축 프레임")
                img = PIL.Image.open(task.get_frame(k, quality="compressed"))
            else:
                raise
        yield k, img


def to_shapes(res, label_ids, models_mod=None):
    """채택 박스 → CVAT LabeledShapeRequest 목록 (TASK에 없는 라벨은 뺌)"""
    if models_mod is None:
        from cvat_sdk.api_client import models as models_mod
    out, skipped = [], Counter()
    for k, fr in res.items():
        for d in fr["accepted"]:
            if d["label"] not in label_ids:
                skipped[d["label"]] += 1
                continue
            out.append(models_mod.LabeledShapeRequest(type="rectangle", frame=int(k), label_id=label_ids[d["label"]],
                                                      points=[float(v) for v in d["box"]], occluded=bool(d["occluded"]),
                                                      source="auto"))
    return out, dict(skipped)


def review_rows(res):
    rows = []
    for k, fr in sorted(res.items()):
        for d in fr["review"]:
            rows.append({"프레임": k, "라벨": d["label"], "표": f"{d['votes']}/{d['n_know']}",
                         "찾은 모델": ", ".join(d["voters"]), "신뢰도": round(max(d["voters"].values()), 3),
                         "x1": round(d["box"][0]), "y1": round(d["box"][1]), "x2": round(d["box"][2]), "y2": round(d["box"][3])})
    return rows


def frame_rows(res):
    rows = []
    for k, fr in sorted(res.items()):
        c = Counter(d["label"] for d in fr["accepted"])
        rows.append({"프레임": k, "채택": len(fr["accepted"]), "검토": len(fr["review"]),
                     **{f"채택 {l}": n for l, n in c.items()}, **{f"모델 {m}": n for m, n in fr["raw"].items()}})
    return rows
