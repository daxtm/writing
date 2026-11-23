# Evidence — gui-continuity-review-export

## Task 1.1 — red offscreen journey (recorded before any review control exists)

Command:

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  python tests/qt_widget_cases.py case_review_journey
```

Observed: the fixed-clock CLI fixture half of the journey runs to completion
(update-state, summary-only, compress, critique, check, revise, status, export
via the in-process CLI with a scripted fake Api, frozen clock, scripted
answers and a built-in-editor replacement — no terminal helpers), then the
journey fails on the missing review controls:

```
TypeError: MainWindow.__init__() got an unexpected keyword argument
'save_picker'. Did you mean 'dir_picker'?
```

All 30 existing offscreen cases still pass; only `case_review_journey` fails
(no skips, no xfails, no implementation). This is the deliberate red state of
task 1.1; later feature commits turn it green.

## Task 1.6 — status overview and destination-picked export (observed)

Headless ops/CLI parity (`tests/test_review_ops.py`):

```
uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' \
  pytest -q tests/test_review_ops.py
# 55 passed
```

Status transcript parity vs the frozen CLI fixtures, read-only active-lore
facts (no discovery/registry write), export bytes (chapters, separators,
empty scenes, inactive branches, `--out`), and guards: project-file aliases
(`state.md/child.md`), stale destinations (`dest_baseline`), symlinks (the
leaf is kept un-resolved so a symlinked final target is refused, never
written through) and unwritable destinations (`could not be written`).

Offscreen cases (`QT_QPA_PLATFORM=offscreen`, subprocess via
`tests/test_qt_cases.py`):

- `case_review_status_export` — new: status facts render and match the CLI
  transcript, refresh after a saved critique flips its crit column; picker
  cancel, overwrite decline/confirm (exact CLI bytes), project-file alias,
  symlink and unwritable refusals, unsaved-report dirty resolution before
  export.
- `case_review_journey` — now green end to end: completed scenes →
  continuity → compression → reports → revision → status → picked export →
  reopen, with file parity against the fixed-clock CLI fixtures. Fixes while
  going green: journey expectations corrected to observed byte behavior
  (state backup has no trailing newline; a "NO CHANGES" second passage
  completes the revise session like the CLI's default-answer run) and s001
  is re-selected before the report step (summary-only had left s002
  selected).

Full suite (`./scripts/check.sh`): **379 passed**, no skips/xfails.

## Task 1.7 — one-worker settlement and review dirty transitions (observed)

Headless commit-group placement (`tests/test_review_ops.py`, new):

- `test_ops_accept_stop_before_commit_group` — a Stop raised before the
  acceptance group writes nothing: no `state.md` change, no summaries, no
  `state_history` backup (the token is checked at the group boundary only).
- `test_ops_accept_finishes_inflight_commit_group` — a stub token raising on
  its second `check()` (Stop pressed after the group's boundary check) never
  interrupts the tiny backup/state/summaries/scenes commit: all writes land,
  `message` stays "saved summaries and state.md", and the group is never
  re-checked mid-write (no rollback promise).

Offscreen cases (both new; confirmed red first — settlement: the gate cleared
on the terminal signal and a second operation could start; dirty sources: a
Save silently launched the export and Discard did not restore the baseline):

- `case_review_settlement` — the busy gate survives a synthetic terminal
  result (`_on_worker_done` with the real op id) until the worker thread
  actually finishes (`_on_thread_finished`, thread captured in a lambda
  default because Qt's `finished` signal carries no arguments); foreign op
  ids' events/terminal results are ignored; busy disables controls and the
  method-level guard still answers "An operation is running"; reading stays
  responsive; a selection change mid-run cannot retarget the running critique
  (saved to s001 while s002 is selected); close during work offers Keep open;
  a Stop between passage decisions reports "revised 1 passages — stopped;
  remaining passages were not revised", leaves the stopped node unchanged and
  ends the session; close after settling resolves steering (Discard) then the
  report edit (Save commits, Cancel keeps the window open and writes nothing).
- `case_review_dirty_sources` — Revise/Export run only from saved sources via
  `_resolve_saved_sources`: Save commits the report/steering and never
  silently launches the action ("press Export/Revise again" is required);
  Discard restores the stored baseline text; Cancel keeps the edit and stops;
  a stale Save fails with the guarded message and keeps the local edited
  text; a timer refresh never clobbers a locally edited report.

Settlement restructure (GUI only): `_on_worker_done` no longer clears the
busy gate; `_on_thread_finished(thread)` clears it only for the live thread;
`_dispatch` captures the token in a lambda default and refuses only when busy
outside settlement (`_settling` allows chained operations such as the
post-accept next proposal); cancelled messages are dedicated per op kind
(continuity/reports/revise) and name exactly what stayed saved. Close resolves
steering → planning → report edit → continuity edit → revision edit.
Documented limits: cooperative Stop is bounded by configured request timeouts
(`_wait_for_settlement` docstring); multi-file saves are not transactions —
Stop lands at group boundaries, completed groups stay saved, messages never
promise rollback.

Full suite (`./scripts/check.sh`): **381 passed**; offscreen runner:
**38/38 cases ok** (36 + 2 new), no skips/xfails.

Real Wayland Stop/close acceptance for review remains PENDING (offscreen is
not compositor evidence).

## Real Wayland acceptance (M3) — PENDING

Real compositor acceptance for the review surface (update-state → export
journey, destination picker, overwrite confirmation, keyboard/clipboard/focus,
resize/100%/200% and available fractional/mixed scaling, light/dark, Stop and
close during review work) has not been performed. It remains a separate owner
desktop step and is never inferred from offscreen results. It will be recorded
here with compositor/runtime/platform details when observed.
