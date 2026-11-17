"""v4.33 학습 자식 프로세스 (b24 T4, 11/17 결정).

실행기(부모)가 `python train_child.py <spec.json>`으로 **새 프로세스 묶음**에서 띄웁니다. GPU가 여럿이면 Ultralytics가
이 프로세스 아래에 DDP 자식들을 만들고, 부모는 권한을 잃으면 묶음 전체를 끝냅니다.

- 콜백·잠금·공유 저장소를 넘겨받지 않습니다 (DDP가 콜백을 직렬화하지 못하던 문제의 원인 제거).
- **자기 작업 폴더에만 씁니다** (spec의 project/name 아래 Ultralytics 산출물, spec의 done 파일, 부모가 정한
  실행별 설정·캐시·임시 폴더 — YOLO_CONFIG_DIR 등, DDP 임시 코드도 여기). 공유 폴더·다른 실행의
  기록·옛 공용 CSV에는 쓰지 않습니다 — 사람 작업자와 앱 작업이 동시에 여럿 돌아도 서로의 기록을 덮지 않게.
  공유 폴더 게시(버전 경로)는 부모가 확인한 뒤에만 합니다.
- 진행은 Ultralytics가 자기 폴더에 쓰는 results.csv로 부모가 읽습니다.
"""
import json
import os
import sys


INTEGRATIONS = ("clearml", "comet", "dvc", "hub", "mlflow", "neptune", "raytune", "tensorboard", "wandb")


def check_own_dirs(project: str):
    """설정·캐시·임시 폴더가 이 실행의 작업 폴더 안인지 (부모가 정함, b26 U4). 아니면 시작하지 않음."""
    root = os.path.realpath(project)
    for k in ("YOLO_CONFIG_DIR", "XDG_CONFIG_HOME", "TMPDIR"):
        v = os.environ.get(k)
        if not v or not os.path.realpath(v).startswith(root + os.sep):
            raise SystemExit(f"{k}가 작업 폴더 밖 — 시작하지 않음")


def main(spec_path: str) -> int:
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    check_own_dirs(spec["project"])
    from ultralytics import YOLO, settings
    try:                                               # 외부 기록 연동 끔 — 이 실행 전용 설정 파일에서만 (사람 작업자의 설정은 그대로)
        settings.update({k: False for k in INTEGRATIONS if k in settings})
    except Exception:
        pass
    model = YOLO(spec["start"])
    r = model.train(data=spec["data"], project=spec["project"], name=spec["name"], exist_ok=True, **spec.get("args", {}))
    metrics = {k: float(v) for k, v in (getattr(r, "results_dict", None) or {}).items() if isinstance(v, (int, float))}
    tmp = spec["done"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics}, f)
    os.replace(tmp, spec["done"])                      # 끝까지 갔을 때만 '끝남' 파일이 생김
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
