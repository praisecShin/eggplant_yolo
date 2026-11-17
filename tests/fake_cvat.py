"""가짜 CVAT (2b 시험용) — handlers.CvatOps를 흉내. 실제 서비스에 접속하지 않음.

- TASK: id → {name, project_id, size, labels, updated, ann}
- 백업·export 준비 작업: request_* → 작업 번호, job_status는 `steps`번 물어야 finished
- 가져오기: import_annotations → 작업 번호, import_status. `import_fail`이면 failed, `hang_imports`면 계속 started
- 모든 호출을 `calls`에 남김 (쓰기 순서·횟수 확인용)
- `fail_get`: 이 TASK의 get_task를 실패시킴
"""
import json
import time


class FakeCvat:
    WRITES = ("import_annotations", "remove_annotations", "rename_task", "create_task", "upload_video",
              "create_from_backup", "move_task")

    def __init__(self, steps: int = 1, clock=time.time):
        self.tasks = {}
        self.jobs = {}
        self.calls = []
        self.steps = steps
        self.clock = clock
        self.n = 0
        self.import_fail = set()
        self.hang_imports = False
        self.fail_get = set()
        self.before_import_hook = None
        self.fail_create = False
        self.status_raise = None                          # 가져오기 상태 조회가 실패 (예: 접수 뒤 401) — b24 T1

    # ---- 준비
    def add_task(self, tid, name, project_id=7, size=10, labels=("fruit", "bud"), ann=None):
        self.tasks[tid] = {"id": tid, "name": name, "project_id": project_id, "size": size, "labels": list(labels),
                           "updated": f"2026-11-16T00:00:{tid % 60:02d}Z",
                           "ann": ann if ann is not None else {"shapes": [], "tracks": [], "tags": []}}
        return self.tasks[tid]

    def _job(self, kind, tid, **kw):
        self.n += 1
        jid = f"{kind}-{self.n}"
        self.jobs[jid] = dict(kind=kind, tid=tid, asked=0, **kw)
        return jid

    # ---- 읽기
    def get_task(self, tid):
        self.calls.append(("get_task", tid))
        if tid in self.fail_get or tid not in self.tasks:
            raise KeyError(tid)
        t = self.tasks[tid]
        return {k: t[k] for k in ("id", "name", "project_id", "size", "labels", "updated")}

    def list_tasks(self, limit=5000):
        self.calls.append(("list_tasks",))
        rows = [{"task_id": t["id"], "name": t["name"], "project_id": t["project_id"], "frames": t["size"],
                 "media": "video", "status": "annotation", "updated_iso": t["updated"]} for t in self.tasks.values()]
        return rows[:limit]

    def get_annotations(self, tid):
        self.calls.append(("get_annotations", tid))
        return json.loads(json.dumps(self.tasks[tid]["ann"]))

    # ---- 백업·export
    def request_backup(self, tid):
        self.calls.append(("request_backup", tid))
        return self._job("backup", tid, snapshot=json.dumps(self.tasks[tid]))

    def request_export(self, tid, fmt, images=False):
        self.calls.append(("request_export", tid, fmt))
        return self._job("export", tid, fmt=fmt, snapshot=json.dumps(self.tasks[tid]["ann"]))

    def job_status(self, job):
        j = self.jobs[job]
        j["asked"] += 1
        return "finished" if j["asked"] >= self.steps else "started"

    def download(self, job, dest):
        self.calls.append(("download", job))
        j = self.jobs[job]
        if j["asked"] < self.steps:
            raise RuntimeError("not ready")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(j["snapshot"])
        return dest

    # ---- 쓰기
    IMPORT_FORMATS = ("CVAT 1.1", "shapes-json")      # 기존 가져오기 형식만 받음 (b23 S6 — 아무 형식이나 받지 않음)

    def import_annotations(self, tid, path, fmt, before_each=None):
        self.calls.append(("import_annotations", tid, fmt))
        if fmt not in self.IMPORT_FORMATS:
            from handlers import ImportRejected
            raise ImportRejected(f"format {fmt}")
        if self.before_import_hook:
            self.before_import_hook(tid)
        if before_each:
            before_each()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        jid = self._job("import", tid, data=data)
        if tid not in self.import_fail and not self.hang_imports:
            t = self.tasks[tid]
            for k in ("shapes", "tracks", "tags"):
                t["ann"][k] = t["ann"].get(k, []) + list(data.get(k, []))
            self.calls.append(("import_done", tid))
            t["updated"] = f"2026-11-16T01:{self.n % 60:02d}:00Z"
        return jid

    def import_status(self, job):
        if self.status_raise:
            raise self.status_raise
        j = self.jobs[job]
        if j["tid"] in self.import_fail:
            return "failed"
        return "started" if self.hang_imports else "finished"

    def remove_annotations(self, tid):
        self.calls.append(("remove_annotations", tid))
        self.tasks[tid]["ann"] = {"shapes": [], "tracks": [], "tags": []}

    def rename_task(self, tid, name):
        self.calls.append(("rename_task", tid, name))
        self.tasks[tid]["name"] = name

    def create_task(self, name, **kw):
        self.calls.append(("create_task", name))
        if self.fail_create:
            raise TimeoutError("응답 잃음")
        tid = max(self.tasks or [100]) + 1
        self.add_task(tid, name, project_id=kw.get("project_id", 7), size=kw.get("size", 0))
        return tid

    def upload_video(self, tid, path, frame_step, quality):
        self.calls.append(("upload_video", tid, frame_step))
        self.tasks[tid]["size"] = 30 // max(1, frame_step)

    def create_from_backup(self, path, name, **kw):
        self.calls.append(("create_from_backup", name))
        if self.fail_create:
            raise TimeoutError("응답 잃음")
        tid = max(self.tasks or [100]) + 1
        self.add_task(tid, "restored_from_backup", project_id=None, size=12)
        return tid

    def move_task(self, tid, project_id):
        self.calls.append(("move_task", tid, project_id))
        self.tasks[tid]["project_id"] = project_id

    def writes(self):
        return [c for c in self.calls if c[0] in self.WRITES]
