# Survey: how real systems model tasks

**Roadmap item:** [0.1 Task and issue-tracker data model](ROADMAP.md#01-task-and-issue-tracker-data-model)
**Status:** in progress — see [Coverage](#coverage) for what is done and what is not
**Deliverable:** this analysis, plus a proposed task data model (Part 4) and a
recommendation for which tracker to implement first (Part 5)

---

## How to read this document

The README's core complaint is that no good open standard for tasks exists, and
that iCalendar in particular has "no clear way to add information about time
estimates and time spent on a task". This document tests that complaint against
what the standards actually say today and against what eleven real systems
actually do, and then proposes a model.

**On sourcing.** Every factual claim about a system is meant to be traceable to a
primary source — a specification, a schema, an API reference, or the source code —
and the source is linked at the point of the claim. Where something could not be
verified from a primary source it is marked **[unverified]** rather than smoothed
over. This document was drafted with AI assistance; the marking discipline exists
so that the author can check the claims rather than having to trust them.

**On scope.** This is research plus a model proposal. Implementing a backend is
separately budgeted ([2.5](ROADMAP.md)), and implementing the time-tracking model
is budgeted separately again. Twenty hours across eleven systems is roughly 1.5 h
each plus write-up: enough for an informed survey, not for deep expertise in any
one of them.

### Coverage

| Part | Subject | State |
|---|---|---|
| 1 | The standards baseline | drafted |
| 2 | The eleven systems | not started |
| 3 | Cross-cutting comparison | not started |
| 4 | Proposed model | not started |
| 5 | Which tracker to implement first | not started |

### The dimensions each system is surveyed against

Taken from the roadmap item, and used as the section structure for every system
in Part 2, so that the systems can be compared row by row in Part 3.

1. **Identity** — stable client-assignable ID, or server-assigned integer?
2. **Time estimate and time spent** — the gap the README names explicitly
3. **Status lifecycle** — fixed enum, or user-definable per project/board?
4. **Priority** — numeric, ordinal, or a label?
5. **Dates** — due, start, scheduled, deferred, and which exist at all
6. **Recurrence** — supported, faked, or absent
7. **Dependencies and parent/child relations**
8. **Assignment, ownership, and multi-user semantics**
9. **Labels/tags/categories**, and whether they are free-form
10. **Change detection** — ETag, revision counter, `updated` timestamp, or nothing
11. **Server-side search and filter**
12. **Auth model, pagination, rate limiting** — a real implementation cost

---

## Part 1: The standards baseline

Before asking what eleven trackers do, it is worth being precise about what the
calendaring standards already offer, because two of the three gaps the README
names have moved since the README was written.

### 1.1 RFC 5545 alone

Plain [RFC 5545](https://datatracker.ietf.org/doc/html/rfc5545) `VTODO` gives a
task: `UID`, `SUMMARY`, `DESCRIPTION`, `DTSTART`, `DUE` **or** `DURATION` (never
both), `COMPLETED`, `PERCENT-COMPLETE`, `PRIORITY` (0–9, 1 highest), `STATUS`
(`NEEDS-ACTION`, `IN-PROCESS`, `COMPLETED`, `CANCELLED`), `CATEGORIES`,
`RELATED-TO` with `RELTYPE` of `PARENT`/`CHILD`/`SIBLING`, `RRULE`, and the
`DTSTAMP`/`CREATED`/`LAST-MODIFIED` timestamps.

The author's own analysis of what this does and does not permit is in plann's
[`TASK_MANAGEMENT.md`](https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md)
and [`NEXT_LEVEL.md`](https://github.com/pycalendar/plann/blob/master/NEXT_LEVEL.md),
and is not repeated here. The short version of its conclusion: of seven things one
wants to record about a task, RFC 5545 has room for three, so `DURATION` gets
pressed into service as the time estimate and `DTSTART` is redefined as "the
latest you can start and still finish by `DUE`".

**That convention is now in conflict with an emerging standard.** See 1.2.

### 1.2 The task extensions draft — the estimate gap is closing

[`draft-ietf-calext-ical-tasks-17`](https://datatracker.ietf.org/doc/draft-ietf-calext-ical-tasks/)
("Task Extensions to iCalendar", Apthorp & Douglass, 10 December 2025) is **past
working-group last call and sitting at the RFC Editor** — datatracker records it as
submitted to the IESG and "In Progress (First Edit)". It is intended as a Proposed
Standard updating RFC 5545. This is not a speculative draft; the library should
plan for it to become an RFC within the funded period.

It defines:

| Name | Kind | Value | Where | Purpose |
|---|---|---|---|---|
| `ESTIMATED-DURATION` | property | DURATION | `VTODO` | the estimated time the task will take |
| `REASON` | property | URI | `VSTATUS`, `PARTICIPANT` | why a status changed |
| `SUBSTATE` | property | TEXT | `VSTATUS` | `OK` / `ERROR` / `SUSPENDED` |
| `TASK-MODE` | property | TEXT | `VTODO` | server-side automation on attendee status change |
| `VSTATUS` | component | — | `VEVENT`, `VTODO`, `VJOURNAL`, `VFREEBUSY`, `PARTICIPANT` | a status change with reason and timestamp |
| `PENDING`, `FAILED` | `STATUS` values | — | `VTODO` | accepted-but-not-started; failed |
| `FAILED` | `PARTSTAT` value | — | `VTODO` `ATTENDEE` | participant failed the task |

**`ESTIMATED-DURATION` closes the estimate half of the README's gap.** The draft is
explicit about the division of labour, and it is the opposite of plann's
convention:

> In a "VTODO" calendar component the property MAY be used to specify the
> estimated duration for the to-do, with or without an explicit time window in
> which the event should be started and completed. When present, "DTSTART" and
> "DUE" or "DTSTART" and "DURATION" properties represent the window in which the
> task can be performed.
> — [§10.1](https://www.ietf.org/archive/id/draft-ietf-calext-ical-tasks-17.txt)

So the standard's model is: `ESTIMATED-DURATION` is the estimate, and
`DTSTART`+`DUE` is the *window*. plann's model is: `DURATION` is the estimate, and
`DTSTART` is derived from it. Both are coherent; they are not the same, and
`DURATION` means different things in each.

The draft also **drops** RFC 5545's rule that `DURATION` in a `VTODO` requires a
`DTSTART` ([§11.1](https://www.ietf.org/archive/id/draft-ietf-calext-ical-tasks-17.txt)),
so a bare `DURATION` with no `DTSTART` becomes legal — which is roughly "an
estimate with no window", and is a third way to say almost the same thing.

> **Finding 1 — the library has a decision to make, and it is not a free one.**
> Three readings of a `VTODO`'s duration fields are now in play: RFC 5545's window,
> the draft's `ESTIMATED-DURATION`, and plann's `DURATION`-as-estimate. Data
> written by plann today will be misread by any client implementing the draft, and
> vice versa. The unified model should carry *estimate* as its own field, map it to
> `ESTIMATED-DURATION` when writing, and read `DURATION`-as-estimate only under an
> explicit compatibility flag. This needs the author's decision — see the open
> questions in Part 4.

### 1.3 The time-spent gap is **not** closing

Neither the tasks draft nor JSCalendar defines anything for time actually spent.
Searching the full text of both for `spent`, `worked`, `worklog` and `actual
duration` returns nothing relevant in either
([draft-17](https://www.ietf.org/archive/id/draft-ietf-calext-ical-tasks-17.txt),
[RFC 8984](https://www.rfc-editor.org/rfc/rfc8984.txt)).

`PERCENT-COMPLETE` exists in both, and it is not a substitute: it says how far
along the task is, not how many hours went into getting there, and the two are
independent — a task can be 50% done after one hour or after forty.

> **Finding 2 — the README's central complaint survives, but only half of it.**
> "No clear way to add time estimates **and** time spent" was true when written.
> The estimate half is being fixed by the IETF. The time-spent half is not being
> fixed by anyone, in either the iCalendar or the JSCalendar lineage. That is the
> gap this library actually has to invent into, and it is why the implementation
> half is separately budgeted.

The author's three candidate workarounds, from plann's
[`NEXT_LEVEL.md`](https://github.com/pycalendar/plann/blob/master/NEXT_LEVEL.md),
with his own assessment:

1. `DTEND`/`DURATION` on `VJOURNAL` — "probably a no-go", legacy validators will reject it
2. A new `PARTSTAT` value, `X-ATTENDED` — his current preferred workaround
3. A new component, `VTIMESPENT`

Part 2 tests these against what the surveyed systems actually store, and Part 4
returns to the choice. Note that candidate 2 has acquired a complication since it
was written: the tasks draft adds `PARTSTAT=FAILED` and a whole `VSTATUS`
component in the same area of the spec, so an `X-ATTENDED` `PARTSTAT` is now
landing next to standardised neighbours rather than into empty space.

### 1.4 RFC 9253 — relationships are solved

[RFC 9253](https://datatracker.ietf.org/doc/html/rfc9253) ("Support for iCalendar
Relationships", published) is more capable than the `PARENT`/`CHILD`/`SIBLING`
that plann's design notes assume, and the notes say so themselves ("When writing
this, I was not aware of RFC9253").

It adds `RELTYPE` values `FINISHTOSTART`, `FINISHTOFINISH`, `STARTTOFINISH`,
`STARTTOSTART` (the four classical project-management dependency types), plus
`FIRST`, `NEXT`, `DEPENDS-ON`, `REFID` and `CONCEPT`; a `GAP` parameter expressing
lead and lag time between two related components; and three new properties —
`LINK` (a typed reference to external information, with a `LINKREL` parameter),
`CONCEPT` (formal, URI-valued categorisation as against `CATEGORIES`' informal
tagging) and `REFID` (a grouping key with no implied semantics).

> **Finding 3 — dependency modelling is a solved problem in iCalendar, and it is
> richer than most of the trackers being surveyed.** `DEPENDS-ON` plus the four
> finish-to-start family covers what Gitea, GitLab and Vikunja express, with room
> left over. This is one of the few places where mapping *into* iCalendar is
> lossless rather than lossy, and `LINK` gives a clean way to keep a pointer back
> to the originating tracker issue.

### 1.5 JSCalendar (RFC 8984) — the other lineage

[RFC 8984](https://www.rfc-editor.org/rfc/rfc8984.txt) matters because
`calendaring-jmap` will speak it, so the unified model must map to it as well as
to iCalendar.

Its `Task` object is closer to what a task tracker wants than `VTODO` is:

- **`estimatedDuration`** (`Duration`) — the estimate, as a first-class field, no
  overloading of the window (§5.2.3)
- **`percentComplete`** (`UnsignedInt`, 0–100)
- **`progress`** (`String`) — `needs-action`, `in-process`, `completed`, `failed`,
  `cancelled`, extensible via the IANA "JSCalendar Enum Values" registry or a
  vendor prefix (§5.2.5)
- **`progressUpdated`** (`UTCDateTime`) — when `progress` was last set (§5.2.6)
- **per-participant `progress` and `progressUpdated`**, with the task-level
  `progress` *derived* from the participants' when not set explicitly: `completed`
  if all participants are, else `failed` if any is, else `in-process` if any is,
  else `needs-action` (§5.2.5)
- **`priority`** — `Int` 0–9, 1 highest, same convention as iCalendar (§4.4.1)
- **`relatedTo`** — `Relation` objects keyed by UID, but only `first`, `next`,
  `child`, `parent`; **RFC 9253's dependency types have no JSCalendar equivalent**
- **`uid`**, **`updated`**, **`sequence`** for identity and change detection

> **Finding 4 — JSCalendar is ahead on progress modelling and behind on
> relationships.** Its per-participant progress with a derived task-level rollup is
> a genuinely better multi-user model than anything in iCalendar, and it is close
> to what several trackers do natively. But its four relation types cannot express
> `DEPENDS-ON` or the finish-to-start family, so a task graph that round-trips
> through JSCalendar loses dependency information that iCalendar can carry. The
> unified model should not adopt either lineage's relation vocabulary wholesale.

### 1.6 Summary of the baseline

| Capability | RFC 5545 | + tasks draft | RFC 9253 | JSCalendar |
|---|---|---|---|---|
| Time estimate | overloaded onto `DURATION` | **`ESTIMATED-DURATION`** | — | **`estimatedDuration`** |
| Time spent | **absent** | **absent** | — | **absent** |
| Progress % | `PERCENT-COMPLETE` | `PERCENT-COMPLETE` | — | `percentComplete` |
| Status | 4 values | 6 values + `VSTATUS` | — | 5 values, extensible |
| Per-participant status | `PARTSTAT` | `PARTSTAT` + `FAILED` | — | per-participant `progress` |
| Parent/child | `RELTYPE` | — | `RELTYPE` | `relatedTo` |
| Dependencies | — | — | **`DEPENDS-ON`, F2S family, `GAP`** | **absent** |
| External links | `URL`, `ATTACH` | — | **`LINK` + `LINKREL`** | `links` |
| Formal categories | `CATEGORIES` | — | **`CONCEPT`** | `categories` / `keywords` |
| Change detection | `SEQUENCE`, `LAST-MODIFIED` | — | — | `sequence`, `updated` |

---

## Part 2: The systems

*Not started. Planned order: Gitea, GitLab, Vikunja, Kanboard, Taskwarrior,
org-mode, OpenProject, Request Tracker, EteSync, Focalboard, Markdown task files.*

---

## Part 3: Cross-cutting comparison

*Not started.*

---

## Part 4: A proposed task model

*Not started. Must resolve: the `DURATION` / `ESTIMATED-DURATION` conflict raised
in Finding 1, and the choice between the three time-spent representations in 1.3.*

---

## Part 5: Which tracker to implement first

*Not started. Feeds roadmap item 2.5.*

---

## Sources

### Standards
- [RFC 5545 — iCalendar](https://datatracker.ietf.org/doc/html/rfc5545)
- [RFC 8984 — JSCalendar](https://www.rfc-editor.org/rfc/rfc8984.txt)
- [RFC 9253 — Support for iCalendar Relationships](https://datatracker.ietf.org/doc/html/rfc9253)
- [draft-ietf-calext-ical-tasks-17 — Task Extensions to iCalendar](https://datatracker.ietf.org/doc/draft-ietf-calext-ical-tasks/)
  ([text of -17](https://www.ietf.org/archive/id/draft-ietf-calext-ical-tasks-17.txt))

### Prior art by the same author
- [plann `TASK_MANAGEMENT.md`](https://github.com/pycalendar/plann/blob/master/TASK_MANAGEMENT.md)
- [plann `NEXT_LEVEL.md`](https://github.com/pycalendar/plann/blob/master/NEXT_LEVEL.md)
- [plann `DESIGN.md`](https://github.com/pycalendar/plann/blob/master/DESIGN.md)

---

*Drafted with AI assistance (Claude Opus 5 via Claude Code) and reviewed by the
author. Claims marked **[unverified]** have not been checked against a primary
source.*
