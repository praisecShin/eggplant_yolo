import sys as _s, os as _o; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); from _nbpick import latest   # v4.31.12 (R13)
import json, os, sys, shutil, time, types, tempfile
from pathlib import Path
T = tempfile.mkdtemp(); BASE = f'{T}/base'; os.makedirs(BASE)
DRIVE = Path(sys.argv[1]).resolve()            # 실행: python3 tests/test_uld.py drive
sys.path.insert(0, str(DRIVE / 'scripts'))
import cvat_task_tools as ctt, web_bridge as wb
ON_KAGGLE, LOCAL_TMP, ULD_COLAB = False, T, f'{T}/CVAT_UpLoader'
who_am_i = lambda: '시험'
_kg_rc = None; _kg_remote = None
ok_all = True
def ok(c, m):
    global ok_all; print(('✅ ' if c else '❌ ') + m); ok_all &= bool(c)
# 가짜 ULD 폴더: 기록 + clip (60프레임, 프레임 번호를 밝기로)
os.makedirs(f'{ULD_COLAB}/registry/tasks'); os.makedirs(f'{ULD_COLAB}/clips')
have_av = True
try:
    import av, numpy as np
    clip = f'{ULD_COLAB}/clips/77_e_G6_261102_3_9_uld.mp4'
    with av.open(clip, 'w') as c:
        st = c.add_stream('mpeg4', rate=30); st.width, st.height, st.pix_fmt = 64, 48, 'yuv420p'
        for i in range(60):
            fr = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 4, dtype='uint8'), format='rgb24')
            for p in st.encode(fr): c.mux(p)
        for p in st.encode(): c.mux(p)
except Exception as e:
    have_av = False; print('(av 없음 → clip 시험 생략)', e); clip = f'{ULD_COLAB}/clips/77_x.mp4'; open(clip, 'wb').write(b'x')
fm = [0, 8, 16, 24, 32, 40, 48, 56]
rec = {'upload_as': 'images', 'frame_map': fm, 'clip_path': 'CVAT_UpLoader/clips/' + os.path.basename(clip), 'clip_bytes': os.path.getsize(clip),
       'clip_w': 64, 'clip_h': 48, 'task_name_initial': 'e_G6_261102_3_9_uld'}
json.dump(rec, open(f'{ULD_COLAB}/registry/tasks/77.json', 'w'))
json.dump({'upload_as': 'video'}, open(f'{ULD_COLAB}/registry/tasks/78.json', 'w'))
_nb = json.load(open(latest(DRIVE / 'notebooks', 'eggplant_yolo_colab'), encoding='utf-8'))
_c0 = ''.join(_nb['cells'][1]['source'])                      # 노트북 0번 셀에서 ULD·이름 규칙 부분만 꺼내 실행
exec(_c0[_c0.index('# ---------------- v4.31.5: ULD'):_c0.index('if ON_KAGGLE:\n    _free = shutil.disk_usage')])

class Fr:
    def __init__(s, name, w=64, h=48): s.name, s.width, s.height = name, w, h
class Task:
    def __init__(s, tid, name, frames=()): s.id, s.name, s._fr, s.updates = tid, name, list(frames), []
    def get_meta(s): return types.SimpleNamespace(frames=s._fr)
    def update(s, d): s.updates.append(d); s.name = d['name']
names = [f'e_G6_261102_3_9_uld_f{n:06d}.jpg' for n in fm]
ok(uld_is_images(uld_task(77)) and not uld_is_images(uld_task(78)) and uld_task(99) is None, 'uld_task: 사진 TASK 77 · 영상 TASK 78 · 기록 없는 99')
ok(uld_mismatch(Task(77, 'x', [Fr(n) for n in names]), rec) == '', '사진 수·이름·크기가 맞으면 통과')
ok('사진 수' in uld_mismatch(Task(77, 'x', [Fr(n) for n in names[:7]]), rec), '사진 수가 다르면 이유')
ok('이름' in uld_mismatch(Task(77, 'x', [Fr(n) for n in names[:7]] + [Fr('e_f000057.jpg')]), rec), '사진 이름이 frame_map과 다르면 이유')
ok('크기' in uld_mismatch(Task(77, 'x', [Fr(n, 32, 24) for n in names]), rec), '사진 크기가 clip과 다르면 이유')
ok(uld_clip(rec) == clip, 'uld_clip: 경로')
rec2 = dict(rec, clip_bytes=5); ok(uld_clip(rec2) is None, 'uld_clip: 크기가 기록과 다르면 None')
uld_clip_done(clip); ok(os.path.exists(clip), 'Colab에서는 clip(Drive 원본)을 지우지 않음')
if have_av:
    n = uld_images(77, f'{BASE}/raw_images')
    got = sorted(os.listdir(f'{BASE}/raw_images'))
    from PIL import Image
    v = [Image.open(f'{BASE}/raw_images/{g}').getpixel((5, 5))[0] for g in got]
    ok(n == 8 and got == names and all(abs(v[k] - fm[k] * 4) <= 6 for k in range(8)), f'uld_images: 8장, 이름·프레임 일치 (밝기 {v})')
    ok(uld_images(77, f'{BASE}/raw_images') == 0 and uld_images(78, f'{BASE}/raw_images') is None, '이미 있으면 다시 안 뽑음 · 영상 TASK는 None')
# 이름 규칙
t = Task(1, 'e_G6_261102_3_9_uld'); r = label_uploaded(t, replaced=False, say=lambda m: None)
ok(t.name == 'e_G6_261102_3_9_uld_AA' and r['renamed'], '_uld → _uld_AA')
bz = f'{T}/before.zip'; open(bz, 'wb').write(b'PK')
os.makedirs(f'{BASE}/videos'); open(f'{BASE}/videos/e_G1_261026_1_1.mp4', 'wb').write(b'x')
t = Task(2, 'e_G1_261026_1_1_uld_AA'); r = label_uploaded(t, replaced=True, before_zip=bz, say=lambda m: None)
ex = os.listdir(f'{BASE}/exports/_aa_replaced')
ok(t.updates == [] and AA_REPLACED_NOTE in r['note'] and len(ex) == 1 and '__2__' in ex[0] and not wb.list_requests(BASE), '_AA 교체: 이름 그대로 · 기록 · 이전 라벨 보관 · 영상 있으면 백업 요청 없음')
t = Task(3, 'e_G1_261026_1_2_uld_AA_r1'); r = label_uploaded(t, replaced=True, before_zip=bz, say=lambda m: None)
rq = wb.list_requests(BASE)
ok(t.updates == [] and len(rq) == 1 and rq[0]['kind'] == 'backup' and rq[0]['task_ids'] == [3], '_AA_r1 교체 + 영상 없음 → 백업 요청 1건')
r = label_uploaded(t, replaced=True, before_zip=bz, say=lambda m: None); ok(len(wb.list_requests(BASE)) == 1, '같은 TASK 백업 요청은 겹치지 않음')
t = Task(77, 'e_G6_261102_3_9_uld_AA'); _ULD['rec'].pop('77', None); label_uploaded(t, replaced=True, before_zip=bz, say=lambda m: None)
ok(len(wb.list_requests(BASE)) == 1, 'ULD clip이 있으면 영상 있음 → 백업 요청 없음')
t = Task(4, 'e_G1_261026_1_3_vf'); r = label_uploaded(t, replaced=True, before_zip=bz, say=lambda m: None)
ok(t.updates == [] and r['note'] == '', '_vf는 이름도 기록도 그대로')
t = Task(5, 'e_G1_261026_1_4_uld'); r = label_uploaded(t, rename=False, say=lambda m: None); ok(t.name.endswith('_uld'), "표시 설정 '' → 이름을 바꾸지 않음")
print('RESULT', ok_all)
