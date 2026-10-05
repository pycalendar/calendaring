# Sync/async architecture: comparison and recommendation

**Roadmap item:** [0.2 Sync/async architecture](ROADMAP.md#02-syncasync-architecture)
**Status:** drafted — awaiting the author's review
**Deliverable:** this comparison, backed by runnable prototypes in
[`prototypes/sync_async/`](../../prototypes/sync_async/)

**Recommendation in one line:** a generator-based Sans-I/O core with two thin
typed façades — one implementation of every I/O method, two hand-thin classes
that carry the correct type signatures.

---

## 1. Method

Everything below has been prototyped and tested; three architectures are implemented against the *same* toy backend and driven by the *same* test suite:

| File | What it is |
|---|---|
| [`common.py`](../../prototypes/sync_async/common.py) | the toy backend, its sync/async/filesystem transports, and a fake server |
| [`p1_dual_mode.py`](../../prototypes/sync_async/p1_dual_mode.py) | runtime dual-mode — the caldav 3.x pattern, as the control |
| [`p2_sansio.py`](../../prototypes/sync_async/p2_sansio.py) | generator-based Sans-I/O |
| [`p2_sansio_bug.py`](../../prototypes/sync_async/p2_sansio_bug.py) | the caldav mistake, planted, so both enforcement mechanisms have a committed specimen |
| [`p2_typed.py`](../../prototypes/sync_async/p2_typed.py) | the same core plus typed façades — **the recommendation** |
| [`p3_greenlet.py`](../../prototypes/sync_async/p3_greenlet.py) | greenlet bridging, the SQLAlchemy pattern |
| [`test_conformance.py`](../../prototypes/sync_async/test_conformance.py) | one suite, 4 prototypes × 2 modes |
| [`measure.py`](../../prototypes/sync_async/measure.py) | produces every number quoted here |
| [`check_ast.py`](../../prototypes/sync_async/check_ast.py) | the CI enforcement check item 1.3 asks for |

Reproduce with `python -m pytest prototypes/sync_async/ -q` and
`python prototypes/sync_async/measure.py`. Current result: **78 passed,
1 xfailed**, and every fenced output block below is printed by `measure.py`.

The xfail is the dual-mode bug. It is applied as a **strict** marker rather than
by calling `pytest.xfail()`, so it asserts two things rather than none: that the
server was not written to, and — because strict means an unexpected pass fails
the suite — that the day p1's bug stops reproducing, the suite says so.

### The toy backend

Two methods would not have been enough. The roadmap asks how each approach
survives a paginated HTTP backend and a filesystem backend, so the toy has four
shapes, and the last two are where designs actually break:

1. `get_task` — one request, one response
2. `save` — one request, mutating
3. `search` — **N requests in a loop** (pagination; what issue trackers force)
4. `complete` — **I/O, then logic, then more I/O** (composition)

Shape 4 is the important one. It is the exact shape of the caldav bug.

---

## 2. The problem, restated from evidence

caldav's [`ASYNC_DESIGN_CRITIQUE.md`](https://github.com/python-caldav/caldav/blob/master/docs/design/ASYNC_DESIGN_CRITIQUE.md)
records that a composite method which forgets its `is_async_client` check
discards a coroutine and does nothing. `p1_dual_mode.uncomplete()`
reproduces it verbatim, and `measure.py` prints it:

```
THE DUAL-MODE BUG  (p1, async: the object looks right, the server is stale)
  uncomplete() returned: BoundTask  status=NEEDS-ACTION
  server still says:     COMPLETED
```

The method returns an object of the right type, with the right attribute values,
and the server was never written to.

The critique also explains why the `RuntimeWarning: coroutine … was never
awaited` that Python does emit is too weak to count;
[`p1_dual_mode.py`](../../prototypes/sync_async/p1_dual_mode.py) reproduces it
(`measure.py` shows `p1_dual_mode.py:124 … self.save()  # BUG`).

So the failure is *not literally silent*, but it is silent enough that every
instance in caldav was found by writing a test for it rather than by observing
it. The distinction matters for the comparison: an approach that turns this into
an exception is strictly better, and an approach that turns it into an exception
**in sync mode as well** is better again.

---

## 3. The candidates

The roadmap lists five. Three were prototyped; two are cost-modelled only, with
the reason given.

| Approach | Prototyped | One source of truth | Build step | C dependency |
|---|---|---|---|---|
| Runtime dual-mode | yes (control) | no | no | no |
| Generator Sans-I/O | **yes** | yes | no | no |
| `greenlet` bridging | **yes** | yes | no | **yes** |
| Separate async classes | no — cost-modelled | no | no | no |
| Async-first + `unasync` codegen | no — cost-modelled | in source | **yes** | no |

**Separate async classes** was not prototyped because its properties are not in
doubt: types are correct by construction, and every I/O method is written twice.
It is the honest baseline for "correct but duplicated", and §6 shows that the
recommended design keeps its typing benefit without its duplication.

**`unasync` codegen** was not prototyped, and this is the clearest gap in the
comparison. The author's stated position is that "write async, generate sync" is
unattractive, and the roadmap records it. Not prototyping it means the comparison
cannot *refute* that position with numbers — it takes it as given. If that
position is softer than stated, this is the one experiment worth adding, because
codegen is the only approach that gets correct types and zero hand-written
duplication simultaneously; it pays for that with a build step, generated code in
tracebacks, and a debugger that steps through a file nobody wrote.

**`asyncio.run()` wrapping** remains rejected without study, as the roadmap says.

---

## 4. Result: can one test suite drive both modes?

Yes, for all of them. [`test_conformance.py`](../../prototypes/sync_async/test_conformance.py)
is 165 lines of code and parametrises over `{p1, p2, p2b, p3} × {sync, async}`. The
only concession it makes is one three-line helper:

```python
async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value
```

This dimension therefore does **not** discriminate between the candidates, which
is itself worth knowing — it removes an argument that might otherwise have been
made for any of them.

---

## 5. Result: correctness under composition

This is the dimension that decides the recommendation.

| | Composite method that forgets the rule | Caught in sync mode? | Caught in async mode? | Catchable statically? |
|---|---|---|---|---|
| p1 dual-mode | silently does nothing | **no — the code is correct in sync** | only a `RuntimeWarning` | no |
| p2 Sans-I/O | raises `SansIOMisuse` | **yes** | **yes** | **yes** |
| p2b typed façade | raises `SansIOMisuse` | **yes** | **yes** | **yes** |
| p3 greenlet | silently does nothing | **no** | **no** | no |

p1's row is the whole problem: the mistake is **invisible in the mode most
developers run their tests in**. A contributor writes a composite method, the
sync suite passes, and the bug ships to async users.

**p3's row was wrong in an earlier draft**, which claimed the mistake "cannot
happen" because composition in greenlet is a plain method call. It can: p3 also
has a public wrapper (`save = public(_save)`) beside the body (`_save`), so a
composite body that calls `self.save()` instead of `self._save()` reproduces
p1's failure exactly — a coroutine from `greenlet_spawn`, created and dropped.
p3 has neither a runtime guard nor a static check for it, so on this axis it is
p1's equal, not p2's better. §8 follows the consequences.

p2 fixes this with a `ContextVar`. Calling a public I/O method from inside
another one raises immediately, and — decisively — it raises in sync mode too:

```
THE SANS-I/O GUARD  (fires in both modes, from p2_sansio_bug.py)
  sync   SansIOMisuse: a public I/O method was called from inside another I/O method.
  async  SansIOMisuse: a public I/O method was called from inside another I/O method.
```

**Where the guard is called turns out to be load-bearing**, and getting it wrong
recreates the very bug. `guard()` must run in a **synchronous frame at the call
site**. Putting it inside `_drive_async` does nothing, because that body does not
execute until the coroutine is awaited — so the discarded-coroutine mistake
discards the check along with it. This is why the async façades in `p2_typed` are
plain `def` returning a coroutine rather than `async def`. (`await
coll.get_task(...)` is unaffected, and §6's typing results are unchanged.)

The static check is the belt to those braces, and it runs against the same
committed specimen:

```
THE STATIC CHECK  (same bug, found without running anything)
  OK - no Sans-I/O composition violations in p2_sansio.py, p2_typed.py
  -> exit 0
  p2_sansio_bug.py:33: save() is the public wrapper - in _io_uncomplete() use 'yield from self._io_save()'
  1 violation(s)
  -> exit 1
```

Both lines matter. It finds the planted bug, **and** it passes the recommended
design — an earlier version of the checker did neither: it missed the
public-wrapper shape entirely and reported eight false violations against
`p2_typed.py`, the architecture it exists to protect.

---

## 6. Result: type checking, and a finding that changes the shape of the answer

The roadmap asks for "mypy/pyright correctness of the public signatures". Three
cases were put to mypy 2.3.1 for each prototype
([`typing_probe/`](../../prototypes/sync_async/typing_probe/)):

- **Case 1** — correct sync use. Must **not** error.
- **Case 2** — using the result without `await` in async mode. **Should** error.
- **Case 3** — `await`ing the result in sync mode. **Should** error.

| | Case 1 (correct) | Case 2 (missing await) | Case 3 (spurious await) |
|---|---|---|---|
| p1 dual-mode | **false positive** | caught | missed |
| p2 Sans-I/O bare | ok | **missed** | **missed** |
| p3 greenlet | ok | **missed** | **missed** |
| **p2b typed façade** | **ok** | **caught** | **caught** |

p1's `Union[Any, Coroutine]` is the worst outcome available: it rejects *correct*
code as well as catching one of the two errors. In practice a caller silences it
with `# type: ignore`, which then also silences the one real catch. p2 and p3, as
bare prototypes, return `Any` — their signatures do not lie, they say nothing.

**The finding.** Implementation duplication and type duplication are *separate
problems with separate solutions*, and no single mechanism solves both:

- The mode is a property of the **instance**. A type checker can only key on the
  **class**. Therefore correct types require two classes, no matter what the
  implementation looks like underneath.
- Sans-I/O and greenlet both solve implementation duplication and neither can
  solve the typing problem, because neither changes that fact.

So the answer is one core plus two typed façades. Each façade method is a
`guard()` plus one line that drives the shared generator body, and it carries the
right signature. From [`p2_typed.py`](../../prototypes/sync_async/p2_typed.py):

```python
class SyncTask(Task, _TaskCore):
    def save(self) -> "SyncTask":
        guard()
        return _drive_sync(self._io_save(), self._transport)

class AsyncTask(Task, _TaskCore):
    def save(self) -> Coroutine[Any, Any, "AsyncTask"]:
        guard()
        return _drive_async(self._io_save(), self._transport)
```

The async façade is a plain `def` returning a coroutine, not `async def` — see
§5 for why an `async def` here would recreate the bug.

There is **no logic** in a façade — no I/O, and no object construction either:
the collection façades differ only by a `_task_cls` attribute and the shared core
does the constructing. So there is nothing to keep in sync but signatures, and
[`test_every_io_body_has_both_facades`](../../prototypes/sync_async/test_conformance.py)
asserts that mechanically rather than leaving it to discipline.

That property had to be *fixed*, not merely claimed: the first draft of
`p2_typed` moved object construction out of the shared bodies and into both
façades, which duplicated real per-mode logic in the one mechanism advertised as
duplication-free. The review caught it. It is worth knowing that this is the
natural drift for this design, and that the completeness test above does not
catch it — only reading the façades does.

mypy's message for Case 2 is even actionable: *"Coroutine[Any, Any, AsyncTask]
has no attribute summary. Maybe you forgot to use await?"*

This also answers the roadmap's explicit question — "can the object layer be
Sans-I/O without an ugly public API?" — with a demonstrated yes. Callers write
`task.save()` or `await task.save()`. Nothing resembling
`client.execute(task.build_save_request())` appears anywhere.

---

## 7. Result: size, and what it does not tell us

From `measure.py`, code lines only (no blanks, comments or docstrings):

| | total | fixed machinery | I/O methods | per I/O method |
|---|---|---|---|---|
| p1 runtime dual-mode | 77 | 4 | 5 | 14.6 |
| p2 generator Sans-I/O | 94 | 50 | 5 | 8.8 |
| p3 greenlet | 91 | 43 | 5 | 9.6 |
| **p2b Sans-I/O + typed façades** (the recommendation) | 129 | 42 | 5 | 17.4 |

p2b is `p2_typed.py` (91 lines: a core of its own plus the façades) and the
drivers and guard it imports from `p2_sansio.py` (38 lines). An earlier draft
added the whole of `p2_sansio.py` instead and so counted every I/O body twice.

Extrapolating the slopes to caldav's **57** `_async_*` methods (counted with
`grep -rc "async def _async_" caldav/` on 2026-09-02): roughly **836 / 551 /
590 / 1033** lines for p1 / p2 / p3 / p2b. The bare Sans-I/O core is the
smallest, because p1 is the only design whose slope includes writing each body
twice. **The recommendation is the largest**, because each I/O method costs one
core body *and* two façade methods.

It is still **not** the argument for anything. Anyone choosing on line count is
choosing on the wrong axis, and the numbers move whenever the toy does: an
earlier draft of this table reported a ~25% gap because `measure.py` divided
every file by a hard-coded five methods, which charged p2 for a sixth body it
happened to contain and excluded module-level setup from "fixed". A later review
found that the table then set p1 against bare p2 rather than against the
recommendation. A measurement that can drift like that should be read as an
order of magnitude, not a score. `measure.py` now counts the methods rather than
assuming them, and prints the p2b row.

The typed façades are the real, visible price of §6's recommendation: about 8.6
lines per I/O method on top of the core, which takes p2b's per-method cost
(17.4) past p1's (14.6). That price buys signatures that do not lie and a misuse that raises
instead of discarding a write. At caldav's scale that is roughly 200 more lines
than p1.

---

## 8. greenlet: no longer competitive

A backend error raised on **page 2 of a paginated search** — a failure partway
through a loop of I/O, which is the realistic bad case:

| | sync frames | async frames | object-layer frame visible |
|---|---|---|---|
| p1 dual-mode | 4 | 8 | yes |
| p2 Sans-I/O | 5 | 8 | yes |
| p3 greenlet | 5 | **12** | yes |

All three keep the failing object-layer line visible, which was the main risk.
The difference is that greenlet's async traceback is not merely longer, it is
**non-linear**: `greenlet_spawn` appears twice and the frames read as though
`await_()` called `greenlet_spawn()` called the transport, which is not the
causal order. Reading it requires knowing how the bridge works. Sans-I/O's
async traceback has the same frame count as plain dual-mode (8); in sync mode it
has one frame more (5 against 4), the driver.

**Why greenlet stops being the runner-up.** An earlier draft of this document
argued that greenlet wins if the author values a rule that *cannot be broken*
over a rule enforced twice — and offered the C dependency and this traceback as
the price. §5 retracts the premise: the rule can be broken in greenlet exactly as
in dual-mode, and nothing catches it.

With that gone, what is left on greenlet's side is ergonomic rather than safety:
composition reads as ordinary blocking code, with no `yield from` and no
generator discipline for a contributor to learn. That is worth something. It is
not worth:

- a compiled C dependency in a library whose dependency set is otherwise pure
  Python,
- a 50%-longer, non-linear async traceback, and
- a bridge a future contributor must understand before they can debug anything,

**for a design that is no safer than the one whose failure modes prompted this
whole item.** greenlet also still needs §6's typed façades, so it does not even
save that work.

This is the one place where the clean-context review changed a conclusion rather
than a claim. The recommendation was already Sans-I/O; the review removed the
argument for the alternative.

---

## 9. Result: pagination and the filesystem backend

Both required by the roadmap, both covered by the shared suite for all three
prototypes:

- `test_search_paginates` asserts 5 tasks at page size 2 take exactly 3
  requests — the loop is genuinely driven, not faked.
- `test_backend_error_mid_pagination_propagates` fails on page 2 specifically.
- `test_filesystem_backend` runs the same object layer against a naturally
  blocking `FileStore`, with the async side pushed to a thread via
  `asyncio.to_thread`.

No candidate had difficulty with either. Worth recording explicitly: the
filesystem case is the one where "write async, generate sync" is least
attractive, because the *sync* implementation is the natural one and the async
version is the wrapper — the opposite of the direction codegen assumes.

---

## 10. Recommendation

Adopt the **generator-based Sans-I/O core with two typed façades**, and implement
it as roadmap item 1.3.

1. I/O methods are written once, as generator bodies named `_io_*`, yielding a
   request and receiving a response.
2. Two drivers, one sync and one async; with the guard they are 38 lines, and
   all the fixed machinery is 42.
3. Two typed façade classes per public class, each method a `guard()` plus a
   one-line delegation, carrying the correct signature. The async façades are
   plain `def` returning a coroutine, **not** `async def` — see §5.
4. Enforcement, all three of which exist in the prototypes, are cheap, and none
   of which is optional:
   - the `_IN_DRIVER` runtime guard via `guard()`, called from a synchronous
     frame at every public entry point, which fires in sync mode too;
   - [`check_ast.py`](../../prototypes/sync_async/check_ast.py) in CI, which
     must pass on the façade modules as well as catch the planted bug;
   - [`test_every_io_body_has_both_facades`](../../prototypes/sync_async/test_conformance.py).

What this buys, restated against the caldav failure record: the bug that produced
`ASYNC_DESIGN_CRITIQUE.md` becomes an exception at the moment it is written, in
the mode the developer is already running, and a CI failure if it somehow gets
committed.

**A caution the review earned.** Every one of those three mechanisms was broken
in the first draft of these prototypes — the guard did not cover the façades, the
static check both missed the real mistake and rejected the recommended design,
and the completeness test did not exist while the document claimed it did. None
of that was visible from the inside. Whatever 1.3 builds, the enforcement needs
its own tests, and they need to be written by someone who did not write the
enforcement.

### What is not settled

1. **`unasync` was not prototyped** (§3), and §8 makes this more pressing than it
   was: with greenlet out, codegen is the only untested alternative left, so
   "Sans-I/O wins" currently means "Sans-I/O beat two designs and one that was
   never run". If the author's position on codegen is negotiable, that experiment
   should happen before 1.3 starts.
2. **Façade generation.** The façades are mechanical enough to generate, which
   would reintroduce a build step through the back door. Recommendation: write
   them by hand and *test* their completeness rather than generate them — but
   this is worth revisiting once the real method count is known.
3. **Cancellation and timeouts** were not tested. A driver loop that is cancelled
   mid-pagination must not leave a half-consumed generator in a bad state, and
   nothing here exercises that.
4. **Threading.** `_IN_DRIVER` is a `ContextVar`, so it is correct per-task and
   per-thread, but a driver that hands work to a thread pool has not been tested.
5. **The caldav bridge** (roadmap 2.1) is the real test: caldav's own objects are
   dual-mode, so the CalDAV backend must adapt p1-shaped code into whatever 1.3
   builds. That is named in the roadmap as the part most likely to overrun, and
   nothing here reduces that risk.
6. **`check_ast.py` is a prototype, not the gate 1.3 needs.** The suite runs
   it (`test_static_check_passes_the_real_modules_and_catches_the_specimen`),
   but a review found three holes, each confirmed with a probe: it only knows
   public names whose `_io_*` body is in the same file, so a call into another
   module's object passes; it flags any attribute of the same name, such as
   `re.search(...)` in a file that defines `_io_search`; and it exempts
   `g = self.save(); yield from g` as delegation. 1.3's check must match on
   `self` and known receivers, resolve names across modules or from a registry,
   and not exempt an assignment of a public call.

---

*Drafted with AI assistance (Claude Opus 5 via Claude Code), then revised after a
clean-context review that overturned one conclusion (§8) and found the
enforcement mechanisms broken in three separate ways (§10). Every number and
every fenced output block is reproducible from `prototypes/sync_async/`; the
prototypes are the deliverable as much as this document is.*
