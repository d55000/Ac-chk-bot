"""
bot/utils/task_manager.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides a stateful **TaskManager** that:

* maps each ``task_id`` to a running :class:`asyncio.Task`;
* enforces a global concurrency limit via :class:`asyncio.Semaphore`;
* supports graceful cancellation with cleanup.

Usage::

    from bot.utils.task_manager import task_manager
    task_id = task_manager.submit(coro, cleanup_callback)
    await task_manager.cancel(task_id)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Coroutine, Optional

from bot.core.config import MAX_WORKERS
from bot.utils.logger import setup_logger

log = setup_logger("task_mgr")


class TaskManager:
    """Manages async worker tasks with concurrency control."""

    def __init__(self, max_workers: int = MAX_WORKERS) -> None:
        self._semaphore = asyncio.Semaphore(max_workers)
        # task_id → asyncio.Task
        self._tasks: dict[str, asyncio.Task] = {}
        # task_id → optional cleanup coroutine / callback
        self._cleanups: dict[str, Optional[Callable[..., Any]]] = {}

    # ── Public API ──────────────────────────────────────────────────────

    def submit(
        self,
        coro: Coroutine,
        cleanup: Optional[Callable[..., Coroutine]] = None,
    ) -> str:
        """Schedule *coro* for execution and return a unique ``task_id``.

        Parameters
        ----------
        coro:
            The coroutine to run (must be awaitable).
        cleanup:
            An optional async callable invoked on cancellation for
            releasing resources (e.g. deleting temp files).
        """
        task_id = uuid.uuid4().hex[:8]
        task = asyncio.create_task(self._worker(task_id, coro))
        self._tasks[task_id] = task
        self._cleanups[task_id] = cleanup
        task.add_done_callback(lambda _t: self._evict(task_id))
        log.info("Task %s submitted", task_id)
        return task_id

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task by its *task_id*.

        Returns ``True`` if the task was found and cancelled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.cancel()
        # Wait for the task to actually finish.
        try:
            await task
        except asyncio.CancelledError:
            pass
        log.info("Task %s cancelled", task_id)
        return True

    @property
    def active_count(self) -> int:
        """Number of tasks currently tracked (running or pending)."""
        return len(self._tasks)

    @property
    def active_tasks(self) -> dict[str, asyncio.Task]:
        """A snapshot of the running task dictionary."""
        return dict(self._tasks)

    # ── Internal helpers ────────────────────────────────────────────────

    async def _worker(self, task_id: str, coro: Coroutine) -> Any:
        """Acquire the semaphore, run *coro*, and handle cancellation."""
        async with self._semaphore:
            try:
                return await coro
            except asyncio.CancelledError:
                log.warning("Task %s was cancelled – running cleanup", task_id)
                cleanup = self._cleanups.get(task_id)
                if cleanup:
                    try:
                        await cleanup()
                    except Exception:
                        log.exception(
                            "Cleanup for task %s raised an exception", task_id
                        )
                raise  # Re-raise so the task is marked cancelled.
            except Exception:
                log.exception("Task %s raised an unhandled exception", task_id)
                raise

    def _evict(self, task_id: str) -> None:
        """Remove a finished task from the internal dictionaries."""
        self._tasks.pop(task_id, None)
        self._cleanups.pop(task_id, None)


# Module-level singleton so every handler shares the same manager.
task_manager = TaskManager()
