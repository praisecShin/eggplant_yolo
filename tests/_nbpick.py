"""v4.31.12 (R13): 시험할 노트북 고르기 — 폴더의 첫 파일이 아니라 버전 번호(4.31.9 < 4.31.12)가 가장 큰 것을 고르고 이름을 출력"""
import re
from pathlib import Path


def latest(folder, prefix):
    found = []
    for p in Path(folder).glob(f"{prefix}_v*.ipynb"):
        m = re.fullmatch(re.escape(prefix) + r"_v(\d+(?:\.\d+)*)\.ipynb", p.name)
        if m:
            found.append((tuple(int(x) for x in m.group(1).split(".")), p))
    assert found, f"{folder}에 {prefix}_v*.ipynb가 없습니다"
    p = max(found)[1]
    print(f"[시험 대상] {p.name}" + (f" (옛 판 {len(found) - 1}개는 무시)" if len(found) > 1 else ""))
    return p
