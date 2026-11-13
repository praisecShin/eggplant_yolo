"""
CVAT export → YOLO 데이터셋 변환 (CVAT for video 1.1 / CVAT for images 1.1 자동 판별)

입력: INPUT_DIR 폴더에 CVAT에서 받은 파일을 섞어 넣으면 됨
    - zip  : export한 zip (이미지 포함이든 annotations만이든)
    - xml  : annotations.xml 단독 (파일 이름은 자유)
  파일마다 XML 안을 보고 형식을 판별한다.
    <image> 요소가 있으면 → CVAT for images 1.1 (이미지별 박스)
    없으면               → CVAT for video 1.1 (track / 프레임 번호)

이미지를 찾는 순서
  video  형식: zip 안 images/frame_XXXXXX → CVAT_FRAMES_DIR(task_<ID>_frame_<N>.jpg) → VIDEOS_DIR의 mp4에서 추출
  images 형식: zip 안 images/<이름>       → IMAGES_DIR(원본 이미지 폴더, 이름 또는 확장자만 다른 이름)

처리 내용
- track이든 프레임별 박스든 모두 프레임별 박스로 펼침 (키프레임 사이 선형 보간,
  outside 없이 끝난 track은 CVAT처럼 끝까지 유지 → 리포트에 표시)
- video zip 안 이미지 번호가 절대(0,10,20…)인지 상대(0,1,2…)인지 자동 판별
- 같은 영상의 프레임은 train/val 한쪽으로만 (video: 영상 이름, images: GROUP_REGEX로 파일명에서 추출)
- VAL_TASKS(v4.13)를 주면 무작위 대신 그 TASK들(의 영상)을 val로 → split_tasks.csv에 TASK별 train/val 기록
- PNG는 JPG(품질 95)로 저장, MERGE_HEALTH / KEEP_CLASSES로 학습 클래스 조정
- occluded 정책(keep/split/drop) + occluded_info.csv, 확인용 _check/, data.yaml, 통계 리포트

사용법: 설정 영역만 고친 뒤  python cvat_to_yolo.py
"""
__version__ = "4.31.9"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import csv
import io
import random
import re
import shutil
import threading
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

# ----------------- [설정 영역] -----------------
INPUT_DIR = Path("./zips")               # CVAT export zip / annotations XML을 모아둔 폴더 (섞어도 됨)
IMAGES_DIR = Path("./raw_images")        # images 형식인데 zip에 이미지가 없을 때: 원본 이미지 폴더
CVAT_FRAMES_DIR = Path("./cvat_frames")  # video 형식인데 zip에 이미지가 없을 때: cvat-cli task frames 결과
VIDEOS_DIR = Path("./videos")            # 위 둘 다 없을 때: 원본 mp4에서 추출
BACKUPS_DIR = None                       # 예: Path("backups") — videos/에 영상이 없으면 TASK 백업 zip(13번 셀)에서 꺼냄
DECODER = "auto"                         # mp4 읽기: "auto"(PyAV 있으면 PyAV) / "pyav"(CVAT와 같은 FFmpeg 방식) / "opencv"
SIZE_MISMATCH = "skip"                   # v4.24.4: 이미지 가로세로 비율이 XML(original_size)과 다른 프레임 — "skip"(빼기, 회전·잘림이면 박스가 어긋남) / "keep"
OUT_DIR = Path("./dataset")

# images 형식: 파일명에서 '영상 이름'을 뽑는 정규식 (첫 번째 괄호). 같은 이름끼리 train/val 한쪽으로.
#   예) GX010123_frame_000123.jpg → GX010123 / 맞지 않으면 그 태스크(zip) 전체를 한 묶음으로 봄
GROUP_REGEX = r"^(.+?)_frame"

# CVAT 라벨명 그대로, 순서 = YOLO 클래스 ID
CLASS_NAMES = ["healthy_fruit", "disease_fruit", "healthy_bud", "disease_bud"]
# True: 병든 것도 합쳐 '모든 열매'=healthy_fruit, '모든 꽃봉오리'=healthy_bud
#       (이름을 CVAT 라벨과 같게 두어 자동 주석이 그대로 올라가게 함)
MERGE_HEALTH = True
MERGE_MAP = {"disease_fruit": "healthy_fruit", "disease_bud": "healthy_bud"}
# 학습할 클래스만 남기기 (None이면 전부). 예: ["healthy_fruit"] → 열매 1클래스 모델
KEEP_CLASSES = ["healthy_fruit"]

OCCLUDED_POLICY = "keep"                 # "keep" | "split" | "drop"
VAL_RATIO = 0.2                          # VAL_TASKS가 None일 때만: val로 뽑을 영상 비율(무작위)
VAL_TASKS = None                         # v4.13: val로 쓸 TASK — {TASK ID 또는 TASK 이름: True/False} · TASK ID/이름 목록 ·
                                         #        함수(task_name, task_id) → True/False. None = 무작위(VAL_RATIO)
SEED = 42
JPG_QUALITY = 95
MAKE_CHECK_IMAGES = 5                    # 묶음(영상)별 확인용 이미지 수 (0이면 생략)
# -----------------------------------------------

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".JPG", ".JPEG", ".PNG")


def _meta_task(root):
    t = root.find("meta/task")
    if t is None:
        t = root.find("meta/job")
    if t is None:
        t = root.find("meta/project")
    return t


def _box_coords(b):
    return [float(b.get(k)) for k in ("xtl", "ytl", "xbr", "ybr")]


def _ignored_shapes(root, stats):
    for tag in ("polygon", "points", "polyline", "skeleton", "mask", "ellipse", "cuboid"):
        n = len(root.findall(f".//{tag}"))
        if n:
            stats[f"ignored_{tag}"] += n


# ---------------- CVAT for video 1.1 ----------------
def parse_video(root):
    t = _meta_task(root)
    info = {
        "id": t.findtext("id") if t is not None else "",
        "source": (t.findtext("source") or t.findtext("name") or "") if t is not None else "",
        "start": int(t.findtext("start_frame") or 0),
        "stop": int(t.findtext("stop_frame") or 0),
        "step": 1,
        "W": float(t.findtext("original_size/width")),
        "H": float(t.findtext("original_size/height")),
    }
    ff = (t.findtext("frame_filter") or "").strip()
    if ff.startswith("step="):
        info["step"] = int(ff.split("=")[1])
    info["frames"] = list(range(info["start"], info["stop"] + 1, info["step"]))

    per_frame = defaultdict(list)   # 절대 프레임 → [(label, occluded, xtl, ytl, xbr, ybr)]
    stats = Counter()
    for tr in root.findall("track"):
        label = tr.get("label")
        kf = sorted(((int(b.get("frame")), b) for b in tr.findall("box")), key=lambda x: x[0])
        if not kf:
            stats["non_box_track"] += 1
            continue
        for i, (f, b) in enumerate(kf):
            if b.get("outside") == "1":
                continue
            c = _box_coords(b)
            occ = b.get("occluded") == "1"
            per_frame[f].append((label, occ, *c))
            stats["keyframe" if b.get("keyframe") == "1" else "interpolated_written"] += 1
            if i + 1 < len(kf):
                f2, b2 = kf[i + 1]
                c2 = _box_coords(b2)
                for g in info["frames"]:
                    if f < g < f2:
                        if b2.get("outside") == "1":     # 다음이 outside면 사라질 때까지 그대로
                            per_frame[g].append((label, occ, *c))
                        else:                            # 선형 보간
                            r = (g - f) / (f2 - f)
                            per_frame[g].append((label, occ, *[a + (z - a) * r for a, z in zip(c, c2)]))
                        stats["interpolated_filled"] += 1
            else:                                         # outside 없이 끝남 → CVAT처럼 끝까지 유지
                for g in info["frames"]:
                    if g > f:
                        per_frame[g].append((label, occ, *c))
                        stats["held_to_end"] += 1
    for b in root.findall("box"):                         # track 밖 단독 박스
        per_frame[int(b.get("frame"))].append((b.get("label"), b.get("occluded") == "1", *_box_coords(b)))
        stats["shape"] += 1
    _ignored_shapes(root, stats)
    return info, per_frame, stats


FRAME_RE = re.compile(r"(?:^|/)images/frame_(\d+)\.(png|jpe?g)$", re.I)


def map_zip_frames(zf, frames):
    """zip 안 images/frame_N → 절대 프레임. 번호 체계 자동 판별."""
    nums = {}
    for n in zf.namelist():
        m = FRAME_RE.search(n.replace("\\", "/"))
        if m:
            nums[int(m.group(1))] = n
    if not nums:
        return {}, "zip에 이미지 없음"
    if set(frames) <= set(nums):
        return {f: nums[f] for f in frames}, "절대 번호"
    if set(nums) == set(range(len(frames))):
        return {f: nums[i] for i, f in enumerate(frames)}, "상대 번호"
    srt = [nums[k] for k in sorted(nums)]
    print(f"  경고: 이미지 {len(nums)}장 / 태스크 프레임 {len(frames)}개 — 번호 체계가 맞지 않음. _check 확인 필수")
    return {f: srt[i] for i, f in enumerate(frames) if i < len(srt)}, "판별 불가 → 정렬 순서로 대응"


VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


def find_video_file(source, task_name=""):
    """VIDEOS_DIR(하위 폴더 포함)에서 영상 찾기: CVAT 원본 파일 이름 → 대소문자 무시 → 확장자 무시 → TASK 기본 이름
    (TASK 기본 이름 = 'eggplant_G1_261019_1_1_uld'에서 상태를 뺀 'eggplant_G1_261019_1_1')"""
    if not VIDEOS_DIR.exists():
        return None
    if source and (VIDEOS_DIR / source).exists():
        return VIDEOS_DIR / source
    files = [f for f in VIDEOS_DIR.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
    if source:
        name = Path(source).name
        for test in (lambda f: f.name == name, lambda f: f.name.lower() == name.lower(),
                     lambda f: f.stem.lower() == Path(name).stem.lower()):
            hit = next((f for f in files if test(f)), None)
            if hit:
                return hit
    m = re.match(r"^(.*?_\d{6,8}_\d+_\d+)(?:_|$)", task_name or "")
    if m:
        b = m.group(1).lower()
        return next((f for f in files if f.stem.lower() == b), None)
    return None


def task_frames(root):
    """meta의 start/stop/step으로 TASK 프레임 번호 목록 (영상 TASK가 아니면 [])"""
    t = _meta_task(root)
    if t is None or t.findtext("start_frame") is None:
        return []
    start, stop = int(t.findtext("start_frame") or 0), int(t.findtext("stop_frame") or 0)
    ff = (t.findtext("frame_filter") or "").strip()
    step = int(ff.split("=")[1]) if ff.startswith("step=") else 1
    return list(range(start, stop + 1, step))


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


def decoder_label(dec=None):
    """디코더 이름과 라이브러리 버전 (예: 'pyav 14.0.1', 'opencv 4.10.0') — 리포트·split_tasks.csv·학습 대장에 남김 (v4.24.4)"""
    dec = dec or _decoder()
    try:
        if dec == "pyav":
            import av
            return f"pyav {av.__version__}"
        import cv2
        return f"opencv {cv2.__version__}"
    except Exception:
        return dec


def _video_meta(path, dec):
    """영상 머리글의 프레임 수와 크기 (모르면 0) — 디코딩하지 않음"""
    try:
        if dec == "pyav":
            import av
            with av.open(str(path)) as c:
                s = c.streams.video[0]
                return int(s.frames or 0), (int(s.codec_context.width or 0), int(s.codec_context.height or 0))
        import cv2
        cap = cv2.VideoCapture(str(path))
        n, w, h = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        cap.release()
        return int(n or 0), (int(w or 0), int(h or 0))
    except Exception:
        return 0, (0, 0)


def _decoder():
    if DECODER in ("pyav", "auto"):
        try:
            import av  # noqa: F401
            return "pyav"
        except ImportError:
            if DECODER == "pyav":
                print("  참고: PyAV가 없어 OpenCV로 읽습니다 (pip install av)")
    return "opencv"


FRAME_CACHE_DIR = None    # 영상에서 뽑은 프레임을 잠시 둘 디스크 폴더 (None = 임시 폴더). 메모리에 쌓지 않음
PROGRESS_HOOK = None      # 오래 걸리는 동안 주기적으로 부를 함수 (노트북의 학습 잠금 갱신용)
LOAD_WORKERS = 4          # v4.30: TASK zip을 동시에 몇 개 읽나 (영상에서 프레임 꺼내기 포함). 1 = 차례로
_VIDEO_LOCK = threading.Lock()                 # 백업에서 영상 꺼내기는 한 번에 하나 (같은 파일에 쓰지 않게)
_PATH_LOCKS, _PATH_LOCKS_LOCK = {}, threading.Lock()


def _path_lock(p):
    """같은 영상에서 동시에 프레임을 꺼내지 않게 (영상마다 잠금)"""
    with _PATH_LOCKS_LOCK:
        return _PATH_LOCKS.setdefault(str(p), threading.Lock())


_TICK_LOCK = threading.Lock()


def _tick():
    if PROGRESS_HOOK and _TICK_LOCK.acquire(blocking=False):   # 여러 줄이 동시에 부르면 하나만
        try:
            PROGRESS_HOOK()
        except Exception:
            pass
        finally:
            _TICK_LOCK.release()


def _tick_old():
    if PROGRESS_HOOK:
        try:
            PROGRESS_HOOK()
        except Exception:
            pass


class _DiskFrames:
    """뽑은 프레임을 디스크(JPG)에 두고, 쓸 때 한 장씩 여는 dict 비슷한 것.
    (v4.6까지는 4K 프레임을 모두 메모리에 들고 있어 TASK가 많으면 Colab RAM 12GB를 넘어 멈췄음)
    v4.24.4: label = 어떤 디코더로 뽑았는지, video_frames·video_size = 영상 머리글 값"""
    def __init__(self):
        self.paths = {}
        self.label, self.video_frames, self.video_size, self.rotation = "", 0, (0, 0), 0

    def get(self, f):
        p = self.paths.get(f)
        return Image.open(p) if p else None

    def __len__(self):
        return len(self.paths)


def _cache_dir(path):
    import tempfile
    root = Path(FRAME_CACHE_DIR) if FRAME_CACHE_DIR else Path(tempfile.gettempdir()) / "eggplant_frame_cache"
    d = root / re.sub(r"[^\w\-]+", "_", Path(path).stem)
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_mp4(path, frames):
    """같은 영상은 한 번에 하나만 꺼냄 (v4.30: TASK를 동시에 읽을 때)"""
    with _path_lock(path):
        return _extract_mp4(path, frames)


def _extract_mp4(path, frames):
    """mp4를 처음부터 순서대로 읽어 frames 번호의 이미지를 꺼냄 (seek보다 정확).
    PyAV(CVAT 서버와 같은 FFmpeg 디코딩)를 기본으로 써서 CVAT 프레임 번호와 맞춤.
    꺼낸 프레임은 바로 디스크에 JPG(품질 98)로 쓰고 메모리에는 경로만 남김."""
    out, want = _DiskFrames(), set(frames)
    if not want:
        return out
    last, cdir = max(want), _cache_dir(path)
    dec = _decoder()
    out.label = decoder_label(dec)
    out.video_frames, out.video_size = _video_meta(path, dec)
    mark = cdir / "_decoder.txt"                  # 캐시에 남은 프레임이 다른 디코더(또는 회전 처리 전)로 뽑은 것이면 버림
    if mark.exists() and mark.read_text(encoding="utf-8").strip() != dec + "+upright":
        for old in cdir.glob("frame_*.jpg"):
            old.unlink()
    mark.write_text(dec + "+upright", encoding="utf-8")

    def keep(idx, pil):
        p = cdir / f"frame_{idx:06d}.jpg"
        if not p.exists():
            pil.save(p, quality=98)
        out.paths[idx] = p

    todo = {i for i in want if not (cdir / f"frame_{i:06d}.jpg").exists()}
    for i in want - todo:                         # 이번 실행에서 이미 뽑은 프레임은 다시 디코딩하지 않음
        out.paths[i] = cdir / f"frame_{i:06d}.jpg"
    if todo:
        last = max(todo)
        if dec == "pyav":
            import av
            with av.open(str(path)) as c:
                st = c.streams.video[0]
                for idx, fr in enumerate(c.decode(st)):
                    if idx == 0 or idx in todo:
                        rot = pyav_rotation(fr, st)
                        if idx == 0:
                            out.rotation = rot
                    if idx in todo:
                        keep(idx, upright_image(fr.to_image(), rot))
                    if idx >= last:
                        break
        else:
            import cv2
            cap = cv2.VideoCapture(str(path))
            try:                                       # OpenCV는 회전 정보대로 스스로 돌려 줌 — 기록만 (PyAV와 같은 반시계 도수로)
                out.rotation = (-int(cap.get(cv2.CAP_PROP_ORIENTATION_META) or 0)) % 360
            except Exception:
                pass
            idx = 0
            while idx <= last:
                ok, img = cap.read()
                if not ok:
                    break
                if idx in todo:
                    keep(idx, Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
                idx += 1
            cap.release()
    if out.rotation:                              # 기록·리포트에 남김 (예: 'pyav 14.0.1 회전 90')
        out.label += f" 회전 {out.rotation}"
    miss = len(want) - len(out)
    print(f"  영상 {Path(path).name}: {out.label}로 {len(out)}장 추출"
          + (f" · 영상 머리글 {out.video_frames}프레임" if out.video_frames else "")
          + (f" {out.video_size[0]}x{out.video_size[1]}" if out.video_size[0] else "")
          + (f" (회전 {out.rotation}° → 돌려서 저장)" if out.rotation else ""))
    if miss:
        print(f"  경고: {Path(path).name}에서 {miss}개 프레임을 못 읽음 (영상이 TASK보다 짧음?)")
    if out.video_frames and out.video_frames < last + 1:
        print(f"  경고: 영상 머리글 프레임 수 {out.video_frames} < TASK 마지막 프레임 {last} + 1 → 다른 영상이거나 잘린 영상인지 확인")
    return out


def _video_for(source, task_name):
    """videos/에서 찾고, 없으면 TASK 백업 zip에서 꺼내 videos/_from_backup/에 저장"""
    with _VIDEO_LOCK:
        return _video_for_one(source, task_name)


def _video_for_one(source, task_name):
    mp4 = find_video_file(source, task_name)
    if mp4 is None and BACKUPS_DIR is not None and task_name:
        try:
            import cvat_task_tools as ctt
            mp4, bz = ctt.video_from_backups(BACKUPS_DIR, task_name, VIDEOS_DIR)
            if mp4 is not None:
                print(f"  영상을 TASK 백업에서 꺼냄: {Path(bz).name} → {Path(mp4).relative_to(VIDEOS_DIR)}")
        except Exception as e:
            print(f"  백업에서 영상 꺼내기 실패: {e}")
            mp4 = None
    return mp4


def build_video_task(root, src_name, zf):
    info, per_frame, stats = parse_video(root)
    stem = Path(info["source"]).stem or Path(src_name).stem
    frames = info["frames"]
    getter, numbering = None, ""
    if zf is not None:
        mapping, numbering = map_zip_frames(zf, frames)
        if mapping:
            getter = lambda f, zf=zf, m=mapping: Image.open(io.BytesIO(zf.read(m[f]))) if f in m else None
    if getter is None:
        paths = {}
        for i, f in enumerate(frames):              # API 프레임 번호 = 상대 번호
            for ext in (".jpg", ".png", ".jpeg"):
                p = CVAT_FRAMES_DIR / f"task_{info['id']}_frame_{i}{ext}"
                if p.exists():
                    paths[f] = p
                    break
        if paths:
            getter, numbering = (lambda f, p=paths: Image.open(p[f]) if f in p else None), "cvat_frames(API 번호)"
    if getter is None:
        t = _meta_task(root)
        mp4 = _video_for(info["source"], (t.findtext("name") or "") if t is not None else "")
        if mp4 is not None:
            imgs = extract_mp4(mp4, frames)
            getter, numbering = (lambda f, d=imgs: d.get(f)), f"mp4 추출({imgs.label})"
            frames_from = f"mp4 {imgs.label}"
        else:
            getter, numbering = (lambda f: None), "이미지 못 찾음"
            frames_from = "없음"
    else:
        frames_from = "export 이미지" if numbering and "cvat_frames" not in numbering else "CVAT 프레임(API)"
    items = [{"key": f, "out": f"{stem}_frame_{f:06d}", "group": stem, "get": (lambda f=f: getter(f)),
              "boxes": per_frame.get(f, []), "W": info["W"], "H": info["H"]} for f in frames]
    desc = f"video / task {info['id']} / {info['source']} / 프레임 {len(frames)}개 (step={info['step']})"
    return {"name": stem, "fmt": "video", "items": items, "stats": stats, "numbering": numbering, "desc": desc,
            "frames_from": frames_from}


# ---------------- CVAT for images 1.1 ----------------
def build_images_task(root, src_name, zf):
    t = _meta_task(root)
    tname = (t.findtext("name") if t is not None else "") or Path(src_name).stem
    prefix = re.sub(r"[^\w\-]+", "_", Path(src_name).stem)
    stats = Counter()
    # zip 안 이미지 색인
    zindex = {}
    if zf is not None:
        for n in zf.namelist():
            nn = n.replace("\\", "/")
            if nn.lower().endswith(tuple(e.lower() for e in IMG_EXTS)):
                zindex.setdefault(nn, n)
                zindex.setdefault(nn.split("/")[-1], n)
                zindex.setdefault("stem:" + Path(nn).stem, n)
    lindex = {}
    if IMAGES_DIR.exists():
        for p in IMAGES_DIR.rglob("*"):
            if p.suffix in IMG_EXTS:
                lindex.setdefault(p.name, p)
                lindex.setdefault("stem:" + p.stem, p)

    def finder(name):
        nn = name.replace("\\", "/")
        base = nn.split("/")[-1]
        for k in ("images/" + nn, nn, base, "stem:" + Path(base).stem):
            if k in zindex:
                return ("zip", zindex[k])
        p = IMAGES_DIR / nn
        if p.exists():
            return ("file", p)
        for k in (base, "stem:" + Path(base).stem):
            if k in lindex:
                return ("file", lindex[k])
        return None

    items, found_zip, found_file = [], 0, 0
    rx = re.compile(GROUP_REGEX) if GROUP_REGEX else None
    for img in root.findall("image"):
        name = img.get("name")
        base = name.replace("\\", "/").split("/")[-1]
        W, H = float(img.get("width")), float(img.get("height"))
        boxes = []
        for b in img.findall("box"):
            if b.get("outside") == "1":
                continue
            if float(b.get("rotation", 0) or 0) != 0:
                stats["rotated_box"] += 1
            boxes.append((b.get("label"), b.get("occluded") == "1", *_box_coords(b)))
            stats["box"] += 1
        loc = finder(name)
        if loc and loc[0] == "zip":
            found_zip += 1
        elif loc:
            found_file += 1

        def get(loc=loc, zf=zf):
            if loc is None:
                return None
            return Image.open(io.BytesIO(zf.read(loc[1]))) if loc[0] == "zip" else Image.open(loc[1])
        m = rx.match(base) if rx else None
        group = m.group(1) if m else prefix
        items.append({"key": int(img.get("id", len(items))), "out": f"{prefix}_{Path(base).stem}",
                      "group": group, "get": get, "boxes": boxes, "W": W, "H": H})
    _ignored_shapes(root, stats)
    items.sort(key=lambda it: it["key"])
    numbering = f"이미지 이름 매칭 (zip {found_zip} / 폴더 {found_file} / 없음 {len(items) - found_zip - found_file})"

    # 영상 TASK를 'CVAT for images'로 라벨만 받은 경우: 이미지 이름 frame_N → 영상에서 추출
    missing = [it for it in items if it["get"]() is None] if found_zip + found_file < len(items) else []
    frames_from = "export 이미지" if found_zip else ("이미지 폴더" if found_file else "없음")
    if missing:
        frames = task_frames(root)
        source = (t.findtext("source") or "") if t is not None else ""
        mp4 = _video_for(source, tname) if frames else None
        nums = {}
        for img in root.findall("image"):
            mm = re.search(r"frame_(\d+)", img.get("name", ""))
            if mm:
                nums[int(img.get("id", -1))] = int(mm.group(1))
        if mp4 is not None and nums:
            vals = set(nums.values())
            if vals <= set(frames):
                to_abs, how = (lambda n: n), "절대 번호"
            elif vals <= set(range(len(frames))):
                to_abs, how = (lambda n: frames[n]), "상대 번호"
            else:
                to_abs, how = (lambda n: n), "번호 판별 불가 → 그대로 사용(_check 확인)"
            want = {to_abs(nums[it["key"]]) for it in missing if it["key"] in nums}
            imgs = extract_mp4(mp4, sorted(want))
            for it in missing:
                if it["key"] in nums:
                    fno = to_abs(nums[it["key"]])
                    it["get"] = (lambda d=imgs, f=fno: d.get(f))
                    it["group"] = mp4.stem                       # 같은 영상끼리 train/val 한쪽으로
            numbering += f" → 영상 {mp4.name}에서 {len(imgs)}장 추출 ({how}, {imgs.label})"
            frames_from = (f"export 이미지 + mp4 {imgs.label}" if found_zip + found_file else f"mp4 {imgs.label}")
        elif frames:
            numbering += f" → 영상 못 찾음 ({source or tname}) — VIDEOS_DIR에 올리세요"
    desc = f"images / {tname} / 이미지 {len(items)}장"
    return {"name": prefix, "fmt": "images", "items": items, "stats": stats, "numbering": numbering, "desc": desc,
            "frames_from": frames_from}


def load_tasks():
    files = sorted(list(INPUT_DIR.glob("*.zip")) + list(INPUT_DIR.glob("*.xml")))
    if not files:
        raise SystemExit(f"{INPUT_DIR}에 zip 또는 xml이 없습니다.")
    def one(fpath):
        zf = None
        try:
            if fpath.suffix.lower() == ".zip":
                zf = zipfile.ZipFile(fpath)
                xn = [n for n in zf.namelist() if n.replace("\\", "/").split("/")[-1] == "annotations.xml"]
                if not xn:
                    print(f"[{fpath.name}] annotations.xml 없음 → 건너뜀")
                    return None
                root = ET.fromstring(zf.read(xn[0]))
            else:
                root = ET.parse(fpath).getroot()
        except (zipfile.BadZipFile, ET.ParseError) as e:
            print(f"[{fpath.name}] 읽기 실패 → 건너뜀 ({e})")
            return None
        if root.find("image") is not None:
            task = build_images_task(root, fpath.name, zf)
        elif root.find("track") is not None or root.find("box") is not None or \
                (_meta_task(root) is not None and _meta_task(root).find("original_size") is not None):
            task = build_video_task(root, fpath.name, zf)
        else:
            print(f"[{fpath.name}] 박스가 없는 파일 → 건너뜀")
            return None
        mt = _meta_task(root)
        task.setdefault("task_id", ((mt.findtext("id") if mt is not None else "") or "").strip())
        task.setdefault("task_name", ((mt.findtext("name") if mt is not None else "") or "").strip())
        task["src"] = fpath.name
        _tick()
        return task

    n = max(1, min(int(LOAD_WORKERS or 1), len(files)))
    if n > 1:                                   # v4.30: TASK마다 영상 디코딩·zip 읽기를 동시에 (결과 순서는 그대로)
        from concurrent.futures import ThreadPoolExecutor
        print(f"TASK {len(files)}개를 {n}개씩 동시에 읽습니다 (영상에서 프레임 꺼내기 포함)")
        with ThreadPoolExecutor(n) as ex:
            got = list(ex.map(one, files))
    else:
        got = [one(f) for f in files]
    tasks = []
    for fpath, task in zip(files, got):
        if task is None:
            continue
        print(f"[{fpath.name}] {task['desc']} / {dict(task['stats'])}")
        print(f"  이미지: {task['numbering']} · 출처 {task.get('frames_from', '')}")
        tasks.append(task)
    return tasks


# ======================= 데이터 통계 리포트 =======================
TRAIN_IMGSZ = 1920      # 학습 때 쓸 imgsz (박스가 학습 해상도에서 몇 px이 되는지 계산용)
FEW_BOXES = 100         # 클래스당 박스가 이보다 적으면 경고
DUP_IOU = 0.7           # 같은 프레임·같은 클래스 박스끼리 IoU가 이 이상이면 중복 의심


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _hbars(title, cats, series, names, unit="개"):
    """가로 막대 (series: [[값...], ...], 시리즈 2개까지). 막대마다 값 직접 표기 + 마우스 오버 툴팁."""
    rowh, gap, left, width = 22, 14, 150, 420
    n = len(series)
    vmax = max([max(s) if s else 0 for s in series] + [1])
    h = 40 + len(cats) * (n * rowh + gap) + 10
    out = [f'<svg viewBox="0 0 {left + width + 90} {h}" role="img" aria-label="{_esc(title)}">']
    out.append(f'<line x1="{left}" y1="30" x2="{left}" y2="{h - 10}" class="axis"/>')
    y = 36
    for ci, c in enumerate(cats):
        out.append(f'<text x="{left - 8}" y="{y + n * rowh / 2 + 4}" text-anchor="end" class="lbl">{_esc(c)}</text>')
        for si in range(n):
            v = series[si][ci]
            w = 0 if v == 0 else max(2, v / vmax * width)
            out.append(f'<g><title>{_esc(c)} · {_esc(names[si])}: {v}{unit}</title>'
                       f'<rect x="{left}" y="{y + 2}" width="{width + 80}" height="{rowh - 4}" fill="transparent"/>'
                       f'<rect x="{left}" y="{y + 3}" width="{w:.1f}" height="{rowh - 6}" rx="3" class="s{si + 1}"/>'
                       f'<text x="{left + w + 6:.1f}" y="{y + rowh / 2 + 4}" class="val">{v}</text></g>')
            y += rowh
        y += gap
    out.append("</svg>")
    legend = ""
    if n > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><i class="sw s{i + 1}"></i>{_esc(nm)}</span>' for i, nm in enumerate(names)) + "</div>"
    return f'<figure><figcaption>{_esc(title)}</figcaption>{legend}{"".join(out)}</figure>'


def _hist(title, values, bin_w=4, max_px=64):
    """박스 짧은 변(학습 해상도 px) 히스토그램. 8px 미만·16px 미만 구간을 음영으로 표시."""
    nb = max_px // bin_w
    counts = [0] * (nb + 1)
    for v in values:
        counts[min(int(v // bin_w), nb)] += 1
    left, width, top, ph = 44, 520, 26, 150
    bw = width / len(counts)
    cmax = max(counts + [1])
    out = [f'<svg viewBox="0 0 {left + width + 20} {top + ph + 46}" role="img" aria-label="{_esc(title)}">']
    for lo, hi, txt in ((0, 8, "못 찾음"), (8, 16, "어려움")):
        x0, x1 = left + lo / bin_w * bw, left + hi / bin_w * bw
        out.append(f'<rect x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{ph}" class="zone"/>'
                   f'<text x="{x0 + 3:.1f}" y="{top + 12}" class="zt">{txt}</text>')
    for i, c in enumerate(counts):
        if not c:
            continue
        hgt = c / cmax * (ph - 18)
        lab = f"{i * bin_w}px 이상" if i == nb else f"{i * bin_w}~{(i + 1) * bin_w}px"
        out.append(f'<g><title>{lab}: {c}개</title>'
                   f'<rect x="{left + i * bw + 1:.1f}" y="{top}" width="{bw - 2:.1f}" height="{ph}" fill="transparent"/>'
                   f'<rect x="{left + i * bw + 1:.1f}" y="{top + ph - hgt:.1f}" width="{bw - 2:.1f}" '
                   f'height="{hgt:.1f}" rx="2" class="s1"/></g>')
    out.append(f'<line x1="{left}" y1="{top + ph}" x2="{left + width}" y2="{top + ph}" class="axis"/>')
    for i in range(0, nb + 1, 2):
        t = f"{i * bin_w}+" if i == nb else f"{i * bin_w}"
        out.append(f'<text x="{left + i * bw:.1f}" y="{top + ph + 16}" text-anchor="middle" class="tick">{t}</text>')
    out.append(f'<text x="{left + width / 2}" y="{top + ph + 36}" text-anchor="middle" class="tick">'
               f'박스 짧은 변 (imgsz={TRAIN_IMGSZ} 기준 px)</text>')
    out.append(f'<text x="{left - 6}" y="{top + 8}" text-anchor="end" class="tick">{cmax}</text>'
               f'<text x="{left - 6}" y="{top + ph}" text-anchor="end" class="tick">0</text>')
    out.append("</svg>")
    note = '<div class="note">회색 구간: 8px 미만은 거의 못 찾고, 8~16px은 찾기 어려움</div>'
    return f'<figure><figcaption>{_esc(title)}</figcaption>{note}{"".join(out)}</figure>'


def write_report(boxes, frames_info, videos, yolo_names, warn_lines):
    """boxes: dict 목록 / frames_info: (video, split, n_boxes) 목록 / videos: 영상별 dict"""
    # ---- CSV ----
    with open(OUT_DIR / "stats_boxes.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["video", "split", "frame", "cvat_label", "train_class", "occluded",
                    "w_px", "h_px", f"short_side_px_at_{TRAIN_IMGSZ}"])
        for b in boxes:
            w.writerow([b["video"], b["split"], b["frame"], b["label"], b["cls"], int(b["occ"]),
                        round(b["w"], 1), round(b["h"], 1), round(b["short"], 1)])
    with open(OUT_DIR / "stats_videos.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        cols = ["video", "split", "frames", "empty_frames", "boxes", "occluded_pct",
                "boxes_per_frame_avg", "boxes_per_frame_max", "held_to_end", "dup_suspects", "frames_from", "numbering"] + CLASS_NAMES
        w.writerow(cols)
        for v in videos:
            w.writerow([v[c] if c in v else v["by_label"].get(c, 0) for c in cols])

    # ---- 경고 ----
    warns = list(warn_lines)
    cnt_cls = Counter(b["cls"] for b in boxes)
    for n in yolo_names:
        if cnt_cls[n] == 0:
            warns.append(f"<b>{n}</b>: 박스 0개 → 이 클래스는 학습되지 않습니다.")
        elif cnt_cls[n] < FEW_BOXES:
            warns.append(f"<b>{n}</b>: 박스 {cnt_cls[n]}개 (권장 최소 {FEW_BOXES}개 미만).")
    tr = Counter(b["cls"] for b in boxes if b["split"] == "train")
    va = Counter(b["cls"] for b in boxes if b["split"] == "val")
    for n in yolo_names:
        if tr[n] and not va[n]:
            warns.append(f"<b>{n}</b>: val에 0개 → 이 클래스의 검증 점수가 나오지 않습니다.")
    for n in yolo_names:
        s = [b["short"] for b in boxes if b["cls"] == n]
        if s:
            tiny = sum(x < 8 for x in s) / len(s)
            if tiny >= 0.2:
                warns.append(f"<b>{n}</b>: {tiny:.0%}가 학습 해상도에서 8px 미만 → imgsz를 키우거나 타일링 필요.")
    dups = sum(v["dup_suspects"] for v in videos)
    if dups:
        warns.append(f"중복 의심 박스 {dups}쌍 (같은 프레임·같은 클래스, IoU≥{DUP_IOU}) → stats_videos.csv의 dup_suspects 확인.")
    held = sum(v["held_to_end"] for v in videos)
    if held:
        warns.append(f"outside 없이 끝난 track에서 끝까지 유지된 박스 {held}개 → 마지막 프레임 중복 가능.")

    # ---- 요약 수치 ----
    n_tr = sum(1 for f in frames_info if f[1] == "train")
    n_va = sum(1 for f in frames_info if f[1] == "val")
    empty = sum(1 for f in frames_info if f[2] == 0)
    occ_all = sum(b["occ"] for b in boxes) / len(boxes) if boxes else 0
    tiles = [("태스크", len(videos)), ("프레임 (train / val)", f"{n_tr} / {n_va}"),
             ("박스", len(boxes)), ("가림 비율", f"{occ_all:.0%}"), ("빈 프레임", empty)]

    # ---- 차트 ----
    charts = [_hbars("학습 클래스별 박스 수 (train / val)", yolo_names,
                     [[tr[n] for n in yolo_names], [va[n] for n in yolo_names]], ["train", "val"])]
    occ_by = [[sum(1 for b in boxes if b["label"] == n and not b["occ"]) for n in CLASS_NAMES],
              [sum(1 for b in boxes if b["label"] == n and b["occ"]) for n in CLASS_NAMES]]
    charts.append(_hbars("CVAT 라벨별 박스 수 (가림 없음 / 가림)", CLASS_NAMES, occ_by, ["가림 없음", "가림"]))
    for n in yolo_names:
        s = [b["short"] for b in boxes if b["cls"] == n]
        if s:
            srt = sorted(s)
            med = srt[len(srt) // 2]
            charts.append(_hist(f"{n} 크기 분포 — {len(s)}개, 중앙값 {med:.0f}px", s))

    # ---- 표 ----
    th = "".join(f"<th>{_esc(c)}</th>" for c in
                 ["태스크(영상)", "분할", "프레임", "빈 프레임", "박스", "가림", "프레임당 평균/최대"] + CLASS_NAMES + ["중복 의심", "끝까지 유지", "이미지 출처·디코더", "번호 맞춤"])
    rows = []
    for v in videos:
        cells = [v["video"], v["split"], v["frames"], v["empty_frames"], v["boxes"], f'{v["occluded_pct"]}%',
                 f'{v["boxes_per_frame_avg"]} / {v["boxes_per_frame_max"]}'] + \
                [v["by_label"].get(c, 0) for c in CLASS_NAMES] + [v["dup_suspects"], v["held_to_end"], v.get("frames_from", ""), v["numbering"]]
        rows.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in cells) + "</tr>")
    cls_rows = "".join(
        f"<tr><td>{_esc(n)}</td><td>{tr[n]}</td><td>{va[n]}</td><td>{tr[n] + va[n]}</td></tr>" for n in yolo_names)

    css = """
:root{--surface:#fcfcfb;--card:#ffffff;--text:#0b0b0b;--muted:#52514e;--rule:#e4e3df;--zone:#efeeea;
--s1:#2a78d6;--s2:#eb6834;--warnbg:#fff4e5;--warnbd:#eda100}
@media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])){--surface:#1a1a19;--card:#232321;
--text:#f0efec;--muted:#c3c2b7;--rule:#3a3936;--zone:#2c2b29;--s1:#3987e5;--s2:#d95926;--warnbg:#3a2e14;--warnbd:#c98500}}
:root[data-theme="dark"]{--surface:#1a1a19;--card:#232321;--text:#f0efec;--muted:#c3c2b7;--rule:#3a3936;--zone:#2c2b29;
--s1:#3987e5;--s2:#d95926;--warnbg:#3a2e14;--warnbd:#c98500}
body{margin:0;background:var(--surface);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:32px 0 10px} .sub{color:var(--muted);margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums} .tile span{color:var(--muted);font-size:12.5px}
.warn{background:var(--warnbg);border-left:4px solid var(--warnbd);border-radius:6px;padding:10px 14px;margin:6px 0}
.ok{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}
figure{margin:0;background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
figcaption{font-weight:600;margin-bottom:6px} svg{width:100%;height:auto;display:block}
.axis{stroke:var(--muted);stroke-width:1} .lbl{fill:var(--text);font-size:14px} .val{fill:var(--muted);font-size:13px} .tick{fill:var(--muted);font-size:12px}
.note{color:var(--muted);font-size:12.5px;margin-bottom:4px}
.s1{fill:var(--s1)} .s2{fill:var(--s2)} .zone{fill:var(--zone)} .zt{fill:var(--muted);font-size:11.5px}
.legend{display:flex;gap:16px;color:var(--muted);font-size:12.5px;margin-bottom:4px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
span .sw.s1{background:var(--s1)} span .sw.s2{background:var(--s2)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th{color:var(--muted);font-weight:600} th:first-child,td:first-child{text-align:left}
@media (max-width:600px){.grid{grid-template-columns:1fr}}
"""
    warn_html = "".join(f'<div class="warn">⚠ {w}</div>' for w in warns) or '<p class="ok">경고 없음</p>'
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>YOLO 데이터 통계</title>
<style>{css}</style></head><body><main>
<h1>YOLO 학습 데이터 통계</h1>
<p class="sub">occluded={OCCLUDED_POLICY} · MERGE_HEALTH={MERGE_HEALTH} · KEEP_CLASSES={KEEP_CLASSES} · 학습 해상도 imgsz={TRAIN_IMGSZ} · 클래스 {len(yolo_names)}개</p>
<div class="tiles">{"".join(f'<div class="tile"><b>{_esc(v)}</b><span>{_esc(k)}</span></div>' for k, v in tiles)}</div>
<h2>점검할 것</h2>{warn_html}
<h2>분포</h2><div class="grid">{"".join(charts)}</div>
<h2>학습 클래스별 박스 수</h2><div class="tw"><table><tr><th>클래스</th><th>train</th><th>val</th><th>합계</th></tr>{cls_rows}</table></div>
<h2>태스크(영상)별 상세</h2><div class="tw"><table><tr>{th}</tr>{"".join(rows)}</table></div>
<p class="sub" style="margin-top:16px">원자료: stats_videos.csv, stats_boxes.csv, occluded_info.csv</p>
</main></body></html>"""
    (OUT_DIR / "stats_report.html").write_text(html, encoding="utf-8")


def _clear_frame_cache():
    import tempfile
    root = Path(FRAME_CACHE_DIR) if FRAME_CACHE_DIR else Path(tempfile.gettempdir()) / "eggplant_frame_cache"
    shutil.rmtree(root, ignore_errors=True)


def _is_val_task(t):
    """VAL_TASKS(사전·목록·함수)로 이 TASK가 val인지"""
    v, tid, name = VAL_TASKS, str(t.get("task_id", "")), t.get("task_name", "")
    if callable(v):
        return bool(v(name, tid))
    if isinstance(v, dict):
        hit = v.get(tid, v.get(name))
        if hit is None and tid.isdigit():
            hit = v.get(int(tid))
        return bool(hit)
    keys = {str(x) for x in v}
    return tid in keys or name in keys


def main():
    _clear_frame_cache()                          # 이전 실행에서 남은 프레임 정리
    try:
        _main()
    finally:
        _clear_frame_cache()


def _main():
    if MERGE_HEALTH:
        train_names = list(dict.fromkeys(MERGE_MAP.get(n, n) for n in CLASS_NAMES))
    else:
        train_names = list(CLASS_NAMES)
    to_train = {n: (MERGE_MAP.get(n, n) if MERGE_HEALTH else n) for n in CLASS_NAMES}
    if KEEP_CLASSES:
        bad = [k for k in KEEP_CLASSES if k not in train_names]
        if bad:
            raise SystemExit(f"KEEP_CLASSES {bad}가 학습 클래스 {train_names}에 없습니다.")
        train_names = [n for n in train_names if n in KEEP_CLASSES]
        to_train = {k: v for k, v in to_train.items() if v in KEEP_CLASSES}
    cidx = {n: i for i, n in enumerate(train_names)}
    yolo_names = ([f"{n}{s}" for n in train_names for s in ("", "_occluded")]
                  if OCCLUDED_POLICY == "split" else list(train_names))

    for s in ("train", "val"):
        (OUT_DIR / s / "images").mkdir(parents=True, exist_ok=True)
        (OUT_DIR / s / "labels").mkdir(parents=True, exist_ok=True)

    tasks = load_tasks()
    if not tasks:
        raise SystemExit("변환할 태스크가 없습니다.")

    # ---- 이미지를 못 찾는 프레임·태스크는 분할 계획 전에 뺌 (빠진 태스크가 val로 뽑혀 val이 0장이 되지 않게) ----
    kept_tasks = []
    for t in tasks:
        avail = [it for it in t["items"] if it["get"]() is not None]
        if len(avail) < len(t["items"]):
            print(f"  경고: {t['name']} 이미지를 찾지 못한 프레임 {len(t['items']) - len(avail)}개 → 제외"
                  + (" (태스크 전체 제외)" if not avail else ""))
        t["items"] = avail
        if avail:
            kept_tasks.append(t)
    tasks = kept_tasks
    if not tasks:
        raise SystemExit("이미지를 찾은 태스크가 없습니다 (zip 안 이미지 / IMAGES_DIR / CVAT_FRAMES_DIR / VIDEOS_DIR 확인).")

    # ---- 이름 겹침 점검 ----
    seen = Counter(it["out"] for t in tasks for it in t["items"])
    dup_names = [n for n, c in seen.items() if c > 1]
    if dup_names:
        print(f"경고: 출력 이름이 겹치는 이미지 {len(dup_names)}개 (같은 영상/태스크를 두 번 넣었는지 확인): {dup_names[:3]}")

    # ---- 분할 계획: 묶음(영상) 단위. 묶음이 1개뿐이면 태스크마다 뒤쪽 블록을 val ----
    gsize = Counter(it["group"] for t in tasks for it in t["items"])
    groups = sorted(gsize)
    val_groups = set()
    by_rule = VAL_TASKS is not None
    if by_rule:                                   # v4.13: 규칙으로 정한 TASK(의 영상 전체)를 val로
        val_groups = {it["group"] for t in tasks if _is_val_task(t) for it in t["items"]}
        moved = sorted(t["task_name"] or t["name"] for t in tasks
                       if not _is_val_task(t) and any(it["group"] in val_groups for it in t["items"]))
        if moved:
            print(f"경고: val TASK와 같은 영상을 쓰는 train TASK {len(moved)}개도 val로 보냄 (한 영상은 한쪽에만): {moved[:5]}")
        if not val_groups:
            print("경고: VAL_TASKS에 맞는 TASK가 없어 val이 0장입니다.")
    elif len(groups) >= 2:
        random.Random(SEED).shuffle(groups)
        total, n = sum(gsize.values()), 0
        for g in groups:
            if n >= round(total * VAL_RATIO):
                break
            val_groups.add(g)
            n += gsize[g]
    else:
        print("참고: 묶음(영상)이 1개뿐이라 뒤쪽 프레임 블록을 val로 사용합니다.")

    occl_rows, cls_count, occ_count, unknown, sc = [], Counter(), Counter(), Counter(), Counter()
    dropped_labels = Counter()
    check_items, size_warned = defaultdict(list), set()
    box_recs, frames_info, video_rows, report_warns = [], [], [], []
    split_rows = []                               # v4.13: TASK별 train/val (split_tasks.csv → 노트북의 TASK 학습 대장)

    for task in tasks:
        tname, items = task["name"], task["items"]
        cut = len(items) - max(1, round(len(items) * VAL_RATIO))
        missing, skipped_size = 0, 0
        v = {"video": tname, "frames_from": task.get("frames_from", ""), "split": "", "frames": 0, "empty_frames": 0, "boxes": 0, "occ": 0,
             "per_frame": [], "held_to_end": task["stats"].get("held_to_end", 0), "dup_suspects": 0,
             "numbering": f"{task['fmt']}: {task['numbering']}", "by_label": Counter()}
        for fi, it in enumerate(items):
            if fi % 50 == 0:
                _tick()
            img = it["get"]()
            if img is None:
                missing += 1
                continue
            W, H = it["W"], it["H"]
            if img.size != (int(W), int(H)):
                ok_ratio = abs(img.size[0] / img.size[1] - W / H) < 0.01
                if tname not in size_warned:
                    size_warned.add(tname)
                    print(f"  {'참고' if ok_ratio else '경고'}: {tname} 이미지 {img.size[0]}x{img.size[1]} vs XML {W:.0f}x{H:.0f} "
                          + ("(비율 같음 → 정규화 좌표라 문제없음)" if ok_ratio else
                             "(비율 다름 → 회전/잘림 — " + ("이 프레임들은 뺌)" if SIZE_MISMATCH == "skip" else "그대로 씀, _check 확인)")))
                    if not ok_ratio:
                        report_warns.append(f"<b>{tname}</b>: 이미지 {img.size[0]}x{img.size[1]}가 XML {W:.0f}x{H:.0f}와 비율이 다름 "
                                            f"(출처 {task.get('frames_from', '')}) → 회전·잘림이면 박스가 어긋남"
                                            + (" — 그런 프레임은 학습에서 뺌." if SIZE_MISMATCH == "skip" else " — _check 이미지 확인."))
                if not ok_ratio and SIZE_MISMATCH == "skip":
                    skipped_size += 1
                    continue
            if by_rule or len(groups) >= 2:
                split = "val" if it["group"] in val_groups else "train"
            else:
                split = "val" if fi >= cut else "train"
            name = it["out"]

            lines, raw, kept = [], [], []
            for label, occ, xtl, ytl, xbr, ybr in it["boxes"]:
                if label not in to_train:
                    if label in CLASS_NAMES:
                        dropped_labels[label] += 1   # MERGE/KEEP_CLASSES로 뺀 클래스
                    else:
                        unknown[label] += 1
                    continue
                xtl, xbr = sorted((min(max(xtl, 0), W), min(max(xbr, 0), W)))
                ytl, ybr = sorted((min(max(ytl, 0), H), min(max(ybr, 0), H)))
                if xbr - xtl <= 1 or ybr - ytl <= 1:
                    continue
                occl_rows.append([f"{name}.jpg", label, int(occ),
                                  round(xtl, 2), round(ytl, 2), round(xbr, 2), round(ybr, 2),
                                  f"{(xtl+xbr)/2/W:.6f}", f"{(ytl+ybr)/2/H:.6f}",
                                  f"{(xbr-xtl)/W:.6f}", f"{(ybr-ytl)/H:.6f}"])
                occ_count[(label, occ)] += 1
                bw_, bh_ = xbr - xtl, ybr - ytl
                kept.append((label, (xtl, ytl, xbr, ybr)))
                v["by_label"][label] += 1
                v["occ"] += occ
                if occ and OCCLUDED_POLICY == "drop":
                    continue
                base = cidx[to_train[label]]
                cid = base * 2 + int(occ) if OCCLUDED_POLICY == "split" else base
                lines.append(f"{cid} {(xtl+xbr)/2/W:.6f} {(ytl+ybr)/2/H:.6f} "
                             f"{(xbr-xtl)/W:.6f} {(ybr-ytl)/H:.6f}")
                raw.append((yolo_names[cid], xtl / W, ytl / H, xbr / W, ybr / H))
                cls_count[yolo_names[cid]] += 1
                box_recs.append({"video": tname, "split": split, "frame": it["key"], "label": label,
                                 "cls": yolo_names[cid], "occ": occ, "w": bw_, "h": bh_,
                                 "short": min(bw_, bh_) * TRAIN_IMGSZ / max(W, H)})

            img.convert("RGB").save(OUT_DIR / split / "images" / f"{name}.jpg", quality=JPG_QUALITY)
            (OUT_DIR / split / "labels" / f"{name}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            sc[split] += 1
            check_items[tname].append((split, name, raw))
            for i in range(len(kept)):
                for j in range(i + 1, len(kept)):
                    if kept[i][0] == kept[j][0] and _iou(kept[i][1], kept[j][1]) >= DUP_IOU:
                        v["dup_suspects"] += 1
            frames_info.append((tname, split, len(lines)))
            v["frames"] += 1
            v["empty_frames"] += len(kept) == 0
            v["boxes"] += len(kept)
            v["per_frame"].append(len(kept))
            v["split"] = split if v["split"] in ("", split) else "train+val"
        if skipped_size:
            print(f"  경고: {tname} 크기 비율이 다른 프레임 {skipped_size}개 → 제외")
        if missing:
            print(f"  경고: {tname} 이미지를 찾지 못한 프레임 {missing}개 → 제외")
            report_warns.append(f"<b>{tname}</b>: 이미지를 찾지 못한 프레임 {missing}개 제외됨.")
        if "판별" in task["numbering"]:
            report_warns.append(f"<b>{tname}</b>: 이미지 번호 체계를 판별하지 못함 → _check 이미지로 박스 위치 확인 필수.")
        if task["stats"].get("rotated_box"):
            report_warns.append(f"<b>{tname}</b>: 회전된 박스 {task['stats']['rotated_box']}개 → 축 정렬 박스로 변환됨(오차 가능).")
        v["occluded_pct"] = round(100 * v["occ"] / v["boxes"]) if v["boxes"] else 0
        v["boxes_per_frame_avg"] = round(v["boxes"] / v["frames"], 1) if v["frames"] else 0
        v["boxes_per_frame_max"] = max(v["per_frame"] or [0])
        video_rows.append(v)
        split_rows.append({"task_id": task.get("task_id", ""), "task_name": task.get("task_name", ""), "src": task.get("src", ""),
                           "video": tname, "split": v["split"], "frames": v["frames"], "boxes": v["boxes"],
                           "frames_from": v["frames_from"]})

    with open(OUT_DIR / "occluded_info.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["image", "label", "occluded", "xtl", "ytl", "xbr", "ybr",
                    "yolo_cx", "yolo_cy", "yolo_w", "yolo_h"])   # yolo_*: 라벨 txt와 같은 값 (검증 스크립트가 사용)
        w.writerows(occl_rows)

    with open(OUT_DIR / "split_tasks.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["task_id", "task_name", "src", "video", "split", "frames", "boxes", "frames_from"])
        w.writeheader()
        w.writerows(split_rows)

    y = [f"path: {OUT_DIR.resolve().as_posix()}", "train: train/images", "val: val/images",
         "", f"nc: {len(yolo_names)}", "names:"] + [f"  {i}: {n}" for i, n in enumerate(yolo_names)]
    (OUT_DIR / "data.yaml").write_text("\n".join(y) + "\n", encoding="utf-8")

    if MAKE_CHECK_IMAGES:
        from PIL import ImageDraw
        chk = OUT_DIR / "_check"
        if chk.exists():
            shutil.rmtree(chk)
        chk.mkdir()
        for tname, its in check_items.items():
            for split, name, raw in its[:: max(1, len(its) // MAKE_CHECK_IMAGES)][:MAKE_CHECK_IMAGES]:
                im = Image.open(OUT_DIR / split / "images" / f"{name}.jpg").convert("RGB")
                d = ImageDraw.Draw(im)
                for lab, a, b, c, e in raw:
                    d.rectangle([a * im.width, b * im.height, c * im.width, e * im.height],
                                outline=(255, 0, 0), width=4)
                    d.text((a * im.width, max(0, b * im.height - 12)), lab, fill=(255, 255, 0))
                im.thumbnail((1080, 1920))
                im.save(chk / f"{name}.jpg", quality=85)

    fmts = Counter(t["fmt"] for t in tasks)
    print(f"\n입력: 태스크 {len(tasks)}개 (video {fmts['video']} / images {fmts['images']}), 묶음(영상) {len(gsize)}개")
    print(f"정책: occluded={OCCLUDED_POLICY}, MERGE_HEALTH={MERGE_HEALTH}, KEEP_CLASSES={KEEP_CLASSES} | 클래스: {yolo_names}")
    if by_rule:
        rc = Counter(r["split"] for r in split_rows)
        print(f"이미지: train {sc['train']} / val {sc['val']} (val = 규칙으로 정한 TASK {rc['val']}개, train TASK {rc['train']}개)")
    else:
        print(f"이미지: train {sc['train']} / val {sc['val']} (val 묶음 {sorted(val_groups) if val_groups else '각 태스크 뒤쪽 블록'})")
    for n in yolo_names:
        print(f"  {n:<26} {cls_count[n]}")
    print("라벨별 가림 비율:")
    for n in CLASS_NAMES:
        tot = occ_count[(n, True)] + occ_count[(n, False)]
        if tot:
            print(f"  {n:<26} {occ_count[(n, True)]}/{tot} ({occ_count[(n, True)]/tot:.0%})")
    zero = [n for n in yolo_names if cls_count[n] == 0]
    if zero:
        print(f"경고: 박스가 0개인 클래스: {zero}")
    if unknown:
        print(f"경고: CLASS_NAMES에 없는 라벨 무시: {dict(unknown)}")
        report_warns.append("CLASS_NAMES에 없는 라벨이 무시됨: " + ", ".join(f"{k} {v}개" for k, v in unknown.items()))
    if dropped_labels:
        print(f"참고: KEEP_CLASSES로 학습에서 뺀 박스: {dict(dropped_labels)}")
        report_warns.append(f"KEEP_CLASSES={KEEP_CLASSES} → 학습에서 뺀 박스: "
                            + ", ".join(f"{k} {v}개" for k, v in dropped_labels.items()))
    if dup_names:
        report_warns.append(f"출력 이름이 겹치는 이미지 {len(dup_names)}개 → 같은 태스크를 두 번 넣었는지 확인.")
    _ff = Counter(v.get("frames_from", "") for v in video_rows)
    print("학습 이미지 출처: " + ", ".join(f"{k or '?'} {n}개 TASK" for k, n in _ff.most_common()))
    write_report(box_recs, frames_info, video_rows, yolo_names, report_warns)
    print(f"확인: {OUT_DIR / '_check'} 이미지에서 박스가 열매에 정확히 맞는지 보세요.")
    print(f"통계: {OUT_DIR / 'stats_report.html'} (브라우저로 열기), stats_videos.csv, stats_boxes.csv")


if __name__ == "__main__":
    main()
