# ADR-0015: Keep Android projects private and transfer portable snapshots

- Status: Accepted
- Date: 2026-11-25
- Related: Android roadmap milestone 1; ADR-0010; ADR-0011; ADR-0014

## Context

`Project` and the shared operations use `pathlib`, directory traversal and
ordinary file replacement. Android's
[Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files)
supplies document URIs through system pickers; these are not interchangeable
with filesystem paths. An author must move projects between Android and desktop
without a new story format or concurrent-writer synchronization.

[App-specific storage](https://developer.android.com/training/data-storage/app-specific)
is removed on uninstall. [Automatic backup](https://developer.android.com/guide/topics/data/autobackup)
has separate backup/device-transfer rules, so exclusions and restoration cannot
be assumed from private filesystem placement alone. References checked
2026-11-25.

## Options

1. Edit a user-selected document-provider directory in place — resembles desktop
   Open, but requires rewriting filesystem assumptions for URI/provider
   semantics and cannot assume existing replacement/stale-check behavior.
2. Edit an app-private ordinary project directory; import/export explicit ZIP
   snapshots and individual resources through system pickers — reuses safe-path
   operations, but users must explicitly transfer copies and keep backups.

## Decision

Choose option 2 because preserving tested filesystem/write behavior is simpler
and safer than converting the writing engine to provider-dependent URI storage.
No all-files permission, automatic cloud sync, directory mirror or merge engine.
The active private directory is authoritative; a picked ZIP is an input/output
snapshot, never a live backing store.

Use a ZIP with project files at its root: unchanged JSON/Markdown tree, accepted
and alternative branches, steering, histories, reports, lore and relative
writer preset. Do not invent a database or mobile-only story schema. Validate
into a fresh staging directory before making a project visible. Reject path
escapes, absolute members, links, duplicate/ambiguous names, invalid required
files and bounded-size/count/expanded-size violations. Choose tested numeric
limits in the transfer change and show actionable errors, not partial imports.
Existing same-name projects require an explicit new-copy name or confirmed
replacement after settlement; failed/cancelled imports preserve the old project.

External absolute or escaping preset/resource references are not portable.
Show the missing dependency; offer explicit picker import/copy and staged
relative-path repair without changing the source archive or desktop directory.
Never silently replace a chosen external preset with bundled defaults.

For project exports, stage settled saved files, omit temporary/transient runner
state and clear the exported `project.json`'s `api_key` without changing the
active project's credential. Redact known credential values from exported
text/log files and refuse export with an actionable diagnostic if the snapshot
cannot be made credential-safe. Explain these credential-only transformations;
with synthetic nonsecret fixtures, all other project bytes round-trip unchanged.
Session keys are never persisted or transferred. Warn about an imported stored
plaintext credential and require an explicit use/clear choice before a provider
action; never reveal or prefill it in a UI field.

Retain ADR-0011's masked session credential and explicit per-project
Save/Replace/Clear using the shared existing `api_key` field, with a plaintext
warning. No new keystore/keyring or secret synchronization is needed for parity.
Display the configured environment-variable name, but do not require Android
users to set a shell environment. Exclude private projects, credential-bearing
state and recovery caches from automatic cloud backup and device transfer using
the applicable Android rules; test the packaged manifest/rules and restoration
behavior rather than relying solely on one backup flag.

Manuscripts, exact-prompt files and project ZIPs are separate explicit exports
through the system picker. A cancelled/revoked/failed destination never reports
success or changes source files; a document provider may retain an incomplete
output document, which must be reported truthfully. Export is not automatic
acceptance, and a ZIP is not concurrent editing or synchronization.

## Consequences

- Good: Shared filesystem checks, histories and project formats stay usable
  without a broad Android storage permission or custom document provider.
- Good: Explicit portable archives support offline desktop round trips and
  backups without transferring credentials by default.
- Bad: Open means importing/selecting a private copy, not editing a desktop
  folder in place. Separate copies diverge and require deliberate handoff.
- Bad: Uninstall destroys unexported projects; the UI must explain backup and
  offer explicit export. Disabling automatic backup sacrifices that convenience.
- Bad: Explicitly saved project keys remain plaintext in private app storage;
  this is not at-rest encryption or protection against a compromised device.
- Bad: Staging copies require extra storage. ZIP validation, external-resource
  repair, credential scrubbing and provider-write failure cases need tests.
