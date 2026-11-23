# Design

## Context

See [proposal.md](proposal.md) for motivation. The prerequisite foundation commits
already track `longform.py` and make `scripts/check.sh` invoke pytest whenever
`tests/` exists. No test runner, packaging configuration, or runtime dependency
change is needed. API code currently calls module-level `httpx.get` and
`httpx.stream`; retries sleep and progress reporting can create threads.

## Goals / Non-Goals

- Protect current deterministic behavior and the existing report command before
  refactoring; make all test inputs synthetic and all side effects temporary.
- Do not convert the CLI into a package, reorganize unrelated helpers, fix
  speculative API behavior, or change the shell check contract.
- Follow [ADR-0002](../../../docs/adr/0002-single-file-cli.md): pure extractions
  remain in the script until a package trigger is actually met.

## Decisions

### Import the script directly

`tests/conftest.py` inserts `Path(__file__).resolve().parents[1]` into `sys.path`;
tests import `longform`. The `__main__` guard keeps imports inert. Prefer this over
editable installation or adding a package just for tests. Keep fixtures in
conftest only where shared; use `tmp_path`, small fake projects, and minimal
synthetic preset dictionaries instead of copying real projects or presets.
Remove real credential environment variables in fixtures; API tests use a fixed
dummy key and a reserved test host such as `https://api.example.invalid/v1`.

Install an autouse guard that raises on real `httpx.HTTPTransport.handle_request`
and unexpected socket connections. MockTransport handles allowed requests without
this real transport. Subprocess checker tests use credential-free temporary
projects and an inherited test-only socket guard (a temporary `sitecustomize.py`
on `PYTHONPATH`), so an accidental live call in the CLI also fails immediately.
This is simpler than creating a new production injection framework.

### Extract the checker calculation, not its command

Introduce this helper inside `longform.py`:

```python
check_report(scene_texts, banned_phrases, n, min_count, top, title) -> str
```

`scene_texts` is an ordered list of
`(scene_id, [(node_id, node_text), ...], joined_active_text)` tuples.
Only nodes on the active chain are supplied; `joined_active_text` is `Tree.text()`
so separator behavior remains unchanged. `title` is the full existing first line,
including `# Check ... (timestamp)`; the helper never reads the clock or files.
It returns the complete report with its final newline.

Keep scene resolution, project reads, tree traversal, `now()`, output path, file
write, report printing, and the final `wrote ...` message in `cmd_check`. Preserve
case-insensitive non-overlapping literal banned matches, 50-character snippet
context and whitespace collapse, the existing `[a-z']+` tokenizer/STOP filter,
within-scene n-grams across joined nodes, minimum count, reverse `(count, gram)`
sorting, top limit, and sorted scene locations. Ignore whitespace-only banned
entries as today. No cross-scene n-grams; inactive branches stay excluded.

The first acceptance test imports the missing helper (initially red), builds a
synthetic two-scene project, compares its pure report against fixed expectations,
then invokes the CLI with `sys.executable longform.py check TEMP_DIR` and
`--scene s1`. Freeze time in direct tests; normalize only the CLI title's timestamp
for subprocess comparisons. Assert the saved file, stdout report, and trailing
`wrote ...` line separately. Keeping the computation inline in `cmd_check` would
force every edge case through filesystem setup instead.

### Cover the existing helper contracts

Use table-driven tests rather than snapshots of generated fiction:

| Area | Cases and assertions |
|---|---|
| `clean_continuation` | End/header tokens; scene-end variants; length truncation after a complete sentence and the 30% cutoff; blank lines; leading whitespace for new text versus continuation; returned flags. |
| `key_match`, `entry_triggered`, `name_variants` | Case/whole-word matching; valid and invalid regex keys; all four selective secondary-key modes and defaults; aliases and multiword first names, preserving current order/duplicates. |
| `split_bible`, `join_bible` | Preamble, multiple/empty sections, no headings, normalized final newline; split/join/split equivalence for normalized input, not arbitrary byte preservation. |
| `extract_json_array`, `extract_tagged` | Tagged/fenced arrays, malformed/non-array text; last complete tag pair, unfinished final opening tag, absent tags, case-insensitive tags. |
| `writer_sampling`, `render_story_string` | Defaults and numeric conversion; optional top-k/max tokens/stops; macro expansion, DRY fields and malformed breaker JSON; unsupported sampler reporting; conditional fields, missing fields, trim/newline behavior. |
| `Tree` | Add/children ordering, head/chain and alternate branches; default/empty/space separators; blocked non-leaf deletion and head rewind on leaf deletion; save/reload using a temporary project. |
| Checker | Banned matching/snippets; stopword filter; threshold/ties/top; sorted locations; empty scenes/no hits; selected scenes and inactive branches; pure/CLI report parity. |

### Test API behavior through HTTP mocks

Use `httpx.MockTransport` with synthetic JSON and SSE responses. Rather than
changing production APIs to accept a client, monkeypatch `longform.httpx.get`
and `longform.httpx.stream` in a scoped fixture to delegate to a real
`httpx.Client` using that transport; close the client at fixture teardown.
The handler rejects unrecognized URL/method combinations and records requests
for assertions. Do not stub `_post` in tests intended to exercise streaming.

Use minimal fake project objects for `cfg`, `f`, `record_calib`, and `log_call`.
Replace `time.sleep` with a recording no-op; freeze time where asserted and disable
progress (`progress=False`) rather than waiting on threads. Cover GET success and
non-retryable errors; transient HTTP/transport retries and seven-attempt
exhaustion; chat versus text endpoint/payload mapping; streamed content, reasoning,
usage, finish reasons, malformed chunks and `[DONE]`; missing-answer errors; and
the existing 400/422 unsupported-extra fallback on text completion. Assert returned
values, captured bodies, and fake log/calibration side effects, never real billing
or model availability. Mocking whole Api methods instead would miss parsing and
payload regressions.

### Reuse existing check discovery

Adding `tests/` already activates
`uv run --with pytest --with httpx pytest -q tests` in `scripts/check.sh`.
The final task tests that path, failure propagation, and the missing-uv diagnostic
using temporary fixtures and a controlled PATH. Do not edit the script merely to
repeat its existing behavior. A shell-contract test can copy the unchanged script
to a temporary repository with fake python3/uv executables, proving command order
and exit propagation without recursively running pytest.

CI uv installation remains the explicit final roadmap phase. Until that lands,
CI can fail with the intended missing-uv diagnostic once `tests/` exists; do not
silence it or describe CI as passing.

## Risks / Trade-offs

- Characterization can encode existing quirks → use explicit expectations and
  preserve behavior here; separately propose intentional behavior changes.
- Mock HTTP cannot verify provider compatibility → that is outside this offline
  suite; recorded request/response contracts remain deterministic.
- Module-level monkeypatching is broad → scope fixtures, close clients, and fail
  unexpected network paths instead of trusting developer credentials.
- uv may download dependencies → provision them before offline execution; tests
  themselves never require network access.

## Migration / Rollback

Build on the two foundation commits, add the failing acceptance test, then the
small helper extraction and the remaining tests. Run the documented suite and
`./scripts/check.sh`. There are no project schema changes or data migrations;
rollback removes the suite and restores the inline report calculation.
