# 10. 자동 라벨(프레임별 shape) 요청 — 9번 셀에서 고른 TASK를 실행기(GPU)에 요청
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
SEND = False   # True = 요청을 보냄 (실행기가 프레임마다 탐지 → 업로드 전 백업 → 올림 → 이름 …_uld → …_uld_AA)
AA_LOCAL = False   # True = 요청 대신 이 Colab(GPU)에서 직접 만들어 보기 → 결과는 내 분석 폴더, 올리기는 6번 셀

assert 'AA_TARGETS' in globals(), '먼저 9번 셀로 대상을 고르세요'
AA_RID = None if AA_LOCAL else (send('shape', AA_TARGETS, AA_PARAMS, go=SEND and bool(AA_TARGETS)) if AA_TARGETS else print('대상이 없습니다 (9번 셀)'))

# ---- AA_LOCAL = True: 셀에서 직접 자동 라벨을 만들어 보기 — 결과는 내 분석 폴더에. 마음에 들면 6번 셀 '이 결과 올리기'
if AA_LOCAL:
    # [v4.33 분석 셀] 계산은 Colab에서, 결과는 내 분석 폴더에 — CVAT·공유 폴더에 쓰지 않음. 올리려면 6번 셀 '이 결과 올리기'
    import json as _json
    assert BEST and os.path.exists(BEST), '모델이 없습니다 (0번 셀 MODEL_CHOICE)'
    AA_RESULTS = globals().get('AA_RESULTS') or {}
    _dev = '0' if __import__('torch').cuda.is_available() else 'cpu'
    for t in AA_TARGETS:
        tid = int(t['task_id']); folder = task_dir(tid)
        print('=' * 70, f"\nTASK {tid} {t['name']}")
        try:
            task = CLIENT.tasks.retrieve(tid)
            r = ctt.auto_annotate_frames(task, f'{SCRIPTS}/cvat_yolo_function.py', BEST, imgsz=IMGSZ, device=_dev,
                                         conf=AA_PARAMS['conf'], collect_only=True, log=print)   # CVAT에 쓰지 않음
            f = f'{folder}/shapes_{ctt.stamp()}.json'
            _json.dump({'shapes': r['shapes']}, open(f, 'w', encoding='utf-8'), ensure_ascii=False)
            AA_RESULTS[tid] = {'file': f, 'fmt': 'shapes-json', 'count': len(r['shapes']), 'kind': 'shape', 'model': model_label(),
                               'settings': {'conf': AA_PARAMS['conf'], 'imgsz': IMGSZ}, 'per_label': r.get('per_label', {})}
            print(f"✅ 박스 {len(r['shapes'])}개 {r.get('per_label', {})} → {os.path.relpath(f, BASE)}")
        except Exception as e:
            print(f'❌ {ctt.api_error(e) if hasattr(ctt, "api_error") else e}')
    print(f'AA_RESULTS {len(AA_RESULTS)}개 → 6번 셀에서 미리 보고 올리기')
