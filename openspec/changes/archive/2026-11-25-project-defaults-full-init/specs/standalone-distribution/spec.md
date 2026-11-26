## ADDED Requirements

### Requirement: Bundle complete new-project defaults inside the executable
The copied executable SHALL include the reviewed application-owned project
defaults and writer preset and create the same complete setup as source init.
Runtime, build and tests SHALL NOT access the owner's original source files.
No adjacent defaults directory, runtime download or manual preset copy SHALL
be required.

#### Scenario: Initialize away from the checkout
- **WHEN** only the executable is copied to an unrelated directory and runs `init` against a fresh path containing spaces with no Python/uv on PATH, no display, blocked network and the owner's source paths unavailable
- **THEN** it exits 0 and creates the same six files and seven directories as source init, including matching configuration and usable preset bytes
- **AND** output matches source after existing program-name/root normalization and neither cwd nor executable-adjacent files supply the defaults

#### Scenario: Repeat and override in the copied executable
- **WHEN** copied-executable init is repeated or supplies an explicit synthetic `--preset FILE`
- **THEN** source/frozen output, warnings, errors and create-missing-only behavior agree, including exact override bytes for a missing destination and preservation of an existing preset

#### Scenario: Build using only reviewed repository assets
- **WHEN** the existing standalone build runs with the owner's original project and preset files inaccessible
- **THEN** it packages only the reviewed application-owned defaults and completes without reading those originals
- **AND** `docs/standalone.md` and distributed third-party notices identify the bundled preset's recorded provenance and applicable source notices without exposing private data

#### Scenario: Missing or corrupt bundled defaults
- **WHEN** an installation or test build lacks a required defaults asset or contains an invalid bundled preset
- **THEN** init fails with an actionable diagnostic instead of reporting complete setup, reading the owner's paths or downloading a replacement
- **AND** it preserves existing project files and reports any completed writes
