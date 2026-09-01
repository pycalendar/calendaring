"""Prototype 3: greenlet bridging (the SQLAlchemy pattern).

One source of truth, no build step, and - unlike Sans-I/O - the object layer is
written in *ordinary blocking style* with no ``yield``, no generators and no
special composition rule:

    def _save(self):
        self._transport.request(Request("PUT", ...))
        return self

In sync mode that call really is blocking.  In async mode the object layer runs
inside a greenlet, and the transport adapter calls ``await_()``, which switches
back to the driver greenlet; the driver awaits the coroutine on the event loop
and switches the result back in.  The object layer never knows.

Composition *inside* the object layer is free: ``_complete()`` calls
``self._save()`` as a plain method call.  But it is not structurally safe.  The
public/private split is the same as in Sans-I/O, so a body that calls the public
``self.save()`` instead of ``self._save()`` discards a coroutine in async mode
exactly as p1 does, and nothing catches it - see sections 5 and 8 of
SYNC_ASYNC_ARCHITECTURE.md.

The costs are a C dependency and what happens to a traceback when a backend
raises; both are measured in measure.py.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, TypeVar

import greenlet

from common import Request, Task

T = TypeVar("T")


class _Missing:
    pass


def await_(awaitable: Any) -> Any:
    """Call from inside a greenlet-driven call stack to await a coroutine."""
    current = greenlet.getcurrent()
    parent = getattr(current, "_driver", None)
    if parent is None:
        raise RuntimeError(
            "await_() called outside a greenlet driver - the object layer was "
            "run synchronously but the transport is async"
        )
    return parent.switch(awaitable)


async def greenlet_spawn(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run blocking-style ``fn`` on the event loop, bridging its await_ calls."""
    driver = greenlet.getcurrent()
    g = greenlet.greenlet(fn)
    g._driver = driver  # type: ignore[attr-defined]
    value: Any = g.switch(*args, **kwargs)
    while not g.dead:
        try:
            result = await value
        except BaseException as exc:  # noqa: BLE001 - forwarded into the greenlet
            value = g.throw(exc)
        else:
            value = g.switch(result)
    return value  # type: ignore[no-any-return]


class _AsyncTransportAdapter:
    """Makes an async transport look blocking to the object layer."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def request(self, req: Request) -> Any:
        return await_(self._inner.request(req))


def public(body: Callable[..., T]) -> Callable[..., Any]:
    """Expose a blocking-style body as ``obj.foo()`` / ``await obj.foo()``."""

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if self._is_async:
            return greenlet_spawn(body, self, *args, **kwargs)
        return body(self, *args, **kwargs)

    wrapper.__name__ = body.__name__.lstrip("_")
    wrapper.__doc__ = body.__doc__
    return wrapper


class Collection:
    def __init__(self, transport: Any) -> None:
        self._is_async = inspect.iscoroutinefunction(transport.request)
        self._transport = _AsyncTransportAdapter(transport) if self._is_async else transport

    # -- ordinary blocking code, written once -----------------------------
    def _get_task(self, uid: str) -> "BoundTask":
        resp = self._transport.request(Request("GET", f"/tasks/{uid}"))
        if resp.status == 404:
            raise KeyError("no such task")
        task = BoundTask.from_dict(resp.body)
        task._collection = self
        task._transport = self._transport
        task._is_async = self._is_async
        return task

    get_task = public(_get_task)

    def _search(self) -> list["BoundTask"]:
        out: list[BoundTask] = []
        cursor: int | None = 0
        while cursor is not None:
            resp = self._transport.request(Request("GET", f"/search?cursor={cursor}"))
            for d in resp.body["items"]:
                t = BoundTask.from_dict(d)
                t._collection = self
                t._transport = self._transport
                t._is_async = self._is_async
                out.append(t)
            cursor = resp.body["next"]
        return out

    search = public(_search)


class BoundTask(Task):
    _collection: Collection
    _transport: Any
    _is_async: bool

    def _save(self) -> "BoundTask":
        self._transport.request(Request("PUT", f"/tasks/{self.uid}", self.to_json()))
        return self

    save = public(_save)

    def _complete(self) -> "BoundTask":
        # Composition is a plain method call.  Nothing to forget.
        fresh = self._collection._get_task(self.uid)
        self.summary = fresh.summary
        self.status = "COMPLETED"
        self._save()
        return self

    complete = public(_complete)

    def _uncomplete(self) -> "BoundTask":
        self.status = "NEEDS-ACTION"
        self._save()
        return self

    uncomplete = public(_uncomplete)
