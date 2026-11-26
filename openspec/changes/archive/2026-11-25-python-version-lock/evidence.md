# Evidence — python-version-lock

Owner-authorized build of the CPython 3.13 minor policy (ADR-0013) on
`feat/guided-workflow` (baseline `dd9803e`, whose >=3.12 crash-floor assertion
and Qt/None-refcount regression remain unchanged). Each task is one commit;
tasks 1.1–1.3 were implemented test-first against failing contracts.

## 1. Check-entry-point contracts (task 1.1, commit `f547fcd`)

`uv run --with pytest ... pytest -q tests/test_check_script.py` on the
baseline: **25 failed** — for missing enforcement (fake commands and synthetic
pins present, real `scripts/check.sh` unchanged). Contracts: the verified
`== python: CPython 3.13.<patch>` line before the phase markers, `uv python
install --upgrade cpython@3.13` provisioning, an explicit
`--python cpython@3.13 --managed-python` request on every `uv run` phase
despite a conflicting `UV_PYTHON`, acceptance of different 3.13 patches
(3.13.9 / 3.13.15) without policy edits, early failure for missing/empty/
multi-line/patch-specific/range/variant-suffixed/non-CPython pins, wrong
implementation/minor reports, provisioning failure, and missing uv.

## 2. Pin, mirror and launcher guard (task 1.2, commit `36328d7`)

- New authoritative `.python-version` = `cpython@3.13` (trailing newline); no
  patch pin anywhere. `longform.py` and `longform_core/cli.py` PEP 723
  `requires-python = ">=3.13,<3.14"`.
- `enforce_python_pin()` in the launcher exits nonzero when the running
  interpreter's minor disagrees, because `uv run --python 3.12/3.14 --script`
  only *warns* (observed on uv 0.12.13).
- Observed from `/tmp/opencode` (outside the checkout):
  `uv run --script .../longform.py --help` → exit 0 (installed 13 packages on
  first run for the new range); `--python 3.12` → exit 2, `--python 3.14` →
  exit 2, both printing the pin-mismatch diagnostic before any command.
- Runtime guidance updated in `AGENTS.md`, `openspec/config.yaml` and the
  launcher docstring: patch updates automatic, minor bumps reviewed.

## 3. Builder verification and sidecar (task 1.3, commit `0e2bf09`)

`scripts/build-standalone.sh` validates the pin, provisions with
`uv python install --upgrade cpython@3.13`, creates its cleared venv with
`--python cpython@3.13 --managed-python`, verifies CPython 3.13.x before
`uv pip install`/PyInstaller, and keeps the independent `>=3.12` assertion.
Fake-provisioning tests cover automatic patch refresh, host/UV_PYTHON
conflicts, PyPy/3.12/3.14 rejections before pip or PyInstaller, provisioning
failure and invalid pins (14 passed). Real build sidecar:

```json
"interpreter": {"requested": "cpython@3.13", "implementation": "CPython",
                "version": "3.13.15"}
```

(the patch is recorded as observed, never asserted against a constant).

## 4. Cache validation (task 1.4, commit `f9b7ac5`)

`tests/test_standalone.py`'s `built` fixture rejects reuse when the pin, the
sidecar's requested minor, its recorded implementation/version, or the actual
build-venv implementation/minor disagree, or metadata is missing/unreadable;
patch-only differences (3.13.9 artifact / 3.13.15 venv and reversed) do not
invalidate; a failed rebuild fails the session instead of accepting the old
executable (11 synthetic contracts, no real rebuild needed).

## 5. Check entry point (task 1.5, this commit)

`./scripts/check.sh`:

```
== python: CPython 3.13.15
== syntax
== cli smoke
== standalone        (rebuild; frozen suite: 70 passed in 37.18s)
== tests             (source/offscreen suite: 515 passed in 17.10s)
```

exit 0. The frozen phase ran the new policy/cache/builder contracts and the
unchanged `test_build_python_does_not_drop_none_refcount_under_qt_churn`; the
source phase ran the check-script, pin/mirror and launcher-guard contracts.
`dist/longform` was rebuilt; `dist/longform-build.json` records the values
above. `openspec validate --all --strict` → **13 passed, 0 failed**.
`uv run --script longform.py --help` from outside the checkout → exit 0;
`dist/longform --help` → exit 0.

## PENDING

Real Wayland acceptance remains PENDING and is unchanged by this change: the
existing owner desktop walkthroughs in
`openspec/changes/standalone-gui/evidence.md` and each guided-workflow
change's `evidence.md` stay pending; no frozen-window, interactive
scaling/theme or mouse/keyboard behavior is claimed here.
