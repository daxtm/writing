# New-project defaults (ADR-0010)

`longform_core/resources/` holds two application-owned runtime resources used
only by initialization (`init DIR`, GUI Create on both its paths):

- `project_defaults.json` — supported nonsecret settings for a new
  `project.json` (`Untitled` title; role/model, sampler, budget, summary,
  banned-phrase and n-gram values).
- `writer_preset.json` — the reviewed SillyTavern master export copied
  byte-identically into new projects.

They are derived, reviewed copies of the owner-selected source files listed
below. The originals are private, untracked and never required at startup,
build or test time.

## Source filenames and provenance

- Source project settings: `project.json` (owner-selected Featherless
  configuration).
- Source preset: `56295265-LLam_ception-1.3.json` (owner-selected SillyTavern
  master export; no third-party license text is available for it and none is
  invented — the sidecar notices record its provenance only, see
  `docs/standalone.md` and `dist/THIRD-PARTY-NOTICES.txt`).

Both were read read-only during implementation to produce the tracked
derivatives; nothing is copied back and the sources are never fixtures.

## Required sanitizing overrides

The three forced fields for every new project, regardless of the source
values:

- `api_key`: forced empty.
- `api_key_env`: forced `FEATHERLESS_API_KEY`.
- `roles.writer.preset`: forced project-relative `writer_preset.json`.

The source project already held exactly these values; the review enforces them
schema-level so a future re-derivation cannot ship credentials silently.

## Supported-field selection and review outcome

Every nested value of both resources was reviewed recursively for credentials,
auth/secret fields, local paths and private story content:

- `project_defaults.json` contains only the supported top-level fields
  (`title`, `target_words`, `api_base`, `api_key`, `api_key_env`,
  `max_context_fallback`, `context_safety_margin`, `prompt_budget`,
  `chars_per_token_default`, `max_parallel`, `request_timeout_s`, `roles`,
  `budget_tokens`, `summary`, `banned_phrases`, `ngram`) with the source's
  reviewed models, sampler values, preset overrides and budgets. No
  unsupported credential/path metadata existed in the source and none was
  copied.
- `writer_preset.json` keeps the export's `instruct`, `context`, `sysprompt`
  and `preset` objects unchanged (sequences, story-string template, system
  prompt text, sampler values). The system-prompt text is generic roleplay
  instruction prose with `{{char}}`/`{{user}}` macros; it contains no private
  story content, names, paths or credentials. The `name` metadata fields
  identify the preset (`LLam@ception-1.3`) and are retained as-is.
- No field needed redaction beyond the forced three; none was discarded.

## Schema validation (fail closed)

`longform_core/defaults.py` validates both resources against the explicit
approved-field schemas in that module (field paths and value kinds, recorded
with the resources). Unknown fields, wrong types, a missing required field, an
unreadable/invalid resource, or a forced field not holding its reviewed value
raise a sanitized `DefaultsError` naming the field path and expected kind —
never a value — and initialization fails closed. There is no fallback to the
old application defaults, no environment substitution and no network fetch.

Tests use synthetic variants (sentinel fields such as injected key/path
metadata) and assert they are rejected without reaching accepted output or
diagnostics; the owner's original files are blocked from test reads at the
exact source paths and never appear in fixtures.
