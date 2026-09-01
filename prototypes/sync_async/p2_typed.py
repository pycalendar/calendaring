"""Prototype 2b: a typed facade over the Sans-I/O core of p2.

The bare prototypes all fail the roadmap's 'public signatures must be correct
under mypy in both modes' test, for two different reasons:

  * p1's ``Union[Any, Coroutine]`` is honest but useless - it rejects *correct*
    sync code as well as incorrect async code.
  * p2 and p3 return ``Any``, so a type checker says nothing at all.

The fix is to separate the two problems, which turn out to be independent:

  * **implementation** duplication is solved by the generator core (p2)
  * **type** duplication is not solvable that way at all, because the mode is a
    property of the *instance* and a type checker can only key on the *class*.

So: one implementation, two typed facades.  Each facade method is one line - a
``guard()`` and a driver call - and carries the correct signature.  There is no
I/O logic and no object construction in a facade: the collection facades differ
only by a ``_task_cls`` attribute, and the core does the constructing.  So
there is nothing to keep in sync but signatures, and
``test_conformance.py::test_every_io_body_has_both_facades`` asserts that
mechanically.

Two things the fix for review finding 1 taught us, both load-bearing:

  * ``guard()`` must be called from a **synchronous frame at the call site**.
    Inside ``_drive_async`` it is useless, because that body does not run until
    the coroutine is awaited - so the discarded-coroutine mistake would discard
    the check with it.
  * hence the async facades are plain ``def`` returning a coroutine, not
    ``async def``.  ``await coll.get_task(...)`` is unaffected, and mypy still
    catches both a missing and a spurious ``await``.
"""

from __future__ import annotations

from typing import Any, Coroutine

from common import AsyncTransport, Request, SyncTransport, Task
from p2_sansio import IO, _drive_async, _drive_sync, guard


class _TaskCore:
    """The single implementation of the task's I/O.  No mode anywhere in it."""

    uid: str
    summary: str
    status: str
    _transport: Any
    _coll: Any

    def to_json(self) -> str:  # pragma: no cover - provided by Task
        raise NotImplementedError

    def _io_save(self) -> IO[Any]:
        yield Request("PUT", f"/tasks/{self.uid}", self.to_json())
        return self

    def _io_complete(self) -> IO[Any]:
        fresh = yield from self._coll._io_get_task(self.uid)
        self.summary = fresh.summary
        self.status = "COMPLETED"
        yield from self._io_save()
        return self

    def _io_uncomplete(self) -> IO[Any]:
        self.status = "NEEDS-ACTION"
        yield from self._io_save()
        return self


class _CollectionCore:
    """The single implementation of the collection's I/O.

    Object construction lives here, not in the facades: a facade supplies only
    ``_task_cls``.  That is what keeps 'no logic in a facade' true.
    """

    _task_cls: type
    _transport: Any

    def _new_task(self, d: dict[str, Any]) -> Any:
        return self._task_cls(self._transport, self, **d)

    def _io_get_task(self, uid: str) -> IO[Any]:
        resp = yield Request("GET", f"/tasks/{uid}")
        if resp.status == 404:
            raise KeyError("no such task")
        return self._new_task(resp.body)

    def _io_search(self) -> IO[Any]:
        out: list[Any] = []
        cursor: int | None = 0
        while cursor is not None:
            resp = yield Request("GET", f"/search?cursor={cursor}")
            out.extend(self._new_task(d) for d in resp.body["items"])
            cursor = resp.body["next"]
        return out


# -- typed facades: signatures only ---------------------------------------


class SyncTask(Task, _TaskCore):
    def __init__(self, transport: SyncTransport, coll: "SyncCollection", **kw: Any) -> None:
        super().__init__(**kw)
        self._transport = transport
        self._coll = coll

    def save(self) -> "SyncTask":
        guard()
        return _drive_sync(self._io_save(), self._transport)

    def complete(self) -> "SyncTask":
        guard()
        return _drive_sync(self._io_complete(), self._transport)

    def uncomplete(self) -> "SyncTask":
        guard()
        return _drive_sync(self._io_uncomplete(), self._transport)


class AsyncTask(Task, _TaskCore):
    def __init__(self, transport: AsyncTransport, coll: "AsyncCollection", **kw: Any) -> None:
        super().__init__(**kw)
        self._transport = transport
        self._coll = coll

    def save(self) -> Coroutine[Any, Any, "AsyncTask"]:
        guard()
        return _drive_async(self._io_save(), self._transport)

    def complete(self) -> Coroutine[Any, Any, "AsyncTask"]:
        guard()
        return _drive_async(self._io_complete(), self._transport)

    def uncomplete(self) -> Coroutine[Any, Any, "AsyncTask"]:
        guard()
        return _drive_async(self._io_uncomplete(), self._transport)


class SyncCollection(_CollectionCore):
    _task_cls = SyncTask

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport

    def get_task(self, uid: str) -> SyncTask:
        guard()
        return _drive_sync(self._io_get_task(uid), self._transport)

    def search(self) -> list[SyncTask]:
        guard()
        return _drive_sync(self._io_search(), self._transport)


class AsyncCollection(_CollectionCore):
    _task_cls = AsyncTask

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    def get_task(self, uid: str) -> Coroutine[Any, Any, AsyncTask]:
        guard()
        return _drive_async(self._io_get_task(uid), self._transport)

    def search(self) -> Coroutine[Any, Any, list[AsyncTask]]:
        guard()
        return _drive_async(self._io_search(), self._transport)
