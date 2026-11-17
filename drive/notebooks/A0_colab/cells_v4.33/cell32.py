# 32. 모델 비교 — 같은 TASK를 여러 모델로 탐지해 지금 CVAT 라벨과 비교 (CVAT에 아무것도 올리지 않음) · 결과는 내 분석 폴더에
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
CMP_TASK_IDS = []         # 비교할 TASK ID 목록, 예: [2700651, 2700652]
CMP_QUERY    = ''         # 또는 TASK 이름 검색 (CMP_TASK_IDS가 비었을 때). 예: 'G1 261019 vf* tag=AA*'
CMP_MODELS   = []         # 비교할 모델 (모델 이름 = 채택 버전 · '.pt' 경로도 됨), 예: ['fruit_r261101_2class', 'fruit_r261101_2class_rotate'] · 비우면 0번 셀에서 고른 모델
CMP_UPLOADED = True       # True = 이 TASK에 마지막으로 올린 자동 라벨(업로드 직후 기록)도 함께 비교 — 검토 완료 TASK일 때만 의미 있음
CMP_CONF     = 0.25       # 모델 탐지 신뢰도 하한
CMP_FRAMES   = 40         # TASK마다 비교할 프레임 수 (TASK 전체에서 고르게, 박스 없는 프레임 포함) · None = 전부 (느림)
CMP_LABELS   = None       # 비교할 라벨, 예: ['healthy_fruit'] · None = 모델이 아는 라벨
# (v4.32의 FROM_REQUESTS 없앰 — 웹 화면의 모델 비교 요청은 v4.33 실행기가 처리. 이 셀은 내 분석용)
LOGIN        = None       # None = 지금 접속 중인 서버 그대로 · 또는 0번 셀 CVAT_PROFILES의 이름
# 기준 = 지금 CVAT 라벨. 이름이 검토 완료(0번 셀 REVIEWED_RULE)면 검토자가 고친 라벨 = 정답 → 정밀도·재현율·F1.
# 검토 전이면 지금 CVAT 라벨(올린 자동 라벨) 기준 '일치도'일 뿐 — 어느 모델이 더 좋은지는 알 수 없음.
# 맞힘 = 같은 라벨 IoU ≥ 0.5 · 잘못 그림(오탐) · 놓침 · 라벨 다름은 따로 셈 (검토 수정량과 같은 짝짓기)

import json, pandas as pd
from IPython.display import display
_CMP_REQ = ''
CMP_TASK_IDS = ctt.as_task_ids(CMP_TASK_IDS)
use_cvat(LOGIN)
if not CMP_TASK_IDS and CMP_QUERY:
    CMP_TASK_IDS = [t['task_id'] for t in ctt.select_tasks(ctt.list_tasks(CLIENT, limit=5000), CMP_QUERY, display=display, label='비교 대상')]
assert CMP_TASK_IDS, 'CMP_TASK_IDS 또는 CMP_QUERY를 적으세요'
assert hasattr(wb, 'compare_models'), 'scripts/를 v4.28.0 이상으로 바꾸세요'

def _cmp_model(name):
    # 모델 이름 → 채택 버전을 해시 대조해 받은 best.pt (공유 runs/는 읽기만) → (경로, 표시)
    lab, w = pick_model(name or None)
    return w, lab

_models = [(n or NAME,) + _cmp_model(n) for n in (CMP_MODELS or [None])]
print(f"▶ TASK {len(CMP_TASK_IDS)}개 × 모델 {len(_models)}개 ({', '.join(m[0] for m in _models)})" + (' + 올린 자동 라벨' if CMP_UPLOADED else '')
      + f" · conf {CMP_CONF} · 프레임 {CMP_FRAMES or '전부'}장씩 · CVAT에 올리지 않음")
_pred = {n: wb.yolo_predictor(w, imgsz=IMGSZ, conf=CMP_CONF) for n, w, lab in _models}
if CMP_LABELS is None and len(_models) > 1:     # v4.31.4: 모델마다 아는 라벨이 다르면 공통 라벨로만 (기준 박스 수가 모델마다 달라지지 않게)
    from ultralytics import YOLO as _Y
    _ln = [{x[:-len('_occluded')] if x.endswith('_occluded') else x for x in _Y(w).names.values()} for n, w, lab in _models]
    _common = set.intersection(*_ln)
    if _common != set.union(*_ln):
        CMP_LABELS = sorted(_common)
        print(f"ℹ️ 모델마다 라벨이 달라 공통 라벨 {CMP_LABELS}로만 비교합니다 (빠진 것: {sorted(set.union(*_ln) - _common)}) — 바꾸려면 CMP_LABELS")
job_start(32, 'compare', {'ids': CMP_TASK_IDS, 'models': [m[0] for m in _models], 'conf': CMP_CONF, 'frames': CMP_FRAMES, 'uploaded': CMP_UPLOADED},
          summary='모델 비교 (올리지 않음)')
_rows, _err = [], 0
for _i, _tid in enumerate(CMP_TASK_IDS, 1):
    try:
        task = CLIENT.tasks.retrieve(_tid)
        _rev = ctt.is_reviewed(task.name, REVIEWED_RULE)
        _dir = task_dir(_tid)
        _ts = ctt.stamp()
        print(f"\n[{_i}/{len(CMP_TASK_IDS)}] TASK {_tid} {task.name} · 기준 = {'검토 뒤 라벨 ✅' if _rev else '검토 전 CVAT 라벨 (일치도만)'}")
        ref = ctt.export_annotations(task, f'{_dir}/compare_ref_{_ts}.zip')
        _src = [{'name': n, 'kind': 'model', 'predict': _pred[n], 'model_label': lab, 'conf': CMP_CONF} for n, w, lab in _models]
        _up = last_upload(_tid) if CMP_UPLOADED else None       # v4.33 실행기 결과 + 옛 기록 중 나중 것
        if _up:
            _up['_src'] = _up['result_file']
        if _up and _rev:
            if os.path.exists(f"{BASE}/{_up['_src']}"):
                _un = wb._upload_model(_up.get('model'), [m[0] for m in _models])
                _src.append({'name': f'올린 자동({_un})', 'kind': 'uploaded', 'file': f"{BASE}/{_up['_src']}", 'model_label': _up.get('model', '')})
        elif _up and not _rev:
            print('   (올린 자동 라벨 = 지금 CVAT 라벨이라 함께 비교하지 않음 — 검토 뒤에 다시 비교하세요)')
        res = wb.compare_models(ref, _src, ctt.cvat_frame_getter(task, ctt.load_annotations(ref)['meta']), max_frames=CMP_FRAMES,
                                labels=CMP_LABELS, reviewed=_rev, log=lambda m: print('  ', m))
        res.update(task_id=_tid, task_name=task.name, time=ctt.now(), ref_file=os.path.relpath(ref, BASE), who=who_am_i(),
                   request=_CMP_REQ)
        _jp = f'{_dir}/compare_{_ts}.json'
        open(_jp, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        wb.write_compare(BASE, _tid, task.name, res, os.path.relpath(ref, BASE), who=who_am_i(), request=res['request'], detail=os.path.relpath(_jp, BASE))   # → 내 분석 폴더 records/
        _sum = wb.compare_summary(res)
        ctt.log_task('compare', _tid, task.name, '완료', model=' vs '.join(s['name'] for s in res['sources']), summary=_sum[:300],
                     file=os.path.relpath(_jp, BASE))
        display(pd.DataFrame([{'대상': s['name'], '종류': '모델 새 탐지' if s['kind'] == 'model' else '올린 자동 라벨', '자동 박스': s['total']['auto'],
                               '기준 박스': s['total']['ref_boxes'], '맞힘': s['total']['tp'], '그중 위치 다름': s['total']['fixed'],
                               '라벨 다름': s['total']['relabeled'], '잘못 그림': s['total']['fp'], '놓침': s['total']['fn'],
                               '정밀도 P': s['total']['precision'], '재현율 R': s['total']['recall'], 'F1': s['total']['f1']}
                              for s in res['sources']]).set_index('대상'))
        if res['best'] and _rev:
            print(f"   → 이 TASK에서 F1이 가장 높은 것: {res['best']}")
        _rows += [{'TASK': _tid, '대상': s['name'], 'F1': s['total']['f1'], 'P': s['total']['precision'], 'R': s['total']['recall'],
                   '검토 완료': _rev} for s in res['sources']]
        print(f"   저장: {os.path.relpath(_jp, BASE)} · 비교 기록·작업 기록은 내 분석 폴더 records/ (공유 화면에 올리려면 '이 결과 올리기' — 2c-4)")
    except Exception as e:
        _err += 1
        print(f"   ⚠️ TASK {_tid} 비교 실패: {ctt.api_error(e) if hasattr(ctt, 'api_error') else e}")
        ctt.log_task('compare', _tid, '', '오류', summary=str(e)[:300])
if len(CMP_TASK_IDS) > 1 and _rows:
    _df = pd.DataFrame(_rows)
    print('\n■ 모델별 평균 (검토 완료 TASK만 — 검토 전 TASK는 일치도라 빼고)')
    _d2 = _df[_df['검토 완료']]
    display(_d2.groupby('대상')[['F1', 'P', 'R']].mean().round(3) if len(_d2) else pd.DataFrame())
job_end('끝' if not _err else '일부 실패', f"TASK {len(CMP_TASK_IDS) - _err}개 비교" + (f" · 실패 {_err}" if _err else ''))
