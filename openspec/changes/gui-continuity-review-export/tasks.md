# Tasks

## 1. Completed scene to exported manuscript

Selected/proposed only: every task below is unimplemented. Each checkbox is
one test-first commit; add its focused tests and usage/evidence notes alongside
the behavior, not in a later testing batch. Reuse existing temporary-project,
provider, picker, choice and offline-network seams.

- [x] 1.1 Add a red offscreen button journey in `tests/qt_widget_cases.py`: completed synthetic scenes → update-state/summary-only preview and Accept → compress → critique/check/save/edit notes → revise Accept then Skip → Status → picked Export → reopen; compare saved outputs with fixed-clock CLI fixtures and forbid terminal/editor helpers. Run through `tests/test_qt_cases.py` and record its initial failure on missing review controls, without skips, xfails or implementation.
- [ ] 1.2 First characterize `cmd_update_state` prompts/files/diff/transcripts, then extract shared review preparation/generation/input-save/accept and add Continuity controls, raw/section editors and state/input-history viewing. Verify headless parity and focused offscreen tests for default/explicit scenes, not-done/earlier-scene confirmation, summary-only flags, malformed raw correction, edit/regenerate/quit, backups, explicit Accept and stale refusal; document the controls.
- [ ] 1.3 First freeze compress range/overlap/error/edit transcripts, then add shared range/generation/accept operations and From/To/Replace/preview controls. Verify headless and offscreen cases for unknown/reversed/equal boundaries, missing summaries, inclusive/multiple overlap, ignored absent endpoints, whole-arc replacement confirmation, edit-input history, regeneration/Quit/no implicit writes and stale replacement sets; document that no new arc-snapshot format exists.
- [ ] 1.4 First freeze critique/check requests, saved reports and overwrite behavior, then add shared generation/check/report-save operations and report selection/view/edit/Save controls. Verify CLI/GUI report bytes, critique-prev backups and notes used by Revise; test scene/all/empty/active-branch scope, exact messages/diffs where applicable, no-provider checks, missing tags, Stop/failure/stale/dirty preservation in headless and offscreen cases; document report save semantics.
- [ ] 1.5 First freeze revise prompts/word diffs/history/transcripts, then add the shared passage session and Revision pane with Accept/Skip/Edit/Regenerate/Quit. Verify headless parity and offscreen flows for accepted-then-skipped passages, saved-notes prerequisites including exclusion of all.md, NO CHANGES/identical/truncated/untagged output, output cap, preceding-tail updates, continuation whitespace, input/node history, Quit/Stop retaining earlier saves, dirty/stale refusal and stale-summary recovery; document in-place shared-node effects.
- [ ] 1.6 First freeze status facts/transcript and exact export bytes, then extend the existing read-only overview/shared lore facts and shared manuscript renderer, with Status and destination-dialog Export/overwrite confirmation. Verify headless/offscreen parity for roles/ceilings/preset/lore/scene freshness/word totals/arcs, read-only undiscovered-lore status, chapters/separators/empty scenes/branches, picker cancel, existing/new/changed/unsafe/unwritable destinations and final word-count/path; document the picker workflow.
- [ ] 1.7 Extend the existing worker settlement and dirty-transition paths for all review editors, with red-to-green headless/offscreen integration cases for single-operation gating until actual thread finish, queued/late signals, responsive reading, Stop/close/Keep open, Save/Discard/Cancel across scene/project/refresh/regenerate/close, source/destination safe guards, API-owned baseline advancement and accurate partial-save counts/errors. Retain all earlier guards/tests; document cooperative timeout and nontransactional-save limits.
- [ ] 1.8 Make `./scripts/check.sh` run every new headless/offscreen case and pass the full suite, reusing discovery and changing the script only if coverage requires it; verify a failing journey/missing Qt fails rather than skips and keep network guards intact. Record exact commands/results and separate real Wayland acceptance in `evidence.md` (PENDING if unavailable), audit every roadmap command/action parity row across M1–M3 with controls/tests/evidence and explicit gaps, and update roadmap/AGENTS status only to what is actually demonstrated. No shipping or automatic completion claim.

## Acceptance boundary

The first task deliberately remains red until the later feature commits make
the journey work. All tests are offline/deterministic with synthetic credentials
only; dependency provisioning is separate. Real compositor/picker/keyboard/
scaling/theme acceptance is a separate owner desktop observation, never inferred
from offscreen results. No further milestone or speculative change is authorized.
