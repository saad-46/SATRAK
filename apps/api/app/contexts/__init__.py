"""Bounded contexts.

Each subpackage is a bounded context with its own ubiquitous language and domain
model, built on the shared kernel (:mod:`app.shared`). Contexts never import each
other's internals; they collaborate via ids, domain events, and published
contracts. Contexts with a full domain model in Epic 2 (``core``, ``identity``,
``organization``) sit alongside reserved placeholders for the feature contexts
whose domain arrives in their own epics.
"""
