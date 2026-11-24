# ADR-0010: Enter project credentials in the GUI using existing storage

- Status: Accepted
- Date: 2026-11-23
- Related: docs/ROADMAP.md guided workflow milestone 1; gui-api-key-setup; ADR-0007

## Context
Api currently resolves a nonempty project api_key before the configured
environment variable. GUI settings intentionally accept no key and display
only availability. The owner now requires credential setup without terminal
exports or JSON editing. New-project defaults and distributed assets must
remain credential-free. Shared operations already support provider factories.

## Options
1. Add a platform credential-store integration and application-wide lookup —
   avoids project-file persistence, but adds a dependency/backend, new lookup
   policy and frozen-runtime verification before basic GUI setup works.
2. Extend the current per-project credential mechanism with masked input,
   explicit storage consent and a session-only alternative — fits existing
   files/provider boundaries, but saved keys remain plaintext in project.json.

## Decision
Choose option 2 because the existing credential field already serves provider
calls and needs a GUI adapter, not another credential subsystem.
Provide masked entry, Use for this session, explicit Save to this project,
Replace and Clear saved key controls in Setup and the wizard. Do not prefill
or reveal an existing key. Label project persistence as plaintext and warn
that sharing/backing up the project includes a saved key; session use is the
default. Saving/clearing modifies only the intended credential field with
existing stale/unsafe-target checks, preserving unrelated config.

A session override is scoped to the current project/window and passed through
shared provider construction, never process-wide environment mutation.
Effective order is session override, existing project key, configured
environment key. Switching projects or closing clears the session override.
Clearing a saved key can expose an environment fallback; report its source
and availability without showing its value. Reopening requires entry again
unless the writer explicitly saved a project key or has an environment key.
Keep CLI resolution unchanged when no GUI session override is supplied.

Only explicit Test connection/Fetch limits/generation may contact the provider.
Redact every effective key source from events, errors and logs. Defaults,
bundles, fixtures and committed documents contain no real credential.

## Consequences
- Good: a first-time writer can configure and use the provider entirely in
  the GUI without a new platform service or credential-file schema.
- Good: existing projects, environment setup and CLI calls stay compatible.
- Bad: explicit project persistence is plaintext and can leak through sharing
  or backups; session-only mode requires reentry after closing.
- Bad: the earlier no-key-entry desktop requirement must be deliberately
  revised when this change is selected; it is not silently satisfied already.
