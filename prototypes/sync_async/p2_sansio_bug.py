"""A deliberately broken Sans-I/O body, kept so the failure is reproducible.

Both enforcement mechanisms are demonstrated against this file rather than
against a transcript pasted into a document:

    python -m pytest test_conformance.py -k misuse   # the runtime guard
    python check_ast.py p2_sansio_bug.py             # the static check

It contains the exact caldav mistake - a composite I/O body calling the
*public* method instead of entering the other body with ``yield from``.
"""

from __future__ import annotations

from common import Task
from p2_sansio import IO, Collection, public


class BuggyTask(Task):
    _collection: Collection
    _transport: object

    def _io_save(self) -> IO["BuggyTask"]:
        from common import Request

        yield Request("PUT", f"/tasks/{self.uid}", self.to_json())
        return self

    save = public(_io_save)

    def _io_uncomplete(self) -> IO["BuggyTask"]:
        self.status = "NEEDS-ACTION"
        self.save()  # BUG: should be `yield from self._io_save()`
        return self
        yield  # pragma: no cover - makes this a generator

    uncomplete = public(_io_uncomplete)
