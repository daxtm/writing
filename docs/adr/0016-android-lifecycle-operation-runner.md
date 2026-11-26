# ADR-0016: Run Android writing operations once with lifecycle-aware cancellation

- Status: Accepted
- Date: 2026-11-25
- Related: Android roadmap milestone 1; ADR-0007; ADR-0012; ADR-0014; ADR-0015

## Context

The shared operations already accept cancellation tokens, provider factories,
source baselines and preview callbacks. The desktop `draft_worker` is a Qt
adapter, not reusable Android threading. Candidate requests can execute in
parallel inside one operation, and partial previews must never become accepted
prose. An Android screen can be recreated without the process dying, or the
process can be killed without a final callback.

[Android process lifecycle](https://developer.android.com/guide/components/activities/process-lifecycle)
documents process importance and kill behavior. A stopped/background process
cannot promise desktop-style Stop-and-wait completion; reference checked
2026-11-25.

## Options

1. Use persistent background scheduling/service execution with replayable jobs —
   can aim for background completion, but adds scheduling/notification policies,
   job persistence and paid-request replay/idempotency concerns.
2. Use one process-owned, foreground-oriented runner, independent of an Activity,
   with cooperative cancellation and saved-artifact recovery — reuses existing
   operation semantics but does not guarantee completion after backgrounding
   or process death.

## Decision

Choose option 2 because the required workflow is interactive writing, not
unattended generation. Full writing-feature parity does not require an Android
background-job product or automatic replay of paid requests.

One operation runs at a time on a background executor; reading/navigation remain
responsive. Kotlin observes immutable typed snapshots/events on the main thread;
Python owns writing rules and files. Preserve the shared operation's internal
candidate concurrency, configured limits, request timeouts, cancellation and
stale-source checks. Do not start one competing runner per screen or use Qt.

Identify events by project/operation and existing candidate/attempt identities.
Rotation/configuration changes reattach without generating again, losing the
active job or rerouting output into another scene. Ignore stale terminal/events.
Conflicting writes, import/export and project switches wait for settlement.
Stop remains cooperative at existing request/chunk/save boundaries; never kill
a Python thread.

Actual app backgrounding, screen lock and explicit leave request Stop; ordinary
rotation is not intentional backgrounding. Do not launch picker workflows
during an unsettled operation. Back/close offers Keep editing or Stop and leave,
resolves dirty editors, and explains that Android can still terminate the
process. Foreground return shows the existing operation/stopping state if alive,
otherwise reloads saved artifacts. No foreground service or WorkManager replay.

On process restart, no request or provisional response is resurrected as
completed or retried automatically. Restore accepted/saved state, explain
interruption, and require explicit Generate to try again. Session credentials
die with the process. Preserve in-progress editor text across rotation; any
private recovery cache used for process-death recovery is labelled unsaved,
credential-free, and requires explicit restore/save/discard rather than changing
the manuscript or readiness automatically.

Do not add a transaction system on the assumption that existing operations are
whole-job atomic. Use existing complete-file replacement and commit groups;
exercise process death before/after representative save boundaries. Saved
complete branches survive, unfinished previews never become passages, and any
cross-file inconsistency is surfaced with recovery guidance rather than
silently deleting work or announcing success. Fix a demonstrated shared unsafe
write at its existing boundary, with a failing test, if the packaged tests
expose one.

## Consequences

- Good: One shared generation/acceptance model and one runner prevent accidental
  duplicate paid calls on rotation, navigation or automatic job replay.
- Good: Existing operation, preview, timeout and stale-write tests remain the
  contract; platform code handles lifecycle instead of duplicating writing rules.
- Bad: Backgrounding can interrupt generation. Stop may await network timeout
  while the process lives, and the OS need not wait for settlement.
- Bad: Process death can lose provisional output and unsaved edits. Complete
  saved files are the recovery boundary, not a promised whole-job transaction.
- Bad: Activity recreation, app backgrounding, stale callbacks, process death
  and dirty editors require packaged instrumentation and real-device evidence,
  beyond desktop/headless tests.
