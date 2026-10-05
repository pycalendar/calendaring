# Prior art, standards and project decisions

**Roadmap item:** [0.3 Prior art, standards and project decisions](ROADMAP.md#03-prior-art-standards-and-project-decisions)
**Status:** drafted by Claude Opus 5.5 on 2026-09-24, updated on 2026-10-05
for 0.2's decision (p4) and re-checked against `caldav` and `calendaring-jmap`
— awaiting the author's review.
Every "decision" below is a *proposal*; none of them is settled until the author
says so.
**Deliverable:** this document

**Findings that need attention before anything else:**

1. **Licensing.** This repository has no `LICENSE` file. Two of its intended
   dependencies, `icalendar-searcher` and `calendaring-jmap`, are
   **AGPL-3.0-or-later**, and `caldav` — dual-licensed GPL-3.0-or-later *or*
   Apache-2.0 — has a hard dependency on `icalendar-searcher`. See [D3](#d3-licence).
2. **The name is already public.** [pycal.org](https://pycal.org) lists
   `calendaring-client` as a planned package, next to the sibling
   `calendaring-jmap` (on PyPI, 1.1.0) and an empty `calendaring-sync` repo. A
   `calendaring-*` family already exists, and that changes the naming question.
   See [D2](#d2-the-name).
3. **Home Assistant's CalDAV integration has no code owner** and pins
   `caldav==3.3.0a1`. That is an opening for outreach, not just an observation.
   See [§1.4](#14-home-assistant).

---

## Part 1: Prior art

### 1.1 icalcli

[icalcli](https://github.com/jrvarma/icalcli) (MIT, 1.1.6, last commit
2026-09-10) was read at source level. The whole program is about 3000 lines, and
1856 of them are the CLI module.

**The "pluggable backend" is duck typing plus a config file that runs Python.**
`~/.icalcli.py` is executed with `importlib` and must define a module-level
`backend_interface` object. The object is expected to have:

- `events` — a list of `icalendar` `VEVENT`s, fully loaded in memory
- `create_event(event, vtimezone)`, `update_event(event, vtimezone)`, `delete_event(uid)`
- `sync(vtimezone)` — flush to storage and reload
- optional attributes `readonly` and `sync_after_edit`, probed with `hasattr()`
  and defaulted by the caller

There is no base class, no protocol and no capability declaration beyond the two
`hasattr` probes. There are two backends: a single `.ics` file (read-only when
given a list of files, and prefixing UIDs with `File<n>:` so they don't collide)
and EteSync 1.0 and 2.0.

**What to take from it:**
- The *shape* is right: backends talk `icalendar` objects, and the front end
  never sees the wire format. That supports [D6](#d6-canonical-in-memory-model).
- The *cache-then-sync* model (edit an in-memory list, call `sync()` to write
  it back) is exactly what a local-file backend (2.2) needs, and exactly wrong
  for CalDAV. icalcli handles the mismatch with `sync_after_edit`. That flag is
  an untyped capability flag, and the lesson is that 1.1 needs a proper one.

**What not to take:**
- A config file that is executed as Python. It is convenient, but it is a code
  execution surface, and 1.4 should use a data format instead.
- Loading everything into memory. That is fine for one person's `.ics` file, and
  unworkable for a CalDAV server with ten years of history or an issue tracker
  with 10 000 issues.
- UID rewriting. Once a UID is prefixed it no longer round-trips.

The README's conclusion stands: icalcli is complementary, not competing. It is
also a possible *consumer*: its backend protocol is small enough that an adapter
from this library to it would be about fifty lines, and that would give icalcli
CalDAV support for free.

### 1.2 vdirsyncer, khal and todoman

[vdirsyncer](https://github.com/pimutils/vdirsyncer) (BSD-3-Clause, 0.21.0,
active) is the closest Python prior art for **a single storage abstraction over
several backends**. It has storage classes for CalDAV/CardDAV, a directory of
files (`filesystem`), a single `.ics` file (`singlefile`), a read-only HTTP feed
(`http`), Google, and an in-memory storage. Its `Storage` base class
(`vdirsyncer/storage/base.py`) is async-only since 0.19:

```
list() -> [(href, etag)]      get(href) -> (item, etag)     get_multi(hrefs)
upload(item) -> (href, etag)  update(href, item, etag)      delete(href, etag)
discover(), create_collection(), get_meta(key), set_meta(key, value)
```

**Why it matters here:** it has already solved roadmap 1.1's "change detection
across backends with no ETag" problem, and the solution is simple. *Every*
storage returns an etag, and backends without one synthesise it:

| Storage | Synthetic etag |
|---|---|
| `filesystem` | `f"{st_mtime_ns};{st_ino}"` — mtime plus inode, taken after an `fsync` on Windows |
| `singlefile` | a hash of the item's content |
| `http` | a hash of the item's content; an item with no `UID` gets its hash *as* the UID |

`update` and `delete` take the etag the caller last saw and raise
`WrongEtagError` if it has changed. That is optimistic concurrency everywhere,
at no cost to backends that have a real ETag. **Proposal for 1.1:** adopt this
contract as it is. For the local-file backend (2.2) the inode part matters,
because it catches atomic-rename writers that keep the same mtime.

vdirsyncer is a *sync* tool, not a library with a domain model. Its `Item` is a
raw string with a few parsed fields, and there is no concept of an event or a
task. Its successor, pimsync, is written in Rust.

**The vdir format** ([spec](https://vdirsyncer.pimutils.org/en/stable/vdir.html))
is a de-facto standard: one directory per collection, one iCalendar object per
file, the file name derived from the UID, and collection metadata in plain files
(`displayname`, `color`). **khal** (events) and **todoman** (`VTODO` tasks) both
operate on a vdir and cache it in SQLite. **Proposal for 2.2:** the local-file
backend should support *both* layouts, a vdir and a single multi-object `.ics`
file, because users have both and the conformance suite will catch any
difference in behaviour. todoman is also the nearest existing "tasks on local
files" CLI, and worth looking at when writing 2.2.

### 1.3 `ical` (Allen Porter)

[`ical`](https://github.com/allenporter/ical) (Apache-2.0, 14.2.0,
`requires-python >=3.11`, pydantic 2) is a second RFC 5545 implementation,
independent of the `icalendar` library. It matters because **Home Assistant uses
it for three integrations** — `local_calendar`, `local_todo` and
`remote_calendar` — and Google Calendar uses it too. The author of `ical` is the
code owner of all of them.

The interesting part is `ical/store.py`: `EventStore` and `TodoStore`, built on a
`GenericStore[T]`, implement **add / edit / delete for recurring objects with a
recurrence range** — "this instance", "this and future". That is the hardest
piece of editing logic in calendaring, and neither `caldav` nor `icalendar`
provides it. `ical/compat/` holds workarounds for broken data from real
producers.

**Implication:** when 1.1 defines how a caller edits one instance of a recurring
task, this code has already worked out the semantics and has the tests. Even if
the library standardises on `icalendar` (D6), `ical`'s store is the reference for
the semantics. It could not be a dependency without taking on a second parser
and pydantic.

### 1.4 Home Assistant

The README names Home Assistant as a target user. This is what its `dev` branch
looks like today (fetched 2026-09-24):

| Integration | Library | Code owner |
|---|---|---|
| `caldav` (calendar + todo) | `caldav==3.3.0a1`, `icalendar==6.3.1`, `vobject==0.9.9` | **none** |
| `local_calendar`, `local_todo` | `ical==14.2.0` | @allenporter |
| `remote_calendar` (iCal feed, silver quality) | `ical==14.2.0` | @Thomas55555, @allenporter |
| `google` | `gcal-sync`, `ical` | @allenporter |
| `todoist` | `todoist-api-python` | @boralyl |

**Home Assistant is itself a multi-backend calendar and task abstraction** —
about the same one this library proposes, one layer higher. Its own model is
prior art:

- `TodoItem`: `summary`, `uid`, `status`, `due` (a date or a datetime),
  `description`, and not much more.
- `TodoItemStatus` has **two values**, `needs_action` and `completed`. The
  CalDAV integration maps `IN-PROCESS` to `needs_action` and `CANCELLED` to
  `completed`, so the round trip loses information. This is the "lowest common
  denominator" risk in the roadmap, shown in production.
- Capabilities are an `IntFlag`, `TodoListEntityFeature`: `CREATE_TODO_ITEM`,
  `DELETE_…`, `UPDATE_…`, `MOVE_…`, `SET_DUE_DATE_ON_ITEM`,
  `SET_DUE_DATETIME_ON_ITEM`, `SET_DESCRIPTION_ON_ITEM`. Service-call fields are
  validated against the feature flag each one needs. This is a working, simple
  answer to 1.1's "capability declaration" item, and it is worth copying the
  idea: capabilities as flags, checked at the boundary.

**What HA would need from this library**, from its integration quality scale
(`script/hassfest/quality_scale.py`). All three rules are Platinum tier:

- `async-dependency` — the library must be async. HA's `caldav` integration
  wraps every call in `async_add_executor_job`. 0.2's decision, async-first
  source with a generated sync copy (p4), provides native async.
- `inject-websession` — the library must accept an HTTP session that HA owns
  (aiohttp). For backends that do their own HTTP (2.3, the feed backend) this
  is a requirement on 1.3's hand-written per-mode layer: it must accept a
  caller-owned session. For the backends that wrap another library it is not
  this library's to meet. Neither `caldav`'s `AsyncDAVClient` nor
  `calendaring-jmap`'s `AsyncJMAPClient` accepts a session today (both create
  their own, with niquests or httpx), and neither supports aiohttp. That is
  an issue to raise with both projects, early.
- `strict-typing` — the library must ship `py.typed` with complete types. D5
  below meets it.

**Proposal:** make the outreach concrete (4.4 already names HA as a
reviewer source). Offer to
become code owner of HA's `caldav` integration, which currently has none, and to
move it onto this library once 2.1 passes the conformance suite. A single
`calendaring` integration covering CalDAV, feeds and local files would overlap
with `remote_calendar` and `local_calendar`. That overlap is a social question
for @allenporter, not a technical one, and should be raised early and politely,
not presented as a finished replacement.

### 1.5 calendaring-jmap (the sibling)

[calendaring-jmap](https://github.com/pycalendar/calendaring-jmap)
(AGPL-3.0-or-later, 1.1.0, `>=3.10`, niquests) is the separately funded JMAP
package that 2.4 will wrap. Its shape:

- **Separate sync and async classes**: `JMAPClient` (2575 lines) and
  `AsyncJMAPClient` (1240 lines, as of 2026-10-05) on a shared
  `_JMAPClientBase`, with pure request builders and response parsers in
  `_methods/`. This is the hand-written "separate classes" option that 0.2
  rejected for duplicating every method, with a Sans-I/O-ish protocol layer
  underneath.
- Typing: `py.typed`, and CI runs plain `mypy --ignore-missing-imports`, not
  `--strict`.
- The API takes and returns **iCalendar strings** (`create_event(calendar_id,
  ical_str)`) and converts to and from JSCalendar internally (`convert/`).
- It has task methods (`get_task_lists`, `create_task`), even though JMAP for
  Tasks is an expired draft (§2).

**Implication for 2.4:** the backend will be an adapter over two ready-made
classes, not an instance of the 0.2 architecture. That is fine and expected.
The conformance suite is what keeps it honest. But it does mean that p4's rule —
one async-first source, the sync copy generated — applies to *this* library's
code, not to its backends' dependencies. In p4 terms the adapter's async half
wraps `AsyncJMAPClient`, and the generated sync half must end up calling
`JMAPClient`, which takes a replacement-map entry in 1.3's generator, just as
2.1 needs for `caldav`'s names.

### 1.6 Outside Python (not verified in this session)

For completeness, and **from general knowledge rather than source reading**: the
two long-lived desktop PIM stacks, GNOME's Evolution Data Server and KDE's
Akonadi, both solved "one API over CalDAV, local files, webcal feeds, Google,
Exchange". Both chose **iCalendar as the canonical in-memory model, with `VTODO`
for tasks**, and converted at the backend boundary. Thunderbird's calendar
providers (CalDAV, ICS, local storage) do the same. None of them models an issue
tracker. That is the part of this project with no prior art, which is why 0.1
and 2.5 carry the risk.

---

## Part 2: Standards

The status of each standard was checked on the IETF datatracker on 2026-09-24.
"Funded" means it is in scope for the 248 hours.

| Standard | Status | What it is to this library | Funded? |
|---|---|---|---|
| RFC 5545 iCalendar | RFC | the canonical data model (D6) | **yes** |
| RFC 7986 new iCalendar properties | RFC | `NAME`, `COLOR`, **`REFRESH-INTERVAL`**, `SOURCE` — the feed backend (2.3) should follow `REFRESH-INTERVAL` | **yes**, read side |
| RFC 9253 relationships | RFC | `LINK`, `CONCEPT`, `REFID`, extended `RELTYPE` — task dependencies (0.1) | **yes** |
| draft-ietf-calext-ical-tasks-17 | RFC Editor queue, "In Final Review" (2026-09-24) | `ESTIMATED-DURATION`, `VSTATUS`, new `STATUS` values — covered in the [task survey §1.2](TASK_MODEL_SURVEY.md) | **yes**, read + write `ESTIMATED-DURATION` |
| RFC 9074 VALARM extensions | RFC | acknowledge/snooze alarms | no — pass through untouched |
| RFC 9073 event publishing extensions | RFC | `PARTICIPANT`, `VLOCATION`, `STRUCTURED-DATA` | no — pass through untouched |
| RFC 7953 VAVAILABILITY | RFC | availability | no |
| RFC 7529 RSCALE | RFC | non-Gregorian recurrence | no — let `recurring-ical-events` handle whatever it handles |
| RFC 5546 iTIP / RFC 6047 iMIP | RFC | scheduling / email invitations | no — README wants email; it is after the funded period |
| RFC 7265 jCal / RFC 6321 xCal | RFC | JSON / XML syntax for iCalendar | no — [`ical2jcal`](https://github.com/pycalendar/ical2jcal) exists in the org already |
| RFC 4791 CalDAV, RFC 6578 sync, RFC 6638 scheduling | RFC | via `caldav` | **yes**, through 2.1 |
| RFC 6764 CalDAV service discovery | RFC | pycal.org promises "point it at a URL, and it figures out the rest" — this is how, for CalDAV | **yes**, through `caldav` |
| RFC 8620 JMAP core | RFC | via `calendaring-jmap` | **yes**, through 2.4 |
| RFC 8984 JSCalendar 1.0 | RFC, being obsoleted | — | no |
| draft-ietf-calext-jscalendarbis-20 | IESG, AD evaluation (2026-09-14) | JSCalendar 2.0 — JMAP's wire model | no — `calendaring-jmap`'s problem |
| draft-ietf-jmap-calendars-29 | RFC Editor queue, "Blocked: Stream Hold" (2026-09-24) — presumably waiting for jscalendarbis, a normative reference; datatracker does not say | JMAP Calendars | **yes**, through 2.4 |
| draft-ietf-jmap-tasks-06 | **expired** (2023), WG milestone Mar 2027 | JMAP Tasks | no — do not build on it |
| draft-ietf-calext-subscription-upgrade-13 | **expired** (2025) | upgrading a feed subscription to CalDAV/JMAP | no — but it is the standards-track form of "point it at a URL"; watch it |
| `webcal:` URI scheme | IANA **provisional** | feed URLs in the wild | **yes** — 2.3 should accept `webcal://` as `https://` |
| `X-WR-CALNAME`, `X-WR-TIMEZONE` | de facto (Apple/Google) | feed metadata | **yes** — [`x-wr-timezone`](https://github.com/pycalendar/x-wr-timezone) exists in the org |
| vdir | de facto ([spec](https://vdirsyncer.pimutils.org/en/stable/vdir.html)) | local storage layout | **yes**, through 2.2 |
| ActivityStreams `Event` + [FEP-8a8e](https://event-federation.eu/) | Fediverse Enhancement Proposal, being implemented by Mobilizon and Gancio | Mobilizon (README) | no — see below |
| Org mode | no formal standard; the [Org Syntax](https://orgmode.org/worg/org-syntax.html) document | task source (0.1 survey) | no |
| todo.txt | de facto | task source (0.1 survey) | no |

**ActivityPub/Mobilizon:** it is out of the funded scope, but it should be named
in the "beyond the funded scope" table. FEP-8a8e is the thing to build on, not
raw ActivityPub, because it exists precisely so that Mobilizon, Gancio and the
WordPress event plugins agree on what an `Event` looks like.

**A standards observation for 1.1:** of everything above, only iCalendar and the
tasks draft are needed to *model* the data. Every other entry is either a
transport (CalDAV, JMAP, HTTP, files) or something that must survive a round trip
untouched. The library's job for the latter is **not to lose them**. "Pass
through untouched" should be a conformance-suite test (1.2): read an object
carrying `VALARM` extensions and `X-` properties, save it, read it back, compare.

---

## Part 3: Project decisions (proposals)

### D1. Packaging principle

*Already decided by the author; this records it.*

**The principle:** logic that is not about the CalDAV protocol does not belong
in the `caldav` library.

Consequences:

- **This library is a separate package**, not a backend layer inside a future
  caldav v4. A multi-backend abstraction is by definition not CalDAV protocol
  logic. `caldav` stays a CalDAV client, and this library depends on it.
- **JMAP lives in `calendaring-jmap`**, which is separately funded and not part
  of these 248 hours. The `caldav/jmap/` module now inside `caldav` is misplaced
  by the same principle. Moving it out is for `caldav` and `calendaring-jmap` to
  arrange, not this roadmap. pycal.org already describes `calendaring-jmap` as
  "currently part of python-caldav, being extracted here".
- **The corollary for this library:** logic that is not about *abstracting
  over* backends does not belong here either. The `icalendar-searcher` split set
  the precedent: client-side search lives in its own package so that both
  `caldav` and this library use the same code. Recurrence-range editing (§1.3),
  if it is ever written in the ecosystem, belongs in a similar standalone
  package, not here.

### D2. The name

Constraint: pick it before the first PyPI upload.

The situation has changed since the README was written:

- `calendaring-jmap` is on PyPI, `calendaring-sync` exists as an empty repo in
  the org, and pycal.org lists `calendaring-client`. There is now a
  **`calendaring-*` family**, and a name outside it would be the odd one out.
- "Calendaring" is the IETF's word, and it formally includes tasks: RFC 5545 is
  the *Internet Calendaring and Scheduling Core Object Specification*, and it
  defines `VTODO`. That is true, but most users will not know it.

PyPI availability, checked 2026-09-24 via the JSON API. A 404 means no project
by that name exists. It does not guarantee the name can be registered:

| Name | PyPI |
|---|---|
| `calendaring-client` | free |
| `calendaring` | free |
| `calendar-client` | free |
| `calendaring-tasks`, `caltask`, `caltasks`, `taskcal` | free |
| `pim-client`, `pimlib` | free |

**Recommendation: keep `calendaring-client`, and make the tagline carry the task
message.** The pycal.org description ("One API for CalDAV, JMAP, and plain
iCalendar feeds") currently says nothing about tasks. Change it and the PyPI
summary to something like *"One Python API for calendars and task lists: CalDAV,
JMAP, iCalendar feeds, local files and issue trackers."* A name that tries to
say "events and tasks and trackers" gets long (`calendaring-and-tasks`) or
vague (`pim-client`, which also suggests contacts). The family prefix is
worth more than the signal.

**Also: register `calendaring` too**, as a placeholder or as the import name. A
bare `calendaring` would otherwise be free for anyone to squat on, next to
three packages that share the prefix. Whether the import name is
`calendaring_client` (consistent with `calendaring_jmap`) or `calendaring`
(shorter) is a minor call. Proposal: `calendaring_client`, for consistency.

**Rejected alternatives:** `calendar-client` is too close to "Google Calendar
client" in search results and not in the family. `pim-*` promises contacts.

### D3. Licence

*Not on the roadmap's list, but it has to be decided before the first upload,
and the dependency picture makes it non-trivial.* This is not legal advice.

| Package | Licence | Relationship |
|---|---|---|
| `caldav` | GPL-3.0-or-later **OR** Apache-2.0 | hard dependency (2.1) |
| `icalendar-searcher` | **AGPL-3.0-or-later** | hard dependency (1.1), and a hard dependency of `caldav` |
| `calendaring-jmap` | **AGPL-3.0-or-later** | dependency of 2.4 |
| `icalendar` | BSD-2-Clause | hard dependency |
| `recurring-ical-events` | LGPL-3.0-or-later | via `caldav`, `icalendar-searcher` |
| this repo | **none** | — |

Two observations:

1. Whatever licence this package gets, a program that installs it with its
   dependencies will contain AGPL code. A permissive licence here would be
   honest about *this* code, but it would not make the whole permissive.
2. The same is already true of `caldav`. Its Apache-2.0 option is largely
   theoretical while `icalendar-searcher` is a hard AGPL dependency, and Home
   Assistant (Apache-2.0) already ships `caldav`. Whether that is a problem is
   for the author to judge. It is noted here because this library would inherit
   it, and HA is a stated target user.

**Options:**
- **AGPL-3.0-or-later**, like the two siblings. Consistent, and it matches what
  users get in practice.
- **GPL-3.0-or-later OR Apache-2.0**, like `caldav`. This only means something
  if `icalendar-searcher` is relicensed or made optional.

**Recommendation:** decide `icalendar-searcher`'s licence first (it is the
author's own package), then license this package to match `caldav`. Add a
`LICENSE` file before any code lands.

### D4. Python version floor

What the ecosystem uses today: `caldav`, `icalendar`, `icalendar-searcher`,
`plann` and `calendaring-jmap` all say `>=3.10`. `ical` says `>=3.11`.

**Python 3.10 reaches end of life this month, October 2026.** Nothing in this
project will be released before then.

**Recommendation: `>=3.11`, and drop each version when CPython drops it.** 3.11
gives, for free:
- `typing.Self`, which the async-first classes, and with them their
  generated sync copies, will use heavily
- `ExceptionGroup` / `except*` — a natural fit for operations that fan out
  across several backends, where some succeed and some fail
- `asyncio.TaskGroup`, for the same fan-out in async mode. Under p4 it
  belongs in the hand-written per-mode layer, not in `_async/`: `asyncio` is
  among the things 0.2 found a token rewrite breaks
- `tomllib`, if 1.4 picks TOML for the configuration file

The cost: `plann` (3.3, dogfooding) would have to raise its floor from 3.10 to
depend on this library unconditionally, or make it optional. The distributions
that still ship 3.10 as system Python, Ubuntu 22.04 among them, also lose out,
but they can install a newer Python.

**Alternative:** `>=3.12`, following Scientific Python SPEC 0, which would allow
the PEP 695 generic syntax. That is not worth losing Debian 12 (3.11) for.

Note that the author's own project template (the *python-project-modernization*
checklist) defaults to `>=3.10` with a 3.10–3.14 CI matrix, and says a higher
floor needs a reason and the author's agreement. The reasons are above, and the
agreement was given:

### D5. Typing strictness

The failure that motivated 0.2 was "annotations that lie", so typing here is
correctness, not style.

**Proposal:**
- Ship `py.typed`.
- `mypy --strict` over the package, **gating in CI**.
- `pyright --verifytypes calendaring_client` at **100 % type completeness of
  the public API**, gating in CI. This checks what users see, and it is what
  Home Assistant's `strict-typing` rule relies on. Under p4 it runs over the
  generated `_sync/` copy as well as `_async/`, since users import both.
- This sits on top of 1.3's own gate (pyright, or mypy with
  `check_untyped_defs`, over both copies, plus a test that the checker flags a
  committed missing-`await` specimen). That gate catches p4's codegen slip;
  `--strict` and `--verifytypes` are about the public API being complete.
  0.2 ran its typing probe under both mypy and pyright, and they agreed for
  p4; they still disagree at the edges elsewhere, notably on overloads.
- This is stricter than the siblings: `caldav` runs no type checker in CI, and
  `calendaring-jmap` runs plain `mypy --ignore-missing-imports`. Where 2.1 and
  2.4 call into them, an untyped or loosely typed return must be narrowed at
  the boundary, not allowed to leak `Any` into the public API.
- No `Any` in a public signature without a comment saying why.
- `typing_extensions` is an allowed runtime dependency.
- Tests: annotations are not required. Ruff's `ANN` rules apply to the package,
  not to `tests/`.

### D6. Canonical in-memory model

*Not on the roadmap's list, but the standards review arrives at it, and 1.1
needs it as input.*

**Proposal: iCalendar, as `icalendar` library objects, is the canonical model.**
Backends that do not speak iCalendar convert at their boundary: JMAP (via
`calendaring-jmap`'s converters), issue trackers, and later org mode.

Why:
- Every funded backend except JMAP and the 2.5 tracker speaks iCalendar or a
  subset of it.
- `icalendar-searcher`, which 1.1 must reuse for identical client-side and
  server-side filtering, works on `icalendar` objects.
- JSCalendar 2.0 is still in IESG evaluation, and JMAP Calendars, which cites
  it normatively, is on hold at the RFC Editor.
- The desktop PIM stacks that solved this problem made the same choice (§1.6).
- It gives pass-through of unknown properties for free (Part 2).

The friendly object model 1.1 designs (`task.due`, `task.estimate`, …) is a
typed view *over* the iCalendar component, not a separate model with its own
storage. That keeps round-tripping lossless, which Home Assistant's two-status
`TodoItem` (§1.4) shows is the thing a thin model loses first.

### D7. Tooling conventions

*Not on 0.3's list either, but 1.5 says "matching the sibling projects", and the
siblings do not match each other.*

| | author's template | `caldav` | `calendaring-jmap` |
|---|---|---|---|
| Build, versioning | hatch + hatch-vcs | hatch + hatch-vcs | hatch + hatch-vcs |
| Changelog | Keep a Changelog, `CHANGELOG.md` | `CHANGELOG.md` | towncrier fragments → `CHANGES.rst` |
| Docs | — | Sphinx | Sphinx, pydata theme, Read the Docs |
| Licence metadata | `license = {text = …}` | PEP 639 string + `license-files` | PEP 639 string, REUSE headers |
| Type checking in CI | — | none | plain mypy |
| HTTP | niquests preferred | niquests (httpx optional) | niquests |
| Other | ruff, pre-commit, lychee, conventional commits, `filterwarnings = ["error"]`, trusted publishing | ruff, pre-commit, lychee, conventional commits | ruff, pre-commit, REUSE, zizmor |

**Proposal for 1.5:** the author's template as the baseline. It is what the
single maintainer works with every day, and its `filterwarnings = ["error"]` is
what 1.3 already demands (`-W error`). Two things to take from
`calendaring-jmap` on top: Sphinx on Read the Docs, since 4.1 needs a doc site
anyway and both siblings use Sphinx; and REUSE, if D3 ends at AGPL, which
makes the licence of every file explicit at little cost. towncrier is not worth
it for a one-maintainer project.

The template's warning against the PEP 639 licence string is about pip 22 on
Ubuntu 22.04, whose system Python is 3.10. With D4's floor of 3.11 those users
cannot install the package anyway, so the string form, as both siblings use it,
is fine.

For HTTP, niquests for 2.3, as the template and both siblings use it, with the
caller-owned session that §1.4 asks for.

---

## Open questions for the author

1. **Licence** (D3): is `icalendar-searcher`'s AGPL deliberate, and does it
   stay? This decides this package's licence.
2. **Name** (D2): keep `calendaring-client`? Register `calendaring` as well?
   Import name `calendaring_client` or `calendaring`?
3. **Python floor** (D4): 3.11, accepting that plann has to follow?
4. **Home Assistant** (§1.4): should the outreach offer code ownership of the
   `caldav` integration? That is a maintenance commitment beyond the grant.
5. **D6**: does "iCalendar is the model, everything else converts" agree with
   the task model proposed in the [0.1 survey](TASK_MODEL_SURVEY.md) Part 4?
   It should, but that is the author's call.
6. **Tooling** (D7): the personal template plus Sphinx and REUSE, without
   towncrier?

---

## References

- icalcli — https://github.com/jrvarma/icalcli
- vdirsyncer — https://github.com/pimutils/vdirsyncer — vdir spec: https://vdirsyncer.pimutils.org/en/stable/vdir.html
- ical — https://github.com/allenporter/ical
- Home Assistant core — https://github.com/home-assistant/core (components `caldav`, `todo`, `local_calendar`, `local_todo`, `remote_calendar`; `script/hassfest/quality_scale.py`)
- calendaring-jmap — https://github.com/pycalendar/calendaring-jmap
- pycal.org — https://github.com/pycalendar/pycal.org (`_data/packages.yml`)
- draft-ietf-calext-ical-tasks — https://datatracker.ietf.org/doc/draft-ietf-calext-ical-tasks/
- draft-ietf-calext-jscalendarbis — https://datatracker.ietf.org/doc/draft-ietf-calext-jscalendarbis/
- draft-ietf-jmap-calendars — https://datatracker.ietf.org/doc/draft-ietf-jmap-calendars/
- draft-ietf-jmap-tasks — https://datatracker.ietf.org/doc/draft-ietf-jmap-tasks/
- draft-ietf-calext-subscription-upgrade — https://datatracker.ietf.org/doc/draft-ietf-calext-subscription-upgrade/
- IANA URI schemes (`webcal`) — https://www.iana.org/assignments/uri-schemes/uri-schemes.xhtml
- FEP-8a8e / Event Federation — https://event-federation.eu/
