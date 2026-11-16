"""v4.31.9 1차 수정 시험: F4(진행 중 요청 소유·깨진 배정) · F15(ULD 교체 연결) · F1(백업 판정) · F17"""
import json, os, shutil, sys
from pathlib import Path
PKG = Path(sys.argv[1]).resolve(); T = Path(__file__).resolve().parent / "_work_4319"; shutil.rmtree(T, ignore_errors=True)
B = T / "base"; shutil.copytree(PKG / "scripts", B / "scripts"); sys.path.insert(0, str(B / "scripts"))
os.environ.update(EGGPLANT_SHARD="t4319", KAGGLE_BASE=str(B))
import web_bridge as wb, train_sim as ts
ok = True
def check(c, m):
    global ok; print(("✅ " if c else "❌ ") + m); ok &= bool(c)
def put(rel, obj):
    p = B / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, ensure_ascii=False)); return p
# F4
put("requests/REQ_r1__track__pending.json", {"id": "r1", "kind": "track", "status": "pending", "created": "2026-11-13T00:00:00Z", "task_ids": [1]})
put("requests/REQ_r2__track__pending.json", {"id": "r2", "kind": "track", "status": "pending", "created": "2026-11-13T00:01:00Z", "task_ids": [2]})
a = wb.take(str(B), "track", who="A", session="sA", limit=1, host="Colab")
check([r["id"] for r in a] == ["r1"], f"A가 r1을 받음 ({[r['id'] for r in a]})")
b = wb.take(str(B), "track", who="B", session="sB", host="Colab")
check([r["id"] for r in b] == ["r2"], f"B는 A가 진행 중인 r1을 가져가지 않음 ({[r['id'] for r in b]})")
a2 = wb.take(str(B), "track", who="A", session="sA", host="Colab")
check([r["id"] for r in a2] == ["r1"], "A는 자기가 받아 둔 r1을 다시 받음 (이어서 처리)")
(B / "requests/assign").mkdir(parents=True, exist_ok=True); (B / "requests/assign/ASSIGN_x.json").write_text("{깨짐")
check(wb._assigned_to_me(str(B), "x", "kaggle_gpu") is False, "읽을 수 없는 배정 파일은 받지 않음")
# F15
U = T / "uld"; U.mkdir()
def rec(tid, name, created, replace):
    (U / f"{tid}.json").write_text(json.dumps({"task_id": tid, "task_name_initial": name, "created_at": created, "upload_as": "images", "frame_map": [0, 8],
                                                "request": {"task": {"replace": replace}}}))
rec(10, "eggplant_G4_261105_3_8_uld", "2026-11-13T09:00:00+09:00", False)   # 00:00 UTC
rec(11, "eggplant_G4_261105_3_8_uld", "2026-11-13T01:00:00Z", True)          # 01:00 UTC — 문자열로는 앞이지만 실제로는 나중
rec(20, "eggplant_G4_261105_3_9_uld", "2026-11-13T00:00:00Z", False)
rec(21, "eggplant_G4_261105_3_9_uld", "2026-11-13T02:00:00Z", False)         # 바꾸기 아님 → 연결 안 함
sc = wb.uld_scan(U)
check(sc["lineage"] == {"10": "11"}, f"교체 연결: 시간대 맞춰 비교 · '바꾸기'로 만든 것만 ({sc['lineage']})")
check(sc["index"] == {"10": "images", "11": "images", "20": "images", "21": "images"}, "ULD 목록")
# F17
check(ts.pick_frames({"frames": [0, 1, 2], "boxes": {}}, 1) == [1], "SIM_FRAMES = 1이면 가운데 한 장")
# F1: CPU 마스터 백업 판정
sys.path.insert(0, str(PKG / "notebooks" / "K_kaggle"))
import kaggle_cpu_master as m
m.BASE = B
(B / "backups").mkdir(exist_ok=True)
(B / "backups/pending_backups.csv").write_text("request_time,server,task_id,task_name,status\n2026-11-13,s,2,b,준비 중\n", encoding="utf-8")
(B / "backups/x").mkdir(parents=True, exist_ok=True); (B / "backups/x/1.zip").write_text("z")   # v4.31.11 (R10): 받음은 파일이 있어야
okk, wait, bad = m.backup_verdict(wb, [{"task_id": 1, "backup_state": "최신", "last_file": "backups/x/1.zip"}, {"task_id": 2, "backup_state": "없음"}, {"task_id": 3, "backup_state": "실패"}], [1, 2, 3, 4])
check((okk, wait, bad) == (["1"], ["2"], ["3", "4"]), f"백업 판정: 받음·받는 중·실패 (만들어지지 않음 포함) {okk, wait, bad}")
print("RESULT", ok); sys.exit(0 if ok else 1)
