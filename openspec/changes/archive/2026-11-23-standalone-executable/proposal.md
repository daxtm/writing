# Proposal

## Why

The owner says it “needs to be standalone exectuable.” Running the current
launcher still requires uv, Python, downloaded dependencies, and the adjacent
package, so copying `longform.py` is not enough.

## What Changes

- Produce one Linux x86_64 executable, `dist/longform`, containing the Python
  runtime, current CLI, dependencies, and TLS certificate data.
- Keep existing command arguments, prompts, credentials, and project files;
  continue supporting the source/uv launcher.
- Add one documented native build command and offline tests that run a copied
  binary away from the checkout with no Python or uv on PATH.
- Record build/runtime compatibility and third-party notices beside the artifact.
  The executable remains runnable without those informational sidecars.

No existing script builds a distributable runtime: `longform.py` launches
source through uv, and `scripts/check.sh` checks source, so a build entry point
is necessary.

## Capabilities

### New Capabilities

- `standalone-distribution`: Build and run the existing writing CLI as a
  self-contained native executable.

### Modified Capabilities

None; the existing offline-regression contract remains unchanged.

## Impact

Build tooling, frozen-process tests, `scripts/check.sh`, ignore rules, and
distribution documentation; build-only PyInstaller dependencies. Reuse the
existing launcher and core, not a second command dispatcher.

After implementation, run `./scripts/build-standalone.sh`, copy `dist/longform`
elsewhere, and run `./longform --help`: it lists the existing commands without
installing Python/uv or contacting an API. `./longform init ./demo` creates the
usual project files.

Out of scope: Windows/macOS/ARM/musl, installers/AppImage, automatic updates,
hosted release publishing, new GUI behavior or bundling the unmerged GUI,
bundled editors, API changes, and live API tests. This selects standalone
distribution explicitly; it does not add installers to the GUI roadmap.
