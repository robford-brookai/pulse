## Purpose

The shared operational shape of the clock-driven jobs: one CLI the platform scheduler invokes,
offline dry-run on both jobs, and the IaC schedule definitions that wire the triggers.

## ADDED Requirements

### Requirement: One CLI exposes both jobs

The package SHALL expose one command-line entrypoint with two subcommands — month-open and the
consent sweep — each runnable standalone by the platform scheduler and exiting nonzero on any
failed run, so scheduler retry and paging key off exit status.

#### Scenario: Subcommands are invocable

- **GIVEN** the installed package
- **WHEN** the CLI is invoked with each subcommand
- **THEN** the named job runs, and an unknown subcommand or missing required argument exits
  nonzero with usage help

### Requirement: Both jobs support an offline dry-run

Each subcommand SHALL accept `--dry-run`, printing the would-declare set — every command the run
would submit — while making no API calls and no network connections at all, so a dry-run is
runnable against fixture inputs on a machine with no ledger access.

#### Scenario: Dry-run declares nothing

- **GIVEN** fixture inputs for a run that would declare commands
- **WHEN** the subcommand runs with `--dry-run` and network access disabled
- **THEN** the would-declare set is printed, the process exits zero, and no API call or socket
  connection is attempted

### Requirement: Schedules are wired as infrastructure config

The schedule triggers SHALL be defined as IaC config in the package's infra directory, per the D14
platform scheduler (SPCS job / EventBridge Scheduler) and the monorepo's existing IaC conventions:
month-open at 00:30 on the 1st of each month with a same-day retry window, the consent sweep
daily. Enabling, changing, or removing a schedule is a config change, never code.

#### Scenario: Schedule definitions exist and match the cadence

- **GIVEN** the package's infra directory
- **WHEN** the schedule definitions are read
- **THEN** month-open is triggered at 00:30 on the 1st with a same-day retry window, the sweep is
  triggered daily, and each trigger targets the corresponding CLI subcommand
