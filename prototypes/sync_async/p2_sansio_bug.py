"""A deliberately broken Sans-I/O body, kept so the failure is reproducible.

Both enforcement mechanisms are demonstrated against this file rather than
against a transcript pasted into a document:

    python -m pytest test_conformance.py -k misuse   # the runtime guard
    python check_ast.py p2_sansio_bug.py             # the static check

It contains both shapes of the mistake.  ``_io_uncomplete`` is the exact
caldav one - a composite I/O body calling the *public* method instead of
entering the other body with ``yield from``; the runtime guard raises.
``_io_reopen`` calls the private body but forgets ``yield from``; the
generator is dropped unstarted, nothing raises or warns, and only the static
check finds it.
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

    def _io_reopen(self) -> IO["BuggyTask"]:
        self.status = "NEEDS-ACTION"
        self._io_save()  # BUG: should be `yield from self._io_save()`
        return self
        yield  # pragma: no cover - makes this a generator

    reopen = public(_io_reopen)
