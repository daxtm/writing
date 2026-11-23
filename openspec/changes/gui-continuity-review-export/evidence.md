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

## Task 1.8 — coverage enforcement, failure injection and M1–M3 parity audit (observed)

### Coverage chain (no second runner)

`./scripts/check.sh` → `uv run --with pytest --with httpx --with
'pyside6>=6.12.0,<6.13' pytest -q tests` → `tests/test_qt_cases.py`
(subprocess, offscreen, `net_guard_env`) → `tests/qt_widget_cases.py` running
every entry of `CASES`. That is the only runner; running
`python tests/qt_widget_cases.py <case>` by hand is a development convenience.
The script itself needed no change. One genuine gap was fixed (commit
`fix(tests): fail the check on unregistered Qt widget cases`): a `case_*`
function missing from `CASES` used to run silently never; the runner now
exits 2 listing any unregistered `case_*` callable. Red proof (injected stub
`case_zz_unregistered`): the child printed
`unregistered Qt widget case(s): case_zz_unregistered` and exited 2, so
`tests/test_qt_cases.py::test_qt_widget_cases_run_offscreen` failed —
`1 failed, 380 passed`. (During this injection the guard first over-reported
`case_owner_flow_reading`/`case_owner_flow_steering`; those are registered
under their unprefixed keys `owner_flow_reading`/`owner_flow_steering` —
the guard now accepts both key styles, and both cases run green.)

### Failure injections (each through the real `./scripts/check.sh`, then restored)

- Missing Qt: `import PySide6` temporarily replaced by
  `import PySide6_noqt` → child exits 2 with "Qt widget cases require
  PySide6; provision it with: uv run --with pytest --with httpx --with
  'pyside6>=6.12.0,<6.13' pytest -q tests (ModuleNotFoundError: No module
  named 'PySide6_noqt')"; wrapper asserts `returncode == 0` and fails;
  **`check.sh` exit 1**. Coverage is never skipped.
- Failing journey: `case_review_journey` parity assert temporarily inverted
  → `FAIL case_review_journey` in the wrapper output; **`check.sh` exit 1**.
- Restored baseline: `./scripts/check.sh` → **exit 0, `381 passed in ~4.9s`**;
  offscreen child reports **38/38 cases ok**. No skips, no xfails anywhere in
  the suite (`grep skip/xfail` finds only docstrings/comments). Network
  guards intact: `conftest.py` autouse offline guards (credentials stripped,
  `socket.connect`/`create_connection` and `httpx.HTTPTransport.handle_request`
  refuse) and the subprocess `sitecustomize` net guard; no test performs a
  live call.

### Full-parity audit — every row of `docs/ROADMAP.md`, verified against code and tests

Verified by grepping `longform_core/gui_window.py` and the test files; each
row names the controls that exist and the tests that execute them offline.

Milestone 1 — draft loop (`gui-drafting-workspace`, implemented; unshipped):

| CLI surface | GUI control(s) | Headless tests | Offscreen cases | Gap |
|---|---|---|---|---|
| `gui DIR` | One window; reading/metadata/notes panes; refresh preserving selection/scroll; sidebar navigation; prose size 8–28 pt spinbox (`_apply_prose_size`) | `test_reader_model.py` (31), `test_gui_dispatch.py` (7) | `owner_flow_reading`, `case_navigation_no_writes`, `case_reading_states`, `case_refresh_preserves_state`, `case_palette_and_prose_size`, `case_readonly_panes`, `case_focus_and_tab_order`, `case_enter_inserts_newline`, `case_invalid_config_and_recovery` | none offline; font choice beyond size is owner detail |
| `draft [--scene]`, resume/next | Scene sidebar select, "Next unfinished", reopen done scenes, prerequisite/status warnings | `test_draft_parity.py::test_cli_routes_generate_through_shared_operation` | `case_draft_generate_acceptance` (reopen), `case_draft_scene_context` (Mark done/Next unfinished) | none |
| `g [N]`/`gN`, swipes | Generate + count spin, streaming/completion preview in the tray, Stop | `test_draft_parity.py` (generation/batch/budget/partial-failure) | `case_draft_generate_acceptance`, `case_draft_stop_and_close`, `case_draft_midstream_failure` | streaming is completion-based (nonstreaming `Api.chat`), documented |
| candidate `K`/`r`/`+`/`v`/`d`/Enter | Tray: Accept, Reroll selected/all, Add N, View, Delete leaf, Keep branches/Discard | `test_draft_parity.py` (reroll/delete-leaf/accept), `test_draft.py` | `case_draft_candidate_tray` | concurrent CLI/GUI writers unsupported (by design) |
| `s`/`se`/`l N`/`who`/`pov` | Multiline steering Save/Clear (Save captures before prompt), length token cap, cast/POV forms | `test_scene_steering.py` (20), `test_draft_parity.py::test_scene_controls_parity` | `owner_flow_steering`, `case_draft_scene_context`, `case_dirty_scene_choices` | none |
| `w`/`e`/`r`/`t`/`j`/`x` | New passage, Edit head with diff/history, Rewind, branch tree/metadata, Jump/Use as head, Delete leaf | `test_draft_parity.py::test_manual_edit_branch_parity`, `test_edit_noop_and_keep_lead_rules` | `case_draft_edit_and_branches`, `case_removed_node_and_scene` | no external editor/terminal helpers (by design) |
| `v`/`v ID`/`tail`/`card`/`c`/`cp` | Marked manuscript, node metadata viewer, Tail N, scene card, Context tab (budget/samplers/injected lore/exact prompt), Save last_prompt.txt | `test_draft_parity.py::test_prompt_dump_parity` | `case_draft_scene_context`, `case_draft_edit_and_branches` | none |
| lore files/commands | Lore tab: list, individual/multi/all toggles, character/aliases/world, JSON/PNG import picker with replace/cancel | `test_lore_ops.py` (4), `test_lore.py` | `case_draft_lore`, `case_stale_conflict` | none |
| `d`, end confirm, `q`, `?`/help | Mark done (+decline end suggestion), Leave draft, Draft help in the reading pane (`DRAFT_HELP`), dirty Save/Discard/Cancel | `test_draft_parity.py::test_accept_matches_shared_operation` | `case_draft_help_and_leave`, `case_close_choices`, `case_dirty_scene_choices` | none |

Milestone 2 — setup/planning (`gui-project-planning`, implemented; unshipped):

| CLI surface | GUI control(s) | Headless tests | Offscreen cases | Gap |
|---|---|---|---|---|
| `init [--preset]`, config | Create/Open dir pickers with create-missing-only init, preset picker + master-export validation, models/roles/settings form | `test_planning_ops.py` (78: init/preset/settings parity) | `case_planning_journey`, `case_planning_create_open` | credentials show name/availability only (by design, never the key) |
| `limits`, `bible` | Explicit limits fetch (credential-name only), bible section forms/answers/edit/accept/history, direct edits | `test_planning_ops.py` (bible/limits parity) | `case_planning_settings_limits`, `case_planning_bible` | `limits.json` matches CLI shape modulo `fetched` (recorded) |
| `outline` | Count/notes editor, Generate/Reroll, candidate viewer/selection, body edit, Cancel | `test_planning_ops.py` (outline parity) | `case_planning_outline` | none |
| `scenes [--force]` | Scene cards list/editor/validation, Generate/Regenerate, Accept/Replace confirmation with backups, Cancel | `test_planning_ops.py` (scenes parity) | `case_planning_scenes`, `case_planning_card_edit` | none |

Milestone 3 — continuity/review/export (this change; unshipped):

| CLI surface | GUI control(s) | Headless tests | Offscreen cases | Gap |
|---|---|---|---|---|
| `update-state [--scene] [--summary-only]`, raw edit/retry, warnings | Continuity tab: scene selection, summary-only flag, diff/raw/section editors, Accept/Edit/Regenerate/Quit, warning confirmation, state/input history | `test_review_ops.py` (57: parity, stale, history, edit semantics) | `case_review_update_state`, `case_review_settlement`, `case_review_dirty_sources`, `case_review_journey` | none |
| `compress --from --to [--replace]` | From/To saved-order combos, overlap Replace confirmation naming whole arcs, preview/Edit/Accept/Regenerate/Quit | `test_review_ops.py` (compress prepare/collision/accept/stale/edit) | `case_review_compress`, `case_review_journey` | no new arc-snapshot format (by design; edited-input versions retained) |
| `critique --scene`, `check [--scene]` | Critique scene / Check scene / Check all, report viewer, built-in report editor with Save/Cancel and backups | `test_review_ops.py` (critique/check parity, no-provider, stale) | `case_review_reports` | all-scenes check is a per-scene loop over saved cards (same CLI scope) |
| `revise --scene` | Revision pane: per-passage diff, Accept/Skip/Edit/Regenerate/Quit, node history "by: revise" | `test_review_ops.py` (revise parity, cap, tail, quit) | `case_review_revise`, `case_review_settlement`, `case_review_journey` | none |
| `status`, `export [--out]` | Status tab (read-only facts, no lore-discovery writes), Export with destination picker/overwrite confirm/alias/symlink/unwritable guards | `test_review_ops.py` (status facts, export bytes/guards) | `case_review_status_export`, `case_review_journey` | none |

Audit outcome: every roadmap row maps to real, executed controls and offline
tests; no row is uncovered at the offscreen/headless level. Explicit
deviations, all documented rather than silent: (1) candidate streaming shows
completion progress because `Api.chat` is nonstreaming; (2) concurrent
CLI/GUI writers remain unsupported; (3) no terminal/external-editor helpers
anywhere; (4) credential forms expose name/availability only; (5) all-scenes
check iterates saved scene cards like the CLI default scope. Explicit gaps:
real Wayland acceptance is PENDING for drafting (generation loop),
Create-to-scene (M2) and review/export (M3) — recorded separately below.
The workspace is therefore **not** claimed complete and nothing is shipped.

### Full-suite results (exact commands)

- `./scripts/check.sh` → `== syntax` ok, `== cli smoke` ok, `== tests`
  `381 passed in ~4.9s`, exit 0.
- `QT_QPA_PLATFORM=offscreen python tests/qt_widget_cases.py` → 38 ok.
- `ock check HEAD` → "Local checks passed" for the 1.7 commit `646aecf` and
  re-run on the 1.8 commits.

## Real Wayland acceptance (M3) — PENDING

Real compositor acceptance for the review surface (update-state → export
journey, destination picker, overwrite confirmation, keyboard/clipboard/focus,
resize/100%/200% and available fractional/mixed scaling, light/dark, Stop and
close during review work) has not been performed. It remains a separate owner
desktop step and is never inferred from offscreen results. It will be recorded
here with compositor/runtime/platform details when observed.
