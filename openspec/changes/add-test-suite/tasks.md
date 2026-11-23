# Tasks

Build on foundation commits `09bb632` and `2609c34`. Keep code in `longform.py`;
do not read private projects/presets or change the existing check script contract.
Each checkbox is one small commit with its tests. See `design.md` for exact
helper input shape, preservation rules, fixtures, and API coverage.

## 1. Establish offline regression coverage

- [x] 1.1 Add `tests/conftest.py` with repo-root `sys.path`, synthetic temporary-project fixtures, credential removal, and fail-closed network guards (including checker subprocesses); add `tests/test_check.py` asserting expected all-scene/selected-scene CLI stdout and saved reports against the proposed pure `check_report` helper. Test: `uv run --with pytest --with httpx pytest -q tests/test_check.py` must initially fail because `check_report` does not exist; record that red result before implementation.
- [x] 1.2 Extract `check_report` inside `longform.py` and delegate only report calculation from `cmd_check`; extend `tests/test_check.py` for empty/no-hit scenes, active versus inactive branches, literal/case-insensitive banned snippets, n-gram stopword filtering, boundaries, thresholds, ties, top limit, and sorted locations. Test: the command from 1.1 now passes with unchanged report formatting, stdout, and output paths.
- [x] 1.3 Add `tests/test_utils.py` for `clean_continuation`, `split_bible`/`join_bible`, `extract_json_array`, and `extract_tagged`, including the valid, truncated, malformed, empty, and normalization cases in the design table. Test: `uv run --with pytest --with httpx pytest -q tests/test_utils.py` passes without API setup.
- [x] 1.4 Add `tests/test_lore.py` for `key_match`, `entry_triggered`, and `name_variants`, including case/whole-word/regex behavior, invalid regexes, all selective secondary-key modes, aliases, and first-name ordering. Test: `uv run --with pytest --with httpx pytest -q tests/test_lore.py` passes with synthetic dictionaries only.
- [x] 1.5 Add `tests/test_prompt.py` for `writer_sampling` and `render_story_string`, covering numeric defaults, mapped/ignored parameters, macro stops, DRY values and malformed JSON, optional fields, conditionals, and trim behavior. Test: `uv run --with pytest --with httpx pytest -q tests/test_prompt.py` passes using minimal synthetic presets.
- [x] 1.6 Add `tests/test_tree.py` for add/head/chain, numeric child ordering, branch selection, separators, non-leaf deletion refusal, head rewind, and temporary-file save/reload. Test: `uv run --with pytest --with httpx pytest -q tests/test_tree.py` passes with no files written outside `tmp_path`.
- [x] 1.7 Add `tests/test_api.py` using MockTransport-backed replacements for module-level HTTP calls, fake project/log/calibration objects, no-op recorded sleeps, and disabled progress; cover GET/error/retry exhaustion, chat/text request bodies, SSE content/reasoning/usage/finish/malformed chunks, no-answer errors, and rejected-extra fallback. Include a test proving unexpected network calls are blocked. Test: `uv run --with pytest --with httpx pytest -q tests/test_api.py` passes with real credentials removed and no network or retry delays.

## 2. Verify the existing check entry point

- [x] 2.1 Add `tests/test_check_script.py` exercising the unchanged shell script in a temporary fixture with fake python3/uv commands: prove syntax/help/pytest command order, a failing pytest exit propagates, and missing uv with `tests/` is an error. Then run `uv run --with pytest --with httpx pytest -q tests` and `./scripts/check.sh` against the real suite; both must pass, and the latter must show `== syntax`, `== cli smoke`, `== tests`, and a nonzero passing test count. Adding `tests/` activates existing discovery: leave `scripts/check.sh` unchanged unless these tests expose a genuine contract defect; CI uv installation remains outside this change.
