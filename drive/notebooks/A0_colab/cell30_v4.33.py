# 30. 실행기 (v4.33) — 이 Colab을 실행기로 띄움: GPU 일(track·shape·학습)과 Drive 버전 기록 복원(23번)
#     요청은 앱·셀이 만들고, 심판(CPU 마스터)이 이 실행기에 배정합니다. 멈추려면 셀을 정지하세요 (지금 단계를 마치고 끝남).
#     이 셀 원문은 2c(사람용 셀)에서 노트북에 넣습니다 — 지금은 파일로만 둡니다 (2b-6).
#
#  · 비밀 값은 Colab 보안 비밀에서만 읽습니다: CVAT_TOKEN. 공유 폴더 접근은 Colab 로그인으로 만든 세션 전용 설정(0600)
#  · 시험(TEST = True)은 eggplant_AA 프로젝트의 REH_ TASK에만 씁니다 (관리자 폴더 config/exec.json의 test_project_id)
TEST = False
FOLDERS = {"gdrive": "", "gadmin": ""}       # 공유 폴더·관리자 폴더의 Drive 폴더 ID (비밀 아님, 배포 계획 표). 시험: gdrive_test·gadmin_test
CAPS = ("gpu", "colab_oauth")                # GPU가 없는 런타임이면 ("colab_oauth",)
SCRIPTS = "/content/drive/MyDrive/eggplant_yolo/scripts"
DRIVE_BASE = "/content/drive/MyDrive/eggplant_yolo"   # 23번 복원이 Drive 버전 기록을 찾을 곳

import os, sys
assert all(FOLDERS.values()), "FOLDERS에 폴더 ID를 넣으세요"
from google.colab import drive, userdata
drive.mount("/content/drive")
os.environ["CVAT_TOKEN"] = (userdata.get("CVAT_TOKEN") or "").strip()     # 이 런타임 안에서만 (파일·출력에 쓰지 않음)
sys.path.insert(0, SCRIPTS)
import exec_host
base = next(n for n in FOLDERS if n.startswith("gdrive")) + ":"
ex = exec_host.main_colab(base, FOLDERS, TEST, SCRIPTS, caps=CAPS, drive_base=DRIVE_BASE)
print("실행기 끝:", ex.notes[-3:])
