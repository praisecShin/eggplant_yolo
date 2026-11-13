"""
검증 1단계: 학습한 YOLO가 val 이미지에서 열매를 얼마나 찾는지, '가림/가림 없음'과 '크기'별로 나눠 계산

입력
  --model    학습한 best.pt
  --dataset  cvat_video_to_yolo.py가 만든 dataset 폴더 (val/images, val/labels, occluded_info.csv)
출력
  화면 요약 + <dataset>/eval_recall.csv (정답 박스마다 찾았는지, IoU, 가림, 크기)

판단 기준(초안 모델): 전체 재현율 70~80% 이상이고 가림 재현율이 크게 떨어지지 않으면 자동 주석에 쓸 만함

사용법
  python eval_occluded_recall.py --model runs/detect/train/weights/best.pt --dataset dataset --imgsz 1920
"""
__version__ = "4.31.9"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import argparse
import csv
from collections import defaultdict
from pathlib import Path

SIZE_BINS = [(0, 16, "16px 미만"), (16, 32, "16~32px"), (32, 64, "32~64px"), (64, 1e9, "64px 이상")]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--dataset", default="dataset")
    ap.add_argument("--split", default="val")
    ap.add_argument("--imgsz", type=int, default=1920)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.5, help="이 이상 겹치면 찾은 것으로 봄")
    ap.add_argument("--device", default=None)
    a = ap.parse_args()

    from ultralytics import YOLO
    ds = Path(a.dataset)
    img_dir, lab_dir = ds / a.split / "images", ds / a.split / "labels"
    images = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
    if not images:
        raise SystemExit(f"{img_dir}에 이미지가 없습니다.")

    # 가림 정보: (이미지, 정규화 좌표 문자열) → occluded
    occ_map = {}
    occ_csv = ds / "occluded_info.csv"
    if occ_csv.exists():
        with open(occ_csv, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if "yolo_cx" in r:
                    key = (r["image"], r["yolo_cx"], r["yolo_cy"], r["yolo_w"], r["yolo_h"])
                    occ_map[key] = r["occluded"] == "1"
    if not occ_map:
        print("참고: occluded_info.csv에 yolo_* 열이 없어 가림별 계산을 건너뜁니다 (변환 스크립트 최신판으로 다시 만들기).")

    model = YOLO(a.model)
    # split 학습 모델: 가림/안 가림 클래스는 같은 물체로 보고 매칭 (위치를 찾았는지가 중요)
    base_of = {i: (n[:-len("_occluded")] if n.endswith("_occluded") else n) for i, n in model.names.items()}
    split_model = any(n.endswith("_occluded") for n in model.names.values())
    rows, stat = [], defaultdict(lambda: [0, 0])   # 그룹 → [찾음, 전체]
    n_pred = n_pred_matched = 0
    for img_path in images:
        r = model.predict(source=str(img_path), imgsz=a.imgsz, conf=a.conf, device=a.device, verbose=False,
                          agnostic_nms=split_model)[0]
        h, w = r.orig_shape
        preds = [(int(c), b) for c, b in zip(r.boxes.cls.tolist(), r.boxes.xyxy.tolist())]
        n_pred += len(preds)
        gts = []
        lab = lab_dir / f"{img_path.stem}.txt"
        if lab.exists():
            for line in lab.read_text(encoding="utf-8").split("\n"):
                p = line.split()
                if len(p) != 5:
                    continue
                c, cx, cy, bw, bh = int(p[0]), *p[1:]
                occ = occ_map.get((f"{img_path.stem}.jpg", cx, cy, bw, bh))
                cx, cy, bw, bh = float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
                gts.append((c, [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], occ))
        # 같은 클래스끼리 IoU 큰 순서로 1:1 매칭
        pairs = sorted(((iou(g[1], p[1]), gi, pi) for gi, g in enumerate(gts) for pi, p in enumerate(preds)
                        if base_of.get(g[0], g[0]) == base_of.get(p[0], p[0])), reverse=True)
        gmatch, used = {}, set()
        for v, gi, pi in pairs:
            if v < a.iou:
                break
            if gi in gmatch or pi in used:
                continue
            gmatch[gi] = v
            used.add(pi)
        n_pred_matched += len(used)
        scale = a.imgsz / max(w, h)
        for gi, (c, box, occ) in enumerate(gts):
            short = min(box[2] - box[0], box[3] - box[1]) * scale
            hit = gi in gmatch
            groups = ["전체", {True: "가림", False: "가림 없음", None: "가림 정보 없음"}[occ]]
            groups += [lbl for lo, hi, lbl in SIZE_BINS if lo <= short < hi]
            groups.append(f"클래스 {model.names.get(c, c)}")
            for g in groups:
                stat[g][0] += hit
                stat[g][1] += 1
            rows.append([img_path.name, model.names.get(c, c), "" if occ is None else int(occ),
                         round(short, 1), int(hit), round(gmatch.get(gi, 0), 3)])

    with open(ds / "eval_recall.csv", "w", newline="", encoding="utf-8-sig") as fh:
        wr = csv.writer(fh)
        wr.writerow(["image", "class", "occluded", f"short_side_px_at_{a.imgsz}", "found", "iou"])
        wr.writerows(rows)

    print(f"\n검증 이미지 {len(images)}장, 정답 박스 {stat['전체'][1]}개, 예측 박스 {n_pred}개 "
          f"(conf≥{a.conf}, IoU≥{a.iou})")
    prec = n_pred_matched / n_pred if n_pred else 0
    print(f"정밀도(예측 중 맞은 비율): {prec:.1%}")
    order = ["전체", "가림 없음", "가림", "가림 정보 없음"] + [b[2] for b in SIZE_BINS] + \
            sorted(k for k in stat if k.startswith("클래스"))
    print(f"{'구분':<14}{'재현율':>8}{'찾음/전체':>12}")
    for k in order:
        if k in stat and stat[k][1]:
            f, t = stat[k]
            print(f"{k:<14}{f / t:>8.1%}{f'{f}/{t}':>12}")
    print(f"상세: {ds / 'eval_recall.csv'}")


if __name__ == "__main__":
    main()
