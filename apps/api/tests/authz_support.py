"""Authorization test world: one builder API with in-memory and PostgreSQL backends.

The contract tests run the same scenarios against both, so the in-memory store used by fast
API tests cannot drift from the SQL that production runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.authz import AccessStore, AccessUser, FirstSeen, SessionState
from app.core.security_audit import InMemorySecurityAuditLog
from app.db.access_store import SqlAccessStore

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


class World(Protocol):
    store: AccessStore

    async def jurisdiction(
        self, code: str, level: str, parent: uuid.UUID | None = None, *, deleted: bool = False
    ) -> uuid.UUID: ...
    async def user(self, subject: str, *, status: str = "active") -> uuid.UUID: ...
    async def role(
        self, code: str, permissions: list[str], *, deleted: bool = False
    ) -> uuid.UUID: ...
    async def assign(
        self,
        user: uuid.UUID,
        role: uuid.UUID,
        jurisdiction: uuid.UUID,
        *,
        kind: str = "assignment",
        reason: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        revoked: bool = False,
    ) -> None: ...


ISSUER = "https://issuer.example.invalid"


@dataclass
class _Assignment:
    user: uuid.UUID
    role: uuid.UUID
    jurisdiction: uuid.UUID
    valid_from: datetime
    valid_to: datetime | None
    revoked: bool


@dataclass
class InMemoryAccessStore:
    """Mirrors ``SqlAccessStore`` semantics; also usable directly as the app's store."""

    users: dict[uuid.UUID, tuple[str, str, str]] = field(
        default_factory=dict
    )  # id -> (iss, sub, status)
    parents: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    deleted_jurisdictions: set[uuid.UUID] = field(default_factory=set)
    roles: dict[uuid.UUID, tuple[frozenset[str], bool]] = field(default_factory=dict)
    assignments: list[_Assignment] = field(default_factory=list)
    revoked_before: dict[uuid.UUID, datetime] = field(default_factory=dict)
    # (issuer, session_key) -> (user_id, revoked)
    sessions: dict[tuple[str, str], tuple[uuid.UUID, bool]] = field(default_factory=dict)

    async def get_or_create_user(self, *, issuer: str, subject: str) -> AccessUser:
        for uid, (iss, sub, status) in self.users.items():
            if (iss, sub) == (issuer, subject):
                return AccessUser(
                    id=uid, status=status, revoked_before=self.revoked_before.get(uid)
                )
        uid = uuid.uuid4()
        self.users[uid] = (issuer, subject, "pending_role_assignment")
        return AccessUser(id=uid, status="pending_role_assignment")

    async def permitted_jurisdictions(
        self, *, user_id: uuid.UUID, permission: str, at: datetime
    ) -> frozenset[uuid.UUID]:
        user = self.users.get(user_id)
        if user is None or user[2] == "disabled":
            return frozenset()
        granted = {
            a.jurisdiction
            for a in self.assignments
            if a.user == user_id
            and not a.revoked
            and a.valid_from <= at
            and (a.valid_to is None or a.valid_to > at)
            and permission in self.roles[a.role][0]
            and not self.roles[a.role][1]
            and a.jurisdiction not in self.deleted_jurisdictions
        }
        result = set(granted)
        changed = True
        while changed:
            changed = False
            for child, parent in self.parents.items():
                if (
                    parent in result
                    and child not in result
                    and child not in self.deleted_jurisdictions
                ):
                    result.add(child)
                    changed = True
        return frozenset(result)

    async def register_session(
        self,
        *,
        user_id: uuid.UUID,
        issuer: str,
        session_key: str,
        expires_at: datetime,
        at: datetime,
        on_first_seen: FirstSeen | None = None,
    ) -> SessionState:
        key = (issuer, session_key)
        if key in self.sessions:
            owner, revoked = self.sessions[key]
            return SessionState(is_new=False, revoked=revoked or owner != user_id)
        self.sessions[key] = (user_id, False)
        if on_first_seen is not None:
            try:
                await on_first_seen()
            except BaseException:
                del self.sessions[key]  # mirrors the SQL transaction rollback
                raise
        return SessionState(is_new=True, revoked=False)

    async def revoke_session(
        self,
        *,
        user_id: uuid.UUID,
        issuer: str,
        session_key: str,
        expires_at: datetime,
        revoked_by: uuid.UUID,
        reason: str,
        at: datetime,
    ) -> None:
        key = (issuer, session_key)
        owner = self.sessions.get(key, (user_id, False))[0]
        if owner == user_id:
            self.sessions[key] = (user_id, True)

    async def revoke_user_sessions(
        self, *, user_id: uuid.UUID, at: datetime, revoked_by: uuid.UUID, reason: str
    ) -> None:
        if user_id in self.users:
            self.revoked_before[user_id] = max(self.revoked_before.get(user_id, at), at)

    async def assignment_jurisdictions(self, *, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
        return frozenset(
            a.jurisdiction for a in self.assignments if a.user == user_id and not a.revoked
        )


class MemoryWorld:
    def __init__(self) -> None:
        self.store = InMemoryAccessStore()
        self.audit = InMemorySecurityAuditLog()

    async def jurisdiction(
        self, code: str, level: str, parent: uuid.UUID | None = None, *, deleted: bool = False
    ) -> uuid.UUID:
        jid = uuid.uuid4()
        self.store.parents[jid] = parent
        if deleted:
            self.store.deleted_jurisdictions.add(jid)
        return jid

    async def user(self, subject: str, *, status: str = "active") -> uuid.UUID:
        uid = uuid.uuid4()
        self.store.users[uid] = (ISSUER, subject, status)
        return uid

    async def role(self, code: str, permissions: list[str], *, deleted: bool = False) -> uuid.UUID:
        rid = uuid.uuid4()
        self.store.roles[rid] = (frozenset(permissions), deleted)
        return rid

    async def assign(
        self,
        user: uuid.UUID,
        role: uuid.UUID,
        jurisdiction: uuid.UUID,
        *,
        kind: str = "assignment",
        reason: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        revoked: bool = False,
    ) -> None:
        self.store.assignments.append(
            _Assignment(user, role, jurisdiction, valid_from or NOW - DAY, valid_to, revoked)
        )


class SqlWorld:
    """Writes real rows (committed) through an owner connection; reads via ``SqlAccessStore``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        maker = async_sessionmaker(engine, expire_on_commit=False)
        self.store = SqlAccessStore(lambda: maker)

    async def reset(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE role_assignment, role_permission, role, permission, user_account, "
                    "organization, jurisdiction RESTART IDENTITY CASCADE"
                )
            )

    async def jurisdiction(
        self, code: str, level: str, parent: uuid.UUID | None = None, *, deleted: bool = False
    ) -> uuid.UUID:
        async with self._engine.begin() as conn:
            return (
                await conn.execute(
                    text(
                        "INSERT INTO jurisdiction (code, name, level, parent_id, is_deleted) "
                        "VALUES (:c, :c, :l, :p, :d) RETURNING id"
                    ),
                    {"c": f"{code}-{uuid.uuid4().hex[:6]}", "l": level, "p": parent, "d": deleted},
                )
            ).scalar_one()

    async def user(self, subject: str, *, status: str = "active") -> uuid.UUID:
        async with self._engine.begin() as conn:
            return (
                await conn.execute(
                    text(
                        "INSERT INTO user_account (issuer, subject, status) "
                        "VALUES (:i, :s, :st) RETURNING id"
                    ),
                    {"i": ISSUER, "s": subject, "st": status},
                )
            ).scalar_one()

    async def role(self, code: str, permissions: list[str], *, deleted: bool = False) -> uuid.UUID:
        async with self._engine.begin() as conn:
            rid = (
                await conn.execute(
                    text(
                        "INSERT INTO role (code, name, is_deleted) VALUES (:c, :c, :d) RETURNING id"
                    ),
                    {"c": f"{code}-{uuid.uuid4().hex[:6]}", "d": deleted},
                )
            ).scalar_one()
            for code_ in permissions:
                pid = (
                    await conn.execute(
                        text(
                            "INSERT INTO permission (code) VALUES (:c) "
                            "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id"
                        ),
                        {"c": code_},
                    )
                ).scalar_one()
                await conn.execute(
                    text("INSERT INTO role_permission (role_id, permission_id) VALUES (:r, :p)"),
                    {"r": rid, "p": pid},
                )
            return rid

    async def assign(
        self,
        user: uuid.UUID,
        role: uuid.UUID,
        jurisdiction: uuid.UUID,
        *,
        kind: str = "assignment",
        reason: str | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        revoked: bool = False,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO role_assignment "
                    "(user_id, role_id, jurisdiction_id, kind, reason, "
                    "valid_from, valid_to, revoked_at) "
                    "VALUES (:u, :r, :j, :k, :why, :vf, :vt, :rv)"
                ),
                {
                    "u": user,
                    "r": role,
                    "j": jurisdiction,
                    "k": kind,
                    "why": reason,
                    "vf": valid_from or NOW - DAY,
                    "vt": valid_to,
                    "rv": NOW - DAY if revoked else None,
                },
            )
