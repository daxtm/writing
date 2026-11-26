# Evidence — gui-project-setup-wizard

All commands run from the working tree at each task commit on
`feat/guided-workflow`, offline (no live API calls; `PlanningFake`/
`FakeProvider` fakes, temporary projects, no real credentials).

## Per-task commits (branch `feat/guided-workflow`, baseline `f9ec01e`)

- 1.1 `baf4059` — journey regression added red first (recorded against a
  throwaway worktree of `f9ec01e`:
  `FAIL case_setup_wizard_journey — AttributeError: 'MainWindow' object has
  no attribute '_guide_active'`); superseded by `467f8f2`.
- 1.2 `467f8f2` — guide chrome/steps, location page, Create; `a01ffe4` —
  dirty continuations (`case_setup_wizard_dirty_create`).
- 1.3 `e027917` — `case_setup_wizard_resume` +
  `test_readiness_guides_resume_steps_without_any_wizard_document`
  (readiness derives resume steps from saved artifacts only).
- 1.4 `dd441f6` — credential plaintext-save consent, session loss on
  close/reentry, bible-answer history, Skip writes nothing, zero provider
  calls outside explicit actions.
- 1.5 `40ce8c6` — outline paid-action labels, in-flight candidate not
  choosable, Reroll appends candidates, Choose is local-only.
- 1.6 `62dd0db` — scene parse-invalid recovery, paid-action label, card
  edit/normalization, first-unfinished handoff, all-done guidance.
- 1.7 `bd4f215` — replacement/downstream case (caught and fixed a real
  bug: `_downstream_note` used `json.loads` without `import json` in
  `longform_core/gui_window.py`, silently dropping the card count) +
  `case_setup_wizard_presentation`, scale-2 run added to
  `tests/test_qt_cases.py`.
- 1.8 (this commit) — reopened journey extended through Write streamed
  candidate/Accept, continuity, critique report, revision, destination-
  picked export and final reopen.

## Implementation commands and results

- `QT_QPA_PLATFORM=offscreen uv run --with pytest --with httpx
  --with 'pyside6>=6.12.0,<6.13' python tests/qt_widget_cases.py` — full
  offscreen suite: all cases `ok`, including the five new wizard cases
  (`case_setup_wizard_journey`, `_resume`, `_dirty_create`,
  `_replacement`, `_presentation`). No `FAIL`.
- Scale 2: `QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 ... python
  tests/qt_widget_cases.py case_setup_wizard_presentation` — `ok`
  (enforced by `tests/test_qt_cases.py::test_qt_presentation_case_at_scale_2`,
  which now runs both presentation cases).
- `./scripts/check.sh` — full pipeline: syntax, CLI smoke, `== standalone`
  (fresh build through `scripts/build-standalone.sh`, frozen tests
  **45 passed**), `== tests` (**490 passed**, includes
  `tests/test_qt_cases.py` with the unregistered-case guard, headless
  readiness regressions in `tests/test_planning_ops.py`, and the CLI/GUI
  parity suites `tests/test_planning_ops.py`, `tests/test_review_ops.py`,
  `tests/test_draft_parity.py` — byte-identical transcripts/files, no
  wizard-only project document, unchanged prompts/samplers/parsing/
  formats/network guards). No step skipped.
- `uv run --with openspec openspec validate --all --strict` —
  **Totals: 12 passed, 0 failed (12 items)**.

## Coverage re-audit (task 1.8)

- `scripts/check.sh` executes every new wizard case because the source
  pytest run includes `tests/test_qt_cases.py`, which launches
  `tests/qt_widget_cases.py` offscreen; that runner exits 2 if any
  `case_*` function is unregistered in `CASES`, so the five wizard cases
  cannot silently drop out. Frozen tests run in step 3 against the built
  artifact; the source run excludes only `tests/test_standalone.py`.
- Journey flow exercised end to end in one window and one worker: Create
  → title → credentials (synthetic, plaintext-save consent) → bible
  answers (history saved; Skip writes nothing) → outline (streamed
  candidates, Reroll/Choose local-only) → scenes (Generate, parse-invalid
  recovery, card edit, Accept; previews never write scenes.json) →
  Enter Write (first unfinished s01, no provider call, no status change)
  → streamed draft candidate/Accept (tray) → update-state (preview never
  writes; accept writes state + history) → critique save → passage
  revise accept (pre-edit history kept) → export through the save-picker
  destination. All-done state guides manual selection; Enter Write resets
  no status.
- Interrupted/reopened: closing mid-guide is safe; every reopen resumes
  at the earliest incomplete saved step; provisionally saved answers and
  unchosen streamed candidates never complete a step; a fully set-up
  project shows "Reopen setup" and resumes at Write.
- Dirty continuations: Back/Next/Save never generate/choose/accept/
  discard; Save-and-resume reuses the planning dirty Save/Discard/Cancel
  flow; external source changes refuse stale writes until Refresh;
  failed/stale Save preserves edits; replacement of saved planning warns
  about downstream effects and preserves backups/trees; one cooperative
  Stop mid-generation saves no candidate and keeps the guide.
- Presentation: keyboard/focus reaches the chrome, no default button
  (Enter in multiline editors never triggers an action), explicit labels
  and step counts, 900×600 and 1150×760 usability with a larger prose
  size, light/dark palettes, scale 1 and 2. Manual/advanced planning
  paths retained (`setup_advanced_btn` untouched).

## Outstanding acceptance (PENDING)

Real Wayland acceptance for the setup-to-export walkthrough remains an
owner desktop step and was **not** observed here: native keyboard
navigation, credential entry, real file pickers, clipboard, window
resize/scaling (100%–200% and fractional), theme switching, and the
Stop/close flow on the live compositor. Offscreen cases at scale 1 and 2
cover presentation logic only.

This change does not complete the guided writing workflow and nothing is
shipped; roadmap boxes remain unticked.
