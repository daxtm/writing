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

## Real Wayland acceptance (M3) — PENDING

Real compositor acceptance for the review surface (update-state → export
journey, destination picker, overwrite confirmation, keyboard/clipboard/focus,
resize/100%/200% and available fractional/mixed scaling, light/dark, Stop and
close during review work) has not been performed. It remains a separate owner
desktop step and is never inferred from offscreen results. It will be recorded
here with compositor/runtime/platform details when observed.
