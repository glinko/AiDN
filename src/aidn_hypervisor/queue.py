from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import get_args
from uuid import uuid4

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.domain.types import TaskStatus

_ALLOWED_TASK_STATUSES = set(get_args(TaskStatus))


@dataclass(frozen=True)
class QueuedTask:
    priority: int
    enqueue_index: int
    created_at: str
    task_id: str
    request: TaskRequest
    status: TaskStatus = "queued"

    @property
    def sort_key(self) -> tuple[int, int]:
        return (-self.priority, self.enqueue_index)


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._tasks: list[QueuedTask] = []
        self._next_enqueue_index = 0

    def enqueue(self, request: TaskRequest) -> QueuedTask:
        task = QueuedTask(
            priority=request.priority,
            enqueue_index=self._next_enqueue_index,
            created_at=datetime.now(timezone.utc).isoformat(),
            task_id=str(uuid4()),
            request=request.model_copy(deep=True),
        )
        self._next_enqueue_index += 1
        self._tasks.append(task)
        self._tasks.sort(key=lambda item: item.sort_key)
        return task

    def peek_next(self) -> QueuedTask | None:
        for task in self._tasks:
            if task.status == "queued":
                return task
        return None

    def transition_status(self, task_id: str, status: TaskStatus) -> QueuedTask:
        if status not in _ALLOWED_TASK_STATUSES:
            raise ValueError(f"Invalid task status: {status}")

        for index, task in enumerate(self._tasks):
            if task.task_id == task_id:
                updated_task = replace(task, status=status)
                self._tasks[index] = updated_task
                return updated_task
        raise KeyError(task_id)

    def snapshot(self) -> list[QueuedTask]:
        return list(self._tasks)

    def restore(self, tasks: list[QueuedTask]) -> None:
        self._tasks = sorted(list(tasks), key=lambda item: item.sort_key)
        if self._tasks:
            self._next_enqueue_index = max(
                task.enqueue_index for task in self._tasks
            ) + 1
        else:
            self._next_enqueue_index = 0

    def get(self, task_id: str) -> QueuedTask:
        for task in self._tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(task_id)
