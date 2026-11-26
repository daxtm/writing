## Purpose

Show each provider-generated answer while it arrives, keeping provisional candidates and retry attempts separate from accepted writing.

## ADDED Requirements

### Requirement: Every generated answer becomes visible before completion
The desktop SHALL display answer deltas before the response completes for
outline Generate/Reroll, scene Generate/Regenerate, draft Generate/Reroll/Add N,
continuity full/summary-only, compression, critique and passage revision/
Regenerate. Every requested candidate SHALL own a live preview.

#### Scenario: Paused answer for each operation family
- **WHEN** each listed action receives a first answer fragment and the fake provider blocks before its final fragment
- **THEN** that action's labelled preview contains the first fragment while the worker is still busy and no completed result exists
- **AND** the visible fragment does not require accepting, saving, selecting another stage or releasing the fake provider

#### Scenario: Concurrent candidates and additional batches
- **WHEN** two outline or draft candidates interleave fragments and a later reroll or Add N starts another batch
- **THEN** every candidate's own preview shows its fragments before completion, including candidates not currently selected
- **AND** opening another candidate shows its accumulated live text without combining candidates or changing accepted content

### Requirement: Preview lifecycle has stable identities
Preview subscribers SHALL receive start/delta/reset/complete events identified
by operation, logical candidate and attempt. Candidate identity SHALL be
assigned before output, not by completion order. A retry SHALL advance only its
attempt and reset only that candidate; completion SHALL identify its final result.

#### Scenario: Retry one of two candidates
- **WHEN** candidate A fails after partial text while B continues and A is retried
- **THEN** A's reset removes its failed-attempt text and its new deltas belong to a new attempt, while B's preview remains intact
- **AND** old-attempt, old-operation and settled-operation events cannot change either current preview

#### Scenario: Out-of-order completion maps to saved results
- **WHEN** candidate B completes before A
- **THEN** each preview's final selection refers to its own saved candidate/node, not its ordinal completion position
- **AND** existing final result ordering and reroll display-slot semantics remain compatible

### Requirement: Waiting and reasoning are distinct from answer text
Before answer deltas the GUI SHALL show Waiting for answer or Thinking status.
Hidden reasoning SHALL never enter answer previews. Delimiters split across
chunks SHALL not leak reasoning or corrupt the visible answer.

#### Scenario: Separate reasoning fields and split delimiters
- **WHEN** a fake response sends reasoning fields, inline thinking tags split across chunks, then answer content
- **THEN** the preview shows waiting/thinking status before the answer and only answer content afterward
- **AND** the completed answer equals existing reasoning-separated output and reasoning-only/no-answer responses retain existing error handling

#### Scenario: Ambiguous implicit thinking prefix
- **WHEN** content could still be an implicit thinking prefix under the existing completed-answer rules
- **THEN** the UI retains Thinking status instead of guessing that hidden content is answer text
- **AND** once an answer boundary is known, its next deltas appear before response completion; a response with no distinguishable boundary is not labelled as a streamed answer

### Requirement: Structured previews remain provisional until final validation
Incomplete JSON, tags and section markers SHALL appear as provisional raw
answer text, not editable accepted records. Existing completed-response
reasoning separation, extraction, cleaning, normalization, warnings and explicit
acceptance/save gates SHALL remain authoritative.

#### Scenario: Incomplete scene JSON and continuity tags
- **WHEN** scene-card JSON or continuity section/tag output pauses midway through a value
- **THEN** raw answer fragments are visible with a provisional label and Accept is unavailable
- **AND** completed output alone goes through the existing card/section parser, including existing invalid-raw recovery paths

#### Scenario: Same final output with and without previews
- **WHEN** identical synthetic complete responses run with and without a preview subscriber
- **THEN** final prompts, provider bodies, parsed results, warnings, accepted files/history and complete candidate saves are identical
- **AND** no partial raw preview becomes a saved passage, accepted bible/outline/scenes, report, state, summary, arc or revision

### Requirement: Streaming preserves cooperative settlement and saved work
Stop/failure SHALL prevent fragment acceptance, further requests/retries and
partial saves. Reading and Stop SHALL stay responsive; conflicting writes
SHALL remain blocked until worker settlement. Previously committed complete
work SHALL survive under existing operation-specific save semantics.

#### Scenario: Stop or fail a paused batch
- **WHEN** one candidate has completed and another is paused after provisional text, then Stop or an exhausted failure occurs
- **THEN** no incomplete candidate is saved or accepted, existing committed candidates remain and head/accepted planning/review content is unchanged
- **AND** failed/stopped previews cannot be accepted, controls recover only after settlement and a late delta cannot revive a closed preview

#### Scenario: Close or navigate while streaming
- **WHEN** the writer reads another scene/stage or closes during a paused response
- **THEN** progress stays labelled for the originating action/scene, reading remains responsive and close offers Keep open or Stop and wait
- **AND** no thread is killed or second project operation started

### Requirement: Preview delivery is optional and secret-safe
Without preview subscribers, existing CLI transcripts/progress and final
outputs SHALL remain unchanged. Preview payloads SHALL exclude credentials,
headers and hidden reasoning, including when an echoed credential spans chunks.

#### Scenario: CLI compatibility and redaction
- **WHEN** frozen CLI fixtures run without preview subscribers and GUI streams include synthetic secret echoes
- **THEN** CLI stdout/stderr snapshots remain unchanged for ordinary responses and every GUI event/preview is credential-redacted
- **AND** default concurrency, prompts, samplers, retry limits and final file formats remain unchanged

### Requirement: Offline checks prove intermediate visibility
Project checks SHALL run paused-fake-stream operation and offscreen widget
tests, not merely final-result assertions. Real Wayland streaming/Stop/close
acceptance SHALL remain separately recorded as PENDING until performed.

#### Scenario: Deterministic blocked-stream proof
- **WHEN** `./scripts/check.sh` runs with network guards and provisioned dependencies
- **THEN** all operation families, concurrent candidates, retry/reset, reasoning, Stop/failure and CLI parity tests execute and pass
- **AND** each visibility test asserts text while its fake completion gate is still closed; missing Qt or a failing case fails checks
