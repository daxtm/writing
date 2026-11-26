# Implementation evidence — gui-generated-text-streaming

All checks run from the repo checkout on `feat/guided-workflow`. Dates: 2026-11-24.

## Commands and results

| Command | Result |
| --- | --- |
| `./scripts/check.sh` | `482 passed` (run 4× consecutively after the final commit; includes `py_compile`, CLI `--help`, the `== standalone` frozen-executable stage and the source pytest stage) |
| `uv run --with pytest --with httpx pytest -q tests/test_api.py` | preview families included in the 482-total suite; 11 new MockTransport preview tests |
| `uv run --with pytest --with httpx pytest -q tests/test_cancel_and_stale.py` | `10 passed` (3 consecutive runs) |
| `uv run --with pytest --with httpx pytest -q tests/test_review_ops.py` | `62 passed` (3 consecutive runs) |
| `timeout 300 env uv run --with httpx --with 'pyside6>=6.12.0,<6.13' python tests/qt_widget_cases.py` | 47 `ok` cases, 0 failures (includes the 4 registered `case_stream_*` cases; run repeatedly) |
| `openspec validate gui-generated-text-streaming --strict` | `Change 'gui-generated-text-streaming' is valid` |
| `openspec validate --all --strict` | `Totals: 12 passed, 0 failed (12 items)` |

Guards preserved: `scripts/check.sh` never skips `== standalone`; `tests/test_standalone.py`
runs the frozen executable away from the checkout with the test-only network guard;
`tests/test_qt_cases.py` runs the offscreen Qt subprocess harness with the
unregistered-case guard enforced (all four `case_stream_*` cases are registered in `CASES`).

## Coverage matrix

Legend: families × candidates × attempts; "attempt reset" = a transport retry or
extra-parameter fallback re-streams under a fresh `attempt_id` and the retired
attempt can never revive its preview.

| Family | Where | Candidates | Attempts / reset | Visible before completion | No-subscriber byte parity |
| --- | --- | --- | --- | --- | --- |
| Provider splitter (`AnswerStream`) | `tests/test_api.py` (11 tests, MockTransport paused byte streams) | n/a | transport-retry reset (`test_preview_transport_retry_resets_attempt`), extra-parameter fallback reset (`test_preview_extra_parameter_fallback_resets_attempt`) | split think delimiter, reasoning field, ambiguous implicit prefix hold, nonthinking immediate, no-answer-never-completes, split-secret redaction | yes (transcripts unchanged; `test_streamed_split_secret_is_never_emitted`) |
| Indexed batch `many`/`chat_many` | `tests/test_api.py` (`test_many_indexed_previews_paused_reverse_completion`, `test_chat_many_preview_events_per_slot`) | per-slot stable ids, interleaving, out-of-order completion, exact request counts | slot-bound subscribers | yes (paused gates) | yes (zero-arg `one()` unchanged) |
| Planning outline Generate (2 candidates) | `case_stream_planning` + 6 `tests/test_planning_ops.py` preview tests | 2 interleaved, own candidate ids | per-candidate keyed | yes (fragment visible while `_busy`, nothing written pre-release) | yes (CLI parity frozen) |
| Planning scenes Generate | `tests/test_planning_ops.py` | single | single | yes | yes |
| Draft Generate/Reroll/Add N | `case_stream_draft_candidates`, `case_stream_retry_stop`, 3 `tests/test_draft_parity.py` preview tests | 2 interleaved + reroll-all batch | late/retired/settled events ignored; retry resets only its attempt | yes (waiting/streaming labels, per-candidate fragments) | yes (legacy delta channel separate; no duplication) |
| Stop/failure (draft) | `case_stream_retry_stop`, `tests/test_cancel_and_stale.py` (2 new tests) | paused slot of a 2-slot batch | stop at chunk/save boundaries | fragment visible before Stop; no completion fabricated | yes |
| Continuity full + summary-only | `case_stream_review`, `tests/test_review_ops.py::test_review_previews_stream_before_completion` (parameterized) | single | single | raw incomplete sections visible pre-release; `state.md`/`summaries.json` untouched pre-accept | yes (byte-identical files/history) |
| Compression | same | single | single | raw arc visible pre-release; nothing appended pre-accept | yes |
| Critique | same | single | single | raw report visible pre-release; saved only on Save | yes |
| Passage revision + Regenerate | same + `case_stream_review` revise phase | single + regenerated attempt | Regenerate re-streams a fresh attempt | yes | yes (accept updates node + history once) |
| Redaction (GUI preview panes) | `case_credentials_redaction` (pre-existing, still green) | n/a | split secrets held back across chunk boundaries in previews | yes | yes |
| Coalesced flush | `longform_core/gui_window.py` (`_schedule_preview_flush`/`_flush_preview_pane`) | n/a | one repaint per GUI event-loop turn while blocked | exercised by every paused Qt case (fragments visible while gates are closed) | n/a |
| Failure labelling | `case_stream_retry_stop`, `longform_core/gui_window.py` settlement | completed vs failed slot of a reroll batch | non-complete previews marked failed at settlement (candidate_failed `k` is completion-order and is never used for slot association, per design) | yes | n/a |

## Commit sequence (this change)

- `41c8c73` task 1.1 — `case_stream_planning` baseline (failing first)
- `887d0a0` task 1.2 — `AnswerStream`, `_post`/`chat`/`complete` preview hooks, 8 API tests
- `fd30d69` task 1.3 — indexed `many`/`chat_many`, paused SSE tests
- `65537a2` task 1.4 — planning ops forwarding + outline/scenes GUI panes
- `a326339` task 1.5 — `generate_candidates(preview_events=)`, draft tray/pane routing, parity tests
- `a03f433` — shared preview envelope alignment in planning op tests
- `1d8aba3` task 1.6 — review/continuity/revision previews + `case_stream_review`
- `6f87407` task 1.7 — settled failure labels, coalesced flushes, Stop/stale coverage

## Native Wayland acceptance — PENDING

Real Wayland acceptance for live previews (deltas appearing on the desktop,
focus behavior during streaming, candidate switching while streaming, Stop
and close during a live stream, scaling/theme) has **not** been observed and
remains an owner desktop step, exactly as recorded for
`gui-drafting-workspace` and `gui-project-planning` (`evidence.md` in each).
Offscreen Qt cases are deterministic substitutes, not a substitute for this
acceptance.
