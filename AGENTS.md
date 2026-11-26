# writing

## What this is
CLI for writers planning and collaboratively drafting long-form fiction with Featherless.ai: a thin `longform.py` launcher over the `longform_core/` package (ADR-0003).

## Stack
Python: CPython 3.13 minor, pinned by the authoritative `.python-version`
(`cpython@3.13`) and mirrored as PEP 723 `requires-python = ">=3.13,<3.14"` in
`longform.py`/`longform_core/cli.py` (ADR-0013); patch updates within 3.13 are
automatic, a minor bump is one reviewed pin/mirror change. uv script runner,
PEP 723 inline `httpx>=0.27` and `pyside6>=6.12.0,<6.13`; argparse CLI, JSON/Markdown files, no database.

## Android target — roadmap only
`docs/ROADMAP.md` now includes an owner-requested Android feature-parity app,
delivered as an owner-signed APK. No Android code, build script, artifact or
OpenSpec change has been created for that track. Create proposals only when a
listed change is selected for build; do not infer implementation from this plan.
The APK request is not permission to ship the unaccepted desktop workspace.

Planned stack (ADR-0014): Kotlin/Jetpack Compose, Chaquopy-embedded CPython 3.13,
`httpx` and the existing Qt-independent `longform_core` operations/resources;
Android API 24+, ARM64 devices and x86_64 emulator coverage. No PySide6, uv runtime,
terminal loop, companion server or duplicated engine in the APK. Host checks
keep ADR-0013's automatic patch policy; Android's embedded patch comes from its
reviewed runtime distribution and is recorded, not replaced by host uv.
Concrete compatible Android build-tool/dependency pins are chosen and locked
in the skeleton, not guessed here. Release ID: `com.daxtm.writing`; debug
adds `.debug`. Owner signing material is external; synthetic signing only for tests.

Milestone 1: `android-apk-project-shell`, `android-project-transfer`,
`android-steered-drafting` — installed APK, ready-project import, credentials,
steering, streamed Generate/Accept, export/reopen/update. Milestone 2:
`android-guided-planning`, `android-draft-feature-parity`,
`android-review-export-parity`, `android-apk-parity-release` — every existing
CLI/desktop action plus guided setup, full offline/device parity and signed APK
handoff. New tests belong in `scripts/check.sh` alongside all existing checks.
Android build/demo commands in the roadmap are planned interfaces, not commands
that currently exist; Android emulator/device acceptance is entirely PENDING.

ADR-0015: private ordinary project directories, system-picker ZIP/resource/
manuscript transfer, unchanged portable files except explicit credential
sanitization; no in-place URI editing, sync or automatic cloud backup. Reuse
ADR-0011's masked session or explicitly saved plaintext project credentials;
no new keyring. Warn that uninstall removes private projects without an export.
ADR-0016: one non-Qt process-owned operation runner, rotation reattaches,
background requests cooperative Stop, no background completion guarantee or
automatic paid replay after process death. Preserve saved branches, never accept
partial previews, and surface interrupted cross-file state honestly.

## Checks
`./scripts/check.sh`: verifies the pin, provisions the latest available
managed CPython 3.13 patch (`uv python install --upgrade cpython@3.13`),
reports `== python: CPython 3.13.<patch>` and runs every phase (syntax, CLI
`--help`, `== standalone`, both pytest processes) on that explicitly selected
interpreter — host Python, active environments and `UV_PYTHON` cannot override
it, and missing/malformed pins, other minors, non-CPython or missing uv fail
early; `== standalone`
(builds `dist/longform` through `scripts/build-standalone.sh` and runs the frozen
executable tests — needs uv and a C compiler providing `cc` for the test-only
network guard, never skipped); source pytest for the remaining regression and
GUI/Qt cases (fails without uv).
Suite: `uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests`;
includes `tests/test_standalone.py`, which builds the standalone executable through
the production script when `dist/longform` is missing or stale and runs it away
from the checkout; `./scripts/check.sh` builds it once and the frozen tests reuse
that artifact; no lint step.
The launcher declares `pyside6>=6.12.0,<6.13` beside `httpx`: `uv run --script longform.py …` downloads
PySide6 (~hundreds of MB of wheel downloads plus installed size, and the matching `uv` cache) on first
use even for CLI-only users, as accepted in ADR-0006; GUI imports stay lazy, so `--help` needs no display.
`ock check` runs committed checks in a clean checkout; there is no hosted CI workflow (`ock ship` runs checks locally before opening the PR).
Run / demo: `uv run --script longform.py --help` prints commands without API calls.
Source runs use an explicitly selected CPython 3.13; the launcher itself exits
nonzero when the running interpreter's minor disagrees with `.python-version`
(uv only warns on a conflicting explicit `--python` request).
A bare `uv run --script longform.py` (or a copied standalone executable with no
arguments, such as a file-manager double-click) opens the GUI for the current
directory; `gui` accepts an optional DIR.
GUI demo: `QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR` (or no
argument / `gui` with no DIR from the project directory) opens one native Wayland
window
(the Plan/Write/Review/Export workspace with the guided setup wizard and
readiness overview; Write carries the complete draft loop: reading all saved
branches/notes, per-scene steering Save/Clear, Generate with count/swipes and
streaming preview, candidate tray Accept/Reroll selected/all/Add N/View/Delete
leaf/Keep branches/Discard, built-in New passage/Edit head editors with
diff/history, Rewind/Use as head/Delete leaf/marked manuscript/Tail N, Scene
tab card/POV/cast/session length/Mark done/Next unfinished, Context tab
budget/samplers/injected-lore/exact prompt/Save last_prompt.txt, Lore tab
toggles/classify/aliases/import; Review covers continuity/compression/reports/
revision; Export covers status and destination-picked export). Generation runs through `longform_core.draft_operations` (Qt-independent, ADR-0007) on
one background worker (`longform_core.draft_worker`); the CLI `draft` loop is an adapter over the same
operations with frozen prompts/transcripts (`tests/test_draft_parity.py`). Stop is cooperative at
request/chunk/save boundaries, close offers Stop-and-wait/Keep open, stale sources refuse writes.
`gui` refuses any explicit platform except `wayland`, never falls back to XWayland, and prints recovery
guidance when Wayland is unavailable. Model/CLI tests run headless; Qt widget tests run offscreen in a
subprocess (`tests/qt_widget_cases.py`, never skipped; 56 cases, all enforced
by an unregistered-case guard). Real Wayland acceptance for setup, planning,
drafting, review and export remains PENDING in each change's `evidence.md` and
is a separate owner desktop step; the shell's pre-drafting smoke (KWin 6.8.3,
PySide6 6.12.0, DPR 1.0) predates generation.

## Desktop workspace status — implemented, unshipped
The owner-authorized **Guided writing workflow** in `docs/ROADMAP.md` is
implemented on `feat/guided-workflow` (unshipped): `project-defaults-full-init`,
`gui-api-key-setup`, `gui-generated-text-streaming`,
`gui-workflow-navigation`, `gui-project-setup-wizard`. Each has OpenSpec
proposal/design/specs, checked test-first tasks and evidence; offline CLI/GUI
parity, offscreen journeys and the standalone build pass. Real Wayland
acceptance remains PENDING in each change's evidence, and this branch is not
`origin/main`; do not claim whole-workspace completion or ship.
This explicit request supersedes the earlier stop-planning instruction below,
not the prohibition on shipping or the outstanding real Wayland acceptance.
ADR-0010 chooses reviewed bundled nonsecret defaults and shared complete init;
ADR-0011 chooses masked per-project/session GUI credential entry using the
existing api_key field only on explicit save (plaintext, not a system keyring);
ADR-0012 extends existing streaming callbacks/worker events to every generated
answer and candidate. Existing name-only credentials and completion-only
planning previews were baseline limitations; ADR-0011 and ADR-0012 now address
them.
The read-only defaults sources are
`/home/daxtm/Documents/fuckpi/project.json` and
`/home/daxtm/Documents/fuckpi/56295265-LLam_ception-1.3.json`; never write there
or require them at app startup, build time or test execution. Review derived
runtime assets before tracking; force empty api_key, FEATHERLESS_API_KEY
environment name and project-relative writer_preset.json. The originals remain
untracked and are never fixtures. GUI full init includes the preset, not
automatic paid generation. Bible setup currently composes local answer forms;
do not invent an AI bible generation endpoint. Reuse planning/review/draft
operations and the one worker; redesign the workflow, not the writing engine.

`docs/ROADMAP.md` requires every CLI/TUI feature in the GUI, start to finish;
the full-parity map was re-audited through the Plan/Write/Review/Export routes.
The native Wayland workspace is implemented on `feat/guided-workflow`
(unshipped): reader shell, complete draft loop, planning, continuity/review/
export and the guided-workflow extension above. All change tasks are checked;
offline CLI/GUI parity is frozen in `tests/test_*_ops.py`, and the offscreen
journeys (`case_planning_journey`, `case_review_journey`,
`case_setup_wizard_journey`, `case_workflow_parity`) run in checks. Real
Wayland acceptance for every milestone remains PENDING in the respective
`evidence.md`. Full completion still requires that separate owner desktop
walkthrough; do not claim whole-workspace completion, and do not ship.
ADR-0004/0005 (integrated from the reader baseline; 0005 superseded by ADR-0006)
select PySide6/Qt Widgets for the expanded native Wayland workspace;
ADR-0007 selects incremental shared operations and one background GUI worker.
Keep existing commands/core behavior and the reader's safe snapshots; keep CLI
prompts/files compatible. The shell's real Wayland acceptance was recorded in
the change's design.md (KWin 6.8.3, `wayland`, PySide6 6.12.0, 1920×1080, DPR
1.0, one window, steering persisted, close exit 0); interactive scaling, theme
switching, and mouse/keyboard work remain an owner acceptance step.

## Layout
- `longform.py`: thin PEP 723 launcher; re-exports the package's public names so `import longform` keeps working.
- `longform_core/`: the implementation — `config` (constants, default config, templates), `utils` (logging, file/JSON/text, diff/parse helpers), `project`, `api`, `tree`, `lore` (cards/books/matching), `prompt`, `checks`, `commands` (cmd_* and interactive helpers), `cli` (argparse/main); `reader_model` (UI-independent sanitized snapshots), `scene_steering` (Qt-independent per-scene steering write adapter), `planning_operations` (Qt-independent init/settings/limits/bible/outline/scenes operations), `gui` (Qt-free Wayland startup policy/dispatch), `gui_window` (PySide6 Qt Widgets shell).
- `scripts/`: check entry point; `tests/`: offline pytest suite (headless model/CLI tests plus `tests/qt_widget_cases.py`, the offscreen Qt widget subprocess cases launched by `tests/test_qt_cases.py`).
- `openspec/`: behavior specs and changes; `docs/`: roadmap and ADRs.
- `.github/`: PR template; `myfic/`: private generated sample, never a test fixture.

## Rules
- Specs: `openspec/`. Decisions: `docs/adr/`. Plan: `docs/ROADMAP.md`.
- Roadmap changes get OpenSpec artifacts only when selected for implementation;
  no speculative change directories. ADR-0004/0005 are integrated, not available numbers.
- Keep `myfic/` and the third-party `56295265-LLam_ception-1.3.json` preset untracked.
  ADR-0010 permits only reviewed, sanitized application-owned runtime defaults,
  not the original private files or private test fixtures.
- Never commit API keys or `.env`; synthetic test credentials only.
- Tests are offline/deterministic: no live API calls; use MockTransport/fakes and temporary projects.
- Keep `longform.py` as the thin PEP 723 launcher over `longform_core/` (ADR-0003); behavior, output, and file formats are frozen behind the test suite. Monkeypatch at the owning module (e.g. `longform.api.warn`), not the launcher re-exports.
