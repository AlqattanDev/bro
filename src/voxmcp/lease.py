"""In-process client ownership and immediate-busy audio operation gating."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import AsyncIterator

from .errors import BusyError


@dataclass(slots=True)
class ClientLease:
    owner_id: str
    acquired_at: float
    heartbeat_at: float
    expires_at: float
    reconnect_until: float | None = None
    reserved_for: str | None = None

    def public(self, *, now: float | None = None) -> dict[str, object]:
        current = time.time() if now is None else now
        return {
            "owned": True,
            "owner_id": self.owner_id,
            "age_seconds": max(0, round(current - self.acquired_at, 3)),
            "expires_in_seconds": max(0, round(self.expires_at - current, 3)),
            "reconnect_grace": (
                max(0, round(self.reconnect_until - current, 3))
                if self.reconnect_until is not None
                else None
            ),
            "reserved_for": self.reserved_for,
        }


class LeaseManager:
    def __init__(
        self,
        *,
        ttl_seconds: float = 600.0,
        reconnect_grace_seconds: float = 30.0,
        clock=time.time,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.reconnect_grace_seconds = reconnect_grace_seconds
        self.clock = clock
        self._lease: ClientLease | None = None
        self._lock = asyncio.Lock()

    async def claim(self, client_id: str, *, force: bool = False) -> dict[str, object]:
        now = self.clock()
        async with self._lock:
            self._expire(now)
            lease = self._lease
            if lease is None:
                self._lease = ClientLease(
                    owner_id=client_id,
                    acquired_at=now,
                    heartbeat_at=now,
                    expires_at=now + self.ttl_seconds,
                )
                return {"claimed": True, **self._lease.public(now=now)}
            if lease.owner_id == client_id:
                lease.heartbeat_at = now
                lease.expires_at = now + self.ttl_seconds
                lease.reconnect_until = None
                return {"claimed": True, "existing": True, **lease.public(now=now)}
            if lease.reserved_for == client_id or force:
                previous = lease.owner_id
                self._lease = ClientLease(
                    owner_id=client_id,
                    acquired_at=now,
                    heartbeat_at=now,
                    expires_at=now + self.ttl_seconds,
                )
                return {"claimed": True, "previous_owner": previous, **self._lease.public(now=now)}
            return {"claimed": False, "busy": True, **lease.public(now=now)}

    async def require(self, client_id: str, *, auto_claim: bool = True) -> None:
        result = await self.claim(client_id) if auto_claim else await self.status()
        if result.get("owner_id") != client_id:
            raise BusyError(f"Audio is owned by {result.get('owner_id', 'another client')}")

    async def heartbeat(self, client_id: str) -> bool:
        now = self.clock()
        async with self._lock:
            self._expire(now)
            if self._lease is None or self._lease.owner_id != client_id:
                return False
            self._lease.heartbeat_at = now
            self._lease.expires_at = now + self.ttl_seconds
            self._lease.reconnect_until = None
            return True

    async def disconnect(self, client_id: str) -> bool:
        now = self.clock()
        async with self._lock:
            if self._lease is None or self._lease.owner_id != client_id:
                return False
            self._lease.reconnect_until = now + self.reconnect_grace_seconds
            self._lease.expires_at = min(
                self._lease.expires_at, self._lease.reconnect_until
            )
            return True

    async def release(self, client_id: str, *, force: bool = False) -> bool:
        async with self._lock:
            if self._lease is None:
                return True
            if not force and self._lease.owner_id != client_id:
                return False
            self._lease = None
            return True

    async def handoff(self, client_id: str, target_id: str) -> dict[str, object]:
        now = self.clock()
        async with self._lock:
            self._expire(now)
            if self._lease is None or self._lease.owner_id != client_id:
                return {"success": False, "reason": "not_owner"}
            self._lease.reserved_for = target_id
            self._lease.expires_at = min(
                self._lease.expires_at, now + self.reconnect_grace_seconds
            )
            return {
                "success": True,
                "from": client_id,
                "reserved_for": target_id,
                "expires_in_seconds": self.reconnect_grace_seconds,
            }

    async def status(self) -> dict[str, object]:
        now = self.clock()
        async with self._lock:
            self._expire(now)
            return self._lease.public(now=now) if self._lease else {"owned": False}

    def _expire(self, now: float) -> None:
        if self._lease is not None and self._lease.expires_at <= now:
            self._lease = None


class OperationGate:
    """Allows one long audio operation and rejects competitors immediately."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._active_client: str | None = None
        self._active_action: str | None = None

    @asynccontextmanager
    async def operation(self, client_id: str, action: str) -> AsyncIterator[None]:
        async with self._guard:
            if self._active_client is not None:
                raise BusyError(
                    f"{self._active_action or 'audio'} is already running for "
                    f"{self._active_client}"
                )
            self._active_client = client_id
            self._active_action = action
        try:
            yield
        finally:
            async with self._guard:
                self._active_client = None
                self._active_action = None

    async def status(self) -> dict[str, object]:
        async with self._guard:
            return {
                "busy": self._active_client is not None,
                "client_id": self._active_client,
                "action": self._active_action,
            }

