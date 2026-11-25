# ADR-0013: Pin one exact CPython release across source, checks, and freezing

- Status: Accepted
- Date: 2026-11-24
- Related: python-version-lock; ADR-0008; ADR-0009

## Context

Commit `dd9803e` on `feat/guided-workflow` addresses the reported standalone
Qt/None-reference crash with a Python 3.13 build request, a Python 3.12 minimum,
and regression coverage. Those constraints still permit interpreter drift:
source metadata accepts newer releases, the build request permits different
3.13 patches, and checks invoke host Python or independently resolved uv
environments. The local post-fix build metadata records CPython 3.13.15.

## Options

1. Keep a minimum version and a minor-version build request — simpler updates
   and broader compatibility, but source, checks, and freezing can silently
   use different interpreters even when dependency pins are unchanged.
2. Own one exact CPython patch pin and enforce agreement across entry points —
   predictable interpreter selection and explicit updates, but patch/security
   updates require review and provisioning that exact release.

## Decision

Choose option 2 because preventing unreviewed interpreter changes is the
request, not merely excluding the already-fixed unsafe Python version.

The authority is a root `.python-version`, initially `cpython@3.13.15`.
The source launcher's PEP 723 `requires-python` is an enforced exact-version
mirror (`==3.13.15`), not another independently maintained policy. Existing
build/check scripts read the authority and verify the actual ordinary
CPython release; tests enforce metadata agreement and reject mismatched
cached build evidence. Updates change the pin and its required mirror in one
reviewed commit and run the existing complete checks, including the committed
crash regression.

## Consequences

- Good: Source execution, tests, and frozen builds agree at implementation and
  patch level; a wrong or unavailable interpreter fails visibly.
- Good: The standalone still needs no external interpreter or pin file.
- Bad: An exact patch may require downloading Python even when a newer Python
  is installed; unavailable provisioning blocks checks and builds.
- Bad: Python security fixes do not arrive automatically. Maintainers must
  deliberately update the pin and mirror, rebuild, and run regression checks.
- Bad: This does not pin the Python distributor's build revision or make
  binaries bit-identical; source dependency ranges and native host requirements
  remain separate compatibility boundaries.
