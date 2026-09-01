"""Shared scaffolding for the 0.2 sync/async architecture prototypes.

Every prototype implements the *same* toy backend against these transports, so
that one conformance suite can drive all of them in both modes and the numbers
in ``docs/design/SYNC_ASYNC_ARCHITECTURE.md`` are comparable.

The toy backend deliberately contains the three shapes that matter:

* ``get_task``   - one request, one response (the easy case)
* ``save``       - one request, mutating (the easy case)
* ``search``     - **N requests in a loop** (pagination; the case that breaks
  naive designs, and the one issue trackers force on us)
* ``complete``   - **I/O, then logic, then more I/O** (composition; this is the
  exact shape of the ``uncomplete()`` bug documented in caldav's
  ``ASYNC_DESIGN_CRITIQUE.md``)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self


class BackendError(Exception):
    """Raised by a transport, to measure traceback quality across prototypes."""


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    body: str | None = None


@dataclass(frozen=True)
class Response:
    status: int
    body: Any


@dataclass
class Task:
    """The toy object.  Pure data; no I/O anywhere in here."""

    uid: str
    summary: str = ""
    status: str = "NEEDS-ACTION"

    def to_json(self) -> str:
        return json.dumps({"uid": self.uid, "summary": self.summary, "status": self.status})

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        return cls(uid=d["uid"], summary=d.get("summary", ""), status=d.get("status", "NEEDS-ACTION"))


# --------------------------------------------------------------------------
# The fake "server".  Shared by every transport so the prototypes see identical
# data and identical failures.
# --------------------------------------------------------------------------

PAGE_SIZE = 2


@dataclass
class Store:
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_on: set[str] = field(default_factory=set)
    request_log: list[Request] = field(default_factory=list)

    def seed(self, n: int) -> Store:
        for i in range(n):
            uid = f"task-{i}"
            self.tasks[uid] = {"uid": uid, "summary": f"Task {i}", "status": "NEEDS-ACTION"}
        return self

    def handle(self, req: Request) -> Response:
        """The single source of truth for what the toy backend does."""
        self.request_log.append(req)
        if req.path in self.fail_on:
            raise BackendError(f"backend blew up on {req.method} {req.path}")
        if req.method == "GET" and req.path.startswith("/tasks/"):
            uid = req.path.removeprefix("/tasks/")
            if uid not in self.tasks:
                return Response(404, None)
            return Response(200, dict(self.tasks[uid]))
        if req.method == "PUT" and req.path.startswith("/tasks/"):
            uid = req.path.removeprefix("/tasks/")
            assert req.body is not None
            self.tasks[uid] = json.loads(req.body)
            return Response(204, None)
        if req.method == "GET" and req.path.startswith("/search"):
            # Paginated: /search?cursor=N
            cursor = 0
            if "cursor=" in req.path:
                cursor = int(req.path.split("cursor=")[1])
            uids = sorted(self.tasks)[cursor : cursor + PAGE_SIZE]
            nxt = cursor + PAGE_SIZE if cursor + PAGE_SIZE < len(self.tasks) else None
            return Response(200, {"items": [dict(self.tasks[u]) for u in uids], "next": nxt})
        raise BackendError(f"unroutable: {req.method} {req.path}")


class SyncTransport:
    """A blocking transport."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def request(self, req: Request) -> Response:
        return self.store.handle(req)


class AsyncTransport:
    """A coroutine transport."""

    def __init__(self, store: Store) -> None:
        self.store = store

    async def request(self, req: Request) -> Response:
        await asyncio.sleep(0)  # a real suspension point, so the loop really runs
        return self.store.handle(req)


class FileStore(Store):
    """Filesystem-backed variant, to test the roadmap's 'not only HTTP' case.

    The point of this class is that its natural implementation is *blocking*
    (``Path.read_text``), so the async side must push it to a thread.  A design
    that assumes 'async is the real one and sync is generated from it' has to
    justify itself here.
    """

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def handle(self, req: Request) -> Response:
        self.request_log.append(req)
        if req.path in self.fail_on:
            raise BackendError(f"backend blew up on {req.method} {req.path}")
        if req.method == "GET" and req.path.startswith("/tasks/"):
            p = self.root / f"{req.path.removeprefix('/tasks/')}.json"
            if not p.exists():
                return Response(404, None)
            return Response(200, json.loads(p.read_text()))
        if req.method == "PUT" and req.path.startswith("/tasks/"):
            p = self.root / f"{req.path.removeprefix('/tasks/')}.json"
            assert req.body is not None
            p.write_text(req.body)
            return Response(204, None)
        if req.method == "GET" and req.path.startswith("/search"):
            cursor = int(req.path.split("cursor=")[1]) if "cursor=" in req.path else 0
            files = sorted(self.root.glob("*.json"))[cursor : cursor + PAGE_SIZE]
            nxt = cursor + PAGE_SIZE if cursor + PAGE_SIZE < len(list(self.root.glob("*.json"))) else None
            return Response(200, {"items": [json.loads(f.read_text()) for f in files], "next": nxt})
        raise BackendError(f"unroutable: {req.method} {req.path}")


class AsyncFileTransport:
    """Async wrapper over blocking filesystem work, via a thread."""

    def __init__(self, store: FileStore) -> None:
        self.store = store

    async def request(self, req: Request) -> Response:
        return await asyncio.to_thread(self.store.handle, req)
