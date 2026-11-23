# Change evidence — gui-drafting-workspace

Per-task red-to-green evidence, test counts, and separate (pending) real Wayland
acceptance. All runs are offline/offscreen; no network access, no skips.

## 1.1 — first offscreen acceptance case (red first)

- Added `case_draft_generate_acceptance` and `case_draft_midstream_failure` to
  `tests/qt_widget_cases.py` (run through the existing `tests/test_qt_cases.py`
  subprocess harness; no skips/xfail).
- Red run (before implementation), recorded verbatim:

```
$ QT_QPA_PLATFORM=offscreen uv run --with pytest --with httpx \
    --with 'pyside6>=6.12.0,<6.13' python tests/qt_widget_cases.py \
    case_draft_generate_acceptance case_draft_midstream_failure
TypeError: MainWindow.__init__() got an unexpected keyword argument 'provider_factory'.
    ...  (Generate was disabled/absent: no drafting controls existed)
2 Qt widget case(s) failed: case_draft_generate_acceptance, case_draft_midstream_failure
FAIL case_draft_generate_acceptance
FAIL case_draft_midstream_failure
```

Expected failure as required by task 1.1: the shell had disabled/missing drafting
controls (no Generate provider seam, no preview/tray/accept). Guards untouched.

- Green run after implementation: both cases pass offscreen through the real
  worker thread and queued signals with the injected fake provider.

## 1.2 — CLI parity capture, then extraction with the CLI as adapter

- New `tests/test_draft_parity.py` (7 tests). First written against the
  pre-extraction loop: fake provider, scripted terminal answers, frozen stdout
  transcript captured byte-for-byte from the pre-extraction `cmd_draft`
  (streamed generation, accept, quit), plus prompt/request/meta, tree/scenes
  and calib parity between CLI and `draft_operations` for continuation,
  swipes/N batches, over-budget refusal (no call), partial batch failure,
  soft failure and explicit accept. All baseline comparisons passed before the
  refactor; the recorded red was the adapter assertion:
- Red run (before the refactor):

```
FAILED tests/test_draft_parity.py::test_cli_routes_generate_through_shared_operation
E       AssertionError: cmd_draft must run generation through draft_operations.generate_candidates
E       assert []
```

- After the refactor (CLI adapter over `generate_candidates` /
  `accept_candidate` / `prepare_report`; `session_info` supplies the prologue
  warnings in the original order via separate `warnings` and
  `sampler_warnings` lists): all 7 parity tests pass; full suite 226 passed.
- Documented deviation: the pre-extraction prologue validated sources by
  building a throwaway prompt; the adapter now validates at the first
  generation/inspection, so a die for unreadable sources can appear slightly
  later in the transcript (valid projects are byte-identical).

## 1.3 — worker barriers, cooperative Stop, safe close, stale refusal

- Headless (`tests/test_cancel_and_stale.py`, 8 tests, written first and green
  against the seams — they are the deterministic barrier cases): cancel before
  request (no call/save), cancel during a blocked stream chunk (distinct
  Cancelled, no partial node), cancel at the save boundary (nothing commits),
  external source change during the request (stale refusal, external change
  preserved), Api token interrupting retry backoff (<1.5s wake, no second
  request), Api token aborting a blocked stream, `Api.many` never swallowing
  cancellation as a candidate failure, repeated Stop idempotent plus
  shortfall reporting.
- Offscreen (written first, red run):
```
AttributeError: 'NoneType' object has no attribute 'set'
2 Qt widget case(s) failed: case_draft_stop_and_close, case_draft_stale_refusal
```
  (the close-during-work dialog and settlement path did not exist yet).
- After implementing closeEvent Stop-and-wait/Keep-open, `_wait_for_settlement`
  (pumped events, never a blocking join or thread kill) and busy-state write
  disabling: `case_draft_stop_and_close` proves Stop at a chunk boundary saves
  nothing, repeated Stop is safe, conflicting writes are disabled while
  working, late payloads of superseded operations are ignored, Keep open
  preserves the running job without cancelling, and Stop and wait settles then
  closes; `case_draft_stale_refusal` proves stale refusal with recovery
  guidance, dirty local text retained and no partial commit.
- Full suite: 234 passed.

## 1.4 — candidate tray controls

- Ops parity first (`tests/test_draft_parity.py`, +2 tests, baselines held
  pre-change): CLI `r 1` keeps the original node as a branch, adds the reroll
  as a sibling of the batch's captured parent and matches the shared
  operation's prompt/meta byte-for-byte; `d K` deletion and
  `draft_operations.delete_leaf` produce identical trees, nonleaf deletion is
  refused and a deleted head leaf moves head to its parent.
- Offscreen `case_draft_candidate_tray` written first; red run:
```
AttributeError: 'MainWindow' object has no attribute 'view_btn'
```
- After implementing View/Reroll selected/Reroll all/Add N/Delete leaf/Keep
  branches/Discard preview (plus slot-merge and shortfall reporting): the case
  passes — View shows saved text without accepting, reroll replaces only
  returned slots (unmatched slots keep originals, "1 of 2" shortfall shown),
  Add extends the batch parent, Delete leaf removes only the leaf, both tray
  closes are non-destructive and the saved nodes/head survive reopen.
- Full suite: 236 passed.

## 1.5 — scene controls and no-call context inspection

- Headless parity first (`tests/test_draft_parity.py`, +2 tests; red run:
```
FAILED tests/test_draft_parity.py::test_scene_controls_parity - AttributeError: ... 'set_cast'
FAILED tests/test_draft_parity.py::test_prompt_dump_parity - StopIteration (test typo, fixed)
```
  then green): CLI `who`/`pov`/`d` route through `set_cast`/`set_pov`/
  `mark_done` with identical scenes.json and byte-identical next prompts;
  CLI `cp` and `dump_prompt` write identical `last_prompt.txt` bytes.
- Offscreen `case_draft_scene_context` written first; red run:
```
AttributeError: module 'longform_core.gui_window' has no attribute 'SCENE'
```
- After implementing the Scene tab (read-only card, POV/cast saves, session
  length, status, earlier-scene warnings, Mark done, Next unfinished) and the
  Context tab (Inspect, Exact prompt, Save last_prompt.txt): the case passes —
  inspection and exact prompt make zero provider calls, the dump equals the
  shown bytes, POV/cast persist, Mark done names continuity as a separate
  later step, Next unfinished selects the first non-done scene (all-done
  explains explicit reopening), declining the model-end suggestion keeps the
  post-accept status, and missing credentials disable only generation while
  inspection stays usable.
- Full suite: 238 passed.

## 1.6 — built-in editors and branch navigation

- Headless parity first (`tests/test_draft_parity.py`, +2 tests): CLI
  `w`/`e`/`r`/`j` route through `append_manual`/`edit_head`/`rewind`/`jump`
  with identical trees, histories (by=user-edit) and planned->drafting;
  empty/unchanged edits are no-ops and `keep_lead` preserves
  continuation-leading whitespace for sep="" nodes.
- Offscreen `case_draft_edit_and_branches` written first; red run:
```
AttributeError: 'MainWindow' object has no attribute 'view_btn'  (editor/branch buttons missing)
```
- After implementing the built-in editor (New passage / Edit head with
  Save/Cancel, diff label, no $EDITOR) and the Branches bar (Rewind, Use as
  head, Delete leaf, Marked manuscript, Tail N): the case passes — manual
  append (source=user, sep "\n\n", planned->drafting), empty/cancel no-ops,
  edit history+diff, rewind keeps branches, explicit jump, nonleaf deletion
  refused with tree unchanged, leaf deleted, marked view and tail match CLI
  semantics. reader_model now carries the sanitized `absent` mentions for
  node warnings. A settlement-slot bug found by the case (KeyError on missing
  "scene" key wedging buttons) is fixed in the ops results and the done
  handler is now exception-guarded.
- Full suite: 240 passed.

## 1.7 — lore listing, classification and import

- Headless first (`tests/test_lore_ops.py`, 4 tests): CLI `lb`
  toggle/all/alias/world flows match the shared operations byte-for-byte in
  `lorebooks.json` AND in the next prepared prompt (matching/injected lore);
  usage refusals; import rules through the existing parser/discovery for
  World Info, V1/V2/V3 cards, PNG (tEXt chara) and valid-empty books;
  invalid/unreadable/no-card inputs write nothing; collision offers
  Replace/Cancel with the destination named, Replace re-verifies baselines
  and preserves existing registry metadata.
- Offscreen `case_draft_lore` written first; red run:
```
AttributeError: module 'longform_core.gui_window' has no attribute 'LORE'
```
- After implementing the Lore tab (tree listing with role classification,
  individual toggle, All on/off, Character + name, aliases, Mark World,
  picker import): the case passes — registry mutations match the ops, a
  constant entry of an ABSENT character's book is (correctly) not injected
  until reclassified World, the imported book appears classified via the
  existing discovery, the collision dialog is offered, invalid imports leave
  the registry and destination untouched, and a cancelled picker writes
  nothing. Toggled-on lore reaches the inspected prompt without any call.
- Full suite: 244 passed.
