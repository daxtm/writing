# ADR-0013: Pin the CPython minor and accept patch updates automatically

- Status: Accepted
- Date: 2026-11-25
- Related: python-version-lock; ADR-0008; ADR-0009

## Context

Commit `dd9803e` on `feat/guided-workflow` addresses the reported standalone
Qt/None-reference crash with a Python 3.13 build request, a Python 3.12 minimum,
and regression coverage. Source metadata still accepts other minors, and checks
invoke host Python or independently resolved uv environments. The owner chose
to prevent minor/implementation drift, not to freeze patch updates. The local
post-fix build records CPython 3.13.15; this is evidence, not a required patch.

## Options

1. Pin an exact CPython patch across entry points — stable patch-level
   selection, but patch/security updates require policy edits and review.
2. Pin the CPython minor across entry points and automatically provision its
   latest available patch — prevents unreviewed minor/implementation changes
   while taking patch fixes, but rebuilds can use different patches.

## Decision

Choose option 2 because the owner explicitly wants automatic patch updates
within 3.13, with review required only for a minor bump.

The authority is a root `.python-version` containing `cpython@3.13`.
The source launcher's PEP 723 mirror is `requires-python = ">=3.13,<3.14"`.
No file or assertion pins a patch. Existing build/check entry points explicitly
refresh/provision the latest 3.13 patch available to their uv resolver, select
CPython 3.13.x, and reject another minor or implementation.

Sidecars record the requested minor and actual full interpreter version.
Cache validation rejects another actual implementation/minor but does not
require patch equality. Tests enforce pin/mirror agreement and acceptance of
different 3.13 patches. A minor bump updates the authority and mirror together
in a reviewed change; a patch update requires no policy edits.

Leave `dd9803e`'s independent CPython >=3.12 crash-floor assertion and
Qt/None-refcount regression unchanged.

## Consequences

- Good: Source execution, tests, and frozen builds stay within the reviewed
  minor; build/check implementation verification prevents host-driven drift.
- Good: Patch fixes are taken automatically during provisioning without
  changing two files for each patch.
- Good: The standalone still needs no external interpreter or pin file.
- Bad: Provisioning may download Python and can fail if the resolver's available
  distribution cannot be obtained. Keeping uv current may be necessary for new
  patch releases to become available to it.
- Bad: Patch-level reproducibility is deliberately not guaranteed; sidecars
  record the actual patch for diagnosis, and mandatory regressions guard updates.
- Bad: Existing copied executables do not self-update. A valid same-minor cache
  can retain an older patch until a normal rebuild; patch difference alone is
  not invalidation.
- Bad: Distributor build revisions, source dependency ranges, and native host
  requirements remain separate compatibility boundaries.
