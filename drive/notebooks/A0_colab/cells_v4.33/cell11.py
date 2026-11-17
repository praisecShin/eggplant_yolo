# 11. 진단 — 모델이 이 TASK 영상에서 무엇을 보는지
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
DIAG_TASK_ID = 0        # ← 진단할 TASK ID (5번 셀을 한 번 실행한 TASK)
DIAG_FRAMES  = 4        # 볼 프레임 수
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
import cv2, numpy as np, matplotlib.pyplot as plt
from ultralytics import YOLO
DIAG_TASK_ID = ctt.as_task_id(DIAG_TASK_ID)          # 2696411 또는 '2696411' 모두 됨
last = last_upload(DIAG_TASK_ID, include_track=True)
assert last and last.get('before_file'), '이 TASK의 자동 라벨 기록(올리기 전 라벨)이 없습니다'
meta = ctt.read_export(f"{BASE}/{last['before_file']}")
video = S.video(meta['source'], last.get('task_name') or '')
assert video, f"videos/에 {meta['source']}가 없습니다"
model = YOLO(BEST)
cap = cv2.VideoCapture(str(video))
vw, vh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
vn, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
print(f"영상 {os.path.basename(str(video))}: {vw}x{vh}, {fps:.1f}fps, {vn}프레임 / TASK 프레임 {meta['start']}~{meta['stop']} step {meta['step']}")
print(f"모델: {model_label()} / 클래스 {list(model.names.values())} / IMGSZ {IMGSZ}")
task_frames = list(range(meta['start'], meta['stop'] + 1, meta['step']))
picks = [task_frames[int(i)] for i in np.linspace(0, len(task_frames) - 1, DIAG_FRAMES)]
cvat_task = CLIENT.tasks.retrieve(DIAG_TASK_ID) if 'CLIENT' in globals() else None
buckets = {'0.5 이상': 0, '0.25~0.5': 0, '0.1~0.25': 0, '0.01~0.1': 0}
fig, axes = plt.subplots(2 if cvat_task else 1, DIAG_FRAMES, figsize=(4 * DIAG_FRAMES, 14 if cvat_task else 7), squeeze=False)
for j, f in enumerate(picks):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f)
    ok_, img = cap.read()
    if not ok_:
        axes[0][j].set_title(f'video frame {f}: read failed'); continue
    r = model.predict(img, imgsz=IMGSZ, conf=0.01, verbose=False)[0]
    vis = img[:, :, ::-1].copy()
    for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
        buckets['0.5 이상' if c >= 0.5 else '0.25~0.5' if c >= 0.25 else '0.1~0.25' if c >= 0.1 else '0.01~0.1'] += 1
        if c < 0.05:
            continue                                   # 너무 낮은 것은 그리지 않음 (숫자에는 포함)
        col = (0, 255, 0) if c >= TRACK_CONF else ((255, 200, 0) if c >= 0.1 else (255, 0, 0))
        cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), col, 6)
        cv2.putText(vis, f'{c:.2f}', (int(x1), max(30, int(y1) - 10)), cv2.FONT_HERSHEY_SIMPLEX, 2, col, 4)
    axes[0][j].imshow(vis); axes[0][j].set_title(f'video frame {f}: {int((r.boxes.conf >= TRACK_CONF).sum())} boxes >= {TRACK_CONF} / {len(r.boxes)} >= 0.01'); axes[0][j].axis('off')
    if cvat_task:
        try:
            k = task_frames.index(f)
            from PIL import Image as PILImage
            try:
                im = PILImage.open(cvat_task.get_frame(k, quality='original'))
            except Exception as e:                     # 고해상도 영상: 원본 프레임 불가(cvat#7425) → 압축 프레임
                if 'resolution' not in str(e):
                    raise
                im = PILImage.open(cvat_task.get_frame(k, quality='compressed'))
            axes[1][j].imshow(im); axes[1][j].set_title(f'CVAT frame {f} ({im.size[0]}x{im.size[1]})')
        except Exception as e:
            axes[1][j].set_title(f'CVAT frame failed: {str(e)[:40]}')
        axes[1][j].axis('off')
cap.release()
plt.tight_layout()
out_png = f'{task_dir(DIAG_TASK_ID)}/diag_{ctt.stamp()}.png'
plt.savefig(out_png, dpi=60); plt.show()
print('신뢰도 분포:', buckets)
print('그림: 초록 = TRACK_CONF 이상, 주황 = 0.1 이상, 빨강 = 0.05~0.1 (위 = 영상 프레임 + 모델 예측, 아래 = 같은 번호의 CVAT 프레임)')
print('저장:', os.path.relpath(out_png, BASE))
