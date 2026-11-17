# 5. track 요청 — 고른 TASK마다 실행기(GPU)가 track을 만들고 바로 CVAT에 올림 (11/17 결정: 한 단계)
# [v4.33 바꾸는 셀] 미리 보기 → 요청 — 이 셀은 CVAT·공유 폴더를 직접 바꾸지 않음. SEND = True일 때만 요청을 보내고 실행기가 처리
assert 'BASE' in globals() and 'S' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'
TRACK_IDS     = []        # 예: [2687720, 2687801] · '2687720, 2687801'도 됨
TRACK_QUERY   = ''        # 또는 TASK 이름 검색 (TRACK_IDS가 비었을 때). 예: 'G6 uld tag=, G2 plant=6..10 uld tag='
TRACK_MODEL   = None      # None = 0번 셀에서 고른 모델 · 모델 이름 (실행기가 그 모델의 채택 버전을 씀)
TRACK_CONF_REQ = None     # None = 0번 셀 TRACK_CONF
TRACK_REPLACE = False     # True = 사람이 단 라벨이 있어도(이름이 …_uld·…_AA가 아님) 백업한 뒤 교체 · False = 그런 TASK는 '보류'
TRACK_SKIP_DONE = True    # True = v4.33 실행기가 이미 track을 올린 TASK는 뺌
SEND          = False     # True = 요청을 보냄
TRACK_LOCAL   = False     # True = 요청 대신 이 Colab(GPU)에서 직접 만들어 보기 → 결과는 내 분석 폴더, 올리기는 6번 셀
# track 세부 설정(fill_gaps·track_buffer·decoder 등)은 실행기 설정(config/exec.json의 track)을 씀 — 셀에서 바꾸지 않음

import pandas as pd
from IPython.display import display
_hits = pick_tasks(TRACK_IDS, TRACK_QUERY, label='track 대상', show=False)
_rows, TRACK_TARGETS = [], []
for t in _hits:
    _end = str(t['name']).endswith(('uld', 'AA'))
    _lu = last_upload(t['task_id'])
    _done = bool(_lu and _lu['source'] == 'v4.33' and _lu['kind'] == 'track')
    _why = '건너뜀: 이미 v4.33 track' if (_done and TRACK_SKIP_DONE) else ''
    if not _why:
        TRACK_TARGETS.append(t)
    _rows.append({'task_id': t['task_id'], 'TASK 이름': t['name'],
                  '기존 라벨': '교체 가능 (uld·AA)' if _end else ('교체 (TRACK_REPLACE)' if TRACK_REPLACE else '있으면 보류 (사람 라벨 보호)'),
                  '마지막 자동 라벨': f"{_lu['source']} {_lu['kind']} {str(_lu['run_time'])[:16]}" if _lu else '', '이번': _why or '요청'})
print(f'track 대상 {len(TRACK_TARGETS)}개 / 고른 TASK {len(_hits)}개')
if _rows:
    display(pd.DataFrame(_rows).set_index('task_id'))
assert TRACK_TARGETS or not _hits, '요청할 TASK가 없습니다'
_m = TRACK_MODEL or NAME
assert _m, '모델이 없습니다 — TRACK_MODEL을 적거나 0번 셀 MODEL_CHOICE'
TRACK_RID = None if TRACK_LOCAL else send('track', TRACK_TARGETS, {'model': _m, 'conf': float(TRACK_CONF_REQ or TRACK_CONF), 'allow_replace': bool(TRACK_REPLACE)},
                 go=SEND and bool(TRACK_TARGETS), note='업로드 전 백업 → 올림 → 이름 …_uld → …_uld_AA') if TRACK_TARGETS else None

# ---- TRACK_LOCAL = True: 셀에서 직접 track을 만들어 보기 — 결과는 내 분석 폴더에. 마음에 들면 6번 셀 '이 결과 올리기'
if TRACK_LOCAL:
    # [v4.33 분석 셀] 계산은 Colab에서, 결과는 내 분석 폴더에 — CVAT·공유 폴더에 쓰지 않음. 올리려면 6번 셀 '이 결과 올리기'
    import json as _json
    assert BEST and os.path.exists(BEST), '모델이 없습니다 (0번 셀 MODEL_CHOICE)'
    TRACK_RESULTS = globals().get('TRACK_RESULTS') or {}
    _settings = {'imgsz': IMGSZ, 'conf': float(TRACK_CONF_REQ or TRACK_CONF), 'fill_gaps': TRACK_FILL_GAPS, 'track_buffer': TRACK_BUFFER,
                 'decoder': TRACK_DECODER, 'frame_offset': TRACK_FRAME_OFFSET, 'box_source': TRACK_BOX_SOURCE, 'near': TRACK_NEAR}
    for t in TRACK_TARGETS:
        tid = int(t['task_id']); ts = ctt.stamp(); folder = task_dir(tid)
        print('=' * 70, f"\nTASK {tid} {t['name']}")
        try:
            task = CLIENT.tasks.retrieve(tid)
            info = ctt.task_basic(task)
            if not info['is_video']:
                print('건너뜀: 사진 TASK (ULD 프레임맵 track은 2c-5) → 9·10번 셀 자동 라벨'); continue
            ref = ctt.export_annotations(task, f'{folder}/reference_{ts}.zip')        # 참조용 export (읽기)
            meta = ctt.read_export(ref)
            video = S.video(meta['source'], info['task_name'])
            if not video:
                print(f"영상 없음: videos/ 또는 backups/에 {meta['source']}"); continue
            out_dir = f'{folder}/track_{ts}'
            rc = run([sys.executable, f'{SCRIPTS}/yolo_track_to_cvat.py', '--model', BEST, '--video', video, '--reference', ref,
                      '--imgsz', IMGSZ, '--conf', _settings['conf'], '--fill-gaps', TRACK_FILL_GAPS, '--track-buffer', TRACK_BUFFER,
                      '--decoder', TRACK_DECODER, '--frame-offset', TRACK_FRAME_OFFSET, '--box-source', TRACK_BOX_SOURCE,
                      '--near', TRACK_NEAR, '--out', out_dir], log=f'{folder}/run_{ts}_track.log')
            if rc != 0:
                print(f'❌ track 생성 실패 (로그 {folder}/run_{ts}_track.log)'); continue
            stem = os.path.splitext(os.path.basename(str(video)))[0]
            tj = _json.load(open(f'{out_dir}/tracks_{stem}.json', encoding='utf-8'))
            TRACK_RESULTS[tid] = {'file': f'{out_dir}/tracks_{stem}.xml', 'fmt': 'CVAT 1.1', 'count': int(tj['tracks']),
                                  'kind': 'track', 'model': model_label(), 'settings': _settings, 'existing': meta['existing_boxes']}
            print(f"✅ track {tj['tracks']}개 → {os.path.relpath(TRACK_RESULTS[tid]['file'], BASE)} (기존 라벨 {meta['existing_boxes']}개)")
        except Exception as e:
            print(f'❌ {ctt.api_error(e) if hasattr(ctt, "api_error") else e}')
    print(f'TRACK_RESULTS {len(TRACK_RESULTS)}개 → 6번 셀에서 미리 보고 올리기')
