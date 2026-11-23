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
