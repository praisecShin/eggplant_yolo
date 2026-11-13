"""v4.31.6: ULD 표시(LC앱 img·uld · 재처리 source) · Kaggle 모델 목록(Drive 목록으로)"""
import json, os, shutil, sys, time
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_st"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ["EGGPLANT_SHARD"] = "st_test"
import web_bridge as wb, relabel_bridge as rb
ok = True
def check(c, m):
    global ok; print(("✅ " if c else "❌ ") + m); ok &= bool(c)
tasks = [{"task_id": 101, "name": "eggplant_G6_261019_1_3_uld", "status": "annotation", "frames": 10, "updated": "", "updated_utc": ""},
         {"task_id": 102, "name": "eggplant_G6_261019_1_4_uld", "status": "annotation", "frames": 10, "updated": "", "updated_utc": ""}]
st = wb.build_state(str(B), tasks, video_stems=set(), backup_bases=set(), uld={"101": "images"}, log=lambda *a: None)
row = {t["id"]: t for t in st["tasks"]}
check(row[101]["uld"] == "images" and row[101]["img"] == "uld", f"LC앱: ULD 사진 TASK → uld=images · img=uld ({row[101]['uld']}, {row[101]['img']})")
check(row[102]["uld"] == "" and row[102]["img"] == "none", "LC앱: ULD 아닌 TASK는 그대로")
# 재처리: source
(B / "runs/m1/weights").mkdir(parents=True); (B / "runs/m1/TRAINING_DONE").write_text("ok")
(B / "runs/m2").mkdir(parents=True); (B / "runs/m2/TRAINING_DONE").write_text("ok")   # Kaggle: best.pt는 Drive에만
(B / "runs/m1/weights/best.pt").write_bytes(b"x")
rows = rb.model_rows(str(B), files={"runs/m2/weights/best.pt": (100, time.time())})
check({r["name"] for r in rows} == {"m1", "m2"}, f"모델 목록: 로컬에 없는 best.pt도 Drive 목록으로 ({[r['name'] for r in rows]})")
check({r["name"] for r in rb.model_rows(str(B))} == {"m1"}, "files 없으면 예전처럼 로컬만")
rb.ensure(str(B)); tr = rb.update_tracked(str(B), tasks)
s2 = rb.build_state(str(B), tr, models=[], media=(set(), set()), uld={"101": "images"})
src = {t["id"]: t["source"] for t in s2["tasks"]}
check(src.get(101) == "ULD" and src.get(102) == "", f"재처리 앱: source ULD ({src})")
print("RESULT", ok); sys.exit(0 if ok else 1)
