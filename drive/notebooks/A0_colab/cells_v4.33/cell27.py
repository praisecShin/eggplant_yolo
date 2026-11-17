# 27. 앙상블 자동 라벨 (분석) — 모델 여러 개가 같은 프레임을 보고, 여러 모델이 동의한 박스만 하나로 합침 · 올리기는 6번 셀
# [v4.33 분석 셀] 계산은 Colab에서, 결과는 내 분석 폴더에 — CVAT·공유 폴더에 쓰지 않음. 올리려면 6번 셀 '이 결과 올리기'
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
EN_MODELS    = []        # 모델 이름 (각 모델의 채택 버전을 해시 대조해 받음) 또는 '.pt' 경로. 예: ['fruit_1920', 'fruit_r261028']
EN_TASK_IDS  = []        # TASK ID. 처음엔 수작업 라벨이 있는 TASK 하나로 시험 → 24번 셀로 비교
EN_QUERY     = ''        # 또는 TASK 이름 검색 (EN_TASK_IDS가 비었을 때)
EN_MIN_VOTES = 2         # 채택 기준: 이 수 이상의 모델이 찾은 박스 (그 라벨을 아는 모델이 더 적으면 그 수)
EN_IOU       = 0.55      # 같은 열매로 묶는 IoU 기준
EN_CONF      = 0.25      # 모델마다 탐지 신뢰도 하한
EN_WEIGHTS   = None      # 모델별 가중치 {'fruit_1920': 1.0, …} · None = 모두 같게
EN_SOURCE    = 'auto'    # 프레임: 'auto' = 원본 영상이 있으면 영상, 없으면 CVAT · 'video' · 'cvat'
EN_FRAMES    = None      # None = TASK 전체 · 시험은 range(0, 30) 처럼
EN_SHOW      = 6         # 그림으로 볼 프레임 수 (검토 박스가 많은 프레임부터)

import json, hashlib, pandas as pd, matplotlib.pyplot as plt
from IPython.display import display
en = load_script('ensemble_annotate.py')
assert EN_MODELS, 'EN_MODELS에 모델 이름을 넣으세요'
_paths = {}
for m in EN_MODELS:
    lab, p = pick_model(m)                      # 채택 버전만 · 해시 대조 (공유 runs/는 읽기만)
    _paths[lab] = p
_cache = globals().setdefault('_EN_CACHE', {})
MODELS = []
for m, p in _paths.items():
    key = (p, os.path.getmtime(p))
    if key not in _cache:
        _cache[key] = en.ModelInfo(m, p)
    MODELS.append(_cache[key])
import torch
_dev = 0 if torch.cuda.is_available() else 'cpu'
print(f"모델 {len(MODELS)}개 · 장치 {'GPU' if _dev == 0 else 'CPU (느림)'} · 채택 {EN_MIN_VOTES}표 이상 · IoU {EN_IOU} · conf {EN_CONF}")
SHORT = {mi.name: f'M{i}' for i, mi in enumerate(MODELS, 1)}
for mi in MODELS:
    print(f"  {SHORT[mi.name]} {mi.name:<40} 라벨 {', '.join(mi.labels)}")
_sig = hashlib.md5(json.dumps([[mi.name, ctt.file_fingerprint(mi.weights)[1]] for mi in MODELS]
                              + [EN_MIN_VOTES, EN_IOU, EN_CONF, EN_WEIGHTS, IMGSZ, str(EN_FRAMES)], sort_keys=True).encode()).hexdigest()[:10]
_hits = pick_tasks(EN_TASK_IDS, EN_QUERY, label='앙상블 대상', show=False)
assert _hits, 'EN_TASK_IDS 또는 EN_QUERY를 넣으세요'
EN_RESULTS = globals().get('EN_RESULTS') or {}
summary = []
for t in _hits:
    tid = int(t['task_id'])
    print('=' * 80)
    task = CLIENT.tasks.retrieve(tid)
    folder = task_dir(tid)
    meta = task.get_meta()
    fr0 = (getattr(meta, 'frames', None) or [None])[0]
    W0, H0 = (getattr(fr0, 'width', None), getattr(fr0, 'height', None)) if fr0 is not None else (None, None)
    deleted = set(getattr(meta, 'deleted_frames', None) or [])
    todo = [k for k in (EN_FRAMES if EN_FRAMES is not None else range(task.size)) if k not in deleted]
    print(f"TASK {tid} '{task.name}' · 프레임 {len(todo)}/{task.size}")
    row = {'task_id': tid, 'task_name': task.name}
    vid = None
    if EN_SOURCE != 'cvat' and ctt.task_basic(task)['is_video']:
        vid = S.video('', task.name)
        if vid is not None:
            al = ctt.check_video_alignment(task, vid, TRACK_FRAME_OFFSET, 'pyav')
            if not al['ok']:
                print(f"⚠️ 영상과 CVAT 프레임이 {al['best_shift']:+d} 어긋남 → CVAT 프레임으로 (20번 셀 진단 권장)"); vid = None
    if EN_SOURCE == 'video' and vid is None:
        print("❌ 원본 영상을 쓸 수 없어 뺌 (EN_SOURCE = 'video')"); row['결과'] = '영상 없음'; summary.append(row); continue
    if vid is not None:
        start, step = ctt.task_frame_map(meta)
        vmap = {start + k * step - TRACK_FRAME_OFFSET: k for k in todo}
        frames_iter = ((vmap[vi], im) for vi, im in ctt.video_frames(vid, vmap, 'pyav'))
        src = f'원본 영상 {os.path.basename(str(vid))}'
    else:
        frames_iter = en.frames_from_cvat(task, todo)
        src = 'CVAT 프레임'
    print(f'프레임 출처: {src}')
    t0 = time.time()
    res = en.run_ensemble(task, MODELS, frames_iter, W0, H0, imgsz=IMGSZ, conf=EN_CONF, iou_thr=EN_IOU,
                          min_votes=EN_MIN_VOTES, weights=EN_WEIGHTS, device=_dev)
    out_dir = f'{folder}/ensemble_{ctt.stamp()}_{_sig}'
    os.makedirs(out_dir, exist_ok=True)
    json.dump({str(k): v for k, v in res.items()}, open(f'{out_dir}/result.json', 'w', encoding='utf-8'), ensure_ascii=False, default=list)
    _settings = {'models': {mi.name: ctt.file_fingerprint(mi.weights)[1] for mi in MODELS}, 'min_votes': EN_MIN_VOTES, 'iou': EN_IOU,
                 'conf': EN_CONF, 'weights': EN_WEIGHTS, 'imgsz': IMGSZ, 'source': src, 'sec': round(time.time() - t0, 1)}
    json.dump(_settings, open(f'{out_dir}/settings.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    pd.DataFrame(en.review_rows(res)).to_csv(f'{out_dir}/review.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(en.contribution(res, [mi.name for mi in MODELS])).to_csv(f'{out_dir}/contribution.csv', index=False, encoding='utf-8-sig')
    _labels = {l.name for l in task.get_labels()}
    shapes = [{'type': 'rectangle', 'frame': int(k), 'label': d['label'], 'points': [float(v) for v in d['box']],
               'occluded': bool(d.get('occluded'))} for k, fr in res.items() for d in fr['accepted'] if d['label'] in _labels]
    _skipped = sum(1 for fr in res.values() for d in fr['accepted'] if d['label'] not in _labels)
    json.dump({'shapes': shapes}, open(f'{out_dir}/shapes.json', 'w', encoding='utf-8'), ensure_ascii=False)
    EN_RESULTS[tid] = {'file': f'{out_dir}/shapes.json', 'fmt': 'shapes-json', 'count': len(shapes), 'kind': 'ensemble',
                       'model': '앙상블: ' + ', '.join(mi.name for mi in MODELS), 'settings': _settings}
    n_rev = sum(len(f['review']) for f in res.values())
    print(f"채택 {len(shapes)}개 · 검토 목록 {n_rev}개" + (f' · TASK에 없는 라벨이라 뺀 박스 {_skipped}개' if _skipped else '')
          + f" · 저장 {os.path.relpath(out_dir, BASE)}")
    row.update(프레임=len(res), 채택=len(shapes), 검토=n_rev, 출처=src)
    if EN_SHOW:
        pick = sorted(res, key=lambda k: (-len(res[k]['review']), -len(res[k]['accepted'])))[:EN_SHOW]
        get = ctt.cvat_frame_getter(task, {'start': 0, 'step': 1})
        fig, axes = plt.subplots(1, len(pick), figsize=(4 * len(pick), 6), squeeze=False)
        for ax, k in zip(axes[0], pick):
            ax.axis('off'); im = get(k)
            if im is None:
                ax.set_title(f'f{k}: no image'); continue
            im = im.convert('RGB'); sx, sy = im.width / (W0 or im.width), im.height / (H0 or im.height)
            ax.imshow(im)
            for d, col, ls in [(d, 'yellow', '-') for d in res[k]['accepted']] + [(d, 'red', '--') for d in res[k]['review']]:
                b = d['box']
                ax.add_patch(plt.Rectangle((b[0] * sx, b[1] * sy), (b[2] - b[0]) * sx, (b[3] - b[1]) * sy, fill=False, ec=col, lw=1.8, ls=ls))
            ax.set_title(f"frame {k} | accepted {len(res[k]['accepted'])} | review {len(res[k]['review'])}", fontsize=9)
        print('노란 실선 = 채택, 빨간 점선 = 검토 목록')
        plt.tight_layout(); plt.show()
    summary.append(row)
print('=' * 80)
display(pd.DataFrame(summary))
print("결과가 괜찮으면 6번 셀: UP_FROM = 'ensemble' (덧붙이려면 UP_MODE = 'append') → 미리 보기 → SEND = True")
