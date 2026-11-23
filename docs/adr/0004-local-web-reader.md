# ADR-0004: Use a read-only standard-library local web reader

- Status: Superseded by ADR-0005
- Date: 2026-11-23
- Related: add-reader-gui; ADR-0003; docs/ROADMAP.md

## Context
The local single-user CLI saves all candidate branches in project trees, but
terminal views and exports do not keep all generated writing continuously
readable. Projects also contain private configuration and API credentials.
The owner wants a browser reading window alongside terminal drafting, without
new dependencies, a build step, or changes to existing project files.

## Options
1. Serve a read-only local web reader with Python's standard library — uses the
   existing runtime and browser, but requires explicit routing, escaping, refresh,
   and listener lifecycle code.
2. Add a framework-backed web application with templates and browser drafting
   controls — established routing/template facilities and room for interaction,
   but adds dependencies and write coordination with the terminal beyond the
   requested reading workflow.
3. Extend terminal paging and export to include all branches — smallest runtime
   surface, but still requires commands or regenerated exports and does not
   provide the requested always-available browser view.

## Decision
Choose option 1: an additive `view` CLI command serving read-only HTML through
`http.server.ThreadingHTTPServer` on literal `127.0.0.1`, with trusted inline
assets and polling of saved files. The deciding reason is that a local browser
can display every saved branch alongside live terminal drafting without a
dependency, frontend build, or second writer.

Keep HTTP strictly read-only: allowlisted writing only, escaped plain text, no
raw configuration/files, no API/provider calls, and no browser edit/generate
operations. Title and target count are the only configuration values exposed.
No authentication, remote binding, or multi-user service is introduced.
Implementation stays in `longform_core/` behind ADR-0003's thin launcher.

## Consequences
- Good: existing drafting and project formats stay unchanged; saved inactive
  branches become readable without repeatedly running terminal commands.
- Good: no new dependency or build step; real HTTP behavior can be tested offline
  with `http.client` and a narrowly permitted ephemeral loopback listener.
- Bad: routing, HTML escaping, safe file selection, browser refresh, and server
  shutdown are maintained here rather than delegated to a web framework.
- Bad: full-page-content polling scales with all saved text and does not show
  unsaved streamed tokens; large projects may refresh more slowly.
- Bad: loopback is not user authentication; other local processes/users may
  reach the reader, and editing or remote access would need a new decision.
