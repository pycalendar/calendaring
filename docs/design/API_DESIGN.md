# Unified API specification

**Roadmap item:** [1.1 Unified API design and peer review](ROADMAP.md#11-unified-api-design-and-peer-review)

**Status:** draft by Claude Opus 5.5, 2026-10-08. Reviewed by the author on
2026-10-08 and 09, comments applied; not yet peer-reviewed ([§11 Peer review](#11-peer-review)).

**Inputs:** [0.1 task model survey](TASK_MODEL_SURVEY.md),
[0.2 sync/async decision](SYNC_ASYNC_ARCHITECTURE.md#11-decision),
[0.3 decisions D1–D7](PRIOR_ART_AND_DECISIONS.md#part-3-project-decisions)

**Consumers:** [roadmap 1.2](ROADMAP.md#12-abstract-base-classes-and-the-backend-conformance-suite) writes the conformance suite against this document, [roadmap 1.3](ROADMAP.md#13-syncasync-scaffolding)
generates the sync copy of what it calls async, [roadmap 1.6](ROADMAP.md#16-time-tracking-model-and-api) adds the time log to the
task model in [§3.4 Task](#34-task).

The test the roadmap sets: does it fit CalDAV *and* a Gitea issue tracker
without lying about either? Each section ends with how it does that.

Import names below say `calendaring`. The name may still change (see the
note under [roadmap 0.3](ROADMAP.md#03-prior-art-standards-and-project-decisions)); nothing in the design depends on it, and the one
place where a name is written into user data, the `X-` prefix ([§3.6 Properties with no standard home](#36-properties-with-no-standard-home)), is
deliberately not the package name.

---

## Decisions in short

| # | Decision | Section |
|---|---|---|
| A1 | Items (events, tasks, journals) are plain data, the same class in sync and async code. I/O lives on `Collection`, `Backend` and `Workspace`, which come in a sync and an async version. | [§1 Layers and modes](#1-layers-and-modes), [§2 The I/O classes](#2-the-io-classes) |
| A2 | An item is a typed view over an `icalendar.Calendar`, delegating to `icalendar`'s own typed properties wherever they exist. | [§3 Items](#3-items) |
| A3 | Search takes an `icalendar_searcher.Searcher`. The server may filter, but only ever *more loosely*; the client always re-filters. Results are therefore identical on every backend by construction. | [§4 Search](#4-search) |
| A4 | Capabilities are a typed table per collection: feature → support level (`FULL`, `LOSSY`, `EMULATED`, `UNSUPPORTED`, `UNKNOWN`). | [§5 Capabilities](#5-capabilities) |
| A5 | Unsupported operations raise before any I/O. A write that would lose data raises by default; the caller can downgrade that to a warning or allow it, per call or per workspace. Emulation happens only where the result is indistinguishable. | [§5.3 What happens when the caller asks for something unsupported](#53-what-happens-when-the-caller-asks-for-something-unsupported) |
| A6 | One exception hierarchy under `CalendaringError`; native exceptions are always chained as `__cause__`. | [§6 Errors](#6-errors) |
| A7 | Every item carries an `etag`, real or synthetic (vdirsyncer's contract). Every collection answers `changes(token)`, natively or by emulation. | [§7 Change detection](#7-change-detection) |
| A8 | The escape hatch is `.native` on every object, typed per backend, plus `native_status` / `native_priority` on tasks. | [§8 The escape hatch](#8-the-escape-hatch) |
| A9 | Fields RFC 5545 lacks go to RFC 9253 or the tasks draft, then `X-PYCAL-*`. | [§3.6 Properties with no standard home](#36-properties-with-no-standard-home) |

---

## 1. Layers and modes

```
Workspace ──< Backend ──────< Collection ──────────< item: Event | Task | Journal
(config,      (one store:      (calendar, task list,  (plain data over
 fan-out)      server, dir,     repo, directory,       icalendar.Calendar)
               file, feed)      feed)
```

- **Workspace** — a set of backends, usually all the ones a configuration
  file ([roadmap 1.4](ROADMAP.md#14-configuration-and-credentials)) lists,
  and operations that fan out across them. Optional: a caller with one
  server never needs it.
- **Backend** — one configured store with its credentials, if any: a
  CalDAV principal, a Gitea instance and token, a directory root, a feed
  URL. Owns the HTTP session where there is one. Its class says which kind
  (`CalDAVBackend`, `FilesBackend`, `GiteaBackend`); `kind` says the same as
  a string.
- **Collection** — the unit that holds items: a CalDAV calendar, a directory
  of `.ics` files or a single `.ics` file, a feed, a JMAP calendar, a Gitea
  repository. Owns the capability table.
- **Item** — `Event`, `Task` or `Journal`, sharing a base class
  `CalendarObject`. One item is one iCalendar object resource: all
  components with one `UID` (the master and its overridden occurrences).

"Collection" rather than "Calendar" because a Gitea repository is not a
calendar, and a CalDAV user loses nothing by the word. "Task" rather than
caldav's "Todo" because the trackers say task or issue, and only iCalendar
says to-do.

"Backend" rather than "Account" or a per-backend "Client" (as in caldav's
`DAVClient`), because a directory or a single `.ics` file has neither an
account nor a server to be a client of. The cost is that "backend" now
names both the kind (the CalDAV backend) and an instance of it (this
`CalDAVBackend` pointed at that server). In practice the class name carries
the kind and the variable carries the instance, and the [roadmap 1.2](ROADMAP.md#12-abstract-base-classes-and-the-backend-conformance-suite) ABC that a
backend author subclasses is the same `Backend`, so there is one word for
it instead of two. The aggregator is a `Workspace`: "client" is an HTTP
word that could mean anything, and a workspace is everything you have
configured (chosen by the author, 2026-10-09; see
[§10 Open questions](#10-open-questions), Q2).

### 1.1 Sync and async

Under p4 the async classes are the source and the sync classes are
generated. The public names follow httpx's pattern: `Workspace` / `AsyncWorkspace`,
`Backend` / `AsyncBackend`, `Collection` / `AsyncCollection`, all importable
from `calendaring`. That costs one replacement-map entry per class in [roadmap 1.3](ROADMAP.md#13-syncasync-scaffolding)'s
generator (unasync would otherwise produce `SyncWorkspace`), which [roadmap 1.3](ROADMAP.md#13-syncasync-scaffolding) already
lists.

**Items are not generated and have no async twin (A1).** They do no I/O.
`task.complete()` does not exist; `collection.complete(task)` does. Reasons:

1. **One `Task` type in both modes.** A helper that formats or validates a
   task works for sync and async callers alike. With mode-specific items
   (`Task`, `AsyncTask`) every such helper is written twice, or typed
   against a protocol, which is the duplication [roadmap 0.2](ROADMAP.md#02-syncasync-architecture) existed to avoid.
2. **No back reference to an I/O object inside data.** caldav's
   `CalendarObjectResource` holds its client; that is how its dual-mode
   methods came to return `Self | Coroutine`, the "annotations that lie"
   that [roadmap 0.2](ROADMAP.md#02-syncasync-architecture) started from.
3. **Items can be built before there is anywhere to put them**
   (`Task.new(summary=...)`), compared, copied and pickled, and moved to
   another backend without dragging a session along.
4. **The cache-then-sync backends (local files, [roadmap 2.2](ROADMAP.md#22-local-icalendar-file-backend)) fit it naturally.**

The cost is familiarity: a caldav user writes `todo.complete()` and
`event.save()`; here it is `cal.complete(todo)` and `cal.save(event)`. The
method names are kept from caldav where the meaning is the same, so the
change is in where the method lives, not what it is called.

Lifecycle: `Workspace` and `Backend`, which own sessions, are context
managers (`with` / `async with`) and have `close()`, awaited in async mode.
A `Collection` is a cheap handle onto its backend's session and has none. The name is `close` in both modes, not
`aclose`, because unasync does not rewrite `aclose` ([sync/async comparison §9](SYNC_ASYNC_ARCHITECTURE.md#9-result-pagination-and-the-filesystem-backend)).

Iteration: `search` returns a list and has an `iter_search` twin that
returns an `Iterator` / `AsyncIterator`, for result sets too large to hold
at once. The other listing methods (`collections`, `tasks`, `events`,
`journals`) return lists; `changes()` returns its set in one piece. `async for` → `for` is in
unasync's table; [roadmap 0.2](ROADMAP.md#02-syncasync-architecture) did not probe it, so [roadmap 1.3](ROADMAP.md#13-syncasync-scaffolding) adds it to the freshness test.

---

## 2. The I/O classes

Signatures are given in their async form; the sync form is identical
without `async`/`await`. Types not defined here are in [§3 Items](#3-items)–[§7 Change detection](#7-change-detection).

### 2.1 Workspace

```python
class AsyncWorkspace:
    @classmethod
    def from_config(cls, path: str | Path | None = None, *, section: str | None = None) -> Self: ...
    def __init__(self, backends: Iterable[AsyncBackend] = ()) -> None: ...

    backends: Sequence[AsyncBackend]

    async def collections(self) -> MultiResult[AsyncCollection]: ...
    async def collection(self, name_or_id: str) -> AsyncCollection: ...   # NotFoundError, AmbiguousError
    async def search(self, searcher: Searcher | None = None, **filters: Any) -> MultiResult[CalendarObject]: ...
    # MultiResult[T]: dataclass with items: list[T], errors: Mapping[str, CalendaringError], raise_for_errors()
    async def close(self) -> None: ...
```

`from_config` is specified by [roadmap 1.4](ROADMAP.md#14-configuration-and-credentials); this document only fixes that it exists and returns
a workspace.

**Fan-out returns partial results.** `Workspace.collections` asks every
backend, and `Workspace.search` every collection, and both return a
`MultiResult` (a generic dataclass): `.items`, `.errors: Mapping[collection_id,
CalendaringError]`, and `.raise_for_errors()`, which raises an
`ExceptionGroup` (new in Python 3.11, which is the supported minimum: [D4](PRIOR_ART_AND_DECISIONS.md#d4-python-version-floor)) if any collection failed. One unreachable server
must not blank a calendar application's agenda, which is what a plain raise
would do; but the failure must not be silent either, and the caller decides
which matters. Async mode runs the collections concurrently with a
`TaskGroup`, in the hand-written per-mode layer ([sync/async comparison §9](SYNC_ASYNC_ARCHITECTURE.md#9-result-pagination-and-the-filesystem-backend)); sync mode runs
them in turn.

### 2.2 Backend

```python
class AsyncBackend:
    @classmethod
    async def connect(cls, url: str, *, username: str | None = None,
                      password: str | None = None, token: str | None = None,
                      kind: str | None = None, session: Any = None, **options: Any) -> AsyncBackend: ...

    id: str                      # stable, from config or derived from the URL
    kind: str                    # "caldav", "files", "feed", "jmap", "gitea", ...
    capabilities: Capabilities   # backend-level: create-collection, ...
    native: object               # see "The escape hatch"

    async def collections(self) -> list[AsyncCollection]: ...
    async def collection(self, name_or_id: str) -> AsyncCollection: ...
    async def create_collection(self, name: str, components: Iterable[Component] = (Component.EVENT,)) -> AsyncCollection: ...
    async def close(self) -> None: ...
```

- `connect` returns the subclass for the kind it picks from the URL when
  `kind` is not given:
  `file:` or a path → files; `webcal:` → feed (fetched as `https:`, [prior art
  Part 2](PRIOR_ART_AND_DECISIONS.md#part-2-standards)); `http(s):` → probe, which is [roadmap 2.3](ROADMAP.md#23-icalendar-feed-backend-read-only-http)'s "feed or CalDAV" detection;
  RFC 6764 discovery for a bare domain comes from `caldav`. Trackers cannot
  be detected and need `kind=`.
- `session` is the caller-owned HTTP session that Home Assistant's
  `inject-websession` rule asks for ([prior art §1.4, Home Assistant](PRIOR_ART_AND_DECISIONS.md#14-home-assistant)). A backend that cannot use
  it raises `ConfigurationError` instead of silently making its own.
- Credentials are never required in the URL or in plain-text configuration
  ([roadmap 1.4](ROADMAP.md#14-configuration-and-credentials)'s keyring work); `connect`'s keyword arguments are for programmatic
  use.

### 2.3 Collection

```python
class AsyncCollection:
    id: str
    backend_id: str
    name: str | None
    color: str | None
    components: frozenset[Component]       # what it can hold; class Component(Enum): EVENT, TASK, JOURNAL
    capabilities: Capabilities
    native: object

    # reading
    async def search(self, searcher: Searcher | None = None, **filters: Any) -> list[CalendarObject]: ...
    def iter_search(self, searcher: Searcher | None = None, **filters: Any) -> AsyncIterator[CalendarObject]: ...
    async def tasks(self, **filters: Any) -> list[Task]: ...           # search(todo=True, ...)
    async def events(self, **filters: Any) -> list[Event]: ...
    async def journals(self, **filters: Any) -> list[Journal]: ...
    async def get(self, uid: str) -> CalendarObject: ...                # NotFoundError
    async def get_by_native_id(self, native_id: str) -> CalendarObject: ...
    async def reload(self, item: T) -> T: ...                           # fresh copy, new etag
    async def relatives(self, item: CalendarObject, reltype: str | None = None) -> list[CalendarObject]: ...

    # writing
    async def add(self, item: T, *, loss: LossPolicy | None = None) -> T: ...
    async def save(self, item: T, *, overwrite: bool = False, scope: Scope = Scope.THIS,
                   loss: LossPolicy | None = None) -> T: ...      # scope: occurrences only, §3.7
    async def delete(self, item: CalendarObject | str, *, overwrite: bool = False) -> None: ...
    async def complete(self, task: Task, at: datetime | None = None,
                       mode: Literal["safe", "this_and_future"] = "safe") -> Task: ...
    def wrap(self, native_item: object) -> CalendarObject: ...         # no I/O; see "The escape hatch"
    async def uncomplete(self, task: Task) -> Task: ...
    async def move(self, item: T, target: AsyncCollection) -> T: ...

    # change detection
    async def changes(self, token: SyncToken | None = None) -> ChangeSet: ...

    async def delete_collection(self) -> None: ...
```

**`add` creates, `save` updates.** `add` fails with `AlreadyExistsError` if
the UID is taken (CalDAV `If-None-Match: *`). `save` sends the item's `etag`
as a precondition and fails with `ConflictError` if the stored object has
changed since it was read; `overwrite=True` drops the precondition. caldav's
`save()` that does either is convenient and is how lost updates happen; the
split costs one method name.

**Writes return the stored item, and the caller must use it.** The returned
copy has the new `etag`, and on a backend that cannot store a
caller-chosen UID (Gitea, [§3.2 Identity](#32-identity)) a different `uid` and a `native_id`. The
argument is not mutated.

**`complete`** is an I/O method because completing a recurring task may
write two objects: caldav's "safe" mode completes a copy of the occurrence
and moves the master's `DTSTART`. The modes are caldav's, with one
exception: caldav guesses that an `RRULE` without `BY*` parts means "an
interval after the actual completion" (org-mode's `.+1w`). That reads into
`RRULE` something the RFC does not say, and is dropped. The next start
follows the `RRULE`, and the interval-from-completion behaviour applies only
when an `X-` property asks for it
([recurring-ical-events issue 292](https://github.com/niccokunzmann/python-recurring-ical-events/issues/292)).
Where that logic should live is
[§10 Open questions](#10-open-questions), Q3.

**`relatives`** fetches the objects an item's `RELATED-TO` points at (and,
for `PARENT`, the children pointing back), as caldav's `get_relatives()`
does. plann calls it 16 times, so it has to be here. Relatives outside
this collection are looked up across the backend.

**`move`** within one backend uses its own move where it has one
(CalDAV `MOVE`); between backends it is `add` to the target, then `delete`
from the source, declared `EMULATED` because it is not atomic: a failure
between the two leaves the item in both places, never in neither.

**How it fits Gitea:** a repository is a collection with `components =
{TASK}`; `events()` returns an empty list rather than raising (there are
none), `add(Event(...))` raises `UnsupportedError(Feature.COMPONENT_EVENT)`.

---

## 3. Items

### 3.1 The base: a typed view over iCalendar

```python
class CalendarObject:
    icalendar: icalendar.Calendar       # the whole VCALENDAR, VTIMEZONEs included
    component: icalendar.Component      # the master (or the occurrence, see is_occurrence)

    uid: str
    native_id: str | None               # backend's own id; None until stored
    etag: str | None                    # real or synthetic (see "Change detection"); None until stored
    collection_id: str | None
    native: object | None               # see "The escape hatch"

    summary: str | None
    description: str | None
    categories: list[str]
    relations: list[Relation]           # RELATED-TO; Relation(uid: str, reltype: str = "PARENT"), RFC 9253 RELTYPE
    attendees: list[Attendee]           # ATTENDEE; on a task, its assignees (see "Task")
    organizer: Attendee | None          # ORGANIZER
    created: datetime | None
    last_modified: datetime | None

    is_occurrence: bool                 # True when produced by search(expand=True)
    recurrence_id: date | datetime | None

    def copy(self) -> Self: ...
```

Per [D6](PRIOR_ART_AND_DECISIONS.md#d6-canonical-in-memory-model) the `icalendar` object is the storage, and the attributes read and
write through to it. **They delegate to `icalendar`'s own typed
properties** — `Todo.DUE`, `Todo.start`, `Todo.duration`, `uid`,
`categories`, the `Event`/`Todo`/`Journal.new()` constructors — which
`icalendar` 6–7 already provides; this library adds only what it lacks
([§3.4 Task](#34-task), [§3.6 Properties with no standard home](#36-properties-with-no-standard-home)). There is one source of truth, so a caller who edits
`item.icalendar` directly sees the change in the typed attributes and vice
versa, and properties the library does not model survive a round trip
untouched (a conformance test proposed in [prior art Part 2](PRIOR_ART_AND_DECISIONS.md#part-2-standards)).

Constructors: `Task.new(summary=..., due=..., **properties)`, and
`Task.from_ical(data)`, `Task(icalendar_instance)`. The `uid` defaults to a
fresh UUID, as `icalendar.Todo.new` does.

### 3.2 Identity

Three concepts, following [survey 3.2](TASK_MODEL_SURVEY.md#32-dimension-by-dimension):

| | Meaning | CalDAV / files | Gitea |
|---|---|---|---|
| `uid` | the iCalendar `UID` | caller-chosen, round-trips | synthesised: `"{issue number}@{host}/{owner}/{repo}"`, stable but not caller-chosen |
| `native_id` | the backend's own key | the resource href | the issue number |
| foreign-id slot | can the backend persist the caller's UID? | — (UID is native) | no; Kanboard's `reference` would be one |

Two capabilities say which applies: `identity.client-uid` (the backend
stores the caller's UID as given) and `identity.foreign-id` (it can store it
in a side slot and find the item by it). Gitea declares both `UNSUPPORTED`:
a task added with UID `abc` comes back with the synthesised one, and
`get("abc")` raises `NotFoundError`. A caller that needs to recognise its
own items there has to keep the mapping itself. This is the place where a
sync tool built on this library learns that it cannot assume UIDs
round-trip, and the conformance suite asserts it.

### 3.3 Event and Journal

```python
class Event(CalendarObject):
    start: date | datetime | None       # DTSTART
    end: date | datetime | None         # DTEND, or DTSTART + DURATION
    duration: timedelta | None
    all_day: bool
    location: str | None
    rrule: icalendar.vRecur | None

class Journal(CalendarObject):
    start: date | datetime | None       # DTSTART
```

Deliberately thin: everything else is reachable through `component`. The
funded backends do not need more, and each typed attribute is a promise
that every backend's mapper handles it.

### 3.4 Task

Incorporates [survey Part 4](TASK_MODEL_SURVEY.md#part-4-a-proposed-task-model).

```python
class TaskStatus(StrEnum):              # values are the iCalendar strings
    PENDING = "PENDING"                 # tasks draft
    NEEDS_ACTION = "NEEDS-ACTION"
    IN_PROCESS = "IN-PROCESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"                   # tasks draft

class Task(CalendarObject):
    status: TaskStatus                  # STATUS; NEEDS_ACTION when absent
    native_status: str | None           # see "Native passthrough"
    priority: int                       # PRIORITY, 0-9, 0 = undefined, 1 = highest
    native_priority: str | None         # see "Native passthrough"
    percent_complete: int | None        # PERCENT-COMPLETE

    start: date | datetime | None       # DTSTART: earliest sensible start (tasks draft reading)
    due: date | datetime | None         # DUE, or DTSTART + DURATION
    completed: datetime | None          # COMPLETED
    planned_start: datetime | None      # X-PYCAL-PLANNED-START
    planned_end: datetime | None        # X-PYCAL-PLANNED-END

    duration: timedelta | None          # derived: DUE - DTSTART; see set_duration()
    estimate: timedelta | None          # ESTIMATED-DURATION (tasks draft)
    # time_log, time_spent: added by roadmap 1.6

    parent: str | None                  # convenience over relations: the PARENT uid
    depends_on: list[str]               # convenience: DEPENDS-ON uids
    rrule: icalendar.vRecur | None

    def set_duration(self, duration: timedelta, keep: Literal["start", "due"] = "due") -> None: ...
```

Decisions in it, each from the survey:

- **`DTSTART` means earliest sensible start.** That is the tasks draft's
  reading and the first in the survey's table; the other senses the survey
  found (planned start, expected completion) get their own fields instead
  of overloading it. Actual start comes from the time log ([roadmap 1.6](ROADMAP.md#16-time-tracking-model-and-api)), not from a
  field.
- **`duration` is derived, not stored.** On a task, `DURATION` is either
  `DUE − DTSTART` or a misused estimate. `task.duration` reads
  `DUE − DTSTART` (or `DURATION` when only that is present), and
  `task.set_duration(d, keep="due" | "start")` moves the other end, as
  caldav's `set_duration(movable_attr=…)` does; plann uses both. The
  default keeps `DUE`, as caldav's does, because a deadline is more often
  fixed than a start. The
  estimate is `estimate` (`ESTIMATED-DURATION`), never `duration`.
- **`remaining` is left out** ([survey §4.4](TASK_MODEL_SURVEY.md#44-details-to-be-decided-later)). Two of the nine systems carry
  it, neither is a funded backend, and every typed field is a mapping
  obligation on every backend. It is reachable through the escape hatch on
  the backends that have it, and can be added later without breaking
  anything.
- **`priority` is iCalendar's 0–9.** The survey found five incompatible
  scales; the mapping to each is the backend's, documented as lossy.
  plann's semantics for 1–9 sit on top of this and are plann's.
- **Assignees are the task's `attendees`**, defined on the base class
  because events have them too. The tasks draft (section 6) says it in so
  many words: "Tasks are assigned to actors using one or more RFC5545
  'ATTENDEE' properties and/or one or more RFC9073 'PARTICIPANT'
  calendar components." So the standard has no gap here, and no `X-`
  property is needed. What looks like a gap is that a tracker knows a
  login (`alice`), while `ATTENDEE` takes a calendar address. A calendar
  address is any URI, not only `mailto:` (RFC 5545 §3.3.3), so the Gitea
  mapper writes the user's profile URL:
  `ATTENDEE;CN=Alice:https://gitea.example.com/alice`. That is valid,
  unique, resolvable, and round-trips, with no fake e-mail address. Mapping
  logins to and from those URIs is the backend's job, and
  `task.assignees` is not a separate field, to avoid two names for one
  thing.

  ```python
  @dataclass
  class Attendee:
      address: str                      # the CAL-ADDRESS URI: mailto:, https:, ...
      name: str | None = None           # CN
      role: str | None = None           # ROLE
      status: str | None = None         # PARTSTAT, including the tasks draft's FAILED
  ```

### 3.5 Native passthrough

`native_status` and `native_priority` are a plain `str | None`, set by the
backend that read the item, and **not serialised into the iCalendar
data** — a Kanboard column name means nothing to a CalDAV server. The rule
that makes them round-trip: setting `status` (or `priority`) clears the
native value. On save, a backend that sees a native value uses it; one that
sees `None` maps the normalised value. So a card read from the "Review"
column (normalised `IN_PROCESS`) and saved unchanged stays in "Review", and
one that the caller sets to `COMPLETED` goes wherever the backend maps
`COMPLETED`.

This answers [survey §4.4](TASK_MODEL_SURVEY.md#44-details-to-be-decided-later)'s question "plain string or typed object": a plain
string. Legal transitions (RT, OpenProject) are reachable through `native`
and are not part of the model.

### 3.6 Properties with no standard home

[D6](PRIOR_ART_AND_DECISIONS.md#d6-canonical-in-memory-model) sets the order: an RFC 5545 property; then RFC 9253 or the tasks draft;
then an `X-` property under one documented prefix. **The prefix is
`X-PYCAL-`**, after the project's name, [pycal.org](https://pycal.org)
(the GitHub organisation is `pycalendar` only because `pycal` was taken),
not `X-CALENDARING-`:

- `plann` and the other pycal tools will write the same properties, and a
  project prefix is not wrong for them;
- the package name may change (see the top of this document), and once
  written into users' calendars a prefix cannot.

In this document: `X-PYCAL-PLANNED-START`, `X-PYCAL-PLANNED-END`.
[roadmap 1.6](ROADMAP.md#16-time-tracking-model-and-api) adds its own. Each gets a line in a
registry table in the user documentation ([roadmap 4.1](ROADMAP.md#41-documentation-structure-and-api-reference)), with the standard property
that would replace it if one appears.

### 3.7 Recurrence

**Words.** A *recurring* object is one with an `RRULE` or `RDATE`. An
*occurrence* is one instance of it: the Wednesday 10:00 meeting on one
particular Wednesday, identified by its `RECURRENCE-ID`. RFC 5545 calls an
occurrence a "recurrence instance", and caldav calls it a "recurrence"
(`save(only_this_recurrence=…)`). This document says "occurrence" because
"recurrence" also means the repetition itself (the rule, "the recurrence
set"), and the two senses get mixed up.

`search(..., expand=True)` returns occurrences: items with `is_occurrence`
set and `recurrence_id` filled in, expanded by `recurring_ical_events` via
`icalendar-searcher`.

**Editing one occurrence works as it does in caldav.** `save(occurrence)`
fetches the master, inserts or replaces the override component for that
`RECURRENCE-ID`, bumps `SEQUENCE` and saves the whole object. That is what
caldav's `save(only_this_recurrence=True)`, its default, does, and what the
recurring-ical-events user guide shows ("Edit one event of an existing
series"). `save(occurrence, scope=Scope.ALL)` (`class Scope(Enum)` with
`THIS`, `ALL` and `THIS_AND_FUTURE`; default `THIS`) applies the change to the
master instead, which is caldav's `all_recurrences=True`. The merge is
`icalendar` manipulation with no I/O, so it works the same on every backend
that stores `RRULE` (`recurrence` capability). Backends that do not
(Gitea) never produce occurrences.

**Not supported: "this and future" for events**, which splits a series in
two. caldav does not offer it either, `ical`'s `store.py` is the reference
for it ([prior art §1.3, `ical`](PRIOR_ART_AND_DECISIONS.md#13-ical-allen-porter)),
and by [D1](PRIOR_ART_AND_DECISIONS.md#d1-packaging-principle) it belongs in a
package of its own. `save(occurrence, scope=Scope.THIS_AND_FUTURE)` raises
`UnsupportedError(Feature.RECURRENCE_EDIT_THIS_AND_FUTURE)` until one exists.

**Completing one occurrence of a recurring task** is `complete(task,
mode=...)` with caldav's two modes, `safe` and `this_and_future`. (caldav
declares `"this_and_future"` but only accepts `"thisandfuture"`: it looks
up `_complete_recurring_<mode>`, and that method is spelled
`_complete_recurring_thisandfuture`. The CalDAV backend passes the working
spelling, and the mismatch is reported as
[caldav issue 735](https://github.com/python-caldav/caldav/issues/735).)
([§2.3 Collection](#23-collection)). Where that code should live is
[§10 Open questions](#10-open-questions), Q3.

[§9 Migrating from caldav](#9-migrating-from-caldav) compares the whole of
caldav's API with this one.

---

## 4. Search

```python
await cal.search(todo=True, start=..., end=..., expand=True)

s = Searcher(todo=True, include_completed=False)
s.add_property_filter("CATEGORIES", "work")
s.add_sort_key("DUE")
await cal.search(s)
```

The keyword form builds a `Searcher` from its constructor fields (`todo`,
`event`, `journal`, `start`, `end`, `alarm_start`, `alarm_end`,
`include_completed`, `expand`), as caldav's `search()` does. Anything more
goes through a `Searcher` object. There is no wrapper: the type is
`icalendar_searcher.Searcher`, imported from there, so caldav's
`CalDAVSearcher` subclass works as is.

**The rule (A3):** a backend translates as much of the searcher as it can
into a server-side query, and the generic layer then runs
`searcher.filter()` over everything the server returned. A server-side
query may therefore over-match but never under-match, and the result is the
same whatever the server did. The conformance suite tests exactly this: the
same data and searcher against each backend, the same answer. caldav's
`CalDAVSearcher` already works this way for CalDAV (server query, client
post-filter); [roadmap 2.1](ROADMAP.md#21-caldav-backend) keeps it.

The cost is bandwidth when a server filters badly, and it is the right
trade: a filter that behaves differently per backend is the problem this
library exists to remove. A caller who knows better uses the escape hatch.

Consequences:

- **Sorting** is done client-side by the searcher, so a sorted `search`
  reads every page before returning. `iter_search` with sort keys does the
  same before yielding the first item; without sort keys it streams.
- **Tracker-native filters** (Gitea milestone, assignee by login) are not
  in the searcher's vocabulary. They are reachable through the escape hatch
  until the searcher grows a way to express them.
- **No `limit` / `offset`.** `Searcher` has none, and a limit applied
  before the client-side filter would be wrong. `iter_search` is the way to
  stop early.
- **Naive datetimes are local time**, as `icalendar-searcher` assumes.

**Risk:** the README of `icalendar-searcher` says that `filter`,
`filter_calendar` and `sort_calendar` are AI-generated and covered only by
AI-generated tests. caldav uses `check_component` and `sort`. The
post-filter needs these methods to be trustworthy, so a thorough review of
them, and the removal of the disclaimers, is requested in
[icalendar-searcher issue 15](https://github.com/pycalendar/icalendar-searcher/issues/15). Until that is done,
[roadmap 1.2](ROADMAP.md#12-abstract-base-classes-and-the-backend-conformance-suite)
builds the post-filter on `check_component`.

**How it fits Gitea:** its issue search API takes state, labels, a
milestone and a since-timestamp. The backend translates `todo=True,
include_completed=False` into `state=open` and `CATEGORIES` into labels,
fetches, and lets the searcher do the rest. Date ranges are client-side
only, and declared so (`search.time-range: EMULATED`).

---

## 5. Capabilities

### 5.1 The table

```python
class Support(Enum):
    FULL = "full"                # works, no information lost
    LOSSY = "lossy"              # works, but a value is mapped or truncated
    EMULATED = "emulated"        # done client-side; same result, more I/O or not atomic
    UNSUPPORTED = "unsupported"  # raises UnsupportedError
    UNKNOWN = "unknown"          # not probed; the operation is attempted

@dataclass(frozen=True)
class Capability:
    level: Support
    details: Mapping[str, Any] = field(default_factory=dict)  # how it is supported; keys per feature
    note: str | None = None               # free text for the capability matrix

class Capabilities(Mapping[Feature, Capability]):
    def supports(self, feature: Feature, *, allow_lossy: bool = False) -> bool: ...  # the boolean view
    def level(self, feature: Feature) -> Support: ...                              # the string view
    def details(self, feature: Feature) -> Mapping[str, Any]: ...                  # the full view
```

**A yes/no answer is not enough, and neither is a level alone.** That is
caldav's experience with its compatibility matrix, where a value is a
boolean, a string or a dict, and helper methods reduce a dict to a boolean
or a string for code that only cares about that. This is the same idea with
a fixed shape. Every entry has a level, which callers branch on, and an
optional `details` mapping for how a feature is supported. For example:

| Feature | Level | `details` |
|---|---|---|
| `task.priority` on Taskwarrior | `LOSSY` | `{"values": [1, 5, 9]}` (H/M/L) |
| `task.status` on Gitea | `LOSSY` | `{"values": ["NEEDS-ACTION", "COMPLETED"]}` |
| `changes` on CalDAV without sync-token | `EMULATED` | `{"method": "etag-listing"}` |
| `search.time-range` on a CalDAV server that ignores it for tasks | `EMULATED` | `{"components": ["VEVENT"]}` |

In configuration files a capability can be given in the same three shapes
caldav accepts, `true`/`false`, a level string, or a dict with `level` and
the details, and is normalised to a `Capability` on load. The details keys
are documented per feature, so the capability matrix (roadmap 4.3) can
print them, and the conformance suite can use them. For example, it
asserts that a `LOSSY` priority comes back as one of the declared `values`.

`Feature` is a `StrEnum` with dotted values, so that it can be written
in configuration files and in the generated capability matrix ([roadmap 4.3](ROADMAP.md#43-backend-capability-matrix)). The
initial set:

| Feature | Meaning |
|---|---|
| `write` | create, update and delete items at all |
| `component.event`, `component.task`, `component.journal` | can hold that component |
| `create-collection`, `delete-collection` | backend-level |
| `search.server-side`, `search.time-range`, `search.text` | how much the server filters; never affects results ([§4 Search](#4-search)) |
| `changes` | `changes()`: `FULL` with a native token, `EMULATED` by listing |
| `write.conditional` | `FULL` with an atomic precondition (ETag, `content_version`); `EMULATED` read-compare-write |
| `identity.client-uid`, `identity.foreign-id` | [§3.2 Identity](#32-identity) |
| `properties.passthrough` | unknown properties and components survive a round trip |
| `recurrence`, `recurrence.edit-this-and-future` | stores `RRULE`; [§3.7 Recurrence](#37-recurrence) |
| `move` | [§2.3 Collection](#23-collection) |
| `task.status`, `task.priority`, `task.percent-complete` | `LOSSY` when values are mapped |
| `task.start`, `task.due`, `task.completed`, `task.planned`, `task.estimate` | |
| `task.relations.parent`, `task.relations.depends-on` | |
| `categories`, `attendees` | for every component; on a task, attendees are its assignees |

[roadmap 1.6](ROADMAP.md#16-time-tracking-model-and-api) adds `task.time-log` and friends. The list is closed per release: the
conformance suite iterates over `Feature`, and a backend's declaration must
cover every member (missing = test failure, not a silent default).

It is a table rather than an `IntFlag` like Home Assistant's, because a
flag is yes/no and the survey's most common answer is "yes, lossily". It has
fewer levels than caldav's `FeatureSet`, which describes *servers* (including
fragile, broken and ungraceful ones) for the client's workarounds. The CalDAV
backend derives this table from caldav's: `full`/`quirk` → `FULL`; anything
caldav works around client-side → `EMULATED`; `unsupported`, `broken`,
`ungraceful` → `UNSUPPORTED`; `fragile`, `unknown` → `UNKNOWN`.

`UNKNOWN` exists because most CalDAV servers have never been probed, and a
library that refused anything unprobed would be unusable against them.
Non-CalDAV backends are code, not servers, and the conformance suite
rejects `UNKNOWN` from them.

### 5.2 Where it lives

On each collection, and on each backend for the backend-level features. A
collection can narrow its backend's (a feed is read-only; one CalDAV
calendar takes only `VTODO`), never widen it.

### 5.3 What happens when the caller asks for something unsupported

Three cases, matching the roadmap's "raise, degrade, or emulate":

- **Unsupported operation → raise, before I/O.** `UnsupportedError`
  carries the `Feature`. Checked at the boundary, as Home Assistant does
  with its service-call validation, so nothing is half done.
- **Lossy write → depends on `LossPolicy`** (`class LossPolicy(Enum)`:
  `RAISE`, `WARN`, `ALLOW`), **default `RAISE`.** The backend's
  mapper runs before the write is sent and returns a list of what it could
  not store (a priority of 3 on a backend with three levels, a fourth
  status, a `DEPENDS-ON` to Gitea's API version without dependencies).
  `RAISE` raises `LossyWriteError` with that list and sends nothing; `WARN`
  emits `LossyWriteWarning` and writes; `ALLOW` writes. The policy is set
  per workspace or backend and can be overridden per call (`loss=`). Default
  `RAISE` because the alternative is the Home Assistant failure ([prior art §1.4, Home Assistant](PRIOR_ART_AND_DECISIONS.md#14-home-assistant)): `IN-PROCESS` silently becoming `needs_action`. A warning is also
  what [roadmap 1.3](ROADMAP.md#13-syncasync-scaffolding)'s `-W error` test runs turn back into a failure.
- **Emulation → automatic, only when indistinguishable.** Client-side
  filtering, change listing and cross-backend move are emulated without
  asking, because the caller gets the same answer ([§4 Search](#4-search)) or a documented
  weaker guarantee (`write.conditional` emulated has a race window). No
  emulation that changes a result is ever automatic.

What the library cannot catch: a server that declares `UNKNOWN` and then
silently drops a property. caldav's hints call that `unsupported`; only a
probe (caldav-server-tester) or a read-back finds it. A `verify=True` on
`save` that reloads and compares is possible and cheap to add; it is left
out until someone needs it ([§10 Open questions](#10-open-questions), Q4).

---

## 6. Errors

```
CalendaringError
├── ConfigurationError            # roadmap 1.4; also a session the backend cannot use
├── AuthenticationError           # 401, bad token
│   └── AuthorizationError        # 403
├── NotFoundError                 # also a LookupError
├── AmbiguousError                # a name matched several collections
├── ConflictError                 # precondition failed: changed since read
│   └── AlreadyExistsError        # add() with a UID already present
├── UnsupportedError              # carries .feature
│   └── LossyWriteError           # carries .losses
├── InvalidDataError              # the backend rejected the data, or it does not parse; also a ValueError
├── RateLimitError                # carries .retry_after: float | None
└── BackendError                  # anything else from the backend or transport
    └── TransportError            # network, TLS, timeout

CalendaringWarning
└── LossyWriteWarning
```

- Every error carries `.backend` and, where known, `.collection_id`.
- **The native exception is always `__cause__`** (`raise … from exc`), so
  a caller can reach `caldav.lib.error.DAVError` or an HTTP response
  without the hierarchy pretending it does not exist.
- `NotFoundError` is also a `LookupError` and `InvalidDataError` a
  `ValueError`, so generic code that catches the built-ins still works.
- `RateLimitError` is raised, not retried. Retrying belongs to the
  hand-written per-mode layer ([roadmap 0.2](ROADMAP.md#02-syncasync-architecture): `asyncio.sleep` must not be in
  `_async/`), and whether it retries is a workspace option ([roadmap 1.4](ROADMAP.md#14-configuration-and-credentials)).
- Fan-out ([§2.1 Workspace](#21-workspace)) does not raise; `MultiResult.raise_for_errors()` raises an `ExceptionGroup` of these.

caldav's errors map one to one where they overlap:
`NotFoundError` → `NotFoundError`, `ETagMismatchError` and
`ScheduleTagMismatchError` → `ConflictError`,
`AuthorizationError` → `AuthenticationError` or `AuthorizationError` by
status code, `RateLimitError` → `RateLimitError`, other `DAVError` →
`BackendError`.

---

## 7. Change detection

Adopts vdirsyncer's contract ([prior art §1.2, vdirsyncer](PRIOR_ART_AND_DECISIONS.md#12-vdirsyncer-khal-and-todoman)), extended to collections.

**Every stored item has an `etag`**, real or synthetic:

| Backend | `etag` | `write.conditional` |
|---|---|---|
| CalDAV | the server's ETag | `FULL` (`If-Match`) |
| files, vdir | `f"{st_mtime_ns};{st_ino}"` | `EMULATED`: compare, then atomic rename |
| files, single `.ics` | hash of the item's serialisation | `EMULATED` |
| feed | hash of the item's serialisation | n/a (read-only) |
| JMAP | the object's state | per `calendaring-jmap` |
| Gitea | `content_version`, plus `updated_at` | `FULL` for the body, `EMULATED` for the rest ([§10 Open questions](#10-open-questions), Q6) |

**Every collection answers `changes(token)`:**

```python
@dataclass(frozen=True)
class ChangeSet:
    changed: list[CalendarObject]       # new or modified since token
    deleted: list[str]                  # uids
    token: SyncToken                    # SyncToken = NewType("SyncToken", str); opaque, persist it and pass it back

cs = await cal.changes()                # everything, plus a token
cs = await cal.changes(cs.token)        # what changed since
```

- CalDAV: RFC 6578 sync-token where the server supports it (`FULL`),
  otherwise emulated by caldav from an ETag listing.
- Files: the token is a compact encoding of `{uid: etag}`; changes are a
  re-scan diffed against it (`EMULATED`).
- Feed: HTTP `ETag`/`Last-Modified` short-circuits "nothing changed";
  otherwise a diff of item hashes, as for files.
- Gitea: `since=` on the issues API finds changed items; finding *deleted*
  ones needs a listing of all ids, so `EMULATED`.

A token is valid only for the collection that issued it. A token the
backend can no longer honour (CalDAV `valid-sync-token` precondition, a
files token from a different directory) raises `ConflictError`, and the
caller starts again with `changes()`.

For Gitea, `updated_at` is the weakest change signal in the survey. The
synthetic etag adds `content_version`, so "changed twice within the clock
resolution" is seen at least for the issue body; whether it covers other
fields is checked in roadmap 2.5 ([§10 Open questions](#10-open-questions), Q6).

---

## 8. The escape hatch

Every `Backend`, `Collection` and item has `.native`:

| Backend | `Backend.native` | `Collection.native` | item `.native` |
|---|---|---|---|
| CalDAV | `caldav.DAVClient` / `AsyncDAVClient` | `caldav.Calendar` | `caldav.CalendarObjectResource` |
| files | the root `Path` | the directory or file `Path` | the file `Path` |
| JMAP | `calendaring_jmap.JMAPClient` / `AsyncJMAPClient` | the calendar id | the JMAP object dict |
| Gitea | the base URL and an HTTP session | the repository dict from the API | the issue dict from the API |

The base classes type it `object`. Each backend's subclass narrows it
(`CalDAVCollection.native: caldav.Calendar`), so a caller who has checked
`isinstance(cal, CalDAVCollection)` gets a typed native object, and
`--verifytypes` ([D5](PRIOR_ART_AND_DECISIONS.md#d5-typing-strictness)) stays at 100 % without an `Any` in the public API.

Rules: the native object is the backend's own, and reading from it is
always safe. Writing through it bypasses this library's guarantees: no
capability check, no loss check, and the item's `etag` is stale afterwards,
so `reload()` it. The item's `native` is a snapshot from when it was read,
not a live handle.

The other direction also works: `collection.wrap(native_item)` turns a
backend object (a `caldav.Todo`, say) into this library's item, without
I/O. Together with `.native` that lets code use both libraries side by side,
which is what a migration needs
([§9 Migrating from caldav](#9-migrating-from-caldav)).

---

## 9. Migrating from caldav

What a caldav user keeps, what changes, and what is only reachable through
the escape hatch ([§8 The escape hatch](#8-the-escape-hatch)). Taken from
caldav's public API as of 2026-10-08 (caldav 3.4.0).

| caldav | calendaring | |
|---|---|---|
| `get_davclient()`, `get_calendar(s)()`, config file | `Backend.connect()`, `Workspace.from_config()` | changed; same config file ([config proposal](CONFIGURATION_PROPOSAL.md)) |
| `principal()`, `calendars()`, `make_calendar(supported_calendar_component_set=…)` | `backend.collections()`, `create_collection(components=…)` | same |
| `get_supported_components()` | `collection.components` | same |
| `search(…)`, `CalDAVSearcher` | `collection.search(…)` with a `Searcher` | same; caldav already post-filters client-side |
| `search(…, server_expand=True)` | not a caller choice; the backend decides, the result is the same | escape hatch |
| `get_object_by_uid()`, `event_by_uid()`, `todo_by_uid()` | `get(uid)` | same |
| `event_by_url()` | `get_by_native_id(href)` | same |
| `add_todo(summary=…)`, `save_todo(…)` | `add(Task.new(summary=…))` | changed: two steps |
| `obj.save()`, `no_overwrite`, `no_create` | `collection.save(obj)`, `collection.add(obj)` | changed: I/O moved, create and update split |
| ETag / Schedule-Tag preconditions on save | `etag` precondition, `ConflictError` | same; Schedule-Tag only through the escape hatch |
| `obj.load()`, `obj.delete()` | `collection.reload(obj)`, `collection.delete(obj)` | changed: I/O moved |
| `multiget()`, `load_by_multiget()` | used inside the backend | not a public call |
| `icalendar_instance`, `edit_icalendar_component()` (borrowing) | `item.icalendar`, `item.component` | simpler: items are plain data, nothing to borrow |
| `vobject_instance` | — | escape hatch (`item.native.vobject_instance`) |
| `data`, `wire_data` | `item.icalendar.to_ical()` | same |
| `search(expand=True)` | `search(expand=True)` | same |
| `save(only_this_recurrence=True)` (default) | `save(occurrence)` | same ([§3.7 Recurrence](#37-recurrence)) |
| `save(all_recurrences=True)` | `save(occurrence, scope=Scope.ALL)` | same |
| `save(only_this_recurrence=None / False)` | — | escape hatch |
| `expand_rrule(start, end)` on an object | `search(expand=True)`, or `recurring_ical_events` directly | changed |
| "this and future" for events | — | missing in both |
| `complete(handle_rrule=True, rrule_mode=…)` | `complete(task, mode=…)` | same modes; caldav's "interval from completion" guess is dropped |
| `complete()` on a recurring task, default `handle_rrule=False` | `complete(task)` handles the `RRULE` (`mode="safe"`) | **behaviour change**: caldav completes the whole series by default |
| `uncomplete()` | `collection.uncomplete(task)` | same |
| `is_pending()` | `task.status` | changed: no helper |
| `get_due()`, `get_duration()`, `set_duration(movable_attr=…)`, `get_dtend()`, `set_end()` | `task.due`, `task.duration`, `task.set_duration(keep=…)`, `event.end` | same, as attributes |
| `set_due(due, move_dtstart=…, check_dependent=…)` | `task.due = …` | **not yet**: `move_dtstart` and `check_dependent` |
| `set_relation()`, `get_relatives()` | `task.relations`, `collection.relatives()` | same |
| `check_reverse_relations()`, `fix_reverse_relations()` | — | **not yet** |
| `objects_by_sync_token()` | `collection.changes(token)` | same |
| `save_with_invites()`, `accept_invite()`, `decline_invite()`, `change_attendee_status()`, `schedule_inbox()`, `freebusy_request()` | `attendees`, `organizer` as data only | escape hatch; scheduling (iTIP) is outside the funded scope |
| `add_attendee()`, `add_organizer()` | `item.attendees.append(…)` | same, as data |
| `propfind()`, `proppatch()`, `report()`, `mkcol()`, `request()` | — | escape hatch (`backend.native`) |
| compatibility hints, `features:` profile | derived capabilities ([§5.1 The table](#51-the-table)); the profile stays in the config | same source |

The two **not yet** rows are pure logic plus a relatives lookup, and fit
in Phase 1 if plann needs them before roadmap 3.3. The behaviour change in
`complete()` is deliberate: completing a whole series because the caller
forgot a flag is the wrong default. caldav's own docstring says it may
make the flag mandatory.

### 9.1 A migration path for plann

plann is the first program that has to move (roadmap 3.3). In its
`plann/*.py` (`git grep -F` at plann 95fdab5, 2026-10-09) it calls
`get_relatives(` 16 times, `.save(` 13, `get_duration(` 9, `get_due(` 7,
`.complete(` 4 and `set_duration(` 4. A big-bang switch is not needed, because the two libraries
share their data model (`icalendar` objects) and the escape hatch goes
both ways:

1. **Connect through calendaring, keep calling caldav.** plann gets its
   collections from `Workspace.from_config()` (roadmap 1.4, which plann's
   credential work already waits for) and uses `collection.native`, a
   `caldav.Calendar`, everywhere else. Nothing else changes.
2. **Move the reads:** search, `get`, `relatives`. Where plann still holds
   caldav objects, `collection.wrap()` converts them.
3. **Move the writes:** `add`, `save`, `complete`, with the `complete()`
   default checked at every call site.
4. **What is left is the gap list.** Every remaining `.native` call is a
   row in the table above that plann needs, and either gets added here or
   stays as a deliberate CalDAV-only feature.

Progress is measurable: the number of `caldav` names plann uses directly.
For the duration, plann depends on both libraries, which it does anyway,
since calendaring depends on caldav.

---

## 10. Open questions

For the author and for peer review. Each has a proposed answer; none blocks
[roadmap 1.2](ROADMAP.md#12-abstract-base-classes-and-the-backend-conformance-suite) from starting.

1. **Items without I/O (A1)** is the largest departure from caldav. It is
   argued in [§1.1 Sync and async](#11-sync-and-async). *Author,
   2026-10-09: "I don't like it — but this is probably a necessary cost of
   getting the async/sync schism right."* Accepted unless a peer reviewer
   brings a better argument.
2. *Decided, 2026-10-09: `Workspace`.* **The name `Client`.** The author disliked it ("could mean anything")
   and suggested `CalendaringConfig`, `CalendaringCollection` and
   `Calendaring`. What the object is: a set of backends, usually loaded from
   configuration, with fan-out operations over them. The criteria: not an
   HTTP word (client, session, connection), says "several sources", and
   survives a package rename.

   | Name | Verdict |
   |---|---|
   | `Client` | an HTTP word, and says nothing about "several" |
   | `CalendaringConfig` | it does I/O, so it is more than a config |
   | `CalendaringCollection` | clashes with `Collection`, which means a calendar here |
   | `Calendaring` | reads well (`Calendaring.from_config()`), but breaks if the package is renamed |
   | `Session` | requests/SQLAlchemy usage, but clashes with the HTTP session a backend owns |
   | **`Workspace`** | "everything you have configured"; no clash; survives a rename |

   **Proposal: `Workspace`**, accepted by the author and applied
   throughout.
3. **Where recurring-task completion lives.** caldav's `complete(handle_rrule=…)`
   logic, and the occurrence merge behind `save(only_this_recurrence=…)`,
   are not CalDAV protocol logic, and by [D1](PRIOR_ART_AND_DECISIONS.md#d1-packaging-principle)
   do not belong in `caldav`. The files backend needs them too. The author
   does not want another package for a few hundred lines, and suggested
   `recurring_ical_events`, which already documents editing one occurrence;
   its maintainer asked for an issue with a proposed API. **Proposal:**
   [recurring-ical-events issue 292](https://github.com/niccokunzmann/python-recurring-ical-events/issues/292). Until it is settled, roadmap 2.1
   calls caldav's code, and roadmap 2.2 waits for the outcome rather than
   copying it. That means the CalDAV backend keeps caldav's "interval after
   completion" guess for an `RRULE` without `BY*` parts until then: a
   known deviation from [§2.3 Collection](#23-collection), listed in the
   capability matrix.
4. **`save(verify=True)`** ([§5.3 What happens when the caller asks for something unsupported](#53-what-happens-when-the-caller-asks-for-something-unsupported)): add now or when asked?
5. *Resolved, 2026-10-09:* assignees are `ATTENDEE`s with the tracker's
   profile URL as the calendar address; no `X-` property
   ([§3.4 Task](#34-task)).
6. **Gitea's `content_version`** covers the issue body; whether it also
   changes on label, state or due-date edits is checked in roadmap 2.5,
   against a Gitea run as a CI service container (the official image with
   SQLite needs a few hundred MB of RAM and no persistent host). This is a
   task for 2.5, not a question for the author. A permanent instance is only
   needed for dogfooding, and is optional.
7. **Feature granularity.** The list in [§5.1 The table](#51-the-table) is what the funded backends
   need. It is closed per release (adding one is a minor version, since
   every backend must declare it); whether that is too rigid for
   third-party backends is a question for after 1.0.
8. **The configuration file is shared by caldav, calendaring-jmap and this
   library.** Where should its parser live? A proposal for the team is in
   [CONFIGURATION_PROPOSAL.md](CONFIGURATION_PROPOSAL.md).

---

## 11. Peer review

Not started. The roadmap's warning applies: a review is a dependency on
someone else's calendar.

| Reviewer (role) | Why | What to ask |
|---|---|---|
| a maintainer of `icalendar` | [§3 Items](#3-items) builds on its typed properties; the [roadmap 4.5](ROADMAP.md#45-documentation-review-and-improvements) documentation contributor comes from there | [§3 Items](#3-items), [§3.6 Properties with no standard home](#36-properties-with-no-standard-home) |
| the author of `ical` and Home Assistant's calendar integrations (@allenporter) | the nearest existing multi-backend model, and the recurrence reference | [§1.1 Sync and async](#11-sync-and-async), [§5 Capabilities](#5-capabilities), [§3.7 Recurrence](#37-recurrence) |
| a `caldav` user with a large codebase on it | the cost of A1 | [§1.1 Sync and async](#11-sync-and-async), [§2.3 Collection](#23-collection) |
| `plann` (the author, as its maintainer) | the committed downstream consumer; [roadmap 1.6](ROADMAP.md#16-time-tracking-model-and-api) depends on [§3.4 Task](#34-task) | [§3.4 Task](#34-task), [§4 Search](#4-search) |
| a vdirsyncer/pimsync maintainer | [§7 Change detection](#7-change-detection) adopts their contract | [§7 Change detection](#7-change-detection) |

What the author needs to do: decide whom to approach, and send this
document, or [§10 Open questions](#10-open-questions) alone; the author's own review is done.

---

*Drafted with AI assistance (Claude Opus 5.5 via Claude Code) from the [roadmap 0.1](ROADMAP.md#01-task-and-issue-tracker-data-model)–[roadmap 0.3](ROADMAP.md#03-prior-art-standards-and-project-decisions)
documents and the source of `caldav`, `icalendar` and `icalendar-searcher` as
checked out on 2026-10-08 and 09. Reviewed by the author (see Status).*
