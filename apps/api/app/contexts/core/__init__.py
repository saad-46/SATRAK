"""Core bounded context — generic, reusable domain entities.

Entities here (documents, tags, comments, audit/activity logs, configuration,
tasks, notifications) are cross-cutting: many feature contexts attach them to
their own aggregates. They depend only on the shared kernel and never on a
feature context.
"""
