## Purpose

Let authors watch every draft candidate arrive without changing complete-branch persistence or explicit control over accepted prose.

## MODIFIED Requirements

### Requirement: Output is progressive and candidates are complete saved branches

The desktop SHALL show live answer text for every candidate, including
multi-candidate Generate, Reroll selected/all and Add N, without blocking reading.
Unsaved partial output SHALL be visibly provisional, never accepted or stored as
a passage. Complete responses SHALL use existing cleaning, cutoff, end and
absent-mention rules.

#### Scenario: One response streams
- **WHEN** a fake provider pauses between text chunks for N=1
- **THEN** the preview shows successive answer chunks while manuscript navigation still works and before the request completes
- **AND** no partial node exists before the complete response is cleaned and saved

#### Scenario: Multiple candidates complete
- **WHEN** N>1 fake responses interleave chunks and complete under the configured max_parallel
- **THEN** each candidate shows its own answer text before completion with stable preview identities that map to final node identities
- **AND** every saved node retains existing source/model/finish/steer/separator/lore/cast/end/trim/absent metadata

#### Scenario: A stream is retried
- **WHEN** an incomplete attempt fails and the existing retry policy makes another attempt
- **THEN** only the affected candidate's provisional preview resets to a new attempt rather than concatenating failed-attempt fragments into the successful passage
- **AND** other candidates and their saved nodes remain unchanged

#### Scenario: Reroll and add candidates stream
- **WHEN** the writer rerolls selected/all candidates or chooses Add N against the captured batch parent
- **THEN** every new response has its own live provisional preview before completion and completed responses retain existing tray-slot and shortfall behavior
- **AND** original saved branches and accepted head remain unchanged until a separate explicit action
