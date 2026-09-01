"""Same three cases as the other probes, against the typed façade."""
from p2_typed import AsyncCollection, SyncCollection

def sync_ok(coll: SyncCollection) -> None:
    task = coll.get_task("x")
    print(task.summary)               # CASE 1: correct - must NOT error

async def async_ok(coll: AsyncCollection) -> None:
    task = await coll.get_task("x")
    print(task.summary)               # CASE 1b: correct - must NOT error

async def async_misuse(coll: AsyncCollection) -> None:
    task = coll.get_task("x")
    print(task.summary)               # CASE 2: WRONG - should error

async def sync_misuse(coll: SyncCollection) -> None:
    task = await coll.get_task("x")   # CASE 3: WRONG - should error
    print(task.summary)
