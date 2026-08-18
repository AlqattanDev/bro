from __future__ import annotations

from collections import deque
from pathlib import Path
import subprocess
from typing import Any

import pytest

from voxmcp.services import (
    LaunchdJobSpec,
    ServiceSpec,
    ServiceSupervisor,
    default_service_specs,
)


LAUNCHCTL = "/bin/launchctl"
UID = 501


class Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeHttpClient:
    def __init__(self, *results: Response | Exception) -> None:
        if not results:
            raise ValueError("at least one fake HTTP result is required")
        self.results = deque(results)
        self.last = results[-1]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, **kwargs: Any) -> Response:
        self.calls.append((url, kwargs))
        result = self.results.popleft() if self.results else self.last
        if isinstance(result, Exception):
            raise result
        return result


class FakeRunner:
    """Stateful launchctl double that rejects shell execution."""

    def __init__(
        self,
        loaded: dict[str, str] | None = None,
        plist_labels: dict[str, str] | None = None,
    ) -> None:
        self.loaded = dict(loaded or {})
        self.plist_labels = dict(plist_labels or {})
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        self.calls.append((command, kwargs))
        assert command[0] == LAUNCHCTL
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

        verb = command[1]
        if verb == "print":
            label = command[2].rsplit("/", 1)[-1]
            if label not in self.loaded:
                return subprocess.CompletedProcess(
                    argv,
                    113,
                    "",
                    f"Could not find service {label}",
                )
            return subprocess.CompletedProcess(argv, 0, self.loaded[label], "")

        if verb == "bootstrap":
            label = self.plist_labels.get(command[3])
            if label is None:
                return subprocess.CompletedProcess(argv, 5, "", "unknown plist")
            self.loaded[label] = launch_output(state="running", pid=700)
            return subprocess.CompletedProcess(argv, 0, "", "")

        target = command[-1]
        label = target.rsplit("/", 1)[-1]
        if verb == "bootout":
            self.loaded.pop(label, None)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if verb == "kickstart":
            if label not in self.loaded:
                return subprocess.CompletedProcess(argv, 113, "", "not loaded")
            self.loaded[label] = launch_output(state="running", pid=701)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 64, "", f"unsupported verb {verb}")


class AlwaysTimeoutRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial")


def launch_output(
    *,
    state: str = "running",
    pid: int | None = 123,
    runs: int = 4,
    last_exit: str = "0",
    stdout: Path | None = None,
    stderr: Path | None = None,
) -> str:
    fields = [f"state = {state}", f"runs = {runs}", f"last exit code = {last_exit}"]
    if pid is not None:
        fields.append(f"pid = {pid}")
    if stdout is not None:
        fields.append(f"stdout path = {stdout}")
    if stderr is not None:
        fields.append(f"stderr path = {stderr}")
    return "\n".join(f"\t{field}" for field in fields)


def make_spec(tmp_path: Path, name: str = "whisper") -> ServiceSpec:
    port = 2022 if name == "whisper" else 8880
    primary = LaunchdJobSpec(
        label=f"com.vox.{name}",
        plist_path=tmp_path / f"com.vox.{name}.plist",
        stdout_path=tmp_path / "vox.out.log",
        stderr_path=tmp_path / "vox.err.log",
    )
    legacy = LaunchdJobSpec(
        label=f"com.voicemode.{name}",
        plist_path=tmp_path / f"com.voicemode.{name}.plist",
        stdout_path=tmp_path / "legacy.out.log",
        stderr_path=tmp_path / "legacy.err.log",
        legacy=True,
    )
    return ServiceSpec(
        name=name,
        health_url=f"http://127.0.0.1:{port}/health",
        jobs=(primary, legacy),
    )


def supervisor(
    spec: ServiceSpec,
    runner: FakeRunner | AlwaysTimeoutRunner,
    http: FakeHttpClient,
    **kwargs: Any,
) -> ServiceSupervisor:
    return ServiceSupervisor(
        {spec.name: spec},
        runner=runner,
        http_client=http,
        uid=UID,
        launchctl_path=LAUNCHCTL,
        **kwargs,
    )


def action_calls(runner: FakeRunner, verb: str) -> list[tuple[str, ...]]:
    return [command for command, _ in runner.calls if len(command) > 1 and command[1] == verb]


def test_specs_require_literal_loopback_http(tmp_path: Path) -> None:
    job = LaunchdJobSpec("com.vox.test", tmp_path / "test.plist")
    with pytest.raises(ValueError, match="loopback"):
        ServiceSpec("test", "http://0.0.0.0:9999/health", (job,))
    with pytest.raises(ValueError, match="literal loopback"):
        ServiceSpec("test", "http://localhost:9999/health", (job,))
    with pytest.raises(ValueError, match="unauthenticated"):
        ServiceSpec("test", "https://127.0.0.1:9999/health", (job,))


def test_default_specs_include_primary_and_current_legacy_labels(tmp_path: Path) -> None:
    specs = default_service_specs(tmp_path)
    assert tuple(specs) == ("whisper", "kokoro")
    assert [job.label for job in specs["whisper"].jobs] == [
        "com.vox.whisper",
        "com.voicemode.whisper",
    ]
    assert [job.label for job in specs["kokoro"].jobs] == [
        "com.vox.kokoro",
        "com.voicemode.kokoro",
    ]
    assert specs["whisper"].jobs[1].legacy is True
    assert specs["kokoro"].jobs[1].legacy is True


@pytest.mark.asyncio
async def test_status_reports_healthy_legacy_job_truthfully(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    actual_out = tmp_path / "actual whisper out.log"
    actual_err = tmp_path / "actual whisper err.log"
    runner = FakeRunner(
        {
            spec.jobs[1].label: launch_output(
                stdout=actual_out,
                stderr=actual_err,
                last_exit="(never exited)",
            )
        }
    )
    http = FakeHttpClient(Response(200))

    status = await supervisor(spec, runner, http).status("whisper")

    assert status.state == "ready"
    assert status.ready is True
    assert status.managed is True
    assert status.process_running is True
    assert status.active_label == "com.voicemode.whisper"
    assert status.using_legacy_label is True
    legacy = next(job for job in status.jobs if job.legacy)
    assert legacy.stdout_path == actual_out
    assert legacy.stderr_path == actual_err
    assert legacy.last_exit_code is None
    assert legacy.last_exit_detail == "(never exited)"
    assert status.to_dict()["health"]["url"] == "http://127.0.0.1:2022/health"


@pytest.mark.asyncio
async def test_status_distinguishes_running_from_healthy(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner({spec.primary_job.label: launch_output(state="running")})
    http = FakeHttpClient(Response(503))

    status = await supervisor(spec, runner, http).status("whisper")

    assert status.state == "unhealthy"
    assert status.process_running is True
    assert status.ready is False
    assert status.health.reachable is True
    assert status.health.status_code == 503


@pytest.mark.asyncio
async def test_status_can_report_healthy_but_unmanaged_endpoint(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    status = await supervisor(
        spec,
        FakeRunner(),
        FakeHttpClient(Response(204)),
    ).status("whisper")

    assert status.state == "external"
    assert status.ready is True
    assert status.managed is False
    assert status.active_label is None


@pytest.mark.asyncio
async def test_status_exposes_primary_legacy_conflict_even_if_endpoint_is_healthy(
    tmp_path: Path,
) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner(
        {
            spec.jobs[0].label: launch_output(pid=100),
            spec.jobs[1].label: launch_output(pid=101),
        }
    )

    status = await supervisor(spec, runner, FakeHttpClient(Response(200))).status("whisper")

    assert status.state == "conflict"
    assert status.ready is True
    assert status.loaded_labels == ("com.vox.whisper", "com.voicemode.whisper")
    assert "multiple" in status.detail


@pytest.mark.asyncio
async def test_start_uses_loaded_legacy_label_without_shell(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner({spec.jobs[1].label: launch_output()})

    result = await supervisor(spec, runner, FakeHttpClient(Response(200))).start("whisper")

    assert result.ok is True
    assert result.labels == ("com.voicemode.whisper",)
    assert action_calls(runner, "kickstart") == [
        (LAUNCHCTL, "kickstart", f"gui/{UID}/com.voicemode.whisper")
    ]
    for command, kwargs in runner.calls:
        assert kwargs["shell"] is False
        assert not any(part in {"source", ".", "uv", "pip", "curl"} for part in command)


@pytest.mark.asyncio
async def test_start_bootstraps_preinstalled_primary_plist(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    primary = spec.primary_job
    assert primary.plist_path is not None
    runner = FakeRunner(plist_labels={str(primary.plist_path): primary.label})

    result = await supervisor(
        spec,
        runner,
        FakeHttpClient(Response(200)),
        path_exists=lambda path: path == primary.plist_path,
    ).start("whisper")

    assert result.ok is True
    assert result.labels == (primary.label,)
    assert action_calls(runner, "bootstrap") == [
        (LAUNCHCTL, "bootstrap", f"gui/{UID}", str(primary.plist_path))
    ]


@pytest.mark.asyncio
async def test_start_refuses_to_invent_or_install_missing_service(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner()

    result = await supervisor(
        spec,
        runner,
        FakeHttpClient(ConnectionError("down")),
        path_exists=lambda _path: False,
    ).start("whisper")

    assert result.ok is False
    assert result.changed is False
    assert result.commands == ()
    assert action_calls(runner, "bootstrap") == []
    assert "pre-installed" in result.detail


@pytest.mark.asyncio
async def test_stop_boots_out_every_loaded_label_to_defeat_keepalive(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner(
        {
            spec.jobs[0].label: launch_output(pid=100),
            spec.jobs[1].label: launch_output(pid=101),
        }
    )

    result = await supervisor(spec, runner, FakeHttpClient(Response(200))).stop("whisper")

    assert result.ok is True
    assert result.changed is True
    assert result.labels == ("com.vox.whisper", "com.voicemode.whisper")
    assert action_calls(runner, "bootout") == [
        (LAUNCHCTL, "bootout", f"gui/{UID}/com.vox.whisper"),
        (LAUNCHCTL, "bootout", f"gui/{UID}/com.voicemode.whisper"),
    ]
    assert runner.loaded == {}


@pytest.mark.asyncio
async def test_restart_is_atomic_for_one_job_and_refuses_label_conflict(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner({spec.primary_job.label: launch_output()})
    service = supervisor(spec, runner, FakeHttpClient(Response(200)))

    restarted = await service.restart("whisper")

    assert restarted.ok is True
    assert action_calls(runner, "kickstart") == [
        (LAUNCHCTL, "kickstart", "-k", f"gui/{UID}/com.vox.whisper")
    ]

    runner.loaded[spec.jobs[1].label] = launch_output(pid=999)
    conflicted = await service.restart("whisper")
    assert conflicted.ok is False
    assert conflicted.commands == ()
    assert "multiple" in conflicted.detail


@pytest.mark.asyncio
async def test_ensure_ready_recovers_with_bounded_restart_and_health_polls(
    tmp_path: Path,
) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner({spec.primary_job.label: launch_output()})
    http = FakeHttpClient(
        ConnectionError("initially down"),
        ConnectionError("still loading"),
        Response(200),
        Response(200),
    )
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = await supervisor(spec, runner, http, sleep=fake_sleep).ensure_ready(
        "whisper",
        restart_attempts=2,
        health_checks_per_attempt=4,
        poll_interval=0.1,
    )

    assert result.ready is True
    assert result.action_attempts == 1
    assert result.checks == 4
    assert len(action_calls(runner, "kickstart")) == 1
    assert sleeps == [0.1, 0.1]


@pytest.mark.asyncio
async def test_ensure_ready_stops_exactly_at_retry_budget(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)
    runner = FakeRunner({spec.primary_job.label: launch_output()})
    http = FakeHttpClient(ConnectionError("always down"))

    async def no_sleep(_seconds: float) -> None:
        return None

    result = await supervisor(spec, runner, http, sleep=no_sleep).ensure_ready(
        "whisper",
        restart_attempts=2,
        health_checks_per_attempt=2,
        poll_interval=0,
    )

    assert result.ready is False
    assert result.action_attempts == 2
    assert result.checks == 7
    assert len(action_calls(runner, "kickstart")) == 2
    assert len(http.calls) == 7


@pytest.mark.asyncio
async def test_tail_logs_uses_launchd_paths_and_reads_only_requested_lines(
    tmp_path: Path,
) -> None:
    spec = make_spec(tmp_path)
    stdout = tmp_path / "live stdout.log"
    stderr = tmp_path / "live stderr.log"
    stdout.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    stderr.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    runner = FakeRunner(
        {
            spec.primary_job.label: launch_output(stdout=stdout, stderr=stderr),
        }
    )

    result = await supervisor(spec, runner, FakeHttpClient(Response(200))).tail_logs(
        "whisper",
        lines=2,
    )

    assert len(result.chunks) == 2
    by_stream = {chunk.stream: chunk for chunk in result.chunks}
    assert by_stream["stdout"].path == stdout
    assert by_stream["stdout"].lines == ("three", "four")
    assert by_stream["stderr"].lines == ("beta", "gamma")
    assert by_stream["stdout"].error is None


@pytest.mark.asyncio
async def test_launchctl_timeout_is_structured_not_misreported_as_stopped(
    tmp_path: Path,
) -> None:
    spec = make_spec(tmp_path)
    runner = AlwaysTimeoutRunner()

    status = await supervisor(
        spec,
        runner,
        FakeHttpClient(Response(200)),
        command_timeout=0.1,
    ).status("whisper")

    assert status.state == "external"
    assert status.ready is True
    assert status.jobs[0].loaded is False
    assert "timed out" in (status.jobs[0].error or "")
    assert all(kwargs["shell"] is False for _, kwargs in runner.calls)
