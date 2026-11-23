# Design

## Context

See [proposal.md](proposal.md) for motivation. `longform_core/cli.py` already
owns argparse and dispatch; `commands.py` contains `draft`, `status`, and
`export`. `Tree.text()` defines active manuscript assembly, including `sep`
and continuation whitespace; `utils.words()` defines counts. `Tree.d` retains
all nodes, a head, steering state, and node edit history. `scenes --force`
retains old tree files, so scene cards alone are not a complete reading index.

`Project` merges configuration defaults but may contain an API key. Its
`read_json` path calls CLI `die` on malformed JSON. Existing writes already use
temporary files plus `os.replace`; changing persistence is unnecessary.
`scripts/check.sh` already discovers all `tests/`. The autouse socket guard in
`tests/conftest.py` currently blocks even loopback connections.

## Goals / Non-Goals

- Keep existing command output, project files, and the thin launcher unchanged.
- Serve only a selected project's writing, with no dependency or asset build.
- Cover actual HTTP responses offline, without browser automation.
- Do not expose a filesystem browser, raw JSON API, or browser draft controls.
  Only persisted content is available; deleted nodes cannot be recovered.

## Decisions

### Local web architecture and ownership

Adopt [ADR-0004](../../../docs/adr/0004-local-web-reader.md): stdlib local web,
read-only. Put server, request-safe loading, HTML rendering, and trusted inline
CSS/JavaScript in `longform_core/web.py`. This is a small reader, not a general
web framework; a template engine, frontend bundle, or a new asset directory
would add machinery without required behavior.

Add argparse `view` and dispatch to `web.cmd_view(args)` in the existing CLI
before its shared `Project` construction, as `init` already does. This lets
the reader's safe loader handle malformed configuration without the existing
CLI loader leaking errors or exiting a request thread. Do not modify the
launcher. Expose `web.create_server(root, port=0)` for tests
and command lifecycle. It returns a bound `ThreadingHTTPServer` subclass and
does not start threads or open a browser. Bind the literal `127.0.0.1` only;
there is no host/listen flag. Default port is 0 to avoid arbitrary conflicts.

The command validates the project, creates the listener, prints/flushed
`Reader: http://127.0.0.1:<server-port>/`, optionally calls `webbrowser.open`
once, and calls `serve_forever`. False/exception from browser opening warns
without stopping service. Ctrl-C runs `server_close` in `finally`, with daemon
request threads and no traceback; do not call blocking `shutdown` from the
same thread running `serve_forever`. Test teardown calls `shutdown` from the
test thread, closes, and joins the serving thread with a timeout.
Invalid configuration, invalid port, and bind failures are concise CLI errors.

### Routes return HTML, not project JSON

| GET route | Content |
|---|---|
| `/` | Current scenes, project progress, links to notes and retained trees |
| `/scenes/<sid>` | Active text, tree index, every node and saved edit history |
| `/notes` | Bible, state, scene/arc summaries, checks and critiques |

No raw-file, node-JSON, static-directory, or version endpoint. Node navigation
uses fragments such as `/scenes/s01#node-n3`; parent/child links are navigational,
never a change to `head`. Every node is expanded in the HTML so inactive content
is searchable and readable, not hidden behind generated-text previews.

On `/`, current scene counts/total match `status`: `words(Tree.text())` for
each card's active head. Also discover direct `trees/*.json` files whose stems
are safe IDs; show stems not in cards in a separate retained-tree section,
excluded from the total. Safe scene IDs are nonempty ASCII letters, digits,
underscore, or hyphen. IDs from cards and filenames must pass that rule before
any path is constructed; node fragments use URL quoting and attribute escaping.
All persisted nodes are rendered, even if not reachable from head; order by
existing node creation/insertion order. Missing optional node fields show
`unavailable`; false flags remain visibly false, and no head means empty text.

### Request-safe reads and an explicit content allowlist

Resolve the root once. Read source files afresh per request; read each required
JSON file once into a request-local snapshot before rendering. Reuse `Tree.text`
and `words` against the validated in-memory tree instead of duplicating joining
rules. Check parent/head references and cycles before calling chain methods,
so invalid structures cannot hang a request.

Use a small reader-local JSON/text loader, not a new general persistence layer:
HTTP needs status errors rather than `die`/process exit. It returns only
allowlisted values and handles missing optional files. `project.json` is required;
take only title and target count, applying current defaults. Never serialize
`Project.cfg`, exceptions, or raw configuration. Malformed/schema-invalid needed
JSON or read errors produce a complete generic 503 page; unknown resources and
unsafe/symlinked sources produce 404. Missing scenes default to an empty list;
missing optional trees are empty. Missing notes files, summaries, or report
directories are labeled empty.

Allowlisted writing: `scenes.json`, safe direct `trees/<sid>.json`, `bible.md`,
`state.md`, `summaries.json` (known scene/arc fields only), and direct `*.md`
files in `checks/` and `critiques/`, sorted by filename and including backups.
Node fields are explicitly selected, including history time/by/text. No presets,
calls, calib/limits, `.env`, histories outside saved node history, lorebooks,
outlines, cached `manuscript.md`, or arbitrary future metadata fields are served.
Active manuscript is derived from trees, not a possibly stale export.

Reject symlinks in any allowlisted path component below the root (including
directories); verify each resolved source remains under the canonical root.
Root itself is the explicitly selected canonical directory. This protects
against accidental linked private files, not concurrent hostile filesystem
mutation by a local process with the writer's access.

### HTTP boundary and escaping

Use a custom `BaseHTTPRequestHandler`, not `SimpleHTTPRequestHandler`.
Parse the request target with `urlsplit`; accept origin-form targets with no
scheme/authority, ignore ordinary query parameters, decode the path once, and
reject percent signs left after decoding, backslashes, NUL, empty interior
segments, `.`/`..`, and unexpected segments. Match exact routes and known safe
scene IDs; do not join URL paths to the filesystem. All unsafe/unknown requests
return a generic 404 without echoing raw input. Disable request logging of raw
targets and do not log configuration.

Require Host exactly `127.0.0.1:<bound-port>` to avoid DNS-rebinding access;
reject foreign/missing Host with 403. All non-GET methods return 405 and
`Allow: GET` without reading or acting on their bodies, including unknown
methods. Implement the fallback as well as the common method handlers.
Do not emit CORS allow headers.

Render all project values through `html.escape(..., quote=True)`, including
titles, filenames, metadata, and text. Preserve whitespace with CSS
`white-space: pre-wrap`; no Markdown renderer. URL components are quoted
separately. Never interpolate project values into JS or CSS. Return UTF-8 HTML,
correct byte `Content-Length`, `Cache-Control: no-store`, and
`X-Content-Type-Options: nosniff` on responses. All navigation/assets are local.

### Refresh without an additional API

Trusted inline JavaScript fetches the current route every 2000 ms after the
previous request completes (no overlapping polls), with caching disabled.
Compare the fetched `<main id="reader-content">` content to the current content;
if different, replace only that element, retaining the window scroll position
and existing location fragment. Restore scroll after replacement; do not
re-jump to a fragment on each poll. Stable rendering has no changing server
timestamp. Initial fragment navigation still jumps to the requested node.
Keep the polling script outside `<main>` so updates cannot duplicate timers.

The generic 503 page has the same shell and polling hook; errors remain visible
and valid data replaces them on the next successful request. Fetch/network
failure leaves the current text visible with a retry indicator outside `<main>`.
A manual reload works without JavaScript; no SSE connection management or
browser storage is needed.

### Offline deterministic verification

Add `tests/test_web.py` with temporary synthetic projects, fixed node times,
known branch text, and synthetic secrets in both configuration and denied files.
Start `create_server(tmp_path, 0)` in a managed thread and use `http.client`
against its assigned port with finite timeouts; always shut it down in teardown.
Assert the real listener address, not merely the printed URL.

Extend the existing test net guard with an explicit opt-in fixture that permits
only the assigned numeric `127.0.0.1` address and port for this server, at both
`socket.create_connection` and `socket.socket.connect` layers. Preserve the
original callables before guards are installed; wrappers delegate only for that
exact pair. Unrequested sockets, other ports/hosts, and real httpx remain blocked.
Do not globally disable the guard or permit every localhost connection.
An in-process server avoids changing `net_guard_env`'s subprocess restrictions.

Test CLI browser calls and interrupt/error lifecycle with fakes at their owning
module. Check polling interval, stable shell, scroll/fragment preservation code,
and no duplicated script in static HTML; separately refetch real HTTP pages
after atomic fixture saves, and after malformed JSON/recovery. This tests the
refresh contract without claiming browser execution coverage.
Parameterize supported routes, unsafe paths, methods, foreign Host, symlinks,
escaped strings, and leakage checks, including error bodies/headers. Hash the
fixture directory before/after requests to prove no writes. Keep `Api` and
external network prohibited throughout.

## Risks / Trade-offs

- Full HTML/tree reloads grow with project size → accept for a single-user MVP;
  no pagination that could hide branches.
- Two-second polling is not token streaming → drafts appear after existing saves.
- Separate files can reflect adjacent saves → per-file snapshots and atomic
  writes prevent partial JSON; no cross-file transaction guarantee.
- Browser scripting is verified without automation → deterministic HTTP and
  script-contract tests, plus the proposal's manual demo.
- Loopback/Host checking is not authentication → local users/processes can read;
  no remote hosting or multi-user protection is promised.
- Optional nested symlinks are rejected rather than followed → some linked
  project material is intentionally unavailable.

## Migration Plan

No data migration. Implement behind the existing suite, document `view --help`,
then run the reader against a synthetic project while saving another branch.
Rollback removes the additive command/module; existing project data and drafting
are unchanged. No open design questions remain.
