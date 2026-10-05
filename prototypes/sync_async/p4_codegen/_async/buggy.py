"""caldav's mistake, planted in async-first source.

``generate.py`` turns it into ``../_sync/buggy.py``, where the same line is a
*correct* sync call.  So the sync test suite passes and only async users lose
the write - the asymmetry that makes p1 dangerous, reproduced in p4.
"""

from __future__ import annotations

from p4_codegen._async.tasks import AsyncTask


class AsyncBuggyTask(AsyncTask):
    async def uncomplete(self) -> AsyncTask:
        self.status = "NEEDS-ACTION"
        self.save()  # BUG: missing await
        return self
