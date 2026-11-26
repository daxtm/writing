# ADR-0014: Use a native Android UI with the shared Python core in an APK

- Status: Accepted
- Date: 2026-11-25
- Related: Android roadmap milestone 1; ADR-0003; ADR-0006; ADR-0007; ADR-0013

## Context

The owner requests an Android app with full existing feature parity, shipped
as an APK. The current UI/worker use PySide6 and require native Wayland; the
Linux frozen binary is not an Android application. Writing operations already
accept providers, cancellation and preview events independently of Qt, and
project data is JSON/Markdown on ordinary filesystem paths.

First-party documentation checked 2026-11-25:
- [Chaquopy Android configuration](https://chaquo.com/chaquopy/doc/current/android.html)
  and [version matrix](https://chaquo.com/chaquopy/doc/current/versions.html):
  current 17.2 supports Python 3.13, requires minimum API 24, and Python 3.12+
  supports 64-bit ABIs only; `arm64-v8a` and `x86_64` are available. Build-time
  Python must match the embedded major/minor. Supported Android Gradle Plugin
  versions are documented per Chaquopy version; these pages are evidence, not
  dependency locks.
- [Qt Android deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-android-deploy.html)
  offers ARM64/x86_64 APK deployment, with Android Qt/PySide wheels and its own
  SDK/NDK/runtime toolchain. The checked current page describes embedded CPython
  3.14; do not assume desktop dependency pins automatically define that runtime.
- [Android app signing](https://developer.android.com/studio/publish/app-signing)
  requires signed applications; retaining signing identity is necessary for
  ordinary in-place upgrades.

## Options

1. Deploy PySide6/Qt to Android and adapt the existing Widgets window — shares
   more UI code, but still needs mobile layouts, Android storage/lifecycle
   integration and a separate Qt Android build/runtime compatibility audit.
2. Build Kotlin/Jetpack Compose screens with Chaquopy embedding the existing
   Python operations — keeps one writing engine and native Android integration,
   but introduces a second UI and a typed language/runtime bridge.

## Decision

Choose option 2. The deciding reason is to share the already-independent
writing engine while implementing Android's actual screen, picker and lifecycle
boundaries, rather than carry the desktop Wayland/Widgets shell onto phones.
ADR-0006 remains the Linux UI decision, not an Android requirement.

Use API 24 minimum, ARM64 device support and x86_64 emulator support. Embed
CPython 3.13 and the needed Python dependencies/resources, not the PEP 723
launcher, PySide6, terminal command loop or Qt worker. Reuse existing operations,
provider construction, validation and events through a narrow typed adapter.
Fix missing shared boundaries there; do not rewrite prompts or writing logic in
Kotlin. No Python install, localhost service or desktop companion is required.

Read the authoritative root minor pin for build-time Python and the embedded
minor setting; reject drift. Host checks continue ADR-0013's uv patch-refresh
policy. Android's patch comes from the selected Chaquopy distribution, is
reported in build metadata and changes through runtime-distribution updates;
host uv cannot replace an embedded Android interpreter. Select and lock a
compatible Chaquopy/Gradle/AGP/JDK/SDK/Compose toolchain in the skeleton, with
real packaged imports, HTTPS/fake-stream and both-ABI acceptance.

Use one repeatable APK build path from the skeleton through final release.
Release ID is `com.daxtm.writing`; debug adds `.debug`. Versions increase for
updates. Release signing material is owner-controlled and external to git;
missing signing input fails rather than substituting debug signing. Automated
release-mode tests use a synthetic identity, never the owner's key. Deliver
the owner-signed APK, checksum and runtime/toolchain/certificate metadata;
prove a same-ID/same-signature update preserves populated app data. A debug
APK alone or Play/AAB publishing does not meet this delivery contract.

## Consequences

- Good: CLI, Linux and Android share prompts, provider behavior and project
  operations; Android can use platform-native UI, file access and lifecycle.
- Good: Installable APK and upgrade behavior are exercised from the first
  slice, without depending on a desktop installation.
- Bad: Kotlin/Compose, Android SDK/Gradle and Chaquopy add build dependencies,
  ABI coverage, bridge tests and a second UI parity maintenance obligation.
- Bad: Embedded Python increases APK size; packaging pure-Python dependencies
  is not proof of Android TLS/native-runtime compatibility, so packaged tests
  are required before asserting support.
- Bad: 32-bit devices and pre-API-24 Android are unsupported. Embedded patch
  availability follows Chaquopy, not the host interpreter resolver.
- Bad: Owner signing-key custody and backup are ongoing obligations; ordinary
  updates depend on identity continuity. No store handles distribution for us.
