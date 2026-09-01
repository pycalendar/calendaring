"""Type-checking probe for p3_greenlet.

Three things a type checker *should* be able to say about the public API.
Whichever of them mypy misses is a signature that lies.
"""
from typing import Any
import p3_greenlet as proto
from common import AsyncTransport, Store, SyncTransport

def sync_ok(coll: Any) -> None:
    coll2: proto.Collection = coll
    task = coll2.get_task("x")
    print(task.summary)          # CASE 1: correct in sync mode - must NOT error

async def async_misuse(coll: proto.Collection) -> None:
    task = coll.get_task("x")
    print(task.summary)          # CASE 2: WRONG in async mode - should error

async def sync_misuse(coll: proto.Collection) -> None:
    task = await coll.get_task("x")   # CASE 3: WRONG in sync mode - should error
    print(task.summary)
