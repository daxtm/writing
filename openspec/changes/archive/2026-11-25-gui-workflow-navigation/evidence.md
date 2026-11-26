# Evidence — gui-workflow-navigation

All commands run from a clean working tree at each task commit on
`feat/guided-workflow`, offline (no live API calls; fakes and temporary
projects only).

## Implementation commands and results

- `timeout 300 env uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' python tests/qt_widget_cases.py` — full offscreen suite: all cases `ok`, including the new `case_workflow_stages`, `case_workflow_readiness`, `case_workflow_dirty_busy`, `case_workflow_parity`, `case_workflow_presentation` (plus existing planning/draft/review/stream cases through the semantic stage/tool routes). No `FAIL`.
- `timeout 600 uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests --ignore=tests/test_standalone.py` — **489 passed** (includes `tests/test_qt_cases.py`, which runs the offscreen case subprocess with the registration guard; plus headless readiness tests in `tests/test_planning_ops.py` and CLI/GUI parity suites).
- Scale 2: `QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 ... python tests/qt_widget_cases.py case_workflow_presentation` — `ok` (also enforced by the new `tests/test_qt_cases.py::test_qt_presentation_case_at_scale_2`).
- `./scripts/check.sh` — full pipeline: `== syntax`, `== cli smoke`, `== standalone` (fresh build through `scripts/build-standalone.sh`, frozen tests **45 passed**), `== tests` (**489 passed**). No step skipped.
- `uv run --with openspec openspec validate --all --strict` — **Totals: 12 passed, 0 failed (12 items)**.

## Coverage re-audit (task 1.8)

- `scripts/check.sh` executes the new stage/readiness/dirty/parity/presentation cases because `pytest -q tests` runs `tests/test_qt_cases.py`, which launches `tests/qt_widget_cases.py` offscreen; that runner's coverage guard exits 2 if any `case_*` function is unregistered, so the new cases can never silently drop out. Frozen tests run in step 3 against the built artifact; the source run excludes only `tests/test_standalone.py` to avoid rebuilding.
- `case_workflow_parity` audits every row of `docs/ROADMAP.md`'s updated full-parity map (route → control list) through the semantic `select_tool` routes; the map itself now names each row's stage → tool path and implementing case. The roadmap extension checklist boxes remain unticked.
- Parity suites unchanged and green: `tests/test_planning_ops.py`, `tests/test_review_ops.py`, `tests/test_draft_parity.py`, `tests/test_gui_dispatch.py` (byte-identical transcripts/prompts/files; `gui.py` startup policy preserved).

## Outstanding acceptance (PENDING, unchanged)

Real Wayland acceptance remains an owner desktop step and was **not**
observed here: keyboard navigation/picker/clipboard, window
resize/scaling (100%–200% and fractional), theme switching, and the
drafting Stop/close flow on the live compositor. Offscreen cases at
scale 1 and 2 cover presentation logic only.

This change is not the completed workspace and nothing is shipped:
the workflow remains unshipped pending the roadmap's remaining
changes and the separate real Wayland acceptance steps.
