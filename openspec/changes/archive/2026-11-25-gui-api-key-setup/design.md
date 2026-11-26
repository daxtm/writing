# Design

## Context

See proposal.md — Why. Full init (`project-defaults-full-init`, ADR-0010) is
already implemented on `feat/guided-workflow`; do not reimplement defaults.
Implement this before streaming, then navigation, then the setup wizard.

Relevant existing seams:

- `Api.__init__` resolves project then environment, builds Authorization and
  currently has no session input. `get("/plan")` already serves limits.
- `draft_operations._provider` supplies `provider_factory(p)` to draft/planning/
  review operations. `review_operations.provider_for` also serves CLI adapters.
- `planning_operations.settings_state` returns `env_value` despite its
  “never includes a key value” docstring; remove that value from public state.
  `project_overview` and `draft_operations.session_info` expose availability,
  but do not account for a window-only credential.
- `fetch_limits` rejects missing disk/environment credentials before consulting
  its factory; session-only mode must fix that precondition too.
- `save_settings` patches nonsecret fields over exact `project.json` bytes.
  `settings_baseline`, `_stale_check`, canonical-root and safe-path helpers
  already implement the persistence boundary.
- `MainWindow._build_setup_tab`, `_load_settings_form`, `_update_setup_tab`,
  `_rebind_root`, `_dispatch` and `closeEvent` own presentation/lifecycle.
  Every generation call already accepts `_provider_factory`.
- `Api` logs output/raw reasoning/bad chunks; batch failures log exceptions.
  Limits scrubbing only knows disk/environment credentials and saves unsanitized
  metadata. Fix these existing leak boundaries, not just widget labels.

## Goals / Non-Goals

**Goals:** one effective credential policy across all GUI calls, no secret in
public state, safe explicit writes, unchanged ordinary CLI behavior.

**Non-goals:** encryption/keyrings, global credentials, new provider API,
process-wide environment changes, automatic validity checks or new storage.

## Decisions

### Extend existing credential/provider boundaries

Follow [ADR-0011](../../../docs/adr/0011-gui-project-credentials.md) and
[ADR-0007](../../../docs/adr/0007-shared-writing-operations.md); they are fixed,
not reopened here. Add an optional keyword session override to `Api` construction
with no-override behavior identical to today. Never place the override in
`Project.cfg`, a saved settings payload or `os.environ`.

`MainWindow` owns a private session value and one helper wrapping its existing
provider factory. Capture the current root, session and redaction context before
dispatch. The production wrapper constructs `Api` with that override; injected
`provider_factory(p)` fakes remain usable and their outputs/errors are subject
to the same sanitization. All GUI calls (limits, connection test, planner,
writer, summarizer, critic, editor, including cached revision/continuity provider
paths) use this wrapper, never an ad-hoc direct `Api` call.

Expose only `available` and `source` (`session`, `project`, `environment`,
`missing`) in read-only views. Extend overview/session prerequisite inputs
with optional availability information rather than fake credentials in config.
For `fetch_limits`, accept an optional effective-availability input from the
GUI wrapper so the early disk-only rejection cannot block a valid session;
default behavior retains the existing missing-key/no-request regression.
CLI `provider_for` and command construction do not pass a session override.

Alternative rejected: mutate a temporary `Project.cfg["api_key"]` or environment.
Both can leak into snapshots/logs or affect another window/CLI adapter.

### Separate masked entry, activation and persistence

Add a Credentials group to `_build_setup_tab` with these stable control roles:

| Control | Behavior |
|---|---|
| `credential_entry` | Password-mode line edit, empty on load, no reveal/prefill |
| `credential_status` | Availability, winning source and environment name only |
| `credential_use_btn` | “Use for this session”, default credential action |
| `credential_clear_session_btn` | Clear window override, expose fallback |
| `credential_save_btn` | “Save to this project” when absent; “Replace saved key” when present |
| `credential_clear_saved_btn` | Clear only saved `api_key`, not session/environment |
| `credential_test_btn` | Explicit “Test connection” |

Trim outer whitespace as existing resolution does; reject empty Use/Save
without changing effective credentials. Entry is inert until an action. Clear
the entry after successful Use/Save; activation is not proof of provider validity.
Save/Replace confirm plaintext `project.json` persistence and sharing/backup
exposure; Clear confirms its target and explains any fallback. Saving a key does
not replace an existing session override. Failed Save neither activates nor
claims to persist it.

Use an explicit credential patch operation beside `save_settings`, reusing
its baseline/parsing helpers and checking configuration, root, destination and
temporary-path safety. Change only `api_key`; Clear writes an empty value.
Do not use `save_input`, backup the old credential, or put it in histories.
Refresh the nonsecret settings baseline after success; resolve dirty unrelated
settings before replacing their loaded baseline. Cancel/failed/stale Save
preserves edits and cancels any deferred transition.

Clear session and entry on successful different-root binding and on actual
close; a cancelled/failed Open keeps the current project's session. Disable
credential changes while any operation is active. Two windows have no shared
session state. This promises lifecycle removal, not cryptographic memory erasure.

### Test the existing plan lookup, never generation

Add `planning_operations.test_connection` using the provider factory and
existing `get("/plan", token=..., on_retry_event=...)` on `_dispatch` with
kind `credential_test`. One plan lookup uses existing retry/timeout behavior;
return a sanitized success/failure summary, discard response content and write
nothing (including `limits.json`). Stop/close follow the existing worker gate.
Missing credentials explain recovery before factory/request construction.
No external endpoint facts or new APIs are assumed.

### Redact before events, diagnostics and persistence

Extend `_scrub_text`/`_sanitize_raw` and the provider/logging boundary to know
all nonempty session, saved-project and configured-environment values, not
only the winning one. Remove `env_value` from settings state and replace any
consumer with private sanitization context. Keep opaque file baselines private;
never emit them or credentials in result objects, reprs, exception chains,
headers, raw config, worker events or startup/settlement diagnostics.

Sanitize provider echoes before `log_call`, malformed-chunk/failure logging,
limits metadata saving and generated-output persistence, so saved candidates
cannot later leak an echoed key into export. Preserve the existing file
schemas and ordinary output bytes; credential echoes are deliberately redacted.
For split callback fragments use a streaming redactor retaining potential
secret-prefix suffixes until safe to emit; never emit an unsafe prefix and
try to retract it afterward. The following streaming change reuses this
boundary. Sanitize at source, not only in `_on_worker_event`, because the
payload itself must be safe. Error adapters and `draft_worker` must not revive
raw exception strings.

Alternative rejected: regex-only masking of known key prefixes and masking
labels alone; arbitrary synthetic values and provider-echoed fragments bypass it.
No claim is made to discover unknown credentials in author-written documents.

## Verification

- `tests/test_api.py`: MockTransport verifies Authorization precedence and
  no-override compatibility, echoed errors/results/logs and chunked redaction.
- `tests/test_planning_ops.py`: credential-only patch preservation, no old-key
  history, stale/symlink/temp refusal, availability-only public states,
  session-only limits and explicit plan-only test with zero writes.
- `tests/test_review_ops.py`, `tests/test_draft_parity.py`: factory propagation,
  normal request/prompt/output/transcript parity and export echo exclusion.
- Register `case_credentials_session`, `case_credentials_storage`,
  `case_credentials_connection` and `case_credentials_redaction` in
  `tests/qt_widget_cases.py` `CASES`; use `PlanningFake`, `ReviewChatFake`,
  injected pickers/choices, `_pump` and actual worker signals. Existing
  `case_planning_settings_limits` changes intentionally from “no key entry”
  to the explicit credential exception, not weaker secret assertions.
- `tests/test_qt_cases.py` and `tests/test_check_script.py` keep missing Qt,
  unregistered cases and failed subprocesses fatal through `scripts/check.sh`.

## Risks / Trade-offs

- [Plaintext project storage can be copied] → warn before each explicit Save/
  Replace; session-only is the default, no history copies.
- [A cached provider or disk-only prerequisite ignores session state] → table-
  driven all-family tests and root/window isolation assertions.
- [Redaction changes normal prose or leaks chunk prefixes] → exact sentinel
  matching, split-boundary tests and unchanged ordinary-response parity fixtures.
- [Python retains old string allocations] → do not promise secure memory wiping.
- [Offscreen is mistaken for Wayland acceptance] → implementation evidence must
  leave real masked entry/focus/clipboard/Stop/close acceptance PENDING until run.

## Migration Plan

No migration/reset. Existing project/environment lookup continues to work;
the GUI adds opt-in actions against the existing field. Rolling back the GUI
does not remove explicitly saved keys; users can Clear them before rollback.
Record actual checks and pending/native Wayland results in this change's
`evidence.md` during implementation. No new ADR is required beyond the linked
accepted storage and operation decisions. No blocking open questions.
