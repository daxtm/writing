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

Real Wayland acceptance for status/export remains PENDING (offscreen is not
compositor evidence).

## Real Wayland acceptance (M3) — PENDING

Real compositor acceptance for the review surface (update-state → export
journey, destination picker, overwrite confirmation, keyboard/clipboard/focus,
resize/100%/200% and available fractional/mixed scaling, light/dark, Stop and
close during review work) has not been performed. It remains a separate owner
desktop step and is never inferred from offscreen results. It will be recorded
here with compositor/runtime/platform details when observed.
