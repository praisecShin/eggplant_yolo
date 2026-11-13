"""v4.31.8: 학습 계획 연구(train_sim) · 고정 시험 TASK · 사라진 TASK · ULD 교체 연결 — 가짜 데이터로"""
import json, os, shutil, sys
from pathlib import Path
import numpy as np
from PIL import Image
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_sim"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ["EGGPLANT_SHARD"] = "sim_test"
import cvat_task_tools as ctt, web_bridge as wb, relabel_bridge as rb, train_sim as ts
ok = True
def check(c, m):
    global ok; print(("✅ " if c else "❌ ") + m); ok &= bool(c)

# ---- 지문: 어두운 이미지 vs 밝은 이미지, 박스 밖만
W, H = 400, 300
def img(level, floor=(120, 80, 40)):
    a = np.full((H, W, 3), level, np.uint8); a[int(H * 0.85):] = floor
    a[50:100, 50:100] = 255                             # 박스 안 흰색 — 배경 밝기에서 빠져야 함
    return Image.fromarray(a)
box = [("t1", "healthy_fruit", False, (50, 50, 100, 100))]
ann = {"frames": [0, 1], "boxes": {0: box, 1: box + [("t2", "healthy_bud", True, (200, 200, 205, 205))]}, "meta": {"W": W, "H": H}}
dark = ts.fingerprint(ann, [0, 1], {0: img(30), 1: img(30)}, W, H)
bright = ts.fingerprint(ann, [0, 1], {0: img(200), 1: img(200)}, W, H)
check(dark["bg_luma"] < 0.2 < 0.6 < bright["bg_luma"], f"배경 밝기: 어두움 {dark['bg_luma']:.2f} < 밝음 {bright['bg_luma']:.2f} (박스 안 흰색은 빠짐)")
check(dark["boxes_per_frame"] == 1.5 and abs(dark["occl_ratio"] - 1 / 3) < 1e-3 and dark["small_ratio"] > 0, f"개체 지문: 박스/프레임 1.5 · 가림 1/3 · 작은 박스 있음 ({dark['small_ratio']})")
# ---- 성적·개수 오차
preds = {0: [("healthy_fruit", False, (52, 52, 100, 100)), ("healthy_fruit", False, (300, 10, 350, 60))], 1: []}
ev = ts.evaluate(ann, [0, 1], preds, labels={"healthy_fruit", "healthy_bud"})
a = ev["_all"]
check((a["tp"], a["fp"], a["fn"]) == (1, 1, 2) and a["precision"] == 0.5 and a["recall"] == 0.3333, f"맞힘·오탐·놓침 (1,1,2) · P 0.5 · R 0.33: {a['tp'], a['fp'], a['fn'], a['precision'], a['recall']}")
hf = ev["healthy_fruit"]
check(hf["count_mae"] == 1.0 and hf["count_bias"] == 0.0 and ev["healthy_bud"]["count_bias"] == -1.0,
      f"개수 오차: 열매 프레임당 1개(+1, −1)·치우침 0 (합 2 vs 2) · 봉오리 −100% (덜 셈) → {hf['count_mae']}, {hf['count_bias']}, {ev['healthy_bud']['count_bias']}")
# ---- 관계: 어두울수록 재현율이 떨어지는 가짜 데이터 40 TASK
rng = np.random.default_rng(1)
fp, rows = {}, []
for i in range(40):
    lum = rng.uniform(0.1, 0.7)
    f = {"task_id": str(i), "task_name": f"eggplant_G{1 + i % 6}_261020_1_{i}_vf", "gh": f"G{1 + i % 6}", "boxes": "50"}
    for k in ts.REL_KEYS:
        f[k] = str(rng.normal(0, 1))
    f["bg_luma"] = str(lum)
    fp[str(i)] = f
    rows.append({"task_id": str(i), "model": "m", "label": "_all", "in_train": "train" if i % 4 == 0 else "",
                 "recall": str(min(1, max(0, 0.4 + 0.8 * lum + (0.1 if i % 4 == 0 else 0) + rng.normal(0, 0.03)))), "count_rel": "0.2"})
rel = ts.relation(fp, rows, "m", "_all", "recall")
top = rel["coef"][0]
check(top["key"] == "bg_luma" and top["effect"] > 0.1 and top["sure"], f"관계: 배경 밝기가 가장 큰 효과, 확실 ({top['key']} {top['effect']} [{top['lo']}, {top['hi']}])")
it = next(c for c in rel["coef"] if c["key"] == "in_train")
check(it["effect"] > 0.05, f"학습에 쓰인 TASK는 재현율이 높음 ({it['effect']})")
gt = ts.group_table(fp, rows, "m")
check(len(gt) == 6 and all("recall" in r for r in gt), "온실별 표 6줄")
# ---- 분할안
train = [str(i) for i in range(30)]; evl = [str(i) for i in range(30, 40)]
fp["39"] = dict(fp["39"], bg_luma="5.0")                  # 아주 다른 환경
sim = ts.simulate(fp, train, evl, rel=rel, roles={t: "val" for t in evl})
r39 = next(r for r in sim["rows"] if r["task_id"] == "39")
check(not r39["covered"] and "배경 밝기" in r39["far_keys"], f"train에 없는 환경은 '덮이지 않음' · 가장 다른 지문 = 배경 밝기 ({r39['far_keys']})")
check(all(0 <= r.get("pred_recall", 0) <= 1 for r in sim["rows"]), "예상 재현율 0~1")
sug = ts.suggest_additions(fp, train[:10], [str(i) for i in range(10, 40)], k=3)
check(sug and sug[0]["task_id"] == "39", f"덮임을 가장 넓히는 TASK = 가장 다른 TASK 먼저 ({[s['task_id'] for s in sug]})")
# ---- 저장·읽기
ts.save_fingerprint(B, dict(fp["1"], per_label={"healthy_fruit": 3}))
ts.save_fingerprint(B, dict(fp["1"], bg_luma="0.9", per_label={}))
check(len(ts.read_fingerprints(B)) == 1 and ts.read_fingerprints(B)["1"]["bg_luma"] == "0.9", "지문은 TASK마다 한 줄 (다시 하면 바꿈)")
# ---- 고정 시험 TASK
ctt.write_test_tasks(B, {"101": "eggplant_G6_261013_1_3", "102": "eggplant_G2_261008_2_5"}, by="t", note="U세트")
te = ctt.read_test_tasks(B)
check(te["ids"] == {"101", "102"} and ("G6", "261013", "1", "3") in te["keys"], "시험 TASK 저장·읽기 (그루 열쇠)")
check(ctt.test_conflict(te, 101, "x") == "시험 TASK" and ctt.test_conflict(te, 999, "eggplant_G6_20261013_1_3_vf") == "같은 그루·촬영일"
      and ctt.test_conflict(te, 998, "eggplant_G6_261013_1_4_vf") == "", "학습에서 뺄 것: 시험 TASK · 같은 그루·촬영일(8자리 날짜도) · 다른 그루는 그대로")
ctt.write_test_tasks(B, {"101": "eggplant_G6_261013_1_3"}, by="t", note="바꿈")
h = ctt.read_test_tasks(B)["history"]
check(len(h) == 2 and h[-1]["removed"] == ["102"], "바꾸면 기록이 남음 (뺀 것)")
# ---- 사라진 TASK · ULD 교체
(B / "status").mkdir(); (B / "status/cvat_tasks.json").write_text(json.dumps({"tasks": {
    "500": {"name": "eggplant_G4_261105_3_8_uld", "gone": True, "gone_at": "2026-11-12T03:00:00Z"},
    "501": {"name": "eggplant_G4_261105_3_8_uld", "gone": False}}}))
tasks = [{"task_id": 501, "name": "eggplant_G4_261105_3_8_uld", "status": "annotation", "frames": 8, "updated": "", "updated_utc": ""}]
st = wb.build_state(str(B), tasks, video_stems=set(), backup_bases=set(), uld={"501": "images"}, replaced={"500": "501"}, log=lambda *a: None)
row = {str(t["id"]): t for t in st["tasks"]}
check("500" in row and row["500"]["stage"] == "CVAT에서 사라짐" and row["500"]["gone_at"].startswith("2026-11-12") and row["500"]["replaced_by"] == "501",
      "LC: 사라진 TASK가 백업 없이도 남음 · 사라진 때 · 새 번호")
check(row["501"].get("replaces") == ["500"], "LC: 새 TASK에 옛 번호")
rb.ensure(str(B))
(B / "relabel").mkdir(exist_ok=True)
rb.update_tracked(str(B), tasks + [{"task_id": 500, "name": "eggplant_G4_261105_3_8_uld"}])
tr = rb.update_tracked(str(B), tasks)
check(tr["500"].get("gone_at", "").startswith("2026-11-12") and not tr["500"]["in_cvat"], "재처리: 사라진 TASK에 사라진 때")
hist = rb.task_record(str(B), "500").get("history") or []
rb.update_tracked(str(B), tasks)
hist2 = rb.task_record(str(B), "500").get("history") or []
check(len(hist) == 1 and hist[0]["kind"] == "gone" and len(hist2) == 1, "재처리 이력에 '사라짐' 한 번만")
s2 = rb.build_state(str(B), models=[], media=(set(), set()), uld={"501": "images"}, replaced={"500": "501"})
r2 = {str(t["id"]): t for t in s2["tasks"]}
check(r2["500"]["replaced_by"] == "501" and r2["500"]["gone_at"], "재처리 앱: 새 번호 · 사라진 때")
print("RESULT", ok); sys.exit(0 if ok else 1)
