# ADR-0008: Distribute a frozen native executable alongside the source launcher

- Status: Accepted
- Date: 2026-11-23
- Related: standalone-executable; ADR-0003; ADR-0006

## Context
The owner requests a standalone executable. The existing PEP 723 launcher
requires uv, Python, httpx, and the adjacent `longform_core` package. Main
currently contains the CLI, not the separate desktop implementation.
Distribution must preserve that implementation and its project files.

PyInstaller documents bundles containing the interpreter and dependencies,
including a single-file mode. On Linux it does not bundle glibc and cannot
promise backwards compatibility with older build baselines. Single-file
execution extracts shared libraries into a temporary directory. A Python
zipapp still requires a compatible installed interpreter.

## Options
1. Ship a zipapp or installable Python command — smaller and simpler to
   maintain, but users must supply Python and install/provision dependencies;
   it does not meet the requested runtime independence.
2. Freeze the existing launcher with PyInstaller in one-file console mode —
   one copyable executable with Python/dependencies, but larger, slower to
   start, native-platform-specific, and still dependent on host system libraries.

## Decision
Choose option 2. The deciding reason is running the copied executable without
Python, uv, or a checkout, rather than merely making source directly executable.
Start with native Linux x86_64 glibc builds of the current CLI. Reuse
`longform.py` as the entry point and retain the existing source invocation.
Keep build dependencies separate from the launcher's runtime dependencies.

The build records its actual runtime boundary; no older-distribution promise
is inferred from a successful local run. This decision does not choose an
installer, authorize a release, or establish frozen Qt/Wayland support.
The planned GUI remains governed by ADR-0006/0007 and its own acceptance.

## Consequences
- Good: the writer can copy one executable and run existing commands without
  provisioning Python tooling; package structure from ADR-0003 is retained.
- Good: source users keep the same launcher and file compatibility.
- Bad: every platform needs a native build and verification; the initial
  Linux baseline may be too new for another distribution.
- Bad: the executable is larger and extracts to executable temporary storage;
  updates require rebuilding and replacing it, including security updates to
  bundled dependencies and CA certificates.
- Bad: frozen library search paths can affect external editors, requiring
  narrowly scoped environment restoration and a regression test.
- Bad: build tooling, third-party notices, and frozen-process checks add
  maintenance and local check time. A future GUI bundle needs Qt plugin,
  system-library, license, and real compositor verification, not this CLI claim.

References (official sources consulted 2026-11-23):
- [PyInstaller 6.22.3 operating modes](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/doc/operating-mode.rst).
- [Linux compatibility and temporary extraction](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/doc/usage.rst).
- [Bundled runtime and external-process library paths](https://github.com/pyinstaller/pyinstaller/blob/v6.22.3/doc/runtime-information.rst).
- [Python zipapp interpreter requirement](https://docs.python.org/3/library/zipapp.html).
- [HTTPX TLS verification and certifi](https://www.python-httpx.org/advanced/ssl/).
- [Official certifi collection hook](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/_pyinstaller_hooks_contrib/stdhooks/hook-certifi.py).
- [PyInstaller release metadata](https://pypi.org/pypi/pyinstaller/6.22.3/json).
