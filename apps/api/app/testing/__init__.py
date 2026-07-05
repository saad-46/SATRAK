"""Reusable testing utilities.

Shipped in ``app`` (not ``tests``) so every bounded context's test suite — and
future integration harnesses — import the same factories and fakes instead of
re-inventing them. Nothing here is imported by production code paths.
"""

from app.testing import factories, fakes

__all__ = ["factories", "fakes"]
