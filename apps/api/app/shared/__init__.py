"""SATRAK shared kernel — the reusable domain platform.

Everything under ``app.shared`` is framework-agnostic, pure-Python building
blocks that every bounded context depends on: base entities, value objects,
domain events, persistence abstractions, and platform service interfaces.

Dependency rule: ``shared`` depends on nothing else in ``app`` (not on ``api``,
``db`` engine wiring, or any bounded context). Infrastructure and API layers
depend inward on ``shared`` — never the reverse.
"""
