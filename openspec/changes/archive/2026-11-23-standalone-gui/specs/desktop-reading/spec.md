# Spec Delta

## ADDED Requirements

### Requirement: Open the workspace with a bare invocation
Running the program without a command SHALL open the native desktop workspace
for the current working directory, equivalent to `gui [DIR]` with `DIR`
defaulting to the current directory. It SHALL NOT report a missing-command
argument error. `--help`, every explicit command, and the native-Wayland-only
policy SHALL keep their existing behavior.

#### Scenario: Launch without arguments from a project
- **WHEN** the owner runs the source launcher with no command from a project directory in a working Wayland session
- **THEN** one native workspace opens for that directory and blocks until it closes
- **AND** no argument error and no fallback platform window are produced

#### Scenario: Launch without arguments from a non-project directory
- **WHEN** the source launcher starts with no command from a directory that is not a project
- **THEN** the workspace opens with its Create/Open controls and explicit warnings
- **AND** no project file is written until the owner confirms Create or Open

#### Scenario: Help remains available without a display
- **WHEN** the launcher runs `--help`
- **THEN** it lists the existing commands, including `gui [DIR]`, and opens no window
