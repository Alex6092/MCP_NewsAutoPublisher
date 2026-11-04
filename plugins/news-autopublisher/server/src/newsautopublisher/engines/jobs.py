"""Tâches de capture moteur exécutées en arrière-plan (elles durent de 1 à 30 minutes)."""

from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

FINAL = ("done", "error")


@dataclass
class EngineJob:
    id: str
    project: str
    engine: str  # unity | unreal
    target: str  # editor | build | mrq
    mode: str  # video | screenshot
    shots: list[str]
    out_dir: str
    status: str = "queued"  # queued | running | assembling | done | error
    message: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float | None = None
    log: str | None = None
    media: list[dict[str, Any]] = field(default_factory=list)

    def save(self) -> None:
        path = Path(self.out_dir) / "job.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, status: str | None = None, message: str | None = None) -> None:
        if status:
            self.status = status
        if message is not None:
            self.message = message
        self.save()

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        end = self.finished or time.time()
        data["elapsed_seconds"] = round(end - self.started, 1)
        return data


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, EngineJob] = {}
        self._lock = threading.Lock()

    def submit(self, job: EngineJob, work: Callable[[EngineJob], None]) -> EngineJob:
        with self._lock:
            busy = [j for j in self.jobs.values()
                    if j.project == job.project and j.engine == job.engine and j.status not in FINAL]
            if busy:
                raise RuntimeError(f"Une capture {job.engine} est déjà en cours pour ce projet ({busy[0].id}).")
            self.jobs[job.id] = job
        job.save()

        def runner() -> None:
            try:
                job.update("running")
                work(job)
                if job.status not in FINAL:
                    job.status = "done"
            except Exception as exc:  # toute erreur termine proprement la tâche
                job.status = "error"
                job.error = f"{exc}" if str(exc) else exc.__class__.__name__
                job.message = traceback.format_exc(limit=3)[-600:]
            finally:
                job.finished = time.time()
                job.save()

        threading.Thread(target=runner, name=f"engine-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str, search_root: Path | None = None) -> EngineJob | None:
        job = self.jobs.get(job_id)
        if job or not search_root:
            return job
        for path in search_root.glob(f"*/engine/{job_id}/job.json"):  # tâche d'une session précédente
            data = json.loads(path.read_text(encoding="utf-8"))
            return EngineJob(**data)
        return None

    def wait(self, job: EngineJob, seconds: float) -> EngineJob:
        deadline = time.time() + max(0.0, min(seconds, 600.0))
        while job.status not in FINAL and time.time() < deadline:
            time.sleep(0.5)
        return job
