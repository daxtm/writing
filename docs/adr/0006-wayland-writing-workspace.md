# ADR-0006: Use Qt Widgets for the Wayland writing workspace

- Status: Accepted
- Date: 2026-11-23
- Related: docs/ROADMAP.md GUI milestone 1; gui-wayland-shell; ADR-0005 on feat/reader-gui

## Context
Main currently provides the Python/uv CLI. The separate `feat/reader-gui`
branch implements a read-only Tkinter/ttk reader with UI-independent safe
snapshots; ADR-0005 there selected Tk partly to avoid new dependencies.
The owner now wants the complete writing flow in a better-looking desktop
window targeting Wayland, not a browser or terminal embedded in a window.
This expands the reader's remit and requires a durable presentation choice.

Qt documents a Wayland client platform plugin and device-independent widget
coordinates. PySide6 wheels include Qt binaries, but their system dependencies
and the target compositor still need verification. Those facts do not promise
flawless fractional scaling, installed plugins, or automatic system theming.

## Options
1. Retain and restyle Tkinter/ttk — reuse existing widgets and avoid another
   dependency, but keep a presentation/runtime whose native Wayland suitability
   has not been established by the existing reader's display test.
2. Replace presentation with PySide6/Qt Widgets — use Qt's documented native
   Wayland client path and standard desktop controls, but add a large dependency,
   migrate widgets, and verify Linux runtime/plugin integration.

## Decision
Choose option 2. The deciding reason is a documented native Wayland execution
path for the requested desktop workspace, rather than investing the expanded
workflow in a toolkit selected for a different, dependency-free reading scope.
Use Qt Widgets, not QML or a browser. Reuse safe snapshots, reader behavior,
and tests; replace presentation rather than maintain two toolkit frontends.

Keep `uv run --script longform.py gui DIR`; add the tested compatible PySide6
range to the launcher's PEP 723 dependencies when implementing. Import GUI
modules lazily so CLI help and writing operations need no display or Qt startup.
Use the explicit `QT_QPA_PLATFORM=wayland` acceptance launch; verify the reported
platform, actual compositor, dialogs, keyboard/clipboard, and scaling. Do not
claim bundled wheels eliminate Linux runtime requirements. Keep offscreen
widget coverage distinct from real Wayland acceptance.

This replaces ADR-0005's Tk/no-new-dependency and read-only presentation
restrictions for the workspace, not its safe reader model. ADR-0005 is absent
from main today; on integration mark it superseded by this ADR without changing
its historical body. Its number and ADR-0004's remain reserved.

## Consequences
- Good: one desktop toolkit supplies the reading and writing interface, with
  an explicit native Wayland acceptance criterion and standard focus/layout tools.
- Good: reusable data/operation tests stay independent of GUI imports.
- Bad: PySide6/Qt increases downloads and disk usage even for CLI-only uv users
  because the shared launcher declares it; GUI imports being lazy does not
  remove that installation cost.
- Bad: existing Tk widgets and widget tests must be replaced; palette contrast,
  fonts, plugin failures, and compositor differences remain application work.
- Bad: no pinned runtime or target-compositor success has been established by
  this documentation-only decision; milestone 1 must verify both.

References (official documentation consulted 2026-11-23):
- [Qt Wayland client plugin](https://doc.qt.io/qt-6/wayland-and-qt.html).
- [Qt for Python installation and bundled binaries](https://doc.qt.io/qtforpython-6/gettingstarted.html).
- [Qt high-DPI behavior and platform differences](https://doc.qt.io/qt-6/highdpi.html).
