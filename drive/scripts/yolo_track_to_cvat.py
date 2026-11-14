"""
학습한 YOLO + 추적기(BoT-SORT)로 원본 mp4를 돌려, CVAT에 올릴 track XML(CVAT for video 1.1)을 만든다.

흐름
  1) 원본 mp4의 '모든 프레임'(30fps)에서 탐지 + 추적 → 열매마다 같은 ID
     (태스크의 10프레임 간격으로 추적하면 열매가 한 번에 100px 넘게 움직여 ID가 자주 끊김)
  2) CVAT 태스크 프레임(예: 0, 10, 20 …)에 해당하는 박스만 남김
  3) 열매가 사라지면 outside="1"로 track을 닫음 (프레임 160 같은 중복 방지)
  4) track 하나에 라벨 하나 (track 안에서 신뢰도 가중 다수결)
  5) 그 태스크에서 export한 zip/XML의 <meta>를 그대로 복사 → 라벨·프레임 설정이 정확히 맞음

CVAT에 올리기
  cvat-cli --server-host https://app.cvat.ai task import-dataset <태스크ID> tracks_<영상>.xml --format "CVAT 1.1"
  또는 CVAT 화면: 태스크 → Actions → Upload annotations → CVAT 1.1
  ※ 업로드하면 그 태스크의 기존 라벨이 바뀔 수 있으니, 먼저 export로 백업하거나 복사한 태스크에서 시험할 것

사용법
  설정 영역을 고친 뒤      python yolo_track_to_cvat.py
  또는 명령줄로 지정 (Colab) python yolo_track_to_cvat.py --model best.pt --video a.mp4 --reference a.zip
  여러 영상을 한 번에:       --video 와 --reference 를 같은 순서로 여러 개 지정
"""
__version__ = "4.32.0"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import argparse
import csv
import zipfile
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

# ----------------- [설정 영역] -----------------
MODEL = "runs/detect/train/weights/best.pt"   # 학습한 가중치
VIDEO = Path("videos/eggplant_G6_20261019_3_10_uld.mp4")   # 원본 mp4 (CVAT에 올린 것과 같은 파일)
REFERENCE = Path("zips/G6_261019_3_10_mp4.zip")  # 같은 태스크에서 export한 zip 또는 annotations.xml
OUT_DIR = Path("./tracks")

IMGSZ = 1920              # 학습 때와 같게
CONF = 0.25               # 탐지 신뢰도 하한
DEVICE = None             # None=자동, "cpu", "0"(GPU)
TRACKER = "botsort.yaml"  # 카메라 움직임 보정 포함. 비교용: "bytetrack.yaml"
MIN_HITS = 5              # 전체 프레임 중 이보다 적게 잡힌 track은 버림 (깜빡이는 오탐 제거)
NEAR = 1                  # 태스크 프레임에 정확히 안 잡혔을 때 앞뒤 몇 프레임까지 빌려올지 (멀리서 빌리면 카메라 이동만큼 밀림. None=step의 절반)
FILL_GAPS = 3             # 잠깐 안 보인 태스크 프레임이 이 개수 이하면 track을 끊지 않고 CVAT 보간에 맡김
TRACK_BUFFER = 90         # 추적기가 안 보이는 물체의 ID를 기억하는 프레임 수 (기본 30 = 1초 → 가림이 많아 늘림)
DECODER = "opencv"        # 영상 읽기: "opencv"(ultralytics 기본) / "pyav"(CVAT와 같은 FFmpeg 방식으로 프레임 번호를 셈)
FRAME_OFFSET = 0          # 영상 프레임 번호 + 이 값 = CVAT 프레임 번호 (20번 셀 진단이 알려 줌)
FRAME_MAP = None          # v4.31.5: 사진 TASK(ULD) — 사진 k번이 영상(clip)의 몇 번째 프레임인지 [0, 8, 16, …].
                          #   주면 영상 전체를 추적한 뒤 이 프레임만 골라 사진 번호 k로 올림 (모든 사진이 키프레임, 한 장에만 보여도 track)
BOX_SOURCE = "detection"  # 박스 좌표: "detection" = 그 프레임에서 모델이 찾은 박스 그대로 (권장)
                          #           "tracker"   = 추적기(칼만 필터)가 예측·보정한 박스 (움직임이 빠르면 늦게 따라와
                          #                         위·아래가 잘리거나 밀림)
# -----------------------------------------------


def load_reference(path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.replace("\\", "/").split("/")[-1] == "annotations.xml")
            root = ET.fromstring(z.read(name))
    else:
        root = ET.parse(path).getroot()
    meta = root.find("meta")
    t = meta.find("task") if meta.find("task") is not None else meta.find("job")
    start = int(t.findtext("start_frame") or 0)
    stop = int(t.findtext("stop_frame") or 0)
    ff = (t.findtext("frame_filter") or "").strip()
    step = int(ff.split("=")[1]) if ff.startswith("step=") else 1
    labels = [l.findtext("name") for l in t.iter("label")]
    _w, _h = t.findtext("original_size/width"), t.findtext("original_size/height")
    W, H = (float(_w), float(_h)) if _w and _h else (None, None)     # 사진 TASK의 export에는 없음 → 영상 크기를 씀
    return meta, list(range(start, stop + 1, step)), step, labels, W, H


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def make_tracker_cfg(name, buffer):
    """ultralytics 기본 추적기 설정을 복사해 track_buffer만 바꾼 yaml을 만든다"""
    try:
        import ultralytics
        import yaml
        src = Path(ultralytics.__file__).parent / "cfg" / "trackers" / name
        cfg = yaml.safe_load(src.read_text())
        cfg["track_buffer"] = int(buffer)
        # 신뢰도 하한(--conf)을 낮췄다면 추적기의 시작·연결 기준도 함께 낮춤 (기본 0.25면 낮은 검출로는 track이 안 생김)
        for k in ("track_high_thresh", "new_track_thresh"):
            if k in cfg:
                cfg[k] = min(float(cfg[k]), float(CONF))
        if "track_low_thresh" in cfg:
            cfg["track_low_thresh"] = min(float(cfg["track_low_thresh"]), float(CONF) / 2)
        out = OUT_DIR / f"_tracker_{Path(name).stem}_buf{buffer}_conf{CONF}.yaml"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(cfg))
        return str(out)
    except Exception as e:
        print(f"참고: 추적기 설정 변경 실패({e}) → 기본 {name} 사용")
        return name


# ---- 세로로 찍은 영상 (v4.24.5) ----
# 휴대폰·카메라를 세워 찍은 영상은 화면이 가로로 저장되고 '돌려서 보여 줘라'는 회전 정보가 붙는다.
# CVAT(FFmpeg)는 이 값대로 돌려 보여 주고 라벨도 돌린 화면 기준이다. PyAV는 돌리지 않으므로 여기서 같게 돌린다.
# (OpenCV는 스스로 돌려 줌.) 값 = 시계 반대 방향 도수: 90 → 반시계 90°, -90(=270) → 시계 90°, 180.
def pyav_rotation(frame, stream=None):
    """PyAV 프레임의 화면 회전(0·90·180·270). frame.rotation(PyAV 14+) → 없으면 스트림 'rotate' 태그(예전 FFmpeg, 시계 방향)"""
    r = getattr(frame, "rotation", None)
    try:
        if r is not None:
            return int(round(float(r))) % 360
        tag = (getattr(stream, "metadata", None) or {}).get("rotate") if stream is not None else None
        return (-int(round(float(tag)))) % 360 if tag not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def upright_array(arr, rotation):
    """numpy 이미지(H×W×C)를 회전 정보대로 돌림 — FFmpeg 자동 회전(CVAT 화면)과 같은 결과"""
    k = (int(rotation) // 90) % 4
    if not k:
        return arr
    import numpy as _np
    return _np.ascontiguousarray(_np.rot90(arr, k))


def upright_image(img, rotation):
    """PIL 이미지를 회전 정보대로 돌림 (upright_array와 같은 방향)"""
    k = (int(rotation) // 90) % 4
    if not k:
        return img
    from PIL import Image as _I
    return img.transpose({1: _I.Transpose.ROTATE_90, 2: _I.Transpose.ROTATE_180, 3: _I.Transpose.ROTATE_270}[k])


def build_tracks(tracks, task_frames, base, occl, near, frame_map=False):
    """추적 결과 {track id: {영상 프레임: (xyxy, cls, conf)}} → CVAT track 목록 [(라벨, [(프레임, outside, xyxy, 가림)])], 표 줄, 버린 수.
    frame_map=False (영상 TASK): 프레임 번호 = 영상 프레임. 빠진 프레임이 FILL_GAPS개 이하면 CVAT 보간에 맡김.
    frame_map=True  (사진 TASK): 프레임 번호 = 사진 순번 k. 보인 사진마다 키프레임, 사이에 안 보이는 사진은 outside,
                    한 장에만 보여도 track. 그 사진의 영상 프레임에 검출이 없고 앞뒤 검출 사이가 FILL_GAPS 이하면 그 사이를 이어 씀."""
    out_tracks, rows, dropped = [], [], 0
    for tid, det in sorted(tracks.items()):
        if len(det) < MIN_HITS:
            dropped += 1
            continue
        votes = defaultdict(float)
        for _box, c, cf in det.values():
            votes[base[c]] += cf                     # 가림/안 가림은 같은 라벨로 합쳐서 투표
        label = max(votes, key=votes.get)
        seen = sorted(det)
        first, last = seen[0], seen[-1]
        # 태스크 프레임마다 검출 여부 (±near 프레임 안의 검출을 빌려옴)
        hits = []         # (태스크 프레임 순번, 프레임, xyxy, 가림)
        for k, f in enumerate(task_frames):
            if f < first - near or f > last + near:
                continue
            cand = [g for g in range(f - near, f + near + 1) if g in det]
            if cand:
                g = min(cand, key=lambda g: abs(g - f))
                hits.append((k, f, det[g][0], int(occl[det[g][1]])))
            elif frame_map:                           # 앞뒤 검출 사이의 짧은 빈틈 → 그 사이를 이어서
                pv = max((g for g in seen if g < f), default=None)
                nx = min((g for g in seen if g > f), default=None)
                if pv is not None and nx is not None and nx - pv - 1 <= FILL_GAPS:
                    w_ = (f - pv) / (nx - pv)
                    bx = tuple(a_ + (b_ - a_) * w_ for a_, b_ in zip(det[pv][0], det[nx][0]))
                    hits.append((k, f, bx, int(occl[det[pv][1]])))
        if not hits:
            dropped += 1
            continue
        boxes = []        # (frame, outside, xyxy, 가림)
        if frame_map:
            hk = {k: (b, oc) for k, _f, b, oc in hits}
            k0, k1 = min(hk), max(hk)
            prev = None
            for k in range(k0, k1 + 1):
                if k in hk:
                    boxes.append((k, 0, hk[k][0], hk[k][1])); prev = hk[k]
                else:
                    boxes.append((k, 1, prev[0], prev[1]))
            if k1 + 1 < len(task_frames):            # 마지막으로 보인 다음 사진에서 닫음
                boxes.append((k1 + 1, 1, hk[k1][0], hk[k1][1]))
        else:
            # 검출된 프레임만 키프레임으로 씀. 사이에 빠진 프레임이 FILL_GAPS개 이하면 그대로 두어
            # CVAT가 키프레임 사이를 보간하게 하고, 더 길게 안 보이면 outside로 닫았다가 다시 연다.
            for j, (k, f, b, oc) in enumerate(hits):
                if j > 0:
                    pk, pf, pb, po = hits[j - 1]
                    if k - pk - 1 > FILL_GAPS:
                        boxes.append((task_frames[pk + 1], 1, pb, po))
                boxes.append((f, 0, b, oc))
            lk, lf, lb, lo = hits[-1]
            if lk + 1 < len(task_frames):                # 마지막으로 보인 다음 프레임에서 닫음
                boxes.append((task_frames[lk + 1], 1, lb, lo))
        out_tracks.append((label, boxes))
        vis = sum(1 for _f, o, _b, _oc in boxes if o == 0)
        rows.append([len(out_tracks) - 1, tid, label, len(det), first, last, vis])
    return out_tracks, rows, dropped


def run_one(model, video, reference):
    meta, task_frames, step, cvat_labels, W, H = load_reference(reference)
    if FRAME_MAP:                                     # 사진 TASK: 영상 프레임 번호 목록 (좌표·크기는 영상 그대로)
        task_frames, step, W, H = [int(x) for x in FRAME_MAP], 1, None, None
        print(f"사진 TASK: 사진 {len(task_frames)}장 = 영상 프레임 {task_frames}")
    near = NEAR if NEAR is not None else max(0, step // 2)
    names = model.names
    # OCCLUDED_POLICY='split'으로 학습한 모델: 'healthy_fruit_occluded' → CVAT 라벨 healthy_fruit + 가림 표시
    base = {i: (n[:-len("_occluded")] if n.endswith("_occluded") else n) for i, n in names.items()}
    occl = {i: n.endswith("_occluded") for i, n in names.items()}
    missing = sorted({b for b in base.values() if b not in cvat_labels})
    if missing:
        raise SystemExit(f"모델 클래스 {missing}가 CVAT 라벨 {cvat_labels}에 없습니다. 이름을 맞추세요.")
    if any(occl.values()):
        print("참고: 가림 클래스(*_occluded)는 같은 이름의 CVAT 라벨 + 가림(occluded) 표시로 올립니다.")

    tracks = defaultdict(dict)   # track id → {frame: (xyxy, cls, conf)}
    last_frame, scale, total_dets = -1, None, 0
    print(f"\n[{video.name}] 기준: {reference.name} / 태스크 프레임 {task_frames[0]}~{task_frames[-1]} step={step}")
    tracker_cfg = make_tracker_cfg(TRACKER, TRACK_BUFFER)
    # 추적기 결과의 박스는 칼만 필터 추정값이라 카메라가 움직이면 실제 열매보다 늦게 따라옴 →
    # 추적 직전의 '모델이 찾은 박스'를 잡아 두었다가 같은 열매(IoU 최대)의 좌표로 바꿔 씀
    raw = {"dets": None}
    def _grab_raw(predictor):
        r0 = predictor.results[0]
        raw["dets"] = None if r0.boxes is None else r0.boxes.data.cpu().numpy().copy()
    if BOX_SOURCE == "detection":
        model.add_callback("on_predict_postprocess_end", _grab_raw)   # 추적기 콜백보다 먼저 등록됨
    swapped = [0, 0]
    kw = dict(persist=True, tracker=tracker_cfg, imgsz=IMGSZ, conf=CONF, device=DEVICE, verbose=False,
              agnostic_nms=any(occl.values()))   # split 모델: 같은 열매에 가림/안 가림 박스가 겹쳐 나오지 않게
    if DECODER == "pyav":
        print("영상 읽기: PyAV (CVAT와 같은 방식)")
        def _frames():
            import av
            with av.open(str(video)) as c:
                st = c.streams.video[0]
                for fr in c.decode(st):              # v4.24.5: 세로 영상은 CVAT처럼 돌려서 추적
                    yield model.track(upright_array(fr.to_ndarray(format="bgr24"), pyav_rotation(fr, st)), **kw)[0]
        stream = _frames()
    else:
        stream = model.track(source=str(video), stream=True, **kw)
    if FRAME_OFFSET:
        print(f"프레임 보정: 영상 프레임 + {FRAME_OFFSET} = CVAT 프레임")
    for vi, r in enumerate(stream):
        fi = vi + FRAME_OFFSET                        # CVAT 프레임 번호
        last_frame = fi
        if fi > task_frames[-1]:
            break                                     # 태스크 범위 뒤는 필요 없음
        if fi < 0:
            continue
        if scale is None:
            h, w = r.orig_shape
            if W is None:
                W, H = float(w), float(h)
            if (w, h) != (int(W), int(H)):
                if (h, w) == (int(W), int(H)):
                    raise SystemExit(f"영상이 {w}x{h}로 읽혀 CVAT({W:.0f}x{H:.0f})와 가로세로가 뒤바뀌었습니다. "
                                     "영상에 회전 정보가 없거나 읽지 못했습니다 → 0번 셀 TRACK_DECODER를 바꿔 보거나("
                                     "'pyav'↔'opencv') 영상을 확인하세요.")
                print(f"참고: 영상 {w}x{h} → CVAT {W:.0f}x{H:.0f}로 좌표 환산")
            scale = (W / w, H / h)
        if fi % 300 == 0:
            print(f"  프레임 {fi} / {task_frames[-1]} …")
        b = r.boxes
        total_dets += 0 if b is None else len(b)
        if b is None or b.id is None:
            continue
        rd = raw["dets"] if BOX_SOURCE == "detection" else None
        for xyxy, tid, c, cf in zip(b.xyxy.tolist(), b.id.int().tolist(), b.cls.int().tolist(), b.conf.tolist()):
            if rd is not None and len(rd):
                ious = [_iou(xyxy, d[:4]) for d in rd]
                j = max(range(len(rd)), key=lambda j: ious[j])
                swapped[1] += 1
                if ious[j] >= 0.3:
                    xyxy = [float(v) for v in rd[j][:4]]
                    swapped[0] += 1
            x1, y1, x2, y2 = xyxy
            tracks[tid][fi] = ((x1 * scale[0], y1 * scale[1], x2 * scale[0], y2 * scale[1]), c, cf)

    if BOX_SOURCE == "detection" and swapped[1]:
        print(f"박스 좌표: 모델이 찾은 박스 사용 {swapped[0]}/{swapped[1]}개 (나머지는 추적기 추정값)")
    if last_frame < task_frames[-1]:
        print(f"경고: 영상이 프레임 {last_frame}에서 끝났는데 태스크는 {task_frames[-1]}까지입니다. 같은 영상인지 확인하세요.")

    # ---- track → CVAT track ----
    out_tracks, rows, dropped = build_tracks(tracks, task_frames, base, occl, near, frame_map=bool(FRAME_MAP))

    # ---- XML 쓰기 ----
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    root.append(meta)
    for i, (label, boxes) in enumerate(out_tracks):
        t = ET.SubElement(root, "track", id=str(i), label=label, source="auto")
        for f, outside, (x1, y1, x2, y2), oc in boxes:
            x1, x2 = max(0.0, min(x1, W)), max(0.0, min(x2, W))
            y1, y2 = max(0.0, min(y1, H)), max(0.0, min(y2, H))
            ET.SubElement(t, "box", frame=str(f), keyframe="1", outside=str(outside), occluded=str(oc),
                          xtl=f"{x1:.2f}", ytl=f"{y1:.2f}", xbr=f"{x2:.2f}", ybr=f"{y2:.2f}", z_order="0")
    if hasattr(ET, "indent"):
        ET.indent(root, space="  ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"tracks_{video.stem}.xml"
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    with open(OUT_DIR / f"tracks_{video.stem}.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["cvat_track", "tracker_id", "label", "hits_all_frames", "first_frame", "last_frame",
                    "visible_task_frames"])
        w.writerows(rows)

    per_label = defaultdict(int)
    for label, _b in out_tracks:
        per_label[label] += 1
    import json
    (OUT_DIR / f"tracks_{video.stem}.json").write_text(json.dumps({
        "video": video.name, "reference": reference.name, "tracks": len(out_tracks), "per_label": dict(per_label),
        "dropped_short": dropped, "task_frames": len(task_frames), "step": step, "model": str(MODEL),
        "imgsz": IMGSZ, "conf": CONF, "tracker": TRACKER, "min_hits": MIN_HITS,
        "track_buffer": TRACK_BUFFER, "fill_gaps": FILL_GAPS, "decoder": DECODER, "frame_offset": FRAME_OFFSET, "frame_map": FRAME_MAP, "box_source": BOX_SOURCE, "near": near, "detections_all_frames": total_dets}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n완료: {out}")
    print(f"track {len(out_tracks)}개 (= 이 영상에서 추정한 개체 수) {dict(per_label)} / 버린 짧은 track {dropped}개")
    print(f"태스크 프레임 {len(task_frames)}개 (step={step}), 빌려오기 범위 ±{near}프레임, 추적기 {TRACKER} "
          f"(buffer {TRACK_BUFFER}), 빈틈 보간 ≤{FILL_GAPS}프레임")
    print(f"검출 박스 수(전체 프레임): {total_dets}개 / 신뢰도 하한 {CONF}")
    print("CVAT에서 확인할 것: ① 같은 열매가 track 2개로 끊긴 곳(Merge로 합치기) ② 놓친 열매 ③ 엉뚱한 박스")
    return out


def main():
    global MODEL, OUT_DIR, IMGSZ, CONF, DEVICE, TRACKER, MIN_HITS, NEAR, FILL_GAPS, TRACK_BUFFER, DECODER, FRAME_OFFSET, BOX_SOURCE, FRAME_MAP
    ap = argparse.ArgumentParser(description="YOLO 추적 결과를 CVAT for video 1.1 track XML로 변환")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--video", nargs="+", default=[str(VIDEO)], help="원본 mp4 (여러 개 가능)")
    ap.add_argument("--reference", nargs="+", default=[str(REFERENCE)],
                    help="같은 태스크에서 export한 zip/XML (--video와 같은 순서)")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--imgsz", type=int, default=IMGSZ)
    ap.add_argument("--conf", type=float, default=CONF)
    ap.add_argument("--device", default=DEVICE)
    ap.add_argument("--tracker", default=TRACKER)
    ap.add_argument("--min-hits", type=int, default=MIN_HITS)
    ap.add_argument("--near", type=int, default=NEAR)
    ap.add_argument("--fill-gaps", type=int, default=FILL_GAPS)
    ap.add_argument("--track-buffer", type=int, default=TRACK_BUFFER)
    ap.add_argument("--decoder", choices=["opencv", "pyav"], default=DECODER)
    ap.add_argument("--frame-offset", type=int, default=FRAME_OFFSET)
    ap.add_argument("--box-source", choices=["detection", "tracker"], default=BOX_SOURCE)
    ap.add_argument("--frame-map", default="", help="사진 TASK: 사진 순서대로 영상 프레임 번호 '0,8,16,…' (v4.31.5)")
    a = ap.parse_args()
    if len(a.video) != len(a.reference):
        raise SystemExit("--video와 --reference 개수가 같아야 합니다 (같은 순서로).")
    MODEL, OUT_DIR, IMGSZ, CONF, DEVICE = a.model, Path(a.out), a.imgsz, a.conf, a.device
    TRACKER, MIN_HITS, NEAR = a.tracker, a.min_hits, a.near
    FILL_GAPS, TRACK_BUFFER = a.fill_gaps, a.track_buffer
    DECODER, FRAME_OFFSET, BOX_SOURCE = a.decoder, a.frame_offset, a.box_source
    FRAME_MAP = [int(x) for x in a.frame_map.replace(" ", "").split(",") if x != ""] or None
    if FRAME_MAP and len(a.video) != 1:
        raise SystemExit("--frame-map은 영상 하나에만 씁니다.")

    from ultralytics import YOLO
    for v, r in zip(a.video, a.reference):
        model = YOLO(MODEL)   # 영상마다 새로 불러 추적기 상태(ID)를 초기화
        run_one(model, Path(v), Path(r))


if __name__ == "__main__":
    main()
