# Proposal

## Why

The current GUI only reports credential availability, so a new writer must use
a terminal or edit JSON before generating anything. Existing settings and
provider factories need a credential adapter, not a separate secret service.

## What Changes

- Extend Setup with masked entry, Use for this session, explicit Save to this
  project/Replace/Clear saved key, plaintext-storage consent and source/status.
- Apply session > project > environment precedence in this window's provider
  calls; clear session state on project switch/close without changing CLI lookup.
- Add explicit Test connection and redact credential values from provider
  results, events, diagnostics, logs and export.
- Fix existing settings/provider paths; no new credential subsystem is needed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `desktop-project-planning`: intentional credential entry/storage exception to
  nonsecret settings, session lifecycle, explicit testing and redaction.

## Impact

Extends `api.py`, shared planning/draft/review provider construction and
`gui_window.py`; uses the existing worker and offline Qt harness.
ADR-0007 and ADR-0011 are fixed decisions; no dependency or file-format change.
`project-defaults-full-init` is already implemented on this branch. Implement
this before `gui-generated-text-streaming`, then navigation and the wizard.

Out of scope: keyring/encryption, shared keys/cloud sync, automatic connection
tests, new provider endpoints, streaming, wizard/layout redesign and shipping.

After implementation, run
`QT_QPA_PLATFORM=wayland uv run --script longform.py gui ./credential-demo`.
Choose Create and Setup, enter a key and Use for this session: status says
“Available — session”, generation is enabled and `project.json` remains
credential-free. Only Test connection contacts the provider for that test.
