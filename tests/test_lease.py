import pytest

from voxmcp.errors import BusyError
from voxmcp.lease import LeaseManager, OperationGate


@pytest.mark.asyncio
async def test_lease_is_immediately_busy_for_other_client():
    lease = LeaseManager()
    assert (await lease.claim("claude"))["claimed"] is True
    other = await lease.claim("codex")
    assert other["claimed"] is False
    assert other["owner_id"] == "claude"


@pytest.mark.asyncio
async def test_handoff_reserves_lease_for_target():
    lease = LeaseManager()
    await lease.claim("claude")
    assert (await lease.handoff("claude", "codex"))["success"] is True
    claimed = await lease.claim("codex")
    assert claimed["claimed"] is True
    assert claimed["previous_owner"] == "claude"


@pytest.mark.asyncio
async def test_operation_gate_does_not_queue_competitor():
    gate = OperationGate()
    async with gate.operation("claude", "listen"):
        with pytest.raises(BusyError):
            async with gate.operation("codex", "speak"):
                pass
