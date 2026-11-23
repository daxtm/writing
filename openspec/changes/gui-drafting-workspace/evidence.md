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
