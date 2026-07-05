# ADR-0004: Ruff as the single Python lint + format + import-sort toolchain

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** SATRAK Engineering

## Context

The Epic 1 Python toolchain was `ruff` (lint) + `black` (format) + `isort`
(imports) + `mypy` (types). During the Epic 2 release audit, `black --check`
could not run at all: **black 26.5.1 aborts on Python 3.12.5** due to a known
CPython 3.12.5 AST-safety regression (`Python 3.12.5 has a memory safety issue …
upgrade to 3.12.6 or downgrade to 3.12.4`). This left the CI format gate
unverifiable and Epic 2 code un-format-checked.

Options: (a) pin the interpreter to 3.12.4/3.12.6+, (b) keep black but tolerate
the fragility, or (c) replace black+isort with `ruff format`.

## Decision

**Standardize on Ruff for linting, formatting, and import sorting; remove black
and isort.**

- `ruff format` is black-compatible (same style, 100-col) and written in Rust, so
  it has **no dependency on the CPython AST** and is immune to the 3.12.5 bug.
- Ruff's `I` lint rule already sorts imports, replacing isort.
- One tool (plus mypy for types) is faster, has a single config surface in
  `pyproject.toml`, and removes two dev dependencies.

CI runs `ruff check` + `ruff format --check`; `make format` runs
`ruff check --fix` + `ruff format`.

## Consequences

- The format gate is verifiable on any patch release of Python 3.12+, unblocking
  CI permanently regardless of the interpreter's point release.
- Fewer moving parts; contributors learn one tool.
- Ruff's formatter is ~99% black-identical; the one-time `ruff format` pass
  renormalized 8 files. Any future black-vs-ruff style nuance is immaterial since
  black is no longer in the toolchain.
- Interpreter version is no longer coupled to the formatter, though pinning
  Python remains good practice and is tracked separately.

## Alternatives considered

- **Pin Python to 3.12.4 / 3.12.6+ and keep black:** rejected — couples the
  formatter to an interpreter point release and keeps three tools where one
  suffices.
- **Keep black, ignore the failure:** rejected — an unverifiable gate is not a
  gate.
