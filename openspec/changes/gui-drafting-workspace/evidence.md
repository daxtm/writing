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
