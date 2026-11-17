"""실제 CVAT 동작 (handlers.CvatOps 구현, 2b-2부터).

지금 쓰는 함수를 감싸기만 합니다 — 새 CVAT 동작을 만들지 않습니다.
- 읽기·export: `cvat_task_tools` (cvat-sdk 클라이언트)
- 백업: `cvat_backup`의 request_backup·check_backup·fetch_backup (requests 세션)

작업 번호는 종류를 앞에 붙여 구분합니다: 'bk:<rq_id>' 백업, 'ex:<rq_id>' export.
토큰은 실행 호스트가 보안 비밀에서 받아 넘깁니다(파일·기록에 쓰지 않음).
쓰기(2b-3): 가져오기(`task.import_annotations` — 그 호출이 끝나면 서버 가져오기도 끝난 것으로 'sync:' 작업 번호),
shape 목록 올리기(`update_annotations` CREATE, 500개씩), 지우기, 이름 바꾸기. 처리기는 이 묶음을 ScopedCvat로 감싸 씀.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from handlers import CvatOps, ImportRejected

IMPORT_FORMATS = ("CVAT 1.1",)              # 가져오기 형식 — v4.32 ctt.IMPORT_FORMAT (b23 S6)


def _rejected(e) -> bool:
    """서버가 분명히 받지 않았다는 응답인가 (4xx, 시간 초과·충돌·제한 제외). 그 밖은 '모름'."""
    st = getattr(e, "status", None) or getattr(e, "status_code", None)
    return isinstance(st, int) and 400 <= st < 500 and st not in (408, 409, 429)


class RealCvat(CvatOps):
    def __init__(self, host: str, token: str, org: Optional[str] = None):
        self.host, self._token, self.org = host.rstrip("/"), token, org
        self._client = None
        self._session = None

    # ---- 접속 (처음 쓸 때)
    def client(self):
        if self._client is None:
            import cvat_task_tools as ctt
            self._client = ctt.connect(self.host, self._token)
            ctt.set_scope(self._client, self.org, "")
        return self._client

    def session(self):
        if self._session is None:
            import cvat_backup as cb
            cb.HOST, cb.AUTH_MODE, cb.CREDENTIALS, cb.ORGANIZATION_SLUG = self.host, "token", self._token, self.org
            s = cb.new_session()
            cb.login(s, "token")
            self._session = s
        return self._session

    # ---- 읽기
    def get_task(self, tid):
        t = self.client().tasks.retrieve(int(tid))
        labels = [getattr(l, "name", "") for l in (t.get_labels() if hasattr(t, "get_labels") else [])]
        upd = getattr(t, "updated_date", None)
        return {"id": int(tid), "name": getattr(t, "name", ""), "project_id": getattr(t, "project_id", None),
                "size": getattr(t, "size", None), "labels": labels,
                "updated": upd.isoformat() if hasattr(upd, "isoformat") else str(upd or "")}

    def list_tasks(self, limit=5000):
        """보이는 모든 조직의 TASK (옛 취합의 ctt.list_tasks_all과 같은 범위)."""
        import cvat_task_tools as ctt
        rows, _ = ctt.list_tasks_all(self.client(), limit=limit)
        for r in rows:
            r["project_id"] = r.get("project") or None
        return rows

    def get_annotations(self, tid):
        a = self.client().tasks.retrieve(int(tid)).get_annotations()
        return a.to_dict() if hasattr(a, "to_dict") else a

    # ---- 백업·export 준비·받기
    def request_backup(self, tid):
        import cvat_backup as cb
        return "bk:" + str(cb.request_backup(self.session(), int(tid)))

    def request_export(self, tid, fmt, images=False):
        import cvat_task_tools as ctt
        return "ex:" + str(ctt.request_export(self.client(), int(tid), fmt, include_images=images))

    def _status(self, job):
        kind, rq = job.split(":", 1)
        if kind == "bk":
            import cvat_backup as cb
            st, url, msg, _ = cb.check_backup(self.session(), rq)
            return st, url, msg
        import cvat_task_tools as ctt
        d = ctt.export_status(self.client(), rq)
        return d["status"], d["result_url"], d["message"]

    def job_status(self, job):
        st, _, _ = self._status(job)
        return {"finished": "finished", "failed": "failed", "expired": "failed"}.get(st, "started" if st != "unknown" else "unknown")

    def download(self, job, dest):
        st, url, msg = self._status(job)
        if st != "finished" or not url:
            raise RuntimeError(f"받을 준비가 안 됨: {st} {msg[:80]}")
        kind = job.split(":", 1)[0]
        if kind == "bk":
            import cvat_backup as cb
            cb.fetch_backup(self.session(), url, Path(dest))
        else:
            import cvat_task_tools as ctt
            ctt.download_result(self.client(), url, Path(dest))
        return dest

    # ---- 쓰기 (2b-3)
    SHAPES_FMT = "shapes-json"

    def import_annotations(self, tid, path, fmt, before_each=None):
        """가져오기 **접수**만 하고 작업 번호를 돌려줌 (끝났는지는 import_status, b24 T1).
        before_each: 서버 쓰기마다 그 앞에서 부름(처리기의 권한 확인, b23 S3).
        ImportRejected는 서버가 **접수 자체를 분명히 거절**했을 때만 — 접수 뒤의 오류는 모두 '모름'(예외 그대로)."""
        if fmt != self.SHAPES_FMT and fmt not in IMPORT_FORMATS:
            raise ImportRejected(f"가져오기 형식이 아님: {fmt}")
        before_each = before_each or (lambda: None)
        t = self.client().tasks.retrieve(int(tid))
        if fmt == self.SHAPES_FMT:
            return self._import_shapes(t, tid, path, before_each)
        before_each()
        try:
            rq = self._submit(t, path, fmt)
        except Exception as e:
            if _rejected(e):
                raise ImportRejected(f"서버가 가져오기 접수를 거절 ({getattr(e, 'status', '')})")
            raise                                          # 접수됐는지 모름
        if not rq:
            raise RuntimeError("가져오기 작업 번호를 받지 못함")   # 접수됐는지 모름
        return "rq:" + rq

    def _submit(self, t, path, fmt) -> str:
        """cvat-sdk AnnotationUploader.upload_file_and_wait의 앞부분(올리기·접수)만 — 기다리기는 하지 않음."""
        import json
        from cvat_sdk.core.uploading import AnnotationUploader
        c = self.client()
        url = c.api_map.make_endpoint_url(t.api.create_annotations_endpoint.path, kwsub={"id": t.id})
        params = {"format": fmt, "filename": Path(path).name}
        resp = AnnotationUploader(c).upload_file(url, Path(path), query_params=params, meta={"filename": params["filename"]})
        return json.loads(resp.data).get("rq_id") or ""

    def _import_shapes(self, t, tid, path, before_each):
        import json
        from cvat_sdk.api_client import models
        from cvat_sdk.core.proxies.annotations import AnnotationUpdateAction
        names = {l.name: l.id for l in t.get_labels()}
        shapes = json.loads(Path(path).read_text(encoding="utf-8")).get("shapes", [])
        reqs = [models.LabeledShapeRequest(type="rectangle", frame=int(x["frame"]), label_id=names[x["label"]],
                                           points=[float(v) for v in x["points"]], occluded=bool(x.get("occluded")),
                                           source="auto") for x in shapes]
        for i in range(0, len(reqs), 500):
            before_each()
            try:
                t.update_annotations(models.PatchedLabeledDataRequest(shapes=reqs[i:i + 500]),
                                     action=AnnotationUpdateAction.CREATE)
            except Exception as e:
                if i == 0 and _rejected(e):
                    raise ImportRejected(f"서버가 첫 묶음을 거절 ({getattr(e, 'status', '')})")
                raise                                      # 앞 묶음이 들어갔거나 결과를 모름
        return f"sync:{tid}:{len(reqs)}"

    def import_status(self, job):
        """queued | started | finished | failed. 조회가 실패하면 예외(처리기는 '모름'으로 다룸) — 4xx도 거절이 아님."""
        job = str(job)
        if job.startswith("sync:"):
            return "finished"
        if not job.startswith("rq:"):
            return "unknown"
        req, _ = self.client().api_client.requests_api.retrieve(job[3:])
        v = str(getattr(getattr(req, "status", None), "value", "") or "")
        return v if v in ("queued", "started", "finished", "failed") else "unknown"

    def remove_annotations(self, tid):
        self.client().tasks.retrieve(int(tid)).remove_annotations()

    def rename_task(self, tid, name):
        self.client().tasks.retrieve(int(tid)).update({"name": name})

    # ---- 새 TASK (2b-5b, DESIGN '새 TASK 만들기')
    def create_task(self, name, project_id=None, labels=None, **kw):
        """빈 TASK — 번호를 먼저 받음 (미디어는 upload_video)."""
        from cvat_sdk.api_client import models as m
        if project_id:
            spec = m.TaskWriteRequest(name=name, project_id=int(project_id))
        else:
            spec = m.TaskWriteRequest(name=name, labels=[m.PatchedLabelRequest(name=n, type="rectangle")
                                                         for n in (labels or ["healthy_fruit", "disease_fruit",
                                                                              "healthy_bud", "disease_bud"])])
        return int(self.client().tasks.create(spec).id)

    def upload_video(self, tid, path, frame_step, quality):
        t = self.client().tasks.retrieve(int(tid))
        t.upload_data(resources=[str(path)], params={"frame_step": int(frame_step), "image_quality": int(quality),
                                                      "use_cache": True})   # cvat-sdk가 서버 처리가 끝날 때까지 기다림

    def create_from_backup(self, path, name, **kw):
        return int(self.client().tasks.create_from_backup(str(path)).id)

    def move_task(self, tid, project_id):
        self.client().tasks.retrieve(int(tid)).update({"project_id": int(project_id)})
