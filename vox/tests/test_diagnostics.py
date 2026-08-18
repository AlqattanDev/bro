from voxmcp.diagnostics import dependency_status, system_status


def test_system_diagnostics_assert_local_only():
    status = system_status()
    assert status["local_only"] is True
    assert status["api_keys_used"] is False


def test_dependency_diagnostics_are_structured():
    status = dependency_status()
    assert "ffmpeg" in status["commands"]
    assert isinstance(status["required_ready"], bool)
