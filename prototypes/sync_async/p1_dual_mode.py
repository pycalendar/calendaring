"""Prototype 1: runtime dual-mode - the caldav 3.x pattern.

Included as the *baseline*, not as a candidate: this is the design whose failure
modes are documented in caldav's ASYNC_DESIGN_CRITIQUE.md.  It is prototyped so
the comparison has a control, and so the silent-discard failure can be
demonstrated rather than asserted.

Rules (from caldav's ASYNC_DUAL_MODE.md):
  * every I/O method starts with `if self.is_async: return self._async_foo(...)`
  * `_async_foo` is never called from anywhere else
  * the public method is annotated as possibly returning a coroutine
"""

from __future__ import annotations

from typing import Any, Coroutine, Union

from common import Request, Response, Task

MaybeAwaitable = Union[Any, Coroutine[Any, Any, Any]]


class Collection:
    def __init__(self, transport: Any, is_async: bool) -> None:
        self._transport = transport
        self.is_async = is_async

    # -- get_task ---------------------------------------------------------
    def get_task(self, uid: str) -> MaybeAwaitable:
        if self.is_async:
            return self._async_get_task(uid)
        resp = self._transport.request(Request("GET", f"/tasks/{uid}"))
        return self._post_get_task(resp)

    async def _async_get_task(self, uid: str) -> Task:
        resp = await self._transport.request(Request("GET", f"/tasks/{uid}"))
        return self._post_get_task(resp)

    def _post_get_task(self, resp: Response) -> BoundTask:
        if resp.status == 404:
            raise KeyError("no such task")
        task = BoundTask.from_dict(resp.body)
        task._collection = self
        return task

    # -- search (paginated: the loop case) --------------------------------
    def search(self) -> MaybeAwaitable:
        if self.is_async:
            return self._async_search()
        out: list[Task] = []
        cursor: int | None = 0
        while cursor is not None:
            resp = self._transport.request(Request("GET", f"/search?cursor={cursor}"))
            out.extend(self._post_search_page(resp))
            cursor = resp.body["next"]
        return out

    async def _async_search(self) -> list[Task]:
        out: list[Task] = []
        cursor: int | None = 0
        while cursor is not None:
            resp = await self._transport.request(Request("GET", f"/search?cursor={cursor}"))
            out.extend(self._post_search_page(resp))
            cursor = resp.body["next"]
        return out

    def _post_search_page(self, resp: Response) -> list[BoundTask]:
        tasks: list[BoundTask] = []
        for d in resp.body["items"]:
            t = BoundTask.from_dict(d)
            t._collection = self
            tasks.append(t)
        return tasks


class BoundTask(Task):
    """A Task that knows its collection, so it can save itself."""

    _collection: Collection

    def save(self) -> MaybeAwaitable:
        if self._collection.is_async:
            return self._async_save()
        self._collection._transport.request(Request("PUT", f"/tasks/{self.uid}", self.to_json()))
        return self

    async def _async_save(self) -> BoundTask:
        await self._collection._transport.request(
            Request("PUT", f"/tasks/{self.uid}", self.to_json())
        )
        return self

    # -- complete: I/O, then logic, then I/O (the composition case) -------
    def complete(self) -> MaybeAwaitable:
        if self._collection.is_async:
            return self._async_complete()
        fresh = self._collection.get_task(self.uid)
        self.summary = fresh.summary
        self.status = "COMPLETED"
        self.save()
        return self

    async def _async_complete(self) -> BoundTask:
        fresh = await self._collection.get_task(self.uid)
        self.summary = fresh.summary
        self.status = "COMPLETED"
        await self.save()
        return self

    # -- uncomplete: THE BUG, reproduced verbatim -------------------------
    # This is the exact shape of the caldav bug: a composite method that forgets
    # the async check.  In sync mode it is correct.  In async mode it returns
    # without error, having written nothing, and the coroutine is discarded.
    #
    # Not *silently*, quite: Python emits `RuntimeWarning: coroutine
    # 'BoundTask._async_save' was never awaited` - on CPython at once, pointing
    # at the line below; elsewhere at garbage-collection time.  But it is only
    # a warning: it names a private method, is hidden by `-W ignore`, and does
    # not stop execution (caldav's ASYNC_DESIGN_CRITIQUE.md).  mypy does not
    # flag the line: `Union[Any, Coroutine]` hides the coroutine (section 5).
    def uncomplete(self) -> MaybeAwaitable:
        self.status = "NEEDS-ACTION"
        self.save()  # BUG in async mode: coroutine created and dropped
        return self
