# 24. 수작업 라벨 ↔ 자동 라벨 비교 — 같은 TASK, 평가 수치 + 대표 화면 (CVAT에 아무것도 올리지 않음) · MODELS = 여러 모델을 같은 정답과 비교 (11/6)
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
TID   = 0              # 비교할 TASK ID (2696411 또는 '2696411')
LOGIN = None           # 그 TASK가 있는 계정 · 0번 셀 CVAT_PROFILES의 이름
GT    = 'auto'         # 수작업(정답): 'auto' = 업로드 직전 백업 → 없으면 exports/의 이 TASK export zip
                       #   · 'backup' = tasks/<ID>/의 업로드 직전 백업 중 라벨이 든 가장 이른 것
                       #   · 'export' = exports/ 안 이 TASK의 export zip (GT_PICK으로 고름)
                       #   · 'cvat'   = 지금 CVAT 라벨 (아직 자동 라벨을 올리지 않은 TASK를 모델과 비교할 때)
                       #   · 파일 경로(BASE 기준, 예 'exports/20261028_125036_cvat_for_images_1_1/eggplant_G5_261019_3_6_vf.zip')
GT_PICK = -1           # GT='export'에서 쓸 것: -1 = 가장 최근 export, 0 = 가장 이른 것 (목록이 표로 나옴)
PRED  = 'cvat'         # 자동: 'cvat' = 지금 CVAT에 있는 라벨(자동 라벨 업로드 후) · 파일 경로(track XML 등)
                       #   · 'model' = 지금 모델(best.pt)로 프레임마다 새로 탐지
CONF  = 0.25           # PRED='model'일 때 신뢰도 하한
MODEL_PICK = None      # PRED='model'일 때 쓸 모델: None = 0번 셀에서 고른 모델 · runs/ 폴더 이름(예 'fruit_r2_A')
                       #   · 0번 셀 MODEL_NAMES 번호(예 2) · best.pt 경로
MAX_FRAMES = None      # 비교 프레임 수 상한 (정답 라벨이 있는 프레임에서 고르게). None = 전부
SHOW_EACH  = 6         # 경우마다 그림 수 (나쁜 것부터)
NEAR, SAME = 0.5, 0.95 # 짝으로 보는 IoU 하한 / '같음'으로 보는 IoU
EDGE_TOL   = 0.02      # 박스 높이·폭의 2% 이하 차이는 '같음'
LABELS     = None      # 비교할 라벨 목록. None = 자동 쪽에 있는 라벨만 (자동 라벨이 bud를 모르면 bud는 빼고). 예: ['healthy_fruit', 'bud']
MODELS     = []      # (모델 비교) 여러 모델을 같은 정답과 차례로 비교 — 예: ['fruit_r261101_2class_rotate', 'James_모델'] 또는 MODEL_NAMES 번호 [3, 4]
                     #   정하면 PRED = 'model'로, 모델마다 표 + 모델별 대표 화면(SHOW_EACH_M개씩) → 마지막에 모델 비교표
                     #   GT는 보통 'export'(vf 이후 검토자 export) — 'auto'면 업로드 직전 백업(=A)이 정답이 되므로 'export'로 바꿈
SHOW_EACH_M = 3      # MODELS일 때 모델마다 경우별 그림 수 (0 = 그림 없이 표만)

import re, glob, numpy as np, matplotlib.pyplot as plt, pandas as pd
from collections import Counter, defaultdict
from IPython.display import display
TID = ctt.as_task_id(TID)
assert TID, 'TID에 TASK ID를 넣으세요'
use_cvat(LOGIN)
task = CLIENT.tasks.retrieve(TID)
tdir = task_dir(TID)

if MODELS and GT == 'auto':
    GT = 'export'
    print("MODELS 비교: GT = 'auto'는 업로드 직전 백업(A)을 정답으로 고르므로 'export'(검토자 export)로 바꿔 씁니다")
if MODELS:
    PRED = 'model'
# ---------- 1) 정답(수작업) ----------
gt_file = None
if GT in ('auto', 'backup'):
    _old = f'{TASKS_DIR}/{TID}'                         # 옛 TASK 폴더(읽기) + v4.33 복구 자료의 올리기 전 라벨
    _new = [f"{BASE}/{u['before_file']}" for u in S.uploads(TID) if u.get('before_file') and os.path.exists(f"{BASE}/{u['before_file']}")]
    cands = _new + sorted(glob.glob(f'{_old}/before_upload_*.zip') + glob.glob(f'{_old}/before_auto_*.zip'),
                   key=lambda p: os.path.basename(p).split('_', 2)[-1])
    info = [(p, sum(len(v) for v in ctt.load_annotations(p)['boxes'].values())) for p in cands]
    print('업로드 직전 백업:', ', '.join(f'{os.path.basename(p)}(박스 {n})' for p, n in info) or f'없음 ({os.path.relpath(tdir, BASE)})')
    with_boxes = [p for p, n in info if n > 0]
    if with_boxes:
        gt_file = with_boxes[0]
    elif GT == 'backup':
        raise SystemExit('⛔ 라벨이 든 업로드 직전 백업이 없습니다 (이 앱의 5·6·10번 셀로 자동 라벨을 올린 TASK에만 생김)\n'
                         "   → GT = 'export'(14번 셀로 받은 export zip) 또는 파일 경로를 적으세요")
if gt_file is None and GT in ('auto', 'export'):
    _nm = task.name.split('_')
    names = ['_'.join(_nm[:k]) for k in range(len(_nm), max(len(_nm) - 3, 1), -1)]   # 뒤에 붙은 _AA 등이 달라도 찾게
    ex = [r for r in ctt.scan_exports(f'{BASE}/exports', names=names, log=None) if str(r.get('task_id')) == str(TID)]
    ex = sorted(ex, key=lambda r: (str(r.get('updated') or ''), float(r.get('mtime') or 0)))
    if ex:
        display(pd.DataFrame([{'#': k, '폴더': r['folder'], '파일': r['file'], 'TASK 수정 시각(export 당시)': str(r.get('updated', ''))[:16]}
                              for k, r in enumerate(ex)]).set_index('#'))
        gt_file = ex[GT_PICK]['zip']
        print(f"export에서 정답 선택 (GT_PICK={GT_PICK}): {ex[GT_PICK]['folder']}/{ex[GT_PICK]['file']}"
              '  ← 수작업 라벨일 때 받은 것인지 위 시각으로 확인하세요')
    if gt_file is None:
        raise SystemExit(f'⛔ TASK {TID}의 수작업 라벨 파일을 찾지 못했습니다: 업로드 직전 백업도, exports/의 export zip도 없음\n'
                         "   → 자동 라벨을 아직 안 올렸다면 GT = 'cvat' (지금 CVAT 라벨) + PRED = 'model'\n"
                         '   → 아니면 14번 셀로 export를 받은 뒤 다시. (13번 셀 TASK 백업 zip은 형식이 달라 쓸 수 없음)')
elif GT == 'cvat':
    gt_file = ctt.export_annotations(task, f'{tdir}/compare_gt_{ctt.stamp()}.zip')
elif gt_file is None:
    gt_file = GT if os.path.isabs(GT) else f'{BASE}/{GT}'
gt = ctt.load_annotations(gt_file)
print(f"정답(수작업): {os.path.relpath(gt_file, BASE)}")

# ---------- 2) 자동 ----------
if PRED == 'cvat':
    assert GT != 'cvat', "GT와 PRED가 둘 다 'cvat'이면 같은 라벨끼리 비교합니다 → PRED = 'model' 또는 track XML 경로"
    pred_file = ctt.export_annotations(task, f'{tdir}/compare_now_{ctt.stamp()}.zip')
    pred = ctt.load_annotations(pred_file)
    pred_desc = f'지금 CVAT 라벨 ({os.path.relpath(pred_file, BASE)})'
def _load_model(pick):
    MODEL_PICK = pick
    from ultralytics import YOLO
    if isinstance(MODEL_PICK, int) and not isinstance(MODEL_PICK, bool):
        assert MODEL_PICK in MODEL_NAMES, f'MODEL_PICK {MODEL_PICK}가 0번 셀 MODEL_NAMES 번호 {list(MODEL_NAMES)}에 없습니다'
        MODEL_PICK = MODEL_NAMES[MODEL_PICK]
    _mlabel, _w = pick_model(MODEL_PICK)              # 채택 버전을 해시 대조해 받음 (공유 runs/는 읽기만)
    model = YOLO(_w)
    base_n = {i: (n[:-9] if n.endswith('_occluded') else n) for i, n in model.names.items()}
    occl = {i: n.endswith('_occluded') for i, n in model.names.items()}
    pred, pred_desc = {'boxes': {}, 'meta': gt['meta']}, f'모델 {_mlabel} 새 탐지 (conf {CONF})'
    return model, base_n, occl, pred, pred_desc

if PRED == 'model':
    model, base_n, occl, pred, pred_desc = _load_model(MODEL_PICK)
else:
    pred_file = PRED if os.path.isabs(PRED) else f'{BASE}/{PRED}'
    pred = ctt.load_annotations(pred_file)
    pred_desc = os.path.relpath(pred_file, BASE)

def _compare(pred, pred_desc, model=None, base_n=None, occl=None, show_each=SHOW_EACH, tag=''):
    """정답 gt와 pred를 짝지어 표·보고서·대표 화면 → (전체 요약 한 줄, 라벨별 F1) 돌려줌"""
    W0, H0 = gt['meta']['W'], gt['meta']['H']
    labeled = sorted(f for f in gt['frames'] if gt['boxes'].get(f))
    frames = labeled if not MAX_FRAMES or len(labeled) <= MAX_FRAMES else \
        [labeled[int(i)] for i in np.linspace(0, len(labeled) - 1, MAX_FRAMES)]
    get = ctt.cvat_frame_getter(task, gt['meta'])            # 라벨러가 본 CVAT 프레임
    if model is not None:
        for k, f in enumerate(frames):
            img = get(f)
            if img is None:
                continue
            img = img.convert('RGB'); sx, sy = W0 / img.width, H0 / img.height
            rr = model.predict(img, imgsz=IMGSZ, conf=CONF, verbose=False, agnostic_nms=any(occl.values()))[0]
            pred['boxes'][f] = [(f'p{k}_{j}', base_n[int(c)], occl[int(c)], (x1 * sx, y1 * sy, x2 * sx, y2 * sy), True)
                                for j, ((x1, y1, x2, y2), c) in enumerate(zip(rr.boxes.xyxy.tolist(), rr.boxes.cls.tolist()))]
    all_gt = {b[1] for v in gt['boxes'].values() for b in v}
    known = set(LABELS) if LABELS else (set(base_n.values()) if model is not None
                                        else {b[1] for v in pred['boxes'].values() for b in v} or all_gt)
    if all_gt - known:
        print(f"비교에서 뺀 라벨 (자동 쪽에 없음): {', '.join(sorted(all_gt - known))}  ← 넣으려면 LABELS에 적기")

    def iou(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - ix*iy
        return ix*iy / u if u > 0 else 0

    def edges(g, p):
        """정답 g 대비 자동 p의 네 변 차이를 말로 (y는 아래로 증가)"""
        gh, gw = g[3]-g[1], g[2]-g[0]; out = []
        d = p[1] - g[1]
        if abs(d) > EDGE_TOL*gh: out.append(f"위쪽(꽃받침 쪽) {abs(d):.0f}px {'잘림' if d > 0 else '더 큼'} ({abs(d)/gh:.0%})")
        d = g[3] - p[3]
        if abs(d) > EDGE_TOL*gh: out.append(f"아래쪽(끝) {abs(d):.0f}px {'잘림' if d > 0 else '더 큼'} ({abs(d)/gh:.0%})")
        d = p[0] - g[0]
        if abs(d) > EDGE_TOL*gw: out.append(f"왼쪽 {abs(d):.0f}px {'좁음' if d > 0 else '넓음'}")
        d = g[2] - p[2]
        if abs(d) > EDGE_TOL*gw: out.append(f"오른쪽 {abs(d):.0f}px {'좁음' if d > 0 else '넓음'}")
        return ', '.join(out) or '네 변 모두 2% 안쪽'

    # ---------- 3) 짝짓기와 평가 ----------
    cases = {'위치·크기 다름': [], '놓침': [], '잘못 그림': []}
    st = defaultdict(Counter); ious, dtop, dbot, dw = [], [], [], []
    for f in frames:
        G = [b for b in gt['boxes'].get(f, []) if b[1] in known]
        P = [b for b in pred['boxes'].get(f, []) if b[1] in known]
        used, mg = set(), set()
        for v, i, j in sorted(((iou(g[3], p[3]), i, j) for i, g in enumerate(G) for j, p in enumerate(P)), reverse=True):
            if v < NEAR or i in mg or j in used:
                continue
            mg.add(i); used.add(j)
            g, p = G[i], P[j]; lb = g[1]
            st[lb]['짝'] += 1; st[lb]['같음(IoU≥%.2f)' % SAME] += v >= SAME; st[lb]['라벨 다름'] += g[1] != p[1]
            st[lb]['가림 표시 다름'] += bool(g[2]) != bool(p[2])
            gh, gw = g[3][3]-g[3][1], g[3][2]-g[3][0]
            ious.append(v); dtop.append((p[3][1]-g[3][1]) / gh); dbot.append((g[3][3]-p[3][3]) / gh)
            dw.append(((p[3][2]-p[3][0]) - gw) / gw)
            if v < SAME or g[1] != p[1]:
                cases['위치·크기 다름'].append(dict(frame=f, gt=g, pr=p, iou=v, bad=1 - v,
                    note=edges(g[3], p[3]) + ('' if g[1] == p[1] else f' · 라벨 다름 {g[1]}→{p[1]}')))
        for i, g in enumerate(G):
            if i not in mg:
                st[g[1]]['놓침'] += 1
                best = max([iou(g[3], p[3]) for p in P], default=0)
                near_p = max(P, key=lambda p: iou(g[3], p[3])) if best > 0 else None
                h = g[3][3] - g[3][1]
                cases['놓침'].append(dict(frame=f, gt=g, pr=near_p, iou=best, bad=h,
                    note=f"{g[1]} 높이 {h:.0f}px{' · 가림' if g[2] else ''}" + (f' · 자동 박스가 겹치나 너무 어긋남 (IoU {best:.2f})' if best > 0 else ' · 근처에 자동 박스 없음')))
        for j, p in enumerate(P):
            if j not in used:
                st[p[1]]['잘못 그림'] += 1
                best = max([iou(p[3], g[3]) for g in G], default=0)
                cases['잘못 그림'].append(dict(frame=f, gt=None, pr=p, iou=best, bad=p[3][3] - p[3][1],
                    note=f"{p[1]} 높이 {p[3][3]-p[3][1]:.0f}px" + (f' · 정답과 IoU {best:.2f} (겹쳐 그림?)' if best > 0 else ' · 정답에 없는 곳')))

    print(f"\nTASK {TID} '{task.name}' · 비교 프레임 {len(frames)}장 (정답 라벨이 있는 프레임)")
    print(f"정답 = {os.path.basename(gt_file)} · 자동 = {pred_desc}")
    rows = []
    for lb in sorted(st) + ['전체']:
        c = sum(st.values(), Counter()) if lb == '전체' else st[lb]
        tp, fn, fp = c['짝'], c['놓침'], c['잘못 그림']
        rows.append({'라벨': lb, '정답 박스': tp + fn, '자동 박스': tp + fp, '짝': tp, '놓침': fn, '잘못 그림': fp,
                     '재현율': round(tp / (tp + fn), 3) if tp + fn else None,
                     '정밀도': round(tp / (tp + fp), 3) if tp + fp else None,
                     'F1': round(2 * tp / (2 * tp + fn + fp), 3) if tp else 0,
                     f'같음(IoU≥{SAME})': c['같음(IoU≥%.2f)' % SAME], '라벨 다름': c['라벨 다름'], '가림 표시 다름': c['가림 표시 다름']})
    summary = pd.DataFrame(rows).set_index('라벨')
    display(summary)
    if ious:
        q = lambda a: f"평균 {np.mean(a):+.1%} · 중앙 {np.median(a):+.1%}"
        print(f"짝지은 박스 {len(ious)}개: IoU 평균 {np.mean(ious):.3f} · 중앙 {np.median(ious):.3f} · 0.75 미만 {np.mean(np.array(ious) < 0.75):.0%}")
        print(f"  위쪽(꽃받침 쪽) 차이 (+ = 자동이 잘림): {q(dtop)}")
        print(f"  아래쪽(끝) 차이     (+ = 자동이 잘림): {q(dbot)}")
        print(f"  폭 차이             (+ = 자동이 넓음): {q(dw)}")
    rep = f"{REPORTS}/manual_vs_auto_{TID}{tag}_{ctt.stamp()}.csv"
    pd.DataFrame([{'경우': k, '프레임': c['frame'], 'IoU': round(c['iou'], 3), '설명': c['note']}
                  for k, lst in cases.items() for c in lst]).to_csv(rep, index=False, encoding='utf-8-sig')
    summary.to_csv(rep.replace('.csv', '_summary.csv'), encoding='utf-8-sig')
    print(f"저장: reports/{os.path.basename(rep)} (경우별 전체 목록), _summary.csv (표)")

    # ---------- 4) 대표 화면 ----------
    for kind, lst in cases.items():
        lst = sorted(lst, key=lambda c: -c['bad'])[:show_each]
        if not lst:
            continue
        print(f"\n■ {kind} (나쁜 것부터 {len(lst)}개)  —  흰 실선 = 수작업, 노란 점선 = 자동")
        display(pd.DataFrame([{'#': k + 1, '프레임': c['frame'], 'IoU': round(c['iou'], 2), '설명': c['note']}
                              for k, c in enumerate(lst)]).set_index('#'))
        fig, axes = plt.subplots(1, len(lst), figsize=(3.2 * len(lst), 4.2), squeeze=False)
        for k, c in enumerate(lst):
            ax = axes[0][k]; ax.axis('off')
            img = get(c['frame'])
            if img is None:
                ax.set_title(f"#{k+1} f{c['frame']}: 이미지 없음"); continue
            img = img.convert('RGB'); sx, sy = img.width / W0, img.height / H0
            bxs = [b[3] for b in (c['gt'], c['pr']) if b]
            x1 = min(b[0] for b in bxs); y1 = min(b[1] for b in bxs); x2 = max(b[2] for b in bxs); y2 = max(b[3] for b in bxs)
            m = 0.35 * max(x2 - x1, y2 - y1)                    # 박스 주변을 잘라 확대
            cx1, cy1, cx2, cy2 = max(0, x1 - m), max(0, y1 - m), min(W0, x2 + m), min(H0, y2 + m)
            ax.imshow(img.crop((cx1 * sx, cy1 * sy, cx2 * sx, cy2 * sy)))
            def rect(b, col, ls):
                ax.add_patch(plt.Rectangle(((b[0] - cx1) * sx, (b[1] - cy1) * sy), (b[2] - b[0]) * sx, (b[3] - b[1]) * sy,
                                           fill=False, ec=col, lw=2.5, ls=ls))
            if c['gt']: rect(c['gt'][3], 'white', '-')
            if c['pr']: rect(c['pr'][3], 'yellow', '--')
            ax.set_title(f"#{k+1} frame {c['frame']} IoU {c['iou']:.2f}", fontsize=9)
        plt.tight_layout(); plt.show()

    return summary, (float(np.mean(ious)) if ious else None)

# ---------- 모델 비교 (MODELS) 또는 한 번 비교 ----------
if MODELS:
    _rows, _f1 = [], {}
    for _pick in MODELS:
        _name = MODEL_NAMES.get(_pick, str(_pick)) if isinstance(_pick, int) else str(_pick)
        print(f"\n{'=' * 20} 모델 {_name} {'=' * 20}")
        _m, _bn, _oc, _pr, _pd = _load_model(_pick)
        _tag = '_' + re.sub(r'[^0-9A-Za-z_.-]', '_', str(_pick))[:40]
        _s, _iou = _compare(_pr, _pd, model=_m, base_n=_bn, occl=_oc, show_each=SHOW_EACH_M, tag=_tag)
        _t = _s.loc['전체'].to_dict()
        _rows.append({'모델': _name, **{k: _t[k] for k in ('정답 박스', '자동 박스', '짝', '놓침', '잘못 그림', '재현율', '정밀도', 'F1')},
                      f'같음(IoU≥{SAME})': _t.get(f'같음(IoU≥{SAME})'), '라벨 다름': _t.get('라벨 다름'),
                      'IoU 평균': round(_iou, 3) if _iou is not None else None})
        _f1[_name] = _s['F1'].drop('전체', errors='ignore')
    print(f"\n{'=' * 20} 모델 비교 · TASK {TID} · 정답 = {os.path.basename(gt_file)} · conf {CONF} · imgsz {IMGSZ} {'=' * 20}")
    _cmp = pd.DataFrame(_rows).set_index('모델')
    display(_cmp)
    print('라벨별 F1:'); display(pd.DataFrame(_f1))
    _rep = f"{REPORTS}/models_vs_gt_{TID}_{ctt.stamp()}.csv"
    _cmp.to_csv(_rep, encoding='utf-8-sig')
    print(f"저장: reports/{os.path.basename(_rep)}")
else:
    _compare(pred, pred_desc, model=(model if PRED == 'model' else None), base_n=(base_n if PRED == 'model' else None),
             occl=(occl if PRED == 'model' else None))
