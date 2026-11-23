# Evidence — gui-project-planning

Recorded on `feat/gui-wayland-shell`, tasks 1.1–1.8. All offline coverage
runs inside `./scripts/check.sh` through pytest discovery and
`tests/test_qt_cases.py` (which executes `tests/qt_widget_cases.py` in an
offscreen subprocess with the network guard). Offscreen is not compositor
acceptance.

## Offline verification (observed)

- `./scripts/check.sh`: syntax, CLI `--help`, and the full offline suite
  (324 passed) — includes the 30 offscreen Qt widget cases, of which the
  planning cases are: `case_planning_journey` (Create-to-scene button flow
  with real worker signals, injected pickers and a fake Api),
  `case_planning_create_open`, `case_planning_settings_limits`,
  `case_planning_bible`, `case_planning_outline`, `case_planning_scenes`,
  `case_planning_card_edit`. No skips; the pre-existing network guards
  (`tests/conftest.py`, subprocess sitecustomize) stay in force.
- Headless parity (`tests/test_planning_ops.py`): `cmd_init` files and
  transcript, `cmd_limits` → `limits.json` (modulo `fetched`),
  `cmd_bible` files/inputs/history/backup bytes + frozen transcript,
  `cmd_outline` candidate/notes/outline/history bytes and planner messages,
  `cmd_scenes` files and planner prompt + frozen transcript summary.
  Sentinel-secret tests cover inline/env credentials for settings, overview
  and limits views and a provider error echoing a key (scrubbed).

## Real Wayland acceptance — PENDING

Not verified on this branch in this session; the following remain an owner
desktop step, matching the drafting workspace's pending acceptance:

- [ ] Create/Open and preset pickers as native dialogs
- [ ] Setup settings form and Fetch limits progress/errors
- [ ] Bible/Outline/Scenes forms: multiline entry, selection, buttons
- [ ] Keyboard/clipboard/focus/resize behavior in the planning panes
- [ ] Available scaling (100%/200%, fractional/mixed monitors) and light/dark themes
- [ ] Planner progress, Stop during a held request, close settlement, reopen

Offscreen coverage of the same controls (buttons, worker signals, fake
providers, stale/cancel/secret paths) passes, but it does not establish
compositor acceptance and is not claimed to.
