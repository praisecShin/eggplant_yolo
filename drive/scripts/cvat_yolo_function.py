"""
학습한 YOLO 모델(best.pt)을 CVAT 자동 주석 함수로 연결하는 파일
- cvat-cli 로컬 실행(task auto-annotate)과 AI 에이전트(function create-native / run-agent) 양쪽에서 사용
- 모델의 클래스 이름이 CVAT 라벨명과 같아야 매칭됨 (healthy_fruit, disease_fruit, healthy_bud, disease_bud)

파라미터 (-p 이름=형식:값):
    model=str:best.pt     학습한 가중치 경로
    imgsz=int:1280        추론 해상도 (학습 때와 같게)
    device=str:cpu        "cpu" / "0"(GPU) / "mps"(Mac)
    tile=bool:false       true면 이미지를 위·아래로 겹쳐 잘라 추론 (작은 꽃봉오리용)
"""
__version__ = "4.31.9"   # 가지 자동 라벨링 앱 버전 (노트북 0번 셀 APP_VERSION과 같아야 함)
import cvat_sdk.auto_annotation as cvataa
import PIL.Image

DEFAULT_CONF = 0.25


class _YoloFunction:
    def __init__(self, model="best.pt", imgsz=1280, device="cpu", tile=False):
        from ultralytics import YOLO  # 함수 로딩 시점에만 import

        self._model = YOLO(model)
        self._imgsz = imgsz
        self._device = device
        self._tile = tile
        # 'healthy_fruit_occluded'(split 학습) → CVAT 라벨 healthy_fruit + 가림 표시
        names = self._model.names
        bases = list(dict.fromkeys(n[:-len("_occluded")] if n.endswith("_occluded") else n for n in names.values()))
        self._to_label = {int(i): bases.index(n[:-len("_occluded")] if n.endswith("_occluded") else n)
                          for i, n in names.items()}
        self._occl = {int(i): n.endswith("_occluded") for i, n in names.items()}
        self.spec = cvataa.DetectionFunctionSpec(
            labels=[cvataa.label_spec(name, k, type="rectangle") for k, name in enumerate(bases)],
        )

    def _predict(self, image, conf, offset_y=0):
        r = self._model.predict(source=image, imgsz=self._imgsz, conf=conf, device=self._device, verbose=False,
                                agnostic_nms=any(self._occl.values()))[0]   # split 모델: 겹친 가림/안 가림 박스 하나로
        out = []
        for box, cls, score in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            x1, y1, x2, y2 = box
            out.append((int(cls), [x1, y1 + offset_y, x2, y2 + offset_y], score))
        return out

    def detect(self, context, image: PIL.Image.Image):
        conf = context.conf_threshold if context.conf_threshold is not None else DEFAULT_CONF
        image = image.convert("RGB")
        if not self._tile:
            dets = self._predict(image, conf)
        else:
            # 세로로 긴 영상(2160x3840)을 위·중간·아래 3조각(겹침 포함)으로 나눠 추론
            W, H = image.size
            h = int(H * 0.45)
            dets = []
            for y0 in (0, (H - h) // 2, H - h):
                dets += self._predict(image.crop((0, y0, W, y0 + h)), conf, offset_y=y0)
            dets = _nms(dets, iou_thr=0.5)
        return [cvataa.rectangle(self._to_label[cls], pts, occluded=self._occl[cls]) for cls, pts, _s in dets]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0


def _nms(dets, iou_thr):
    """조각 겹침 구간에서 생긴 중복 박스 제거 (같은 클래스끼리)"""
    keep = []
    for d in sorted(dets, key=lambda d: -d[2]):
        if all(d[0] != k[0] or _iou(d[1], k[1]) < iou_thr for k in keep):
            keep.append(d)
    return keep


def create(model: str = "best.pt", imgsz: int = 1280, device: str = "cpu", tile: bool = False):
    return _YoloFunction(model=model, imgsz=imgsz, device=device, tile=tile)
