"""
검증 2·3단계: 자동으로 만든 track(XML)을 정답(XML/zip)과 비교

  2단계 (바로 가능): 정답 = 사람이 손으로 그린 기존 라벨 (프레임별 박스, track 아님)
        → 프레임별 탐지 정확도(정밀도·재현율)만 계산
  3단계 (검수 후):   정답 = 자동 track을 CVAT에서 사람이 고친 뒤 다시 export한 것 (track 형식)
        → 탐지 정확도 + 추적 정확도(ID 끊김, ID 바뀜, 개체 수 오차, IDF1 근사)

※ 정답 영상은 학습에 쓰지 않은 영상이어야 함 (학습에 쓴 영상이면 점수가 부풀려짐)

사용법
  python compare_tracks.py --pred tracks/tracks_영상.xml --gt zips/영상.zip
  출력: 화면 요약 + 예측 XML 옆에 compare_<pred이름>.csv (정답 track별 상세)
"""
__version__ = "4.31.9"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import argparse
import csv
import zipfile
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET


def load_root(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.replace("\\", "/").split("/")[-1] == "annotations.xml")
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def expand(root):
    """→ task_frames, {frame: [(track_id, label, box)]}, {track_id: 보이는 프레임 수}"""
    t = root.find("meta/task")
    if t is None:
        t = root.find("meta/job")
    start, stop = int(t.findtext("start_frame") or 0), int(t.findtext("stop_frame") or 0)
    ff = (t.findtext("frame_filter") or "").strip()
    step = int(ff.split("=")[1]) if ff.startswith("step=") else 1
    frames = list(range(start, stop + 1, step))
    per = defaultdict(list)
    vis = defaultdict(int)
    for tr in root.findall("track"):
        tid, label = tr.get("id"), tr.get("label")
        kf = sorted(((int(b.get("frame")), b) for b in tr.findall("box")), key=lambda x: x[0])
        for i, (f, b) in enumerate(kf):
            if b.get("outside") == "1":
                continue
            c = [float(b.get(k)) for k in ("xtl", "ytl", "xbr", "ybr")]
            per[f].append((tid, label, c))
            vis[tid] += 1
            nxt = kf[i + 1] if i + 1 < len(kf) else None
            for g in frames:
                if g <= f:
                    continue
                if nxt is None:            # outside 없이 끝나면 끝까지 유지 (CVAT 동작)
                    per[g].append((tid, label, c))
                    vis[tid] += 1
                elif g < nxt[0]:           # 키프레임 사이: 다음이 outside면 그대로 유지, 아니면 선형 보간
                    if nxt[1].get("outside") == "1":
                        ci = c
                    else:
                        c2 = [float(nxt[1].get(k)) for k in ("xtl", "ytl", "xbr", "ybr")]
                        r = (g - f) / (nxt[0] - f)
                        ci = [x + (y - x) * r for x, y in zip(c, c2)]
                    per[g].append((tid, label, ci))
                    vis[tid] += 1
    for k, b in enumerate(root.findall("box")):   # track 밖 단독 박스
        tid = f"shape{k}"
        per[int(b.get("frame"))].append((tid, b.get("label"), [float(b.get(x)) for x in ("xtl", "ytl", "xbr", "ybr")]))
        vis[tid] += 1
    return frames, per, vis


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def assign(matrix_counts, g_ids, p_ids):
    """정답 track ↔ 예측 track 1:1 배정으로 겹친 프레임 수 합 최대화 (IDF1용)"""
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        m = np.zeros((len(g_ids), len(p_ids)))
        for (g, p), v in matrix_counts.items():
            m[g_ids.index(g), p_ids.index(p)] = v
        r, c = linear_sum_assignment(-m)
        return int(m[r, c].sum())
    except ImportError:          # scipy가 없으면 탐욕적 배정 (근사)
        used_g, used_p, tot = set(), set(), 0
        for (g, p), v in sorted(matrix_counts.items(), key=lambda x: -x[1]):
            if g not in used_g and p not in used_p:
                used_g.add(g); used_p.add(p); tot += v
        return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="yolo_track_to_cvat.py가 만든 XML")
    ap.add_argument("--gt", required=True, help="정답: CVAT export zip 또는 annotations.xml")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--json", default=None, help="요약 수치를 JSON으로 저장할 경로 (작업 대장용)")
    ap.add_argument("--csv", default=None, help="정답 track별 상세 CSV 경로 (기본: 예측 XML 옆)")
    ap.add_argument("--gt-labels", default=None,
                    help="정답에서 비교 대상으로 볼 라벨(쉼표 구분). 기본: 예측 라벨 + 그 disease_ 짝")
    a = ap.parse_args()

    pf, pred, pvis = expand(load_root(a.pred))
    gf, gt, gvis = expand(load_root(a.gt))
    frames = sorted(set(pf) & set(gf))
    if not frames:
        raise SystemExit("두 파일의 태스크 프레임이 겹치지 않습니다. 같은 태스크의 파일인지 확인하세요.")
    if set(pf) != set(gf):
        print(f"참고: 프레임 설정이 다릅니다. 겹치는 프레임 {len(frames)}개만 비교합니다.")
    pred_labels = {l for f in pred for _t, l, _b in pred[f]}
    if a.gt_labels:
        gt_labels = set(a.gt_labels.split(","))
    else:
        gt_labels = pred_labels | {l.replace("healthy_", "disease_") for l in pred_labels}
    print(f"비교 대상 라벨 — 예측: {sorted(pred_labels)} / 정답: {sorted(gt_labels)} (라벨 구분 없이 위치로 매칭)")

    tp = fp = fn = 0
    gt_tracks = defaultdict(list)       # 정답 track → [(frame, 매칭된 예측 track 또는 None)]
    counts = defaultdict(int)
    n_gt_boxes = n_pred_boxes = 0
    for f in frames:
        G = [(t, b) for t, l, b in gt.get(f, []) if l in gt_labels]
        P = [(t, b) for t, l, b in pred.get(f, [])]
        n_gt_boxes += len(G)
        n_pred_boxes += len(P)
        pairs = sorted(((iou(g[1], p[1]), gi, pi) for gi, g in enumerate(G) for pi, p in enumerate(P)), reverse=True)
        gm, used = {}, set()
        for v, gi, pi in pairs:
            if v < a.iou:
                break
            if gi in gm or pi in used:
                continue
            gm[gi] = pi
            used.add(pi)
        tp += len(gm)
        fn += len(G) - len(gm)
        fp += len(P) - len(used)
        for gi, (gtid, _b) in enumerate(G):
            ptid = P[gm[gi]][0] if gi in gm else None
            gt_tracks[gtid].append((f, ptid))
            if ptid is not None:
                counts[(gtid, ptid)] += 1

    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    print(f"\n[탐지] 프레임 {len(frames)}개, 정답 박스 {n_gt_boxes}, 예측 박스 {n_pred_boxes} (IoU≥{a.iou})")
    print(f"  정밀도 {prec:.1%}  재현율 {rec:.1%}  F1 {f1:.1%}   (맞음 {tp} / 엉뚱 {fp} / 놓침 {fn})")

    pred_ids = sorted({t for f in frames for t, _l, _b in pred.get(f, [])})
    gt_ids = sorted(gt_tracks)
    multi = [t for t in gt_ids if len(gt_tracks[t]) > 1]
    is_track_gt = len(multi) >= max(1, 0.5 * len(gt_ids))
    rows = []
    summary = {"frames": len(frames), "gt_boxes": n_gt_boxes, "pred_boxes": n_pred_boxes, "tp": tp, "fp": fp, "fn": fn,
               "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
               "pred_tracks": len(pred_ids), "gt_is_track": is_track_gt}
    if not is_track_gt:
        print("\n[추적] 정답이 track 형식이 아닙니다(대부분 한 프레임짜리). 추적 정확도는 계산하지 않습니다.")
        print("  → 자동 track을 CVAT에서 검수·수정한 뒤 export한 파일을 --gt로 주면 계산됩니다.")
        print(f"  참고: 예측 track 수 {len(pred_ids)}개 (= 자동으로 추정한 개체 수)")
    else:
        frag = switches = 0
        for g in gt_ids:
            seq = [p for _f, p in sorted(gt_tracks[g]) if p is not None]
            ids = set(seq)
            frag += max(0, len(ids) - 1)
            switches += sum(1 for x, y in zip(seq, seq[1:]) if x != y)
            rows.append([g, len(gt_tracks[g]), len(seq), len(ids), " ".join(map(str, sorted(ids)))])
        merges = 0
        p2g = defaultdict(set)
        for (g, p), v in counts.items():
            p2g[p].add(g)
        merges = sum(len(s) - 1 for s in p2g.values() if len(s) > 1)
        idtp = assign(counts, gt_ids, pred_ids) if counts else 0
        idf1 = 2 * idtp / (n_gt_boxes + n_pred_boxes) if n_gt_boxes + n_pred_boxes else 0
        print(f"\n[추적] 정답 track {len(gt_ids)}개 / 예측 track {len(pred_ids)}개 → 개체 수 오차 {len(pred_ids) - len(gt_ids):+d}")
        print(f"  끊김(정답 1개가 예측 여러 개로 나뉨): {frag}회   — CVAT에서 Merge로 고친 횟수에 해당")
        print(f"  ID 바뀜(같은 열매의 예측 ID가 도중에 바뀜): {switches}회")
        print(f"  섞임(예측 1개가 정답 여러 개를 이어 붙임): {merges}회")
        print(f"  IDF1(근사): {idf1:.1%}   — 같은 열매를 끝까지 같은 ID로 따라간 정도")
        summary.update({"gt_tracks": len(gt_ids), "count_error": len(pred_ids) - len(gt_ids), "fragments": frag,
                        "id_switches": switches, "merges": merges, "idf1": round(idf1, 4)})

    out = Path(a.csv) if a.csv else Path(a.pred).parent / f"compare_{Path(a.pred).stem}.csv"   # 기본: 예측 XML 옆
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["gt_track", "gt_visible_frames", "matched_frames", "n_pred_ids", "pred_ids"])
        if rows:
            w.writerows(rows)
        else:
            for g in gt_ids:
                seq = [p for _f, p in gt_tracks[g] if p is not None]
                w.writerow([g, len(gt_tracks[g]), len(seq), len(set(seq)), " ".join(map(str, sorted(set(seq))))])
    print(f"상세: {out}")
    if a.json:
        import json
        Path(a.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
