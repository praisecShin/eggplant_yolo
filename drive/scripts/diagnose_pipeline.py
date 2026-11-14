"""
자동 라벨링이 왜 안 맞는지 단계별로 찾기 (손으로 라벨한 TASK 하나로 시험)

  ① 프레임 맞춤 : CVAT가 보여 주는 프레임 k  ↔  원본 mp4의 프레임 번호  (OpenCV / PyAV 각각, 몇 프레임 밀렸는지)
  ② 모델        : CVAT 프레임에 모델을 돌려 손 라벨(GT)과 비교 → 모델 자체 성능 (정밀도·재현율)
  ③ 영상 프레임 : 같은 번호의 mp4 프레임에 모델 → ②보다 많이 나쁘면 디코딩·프레임 밀림 문제
  ④ track XML   : 5번 셀이 만든 track XML ↔ GT → ②는 좋은데 ④가 나쁘면 추적·변환 문제

노트북 20번 셀에서 run_diagnosis(...)를 부른다. CVAT·Drive의 라벨은 바꾸지 않는다.
"""
__version__ = "4.32.0"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import io
import numpy as np

THUMB = (160, 90)          # 프레임 비교용 축소 크기


def _gray_thumb(img_rgb_or_bgr):
    import cv2
    a = np.asarray(img_rgb_or_bgr)
    if a.ndim == 3:
        a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    a = cv2.resize(a, THUMB, interpolation=cv2.INTER_AREA).astype(np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


def _diff(a, b):
    return float(np.mean((a - b) ** 2))


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


def read_video_thumbs(path, wanted, decoder="opencv", keep_full=()):
    """wanted 프레임 번호의 축소 회색 이미지, keep_full 번호는 원본(RGB)도. 순차로 읽어 번호를 셈.
    반환: (thumbs, fulls, size(w,h), 읽은 프레임 수)"""
    wanted, keep_full = set(wanted), set(keep_full)
    last = max(wanted | keep_full) if (wanted or keep_full) else -1
    thumbs, fulls, size, n = {}, {}, None, 0
    if decoder == "pyav":
        import av
        with av.open(str(path)) as c:
            st = c.streams.video[0]
            for i, fr in enumerate(c.decode(st)):
                n = i + 1
                if i in wanted or i in keep_full:
                    rgb = upright_array(fr.to_ndarray(format="rgb24"), pyav_rotation(fr, st))   # v4.24.5
                    size = (rgb.shape[1], rgb.shape[0])
                    if i in wanted:
                        thumbs[i] = _gray_thumb(rgb)
                    if i in keep_full:
                        fulls[i] = rgb
                if i >= last:
                    break
    else:
        import cv2
        cap = cv2.VideoCapture(str(path))
        i = 0
        while i <= last:
            ok, bgr = cap.read()
            if not ok:
                break
            n = i + 1
            if i in wanted or i in keep_full:
                rgb = bgr[:, :, ::-1]
                size = (rgb.shape[1], rgb.shape[0])
                if i in wanted:
                    thumbs[i] = _gray_thumb(rgb)
                if i in keep_full:
                    fulls[i] = np.ascontiguousarray(rgb)
            i += 1
        cap.release()
    return thumbs, fulls, size, n


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def match_pr(gt, pred, thr=0.5):
    """라벨 무시(박스 위치만)로 맞춤. 반환 (TP, GT 수, 예측 수)"""
    used, tp = set(), 0
    for g in gt:
        best, bj = thr, None
        for j, p in enumerate(pred):
            if j not in used:
                v = _iou(g, p)
                if v >= best:
                    best, bj = v, j
        if bj is not None:
            used.add(bj)
            tp += 1
    return tp, len(gt), len(pred)


def _pr_text(tp, ng, npd):
    p = tp / npd if npd else 0.0
    r = tp / ng if ng else 0.0
    return p, r, f"정밀도 {p:.0%} · 재현율 {r:.0%} (맞음 {tp} / 정답 {ng} / 예측 {npd})"


def run_diagnosis(task, gt_path, video_path, model_path, imgsz=1920, conf=0.25, samples=6, window=15,
                  track_xml=None, draw=3, out_png=None, log=print):
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cvat_task_tools as ctt
    import cv2
    from PIL import Image
    from ultralytics import YOLO

    res = {}
    gt = ctt.load_annotations(gt_path)
    frames = gt["frames"]
    model = YOLO(model_path)
    base = {i: (n[:-9] if n.endswith("_occluded") else n) for i, n in model.names.items()}
    known = set(base.values())
    gt_boxes = {f: [b[3] for b in lst if b[1] in known] for f, lst in gt["boxes"].items()}
    labelled = [f for f in frames if gt_boxes.get(f)]
    if not labelled:
        raise SystemExit(f"GT에 모델 클래스 {sorted(known)} 박스가 없습니다. 손으로 라벨한 TASK의 export/백업을 주세요.")
    picks = [labelled[int(i)] for i in np.linspace(0, len(labelled) - 1, min(samples, len(labelled)))]
    picks = sorted(set(picks))
    W, H = gt["meta"]["W"], gt["meta"]["H"]
    log(f"GT: {gt['meta']['name']} · TASK 프레임 {len(frames)}개 (step {gt['meta']['step']}) · 모델 클래스 박스가 있는 프레임 {len(labelled)}개")
    log(f"모델 클래스 {sorted(known)} · 시험 프레임 {picks}")

    # ---- ① 프레임 맞춤 ----
    cv_imgs, cv_thumbs = {}, {}
    for f in picks:
        k = frames.index(f)
        try:
            im = Image.open(task.get_frame(k, quality="original")).convert("RGB")
        except Exception as e:                      # 고해상도 영상: 원본 프레임 불가(cvat#7425) → 압축 프레임
            if "resolution" not in str(e):
                raise
            im = Image.open(task.get_frame(k, quality="compressed")).convert("RGB")
            if W and H and im.size != (int(W), int(H)):
                im = im.resize((int(W), int(H)))
            if f == picks[0]:
                log("  참고: 원본 프레임을 서버가 만들지 못해(고해상도, cvat#7425) 압축 프레임으로 비교합니다")
        cv_imgs[f] = np.asarray(im)
        cv_thumbs[f] = _gray_thumb(cv_imgs[f])
    log(f"\n① 프레임 맞춤 — CVAT 프레임 크기 {cv_imgs[picks[0]].shape[1]}x{cv_imgs[picks[0]].shape[0]} (export 기준 {W:.0f}x{H:.0f})")
    wanted = {g for f in picks for g in range(max(0, f - window), f + window + 1)}
    res["offset"] = {}
    decoders = ["opencv"]
    try:
        import av  # noqa
        decoders.append("pyav")
    except Exception:
        log("  (PyAV 없음 → pip install av 하면 CVAT와 같은 방식의 디코딩도 비교)")
    vid_full = {}
    for dec in decoders:
        th, full, size, n = read_video_thumbs(video_path, wanted, dec, keep_full=picks if dec == "opencv" else ())
        if dec == "opencv":
            vid_full = full
        offs = []
        for f in picks:
            cands = {g - f: _diff(cv_thumbs[f], th[g]) for g in range(f - window, f + window + 1) if g in th}
            if not cands:
                offs.append(None)
                continue
            best = min(cands, key=cands.get)
            offs.append((best, cands[best], cands.get(0)))
        ok = [o for o in offs if o]
        same = ok and all(o[0] == ok[0][0] for o in ok)
        res["offset"][dec] = [o[0] if o else None for o in offs]
        log(f"  {dec:6s}: 영상 {size[0] if size else '?'}x{size[1] if size else '?'} · 읽은 프레임 {n} · "
            f"밀림(영상 번호 - CVAT 번호) = {[o[0] if o else '없음' for o in offs]}"
            + ("  ✅ 일치" if same and ok[0][0] == 0 else (f"  ⚠️ 일정하게 {ok[0][0]}프레임 밀림" if same else "  ❌ 프레임마다 다름")))
        if ok:
            log(f"          차이값(작을수록 같음) 최적 {np.mean([o[1] for o in ok]):.2f} / 같은 번호 {np.mean([o[2] for o in ok if o[2] is not None]):.2f}")
        if size and (size[0], size[1]) != (int(W), int(H)):
            log(f"  ⚠️ 영상 크기 {size} ≠ CVAT {W:.0f}x{H:.0f}" + (" — 가로세로 뒤바뀜(회전 메타데이터)" if size == (int(H), int(W)) else ""))

    # ---- ② CVAT 프레임 / ③ 영상 프레임 에 모델 ----
    preds_cv, preds_vid = {}, {}
    tot_cv, tot_vid = [0, 0, 0], [0, 0, 0]
    for f in picks:
        r = model.predict(cv_imgs[f], imgsz=imgsz, conf=conf, verbose=False, agnostic_nms=True)[0]
        preds_cv[f] = r.boxes.xyxy.tolist()
        for i, v in enumerate(match_pr(gt_boxes[f], preds_cv[f])):
            tot_cv[i] += v
        if f in vid_full:
            img = vid_full[f]
            r = model.predict(img, imgsz=imgsz, conf=conf, verbose=False, agnostic_nms=True)[0]
            sx, sy = W / img.shape[1], H / img.shape[0]
            preds_vid[f] = [(a * sx, b * sy, c * sx, d * sy) for a, b, c, d in r.boxes.xyxy.tolist()]
            for i, v in enumerate(match_pr(gt_boxes[f], preds_vid[f])):
                tot_vid[i] += v
    p2, r2, t2 = _pr_text(*tot_cv)
    p3, r3, t3 = _pr_text(*tot_vid)
    log(f"\n② 모델 × CVAT 프레임 (conf {conf}, IoU 0.5): {t2}")
    log(f"③ 모델 × mp4 프레임(OpenCV, 같은 번호): {t3}")
    res.update(model_cvat=(p2, r2), model_video=(p3, r3))

    # ---- ④ track XML ----
    if track_xml:
        tr = ctt.load_annotations(track_xml)
        tot = [0, 0, 0]
        for f in labelled:
            pb = [b[3] for b in tr["boxes"].get(f, [])]
            for i, v in enumerate(match_pr(gt_boxes[f], pb)):
                tot[i] += v
        p4, r4, t4 = _pr_text(*tot)
        log(f"④ track XML × GT (라벨 있는 프레임 {len(labelled)}개 전체): {t4}")
        res["track_xml"] = (p4, r4)

    # ---- 판정 ----
    log("\n판정")
    off = res["offset"].get("opencv", [])
    off_ok = off and all(o == 0 for o in off)
    if not off_ok:
        known_off = [o for o in off if o is not None]
        if known_off and len(set(known_off)) == 1:
            log(f"  ❌ mp4(OpenCV) 프레임이 CVAT보다 {known_off[0]}프레임 밀려 있습니다 → 5번 셀 TRACK_FRAME_OFFSET = {-known_off[0]} 로 다시 track 생성")
        else:
            log("  ❌ 프레임 밀림이 일정하지 않습니다 → 5번 셀 TRACK_DECODER = 'pyav' 로 시험"
                + (f" (PyAV 결과 {res['offset'].get('pyav')})" if "pyav" in res["offset"] else ""))
    else:
        log("  ✅ ① 프레임 번호는 맞습니다")
    if r2 < 0.3:
        log("  ❌ ② 모델이 CVAT 프레임에서도 열매를 거의 못 찾습니다 → 모델·학습 데이터 문제 (아래 '학습 점검')")
    elif r2 < 0.6:
        log("  ⚠️ ② 모델 재현율이 낮습니다 → conf 낮추기(0.1~0.15), 데이터 늘리기")
    else:
        log("  ✅ ② 모델은 CVAT 프레임에서 열매를 찾습니다")
    if preds_vid and r3 < r2 - 0.2:
        log("  ❌ ③ mp4 프레임에서 훨씬 나쁨 → 디코딩/프레임 밀림 (①과 함께 보기)")
    if "track_xml" in res and res["track_xml"][1] < r2 - 0.2:
        log("  ❌ ④ track XML이 모델보다 나쁨 → 추적 설정(TRACK_CONF·MIN_HITS) 또는 프레임 변환 문제")

    # ---- 그림 ----
    if draw:
        import matplotlib.pyplot as plt
        sel = picks[:: max(1, len(picks) // draw)][:draw]
        fig, axes = plt.subplots(2, len(sel), figsize=(6 * len(sel), 7), squeeze=False)
        for j, f in enumerate(sel):
            for row, (img, pred, name) in enumerate([(cv_imgs[f], preds_cv[f], "CVAT frame"),
                                                     (vid_full.get(f), preds_vid.get(f, []), "mp4 frame (OpenCV)")]):
                ax = axes[row][j]
                ax.axis("off")
                if img is None:
                    ax.set_title(f"{name} {f}: none")
                    continue
                vis = np.ascontiguousarray(img).copy()
                sx, sy = img.shape[1] / W, img.shape[0] / H
                lw = max(3, img.shape[1] // 400)
                for (a, b, c, d) in gt_boxes[f]:
                    cv2.rectangle(vis, (int(a * sx), int(b * sy)), (int(c * sx), int(d * sy)), (255, 255, 255), lw + 2)
                for (a, b, c, d) in pred:
                    cv2.rectangle(vis, (int(a * sx), int(b * sy)), (int(c * sx), int(d * sy)), (255, 230, 0), lw)
                ax.imshow(vis)
                tp, ng, npd = match_pr(gt_boxes[f], pred)
                ax.set_title(f"{name} {f}: GT {ng} / pred {npd} / match {tp}")
        fig.suptitle("white = hand label (GT), yellow = model prediction", y=1.0)
        plt.tight_layout()
        if out_png:
            plt.savefig(out_png, dpi=60)
        plt.show()
    return res
