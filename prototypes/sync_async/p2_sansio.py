"""Prototype 2: generator-based Sans-I/O (the h11 / hyper-h2 pattern).

One source of truth, no build step.  Every I/O method is written *once*, as a
generator that ``yield``s a Request and receives a Response back.  Two thin
drivers - one sync, one async - feed it from a transport.

    def _io_save(self):
        yield Request("PUT", ...)      # the driver sends the Response back in
        return self

    save = public(_io_save)            # gives task.save() / await task.save()

The public API requirement from the roadmap is met: a caller writes
``task.save()`` or ``await task.save()``, never ``client.execute(...)``.

The interesting part is composition.  A method that does I/O, then logic, then
more I/O calls the *generator body* with ``yield from``:

    def _io_complete(self):
        fresh = yield from self._collection._io_get_task(self.uid)
        self.status = "COMPLETED"
        yield from self._io_save()
        return self

Forgetting the ``yield from`` is the failure this design must answer for, since
it is the same shape as caldav's silent-discard bug.  It is answered twice over:

  1. ``_IN_DRIVER`` - every public entry point calls ``guard()`` from a
     synchronous frame before any coroutine exists, so entering an I/O body any
     way other than ``yield from`` raises immediately.  It fires in **sync**
     mode as well, so the ordinary sync test suite catches the mistake - the
     decisive difference from the dual-mode pattern, where the bug is invisible
     until someone runs the async path.  ``guard()`` is exported because the
     typed facades in ``p2_typed`` bypass ``public()`` and must call it too.
  2. ``check_ast.py`` finds both shapes of the mistake statically.  The
     deliberately broken example lives in ``p2_sansio_bug.py`` rather than here,
     so that this module passes its own checker.
"""

from __future__ import annotations

import inspect
from contextvars import ContextVar
from typing import Any, Callable, Generator, TypeVar

from common import Request, Response, Task

T = TypeVar("T")
IO = Generator[Request, Response, T]

_IN_DRIVER: ContextVar[bool] = ContextVar("_in_driver", default=False)


class SansIOMisuse(RuntimeError):
    """Raised when a public I/O method is called from inside another one."""


def guard() -> None:
    """Refuse to enter an I/O body from inside a running driver.

    **This must be called from a synchronous frame at the call site.**  Putting
    it inside ``_drive_async`` is not enough: that body does not run until the
    coroutine is awaited, so the mistake it exists to catch - a discarded
    coroutine - would discard the check along with it.  Hence every public
    entry point calls ``guard()`` itself, and the async ones are plain ``def``
    returning a coroutine rather than ``async def``.
    """
    if _IN_DRIVER.get():
        raise SansIOMisuse(
            "a public I/O method was called from inside another I/O method. "
            "Use 'yield from self._io_<name>(...)' to compose I/O bodies."
        )


def _drive_sync(gen: IO[T], transport: Any) -> T:
    guard()
    token = _IN_DRIVER.set(True)
    try:
        try:
            req = next(gen)
            while True:
                req = gen.send(transport.request(req))
        except StopIteration as stop:
            return stop.value
    finally:
        _IN_DRIVER.reset(token)


async def _drive_async(gen: IO[T], transport: Any) -> T:
    token = _IN_DRIVER.set(True)
    try:
        try:
            req = next(gen)
            while True:
                req = gen.send(await transport.request(req))
        except StopIteration as stop:
            return stop.value
    finally:
        _IN_DRIVER.reset(token)


def public(body: Callable[..., IO[T]]) -> Callable[..., Any]:
    """Wrap a generator I/O body as a dual-mode public method."""

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        guard()  # synchronous frame: fires before any coroutine is created
        gen = body(self, *args, **kwargs)
        transport = self._transport
        if inspect.iscoroutinefunction(transport.request):
            return _drive_async(gen, transport)
        return _drive_sync(gen, transport)

    wrapper.__name__ = body.__name__.removeprefix("_io_")
    wrapper.__doc__ = body.__doc__
    wrapper._io_body = body  # type: ignore[attr-defined]
    return wrapper


class Collection:
    def __init__(self, transport: Any) -> None:
        self._transport = transport

    def _io_get_task(self, uid: str) -> IO["BoundTask"]:
        resp = yield Request("GET", f"/tasks/{uid}")
        if resp.status == 404:
            raise KeyError("no such task")
        task = BoundTask.from_dict(resp.body)
        task._collection = self
        task._transport = self._transport
        return task

    get_task = public(_io_get_task)

    def _io_search(self) -> IO[list["BoundTask"]]:
        out: list[BoundTask] = []
        cursor: int | None = 0
        while cursor is not None:
            resp = yield Request("GET", f"/search?cursor={cursor}")
            for d in resp.body["items"]:
                t = BoundTask.from_dict(d)
                t._collection = self
                t._transport = self._transport
                out.append(t)
            cursor = resp.body["next"]
        return out

    search = public(_io_search)


class BoundTask(Task):
    _collection: Collection
    _transport: Any

    def _io_save(self) -> IO["BoundTask"]:
        yield Request("PUT", f"/tasks/{self.uid}", self.to_json())
        return self

    save = public(_io_save)

    def _io_complete(self) -> IO["BoundTask"]:
        fresh = yield from self._collection._io_get_task(self.uid)
        self.summary = fresh.summary
        self.status = "COMPLETED"
        yield from self._io_save()
        return self

    complete = public(_io_complete)

    def _io_uncomplete(self) -> IO["BoundTask"]:
        self.status = "NEEDS-ACTION"
        yield from self._io_save()
        return self

    uncomplete = public(_io_uncomplete)
