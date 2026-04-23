import threading
import uuid
from typing import Dict

from app.models import TaskProgress, TaskStatus


class TaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, TaskProgress] = {}
        self._lock = threading.Lock()

    def create_task(self) -> TaskProgress:
        task_id = str(uuid.uuid4())
        task = TaskProgress(task_id=task_id, status=TaskStatus.pending)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        progress: int | None = None,
        stage: str | None = None,
        detail: str | None = None,
        output_files: list[str] | None = None,
        citations: dict[str, str] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if stage is not None:
                task.stage = stage
            if detail is not None:
                task.detail = detail
            if output_files is not None:
                task.output_files = output_files
            if citations is not None:
                task.citations = citations
            if error is not None:
                task.error = error

    def get(self, task_id: str) -> TaskProgress | None:
        with self._lock:
            return self._tasks.get(task_id)
