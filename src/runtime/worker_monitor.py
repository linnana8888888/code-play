"""Worker Monitor — asyncio-based worker tracking with timeout and cancellation."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("code_play.worker_monitor")

DEFAULT_TIMEOUT_S = 30 * 60  # 30 minutes
STUCK_BUFFER_S = 5 * 60  # 5 min buffer beyond worker timeout


@dataclass
class ActiveWorker:
    task_id: str
    instance_id: str
    agent_type: str
    model: str
    started_at: datetime
    asyncio_task: asyncio.Task | None = None
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def elapsed_ms(self) -> int:
        return int((datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000)


class WorkerMonitor:
    def __init__(self):
        self._workers: dict[str, ActiveWorker] = {}
        self._broadcast = None

    def set_broadcast(self, callback):
        self._broadcast = callback

    def is_running(self, task_id: str) -> bool:
        return task_id in self._workers

    def register(self, task_id: str, instance_id: str, agent_type: str, model: str) -> ActiveWorker:
        if task_id in self._workers:
            raise RuntimeError(f"Worker already running for task {task_id}")
        worker = ActiveWorker(
            task_id=task_id,
            instance_id=instance_id,
            agent_type=agent_type,
            model=model,
            started_at=datetime.now(timezone.utc),
        )
        self._workers[task_id] = worker
        self._emit("worker_started", task_id=task_id, instance_id=instance_id, model=model)
        return worker

    def attach_task(self, task_id: str, asyncio_task: asyncio.Task):
        worker = self._workers.get(task_id)
        if worker:
            worker.asyncio_task = asyncio_task

    def unregister(self, task_id: str, success: bool = True):
        worker = self._workers.pop(task_id, None)
        if worker:
            event = "worker_completed" if success else "worker_failed"
            self._emit(event, task_id=task_id, instance_id=worker.instance_id,
                       duration_ms=worker.elapsed_ms)

    def cancel(self, task_id: str) -> bool:
        worker = self._workers.get(task_id)
        if not worker:
            return False
        worker._cancel_event.set()
        if worker.asyncio_task and not worker.asyncio_task.done():
            worker.asyncio_task.cancel()
        self._emit("worker_cancelled", task_id=task_id, instance_id=worker.instance_id)
        return True

    def cancel_all(self) -> list[str]:
        cancelled = []
        for task_id in list(self._workers.keys()):
            if self.cancel(task_id):
                cancelled.append(task_id)
        return cancelled

    def is_cancelled(self, task_id: str) -> bool:
        worker = self._workers.get(task_id)
        return worker._cancel_event.is_set() if worker else False

    def get_active(self) -> list[dict]:
        return [
            {
                "task_id": w.task_id,
                "instance_id": w.instance_id,
                "agent_type": w.agent_type,
                "model": w.model,
                "started_at": w.started_at.isoformat(),
                "elapsed_ms": w.elapsed_ms,
            }
            for w in self._workers.values()
        ]

    def get_count(self) -> int:
        return len(self._workers)

    def _emit(self, event_type: str, **data):
        if self._broadcast:
            try:
                payload = {"type": event_type, "data": data}
                coro = self._broadcast(payload)
                if asyncio.iscoroutine(coro):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(coro)
                    else:
                        loop.run_until_complete(coro)
            except Exception as e:
                logger.debug(f"Worker monitor broadcast failed: {e}")


worker_monitor = WorkerMonitor()
