# 7. 검수 결과 수집 — CVAT에서 검수(Merge·추가·삭제)를 끝낸 TASK ID를 적고 실행 → 검증 3단계
# [v4.33 분석 셀] 읽기·분석만 — 저장은 내 분석 폴더(OUT), 공유 Drive·CVAT에는 쓰지 않음
assert 'BASE' in globals(), '먼저 0번 셀(공통 설정·준비)을 실행하세요'

REVIEW_IDS = []         # 예: [2687801]
LOGIN = None            # None = 지금 접속 중인 서버 그대로 · 또는 0번 셀 CVAT_PROFILES의 이름 ('token', 'password', 'B' …)

use_cvat(LOGIN)
import json
if ctt.as_task_ids(REVIEW_IDS):
    job_start(7, 'review', {'ids': REVIEW_IDS})
for tid in ctt.as_task_ids(REVIEW_IDS):
    ts = ctt.stamp()
    folder = task_dir(tid)
    log = f'{folder}/run_{ts}_review.log'
    row = dict(run_time=ctt.now(), action='review', task_id=tid, server=CVAT_SERVER)
    print('=' * 70, f'\nTASK {tid}')
    try:
        # 비교 대상: 실제로 CVAT에 올린 track (다시 생성만 하고 안 올린 결과가 아니라)
        last = last_upload(tid, include_track=True)      # v4.33 실행기 결과 + 옛 작업 대장 중 나중 것
        ups = [last] if last and last.get('status') == '업로드 완료' else []
        if not last or not last.get('result_file'):
            row.update(status='보류', note='track 생성·업로드 기록 없음')
            continue
        print('비교할 자동 track:', last['result_file'], '(업로드한 것)' if ups else '(업로드 기록 없음 → 마지막 생성본)')
        task = CLIENT.tasks.retrieve(tid)
        reviewed = ctt.export_annotations(task, f'{folder}/reviewed_{ts}.zip')
        row.update(task_name=task.name, video=last.get('video', ''), model=last.get('model', ''), note=f"기준 {last['source']}",
                   backup_file=os.path.relpath(reviewed, BASE), result_file=last['result_file'])
        cj = f'{folder}/compare_L3_{ts}.json'
        run([sys.executable, f'{SCRIPTS}/compare_tracks.py', '--pred', f"{BASE}/{last['result_file']}", '--gt', reviewed,
             '--json', cj, '--csv', f'{folder}/compare_L3_{ts}.csv'], log=log)
        m = json.load(open(cj, encoding='utf-8'))
        row.update(tracks=m.get('pred_tracks', ''), precision=m['precision'], recall=m['recall'], f1=m['f1'],
                   count_error=m.get('count_error', ''), fragments=m.get('fragments', ''),
                   id_switches=m.get('id_switches', ''), idf1=m.get('idf1', ''))
        row.update(status='검수 수집 완료' if m.get('gt_is_track') else '검수 수집 (track 형식 아님)',
                   note='분석 결과 (내 분석 폴더) — 학습 데이터로 쓰려면 14번 셀 요청')
    except Exception as e:
        row.update(status='오류', note=str(e)[:300])
        print('❌ 오류:', e)
    finally:
        ctt.append_registry(REGISTRY, **row)
if not REVIEW_IDS:
    print('REVIEW_IDS가 비어 있습니다.')
if ctt.as_task_ids(REVIEW_IDS):
    job_end()
