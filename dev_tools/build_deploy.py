"""배포 묶음 만들기 (설계 8판 '실행 코드의 신뢰 경계' 배포 순서 ①~④).

① scripts 등 파일 확정 → ② 배포 목록(manifest.json) → ③ 목록 해시를 마스터 노트북에 고정 → ④ 마스터 노트북 해시(Keeper용)

사용:
  python3 dev_tools/build_deploy.py --out /tmp/deploy --kaggle-user <K 계정 이름> [--test] [--gpu-notebook <ipynb>]

결과 폴더를 관리자 폴더의 deploy/로 그대로 올리고, 출력된 MASTER_NB_SHA256을 Keeper Script Properties에 넣습니다.
비밀 값은 다루지 않습니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "drive" / "notebooks" / "K_kaggle" / "master_boot_v4.33.py"
# 예전에 쓰던 이름 — 배포 목록에 없으면 거절. scripts에서 지우거나 이름을 바꾼 모듈은 여기에 **계속 쌓음** (지우지 않음)
LEGACY_MODULES = ("kaggle_cpu_master", "master_boot_v4", "eggplant_common")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def kernel_meta(slug: str, title: str, code_file: str, gpu: bool, datasets) -> dict:
    return {"id": slug, "title": title, "code_file": code_file, "language": "python", "kernel_type": "notebook",
            "is_private": "true", "enable_gpu": "true" if gpu else "false", "enable_tpu": "false",
            "enable_internet": "true", "dataset_sources": list(datasets or []), "competition_sources": [],
            "kernel_sources": []}


def notebook(source: str) -> bytes:
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                     "source": source.splitlines(keepends=True)}],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    return (json.dumps(nb, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def build(out: Path, kaggle_user: str, test: bool, gpu_notebook: Path = None, datasets=(), src: Path = ROOT) -> dict:
    sfx_slug, sfx_title = ("-test", "_test") if test else ("", "")
    remote, admin = ("gdrive_test:", "gadmin_test:") if test else ("gdrive:", "gadmin:")
    if out.exists():
        shutil.rmtree(out)
    (out / "scripts").mkdir(parents=True)
    files = {}
    for p in sorted((src / "drive" / "scripts").glob("*.py")) + [src / "drive" / "scripts" / "notebook_cells.json"]:
        if p.exists():
            files["scripts/" + p.name] = p.read_bytes()
    if gpu_notebook:
        gname = f"eggplant_gpu_worker{sfx_title}.ipynb"
        files[gname] = Path(gpu_notebook).read_bytes()
        gslug = f"{kaggle_user}/eggplant-gpu-worker{sfx_slug}"
        files["kernel-metadata-gpu-worker.json"] = json.dumps(
            kernel_meta(gslug, f"eggplant-gpu-worker{sfx_title}", gname, True, datasets), indent=2).encode()
    # 가지 앱 모듈 이름 (지금 scripts + 옛 이름): 목록에 없으면 설치 폴더에서도 불러오지 않음 (V3)
    reserved = sorted({p.stem for p in (src / "drive" / "scripts").glob("*.py")} | set(LEGACY_MODULES))
    # ② 배포 목록 — 마스터 노트북·목록 자신은 넣지 않음 (한 방향 사슬)
    manifest = (json.dumps({"files": {k: sha256(v) for k, v in sorted(files.items())}}, ensure_ascii=False,
                           sort_keys=True, indent=1)).encode()
    man_sha = sha256(manifest)
    # ③ 목록 해시를 마스터 노트북에 고정
    boot = BOOT.read_text(encoding="utf-8")
    boot = (boot.replace("__MANIFEST_SHA256__", man_sha).replace("__TEST__", "True" if test else "False")
            .replace("__REMOTE__", remote).replace("__ADMIN_REMOTE__", admin)
            .replace("__RESERVED__", repr(reserved)))
    nb_name = f"eggplant_cpu_master{sfx_title}.ipynb"
    nb = notebook(boot)
    # ④ Keeper용 해시
    nb_sha = sha256(nb)
    for rel, b in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    (out / "manifest.json").write_bytes(manifest)
    (out / nb_name).write_bytes(nb)
    mslug = f"{kaggle_user}/eggplant-cpu-master{sfx_slug}"
    (out / "kernel-metadata.json").write_text(json.dumps(       # Keeper가 읽음 (마스터 실행 설정)
        kernel_meta(mslug, f"eggplant-cpu-master{sfx_title}", nb_name, False, datasets), indent=2), encoding="utf-8")
    info = {"test": test, "manifest_sha256": man_sha, "master_nb_sha256": nb_sha, "master_notebook": nb_name,
            "master_slug": mslug, "files": len(files), "remote": remote, "admin_remote": admin}
    (out / "DEPLOY_INFO.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="가지 앱 배포 묶음 만들기")
    ap.add_argument("--out", required=True)
    ap.add_argument("--kaggle-user", required=True, help="K Kaggle 계정 이름 (노트북 주소 앞부분)")
    ap.add_argument("--test", action="store_true", help="예행 연습용 (_test 이름, 시험 연결)")
    ap.add_argument("--gpu-notebook", default=None)
    ap.add_argument("--dataset", action="append", default=[], help="붙일 Kaggle 데이터셋 (예: rclone 바이너리)")
    a = ap.parse_args(argv)
    info = build(Path(a.out), a.kaggle_user, a.test, Path(a.gpu_notebook) if a.gpu_notebook else None, a.dataset)
    print(json.dumps(info, indent=2, ensure_ascii=False))
    print(f"\nKeeper Script Properties → MASTER_NB_SHA256 = {info['master_nb_sha256']}")
    print(f"관리자 폴더에 올릴 것: {a.out}/ 전체 → {'eggplant_admin_test' if a.test else 'eggplant_admin'}/deploy/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
