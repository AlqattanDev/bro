"""Local speech-service supervision without runtime installation or updates.

The supervisor deliberately keeps two facts separate:

* launchd state answers whether Vox manages a process; and
* loopback health answers whether the service is actually usable.

That distinction prevents a loaded or running launchd job from being reported
as healthy when its HTTP endpoint is unavailable.  Runtime lifecycle commands
are restricted to launchctl's load/start/stop primitives.  Package managers,
downloaders, shell evaluation, and environment-file sourcing do not belong in
this module.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import time
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

import httpx


ServiceState = Literal[
    "ready",
    "external",
    "conflict",
    "starting",
    "unhealthy",
    "stopped",
    "not_loaded",
]
LogStreamName = Literal["stdout", "stderr", "both"]


class HttpClient(Protocol):
    """Small subset of an async HTTP client needed for health checks."""

    async def get(self, url: str, **kwargs: Any) -> Any: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class LaunchdJobSpec:
    """One launchd label that may own a speech service."""

    label: str
    plist_path: Path | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    legacy: bool = False

    def __post_init__(self) -> None:
        if not self.label or "/" in self.label or self.label.strip() != self.label:
            raise ValueError(f"invalid launchd label: {self.label!r}")


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Static, local-only definition of a supervised service."""

    name: str
    health_url: str
    jobs: tuple[LaunchdJobSpec, ...]

    def __post_init__(self) -> None:
        if not self.name or self.name.strip() != self.name:
            raise ValueError(f"invalid service name: {self.name!r}")
        if not self.jobs:
            raise ValueError(f"service {self.name!r} must define at least one launchd job")
        labels = [job.label for job in self.jobs]
        if len(labels) != len(set(labels)):
            raise ValueError(f"service {self.name!r} has duplicate launchd labels")
        _require_loopback_http_url(self.health_url)

    @property
    def primary_job(self) -> LaunchdJobSpec:
        return self.jobs[0]

    @property
    def legacy_jobs(self) -> tuple[LaunchdJobSpec, ...]:
        return tuple(job for job in self.jobs if job.legacy)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured result of one bounded, argv-only subprocess invocation."""

    argv: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Truthful result of one loopback HTTP health check."""

    url: str
    reachable: bool
    healthy: bool
    status_code: int | None
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "reachable": self.reachable,
            "healthy": self.healthy,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class LaunchdJobStatus:
    """Parsed state for one possible primary or migration-time job."""

    label: str
    legacy: bool
    loaded: bool
    state: str | None = None
    pid: int | None = None
    runs: int | None = None
    last_exit_code: int | None = None
    last_exit_detail: str | None = None
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    error: str | None = None

    @property
    def running(self) -> bool:
        return self.loaded and self.state == "running"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "legacy": self.legacy,
            "loaded": self.loaded,
            "state": self.state,
            "running": self.running,
            "pid": self.pid,
            "runs": self.runs,
            "last_exit_code": self.last_exit_code,
            "last_exit_detail": self.last_exit_detail,
            "stdout_path": str(self.stdout_path) if self.stdout_path else None,
            "stderr_path": str(self.stderr_path) if self.stderr_path else None,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Combined launchd and endpoint state; neither is inferred from the other."""

    service: str
    state: ServiceState
    ready: bool
    managed: bool
    process_running: bool
    active_label: str | None
    using_legacy_label: bool
    loaded_labels: tuple[str, ...]
    health: HealthStatus
    jobs: tuple[LaunchdJobStatus, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "state": self.state,
            "ready": self.ready,
            "managed": self.managed,
            "process_running": self.process_running,
            "active_label": self.active_label,
            "using_legacy_label": self.using_legacy_label,
            "loaded_labels": list(self.loaded_labels),
            "health": self.health.to_dict(),
            "jobs": [job.to_dict() for job in self.jobs],
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ServiceActionResult:
    """Structured outcome of a launchd lifecycle request."""

    service: str
    action: Literal["start", "stop", "restart"]
    ok: bool
    changed: bool
    labels: tuple[str, ...]
    commands: tuple[CommandResult, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "action": self.action,
            "ok": self.ok,
            "changed": self.changed,
            "labels": list(self.labels),
            "commands": [command.to_dict() for command in self.commands],
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EnsureReadyResult:
    """Bounded readiness attempt including every lifecycle action taken."""

    service: str
    ready: bool
    checks: int
    action_attempts: int
    status: ServiceStatus
    actions: tuple[ServiceActionResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "ready": self.ready,
            "checks": self.checks,
            "action_attempts": self.action_attempts,
            "status": self.status.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True, slots=True)
class LogChunk:
    """Bounded tail from one configured or launchd-reported log file."""

    label: str
    stream: Literal["stdout", "stderr"]
    path: Path
    lines: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "stream": self.stream,
            "path": str(self.path),
            "lines": list(self.lines),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class LogTail:
    """Structured result of a bounded service-log read."""

    service: str
    requested_lines: int
    chunks: tuple[LogChunk, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "requested_lines": self.requested_lines,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "detail": self.detail,
        }


def _require_loopback_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"health URL must be unauthenticated loopback HTTP: {url!r}")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError(f"health URL must use a literal loopback address: {url!r}") from exc
    if not address.is_loopback:
        raise ValueError(f"health URL is not loopback-only: {url!r}")


def default_service_specs(home: Path | None = None) -> Mapping[str, ServiceSpec]:
    """Build primary Vox and migration-time VoiceMode service definitions."""

    root = Path.home() if home is None else Path(home)
    launch_agents = root / "Library" / "LaunchAgents"
    legacy_logs = root / ".voicemode" / "logs"

    whisper = ServiceSpec(
        name="whisper",
        health_url="http://127.0.0.1:2022/health",
        jobs=(
            LaunchdJobSpec(
                label="com.vox.whisper",
                plist_path=launch_agents / "com.vox.whisper.plist",
                stdout_path=Path("/dev/null"),
                stderr_path=Path("/dev/null"),
            ),
            LaunchdJobSpec(
                label="com.voicemode.whisper",
                plist_path=launch_agents / "com.voicemode.whisper.plist",
                stdout_path=legacy_logs / "whisper" / "whisper.out.log",
                stderr_path=legacy_logs / "whisper" / "whisper.err.log",
                legacy=True,
            ),
        ),
    )
    kokoro = ServiceSpec(
        name="kokoro",
        health_url="http://127.0.0.1:8880/health",
        jobs=(
            LaunchdJobSpec(
                label="com.vox.kokoro",
                plist_path=launch_agents / "com.vox.kokoro.plist",
                stdout_path=Path("/dev/null"),
                stderr_path=Path("/dev/null"),
            ),
            LaunchdJobSpec(
                label="com.voicemode.kokoro",
                plist_path=launch_agents / "com.voicemode.kokoro.plist",
                stdout_path=legacy_logs / "kokoro" / "kokoro.out.log",
                stderr_path=legacy_logs / "kokoro" / "kokoro.err.log",
                legacy=True,
            ),
        ),
    )
    return MappingProxyType({"whisper": whisper, "kokoro": kokoro})


SERVICE_SPECS = default_service_specs()
WHISPER_SPEC = SERVICE_SPECS["whisper"]
KOKORO_SPEC = SERVICE_SPECS["kokoro"]


class ServiceSupervisor:
    """Supervise immutable, pre-installed local speech services."""

    def __init__(
        self,
        specs: Mapping[str, ServiceSpec] | None = None,
        *,
        runner: Runner = subprocess.run,
        http_client: HttpClient | None = None,
        sleep: Sleeper = asyncio.sleep,
        path_exists: Callable[[Path], bool] = Path.exists,
        uid: int | None = None,
        launchctl_path: str = "/bin/launchctl",
        command_timeout: float = 5.0,
        health_timeout: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if command_timeout <= 0 or health_timeout <= 0:
            raise ValueError("command and health timeouts must be positive")
        self.specs = dict(SERVICE_SPECS if specs is None else specs)
        if not self.specs:
            raise ValueError("at least one service spec is required")
        for key, spec in self.specs.items():
            if key != spec.name:
                raise ValueError(f"service mapping key {key!r} does not match {spec.name!r}")
        self._runner = runner
        self._http_client = http_client
        self._sleep = sleep
        self._path_exists = path_exists
        self._uid = os.getuid() if uid is None else uid
        self._launchctl_path = launchctl_path
        self._command_timeout = command_timeout
        self._health_timeout = health_timeout
        self._clock = clock

    def _spec(self, service: str) -> ServiceSpec:
        try:
            return self.specs[service]
        except KeyError as exc:
            choices = ", ".join(sorted(self.specs))
            raise KeyError(f"unknown service {service!r}; expected one of: {choices}") from exc

    @property
    def _domain(self) -> str:
        return f"gui/{self._uid}"

    async def _run(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(str(part) for part in argv)
        if not command or command[0] != self._launchctl_path:
            return CommandResult(command, None, error="runtime service commands must use launchctl")
        try:
            completed = await asyncio.to_thread(
                self._runner,
                list(command),
                capture_output=True,
                text=True,
                timeout=self._command_timeout,
                check=False,
                shell=False,
            )
            return CommandResult(
                command,
                completed.returncode,
                completed.stdout or "",
                completed.stderr or "",
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command,
                None,
                stdout=_coerce_output(exc.stdout),
                stderr=_coerce_output(exc.stderr),
                error=f"launchctl timed out after {self._command_timeout:.2f}s",
            )
        except OSError as exc:
            return CommandResult(command, None, error=f"launchctl failed: {exc}")

    async def check_health(self, service: str) -> HealthStatus:
        """Check only the service's literal loopback health endpoint."""

        spec = self._spec(service)
        started = self._clock()
        try:
            if self._http_client is None:
                async with httpx.AsyncClient(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=self._health_timeout,
                ) as client:
                    response = await client.get(spec.health_url)
            else:
                response = await self._http_client.get(
                    spec.health_url,
                    timeout=self._health_timeout,
                    follow_redirects=False,
                )
            status_code = int(response.status_code)
            healthy = 200 <= status_code < 300
            return HealthStatus(
                url=spec.health_url,
                reachable=True,
                healthy=healthy,
                status_code=status_code,
                latency_ms=round((self._clock() - started) * 1000, 2),
                error=None if healthy else f"health endpoint returned HTTP {status_code}",
            )
        except Exception as exc:  # clients expose several transport exception types
            return HealthStatus(
                url=spec.health_url,
                reachable=False,
                healthy=False,
                status_code=None,
                latency_ms=round((self._clock() - started) * 1000, 2),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _inspect_job(self, job: LaunchdJobSpec) -> LaunchdJobStatus:
        result = await self._run((self._launchctl_path, "print", f"{self._domain}/{job.label}"))
        if not result.ok:
            error = result.error or _first_nonempty(result.stderr, result.stdout)
            return LaunchdJobStatus(
                label=job.label,
                legacy=job.legacy,
                loaded=False,
                stdout_path=job.stdout_path,
                stderr_path=job.stderr_path,
                error=error or "launchd job is not loaded",
            )
        return _parse_launchctl_print(job, result.stdout)

    async def _inspect_jobs(self, spec: ServiceSpec) -> tuple[LaunchdJobStatus, ...]:
        # Keep launchctl calls ordered so primary-vs-legacy selection is stable.
        statuses: list[LaunchdJobStatus] = []
        for job in spec.jobs:
            statuses.append(await self._inspect_job(job))
        return tuple(statuses)

    async def status(self, service: str) -> ServiceStatus:
        """Return launchd and health state without conflating the two."""

        spec = self._spec(service)
        jobs, health = await asyncio.gather(self._inspect_jobs(spec), self.check_health(service))
        loaded = tuple(job for job in jobs if job.loaded)
        active = loaded[0] if loaded else None
        running = any(job.running for job in loaded)

        if len(loaded) > 1:
            state: ServiceState = "conflict"
            detail = (
                "multiple launchd labels are loaded; stop the duplicate before relying "
                "on lifecycle operations"
            )
        elif health.healthy and active is None:
            state = "external"
            detail = "loopback endpoint is healthy but no known launchd job is loaded"
        elif health.healthy:
            state = "ready"
            detail = "loopback endpoint is healthy"
        elif active is None:
            state = "not_loaded"
            detail = "no known launchd job is loaded and the endpoint is unavailable"
        elif active.state in {"spawn scheduled", "waiting", "starting"}:
            state = "starting"
            detail = f"launchd reports {active.state!r}; endpoint is not ready"
        elif active.running:
            state = "unhealthy"
            detail = "launchd process is running but the endpoint health check failed"
        else:
            state = "stopped"
            detail = f"launchd job is loaded with state {active.state!r}; endpoint is unavailable"

        return ServiceStatus(
            service=service,
            state=state,
            ready=health.healthy,
            managed=bool(loaded),
            process_running=running,
            active_label=active.label if active else None,
            using_legacy_label=bool(active and active.legacy),
            loaded_labels=tuple(job.label for job in loaded),
            health=health,
            jobs=jobs,
            detail=detail,
        )

    async def all_statuses(self) -> dict[str, ServiceStatus]:
        """Return status for every configured service."""

        names = tuple(self.specs)
        statuses = await asyncio.gather(*(self.status(name) for name in names))
        return dict(zip(names, statuses, strict=True))

    async def start(self, service: str) -> ServiceActionResult:
        """Start a loaded job or bootstrap an already-installed plist."""

        spec = self._spec(service)
        jobs = await self._inspect_jobs(spec)
        loaded = tuple(job for job in jobs if job.loaded)
        if len(loaded) > 1:
            return _action_failure(service, "start", loaded, "multiple launchd labels are loaded")
        if loaded:
            job = loaded[0]
            command = await self._run(
                (self._launchctl_path, "kickstart", f"{self._domain}/{job.label}")
            )
            return _single_command_action(service, "start", job.label, command)

        candidate = next(
            (
                job
                for job in spec.jobs
                if job.plist_path is not None and self._path_exists(job.plist_path)
            ),
            None,
        )
        if candidate is None:
            return ServiceActionResult(
                service=service,
                action="start",
                ok=False,
                changed=False,
                labels=(),
                commands=(),
                detail="no pre-installed primary or legacy launchd plist was found",
            )
        command = await self._run(
            (self._launchctl_path, "bootstrap", self._domain, str(candidate.plist_path))
        )
        return _single_command_action(service, "start", candidate.label, command)

    async def stop(self, service: str) -> ServiceActionResult:
        """Boot out all known loaded labels so KeepAlive cannot immediately respawn."""

        spec = self._spec(service)
        loaded = tuple(job for job in await self._inspect_jobs(spec) if job.loaded)
        if not loaded:
            return ServiceActionResult(
                service=service,
                action="stop",
                ok=True,
                changed=False,
                labels=(),
                commands=(),
                detail="service is already stopped; no known launchd label is loaded",
            )
        commands: list[CommandResult] = []
        for job in loaded:
            commands.append(
                await self._run(
                    (self._launchctl_path, "bootout", f"{self._domain}/{job.label}")
                )
            )
        ok = all(command.ok for command in commands)
        return ServiceActionResult(
            service=service,
            action="stop",
            ok=ok,
            changed=ok,
            labels=tuple(job.label for job in loaded),
            commands=tuple(commands),
            detail="service labels booted out" if ok else "one or more launchd bootout commands failed",
        )

    async def restart(self, service: str) -> ServiceActionResult:
        """Restart one loaded label, or start from an already-installed plist."""

        spec = self._spec(service)
        loaded = tuple(job for job in await self._inspect_jobs(spec) if job.loaded)
        if len(loaded) > 1:
            return _action_failure(service, "restart", loaded, "multiple launchd labels are loaded")
        if not loaded:
            started = await self.start(service)
            return ServiceActionResult(
                service=service,
                action="restart",
                ok=started.ok,
                changed=started.changed,
                labels=started.labels,
                commands=started.commands,
                detail=(
                    "service was not loaded; bootstrapped an installed plist"
                    if started.ok
                    else started.detail
                ),
            )
        job = loaded[0]
        command = await self._run(
            (self._launchctl_path, "kickstart", "-k", f"{self._domain}/{job.label}")
        )
        return _single_command_action(service, "restart", job.label, command)

    async def ensure_ready(
        self,
        service: str,
        *,
        restart_attempts: int = 2,
        health_checks_per_attempt: int = 8,
        poll_interval: float = 0.25,
    ) -> EnsureReadyResult:
        """Boundedly start/restart a service and wait for loopback health.

        At most ``restart_attempts`` lifecycle commands and exactly bounded
        health polls are performed.  Expected unavailability is returned as
        structured state rather than hidden behind an unbounded retry loop.
        """

        if restart_attempts < 0:
            raise ValueError("restart_attempts must be non-negative")
        if health_checks_per_attempt < 1:
            raise ValueError("health_checks_per_attempt must be at least one")
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative")

        current = await self.status(service)
        checks = 1
        actions: list[ServiceActionResult] = []
        if current.ready:
            return EnsureReadyResult(service, True, checks, 0, current, ())

        for _ in range(restart_attempts):
            action = await (self.restart(service) if current.managed else self.start(service))
            actions.append(action)
            if action.ok:
                for _ in range(health_checks_per_attempt):
                    if poll_interval:
                        await self._sleep(poll_interval)
                    health = await self.check_health(service)
                    checks += 1
                    if health.healthy:
                        current = await self.status(service)
                        checks += 1
                        return EnsureReadyResult(
                            service,
                            current.ready,
                            checks,
                            len(actions),
                            current,
                            tuple(actions),
                        )
            current = await self.status(service)
            checks += 1
            if current.ready:
                return EnsureReadyResult(
                    service,
                    True,
                    checks,
                    len(actions),
                    current,
                    tuple(actions),
                )

        return EnsureReadyResult(
            service,
            current.ready,
            checks,
            len(actions),
            current,
            tuple(actions),
        )

    async def tail_logs(
        self,
        service: str,
        *,
        lines: int = 50,
        stream: LogStreamName = "both",
    ) -> LogTail:
        """Read bounded tails from launchd-reported or configured log files."""

        if not 1 <= lines <= 1000:
            raise ValueError("lines must be between 1 and 1000")
        if stream not in {"stdout", "stderr", "both"}:
            raise ValueError("stream must be 'stdout', 'stderr', or 'both'")

        spec = self._spec(service)
        statuses = await self._inspect_jobs(spec)
        selected = tuple(job for job in statuses if job.loaded)
        if not selected:
            selected = tuple(
                LaunchdJobStatus(
                    label=job.label,
                    legacy=job.legacy,
                    loaded=False,
                    stdout_path=job.stdout_path,
                    stderr_path=job.stderr_path,
                )
                for job in spec.jobs
                if (job.stdout_path and self._path_exists(job.stdout_path))
                or (job.stderr_path and self._path_exists(job.stderr_path))
            )

        requests: list[tuple[str, Literal["stdout", "stderr"], Path]] = []
        suppressed = 0
        for job in selected:
            if stream in {"stdout", "both"} and job.stdout_path:
                if job.stdout_path == Path("/dev/null"):
                    suppressed += 1
                else:
                    requests.append((job.label, "stdout", job.stdout_path))
            if stream in {"stderr", "both"} and job.stderr_path:
                if job.stderr_path == Path("/dev/null"):
                    suppressed += 1
                else:
                    requests.append((job.label, "stderr", job.stderr_path))

        chunks: list[LogChunk] = []
        seen: set[tuple[str, Path]] = set()
        for label, source, path in requests:
            key = (source, path)
            if key in seen:
                continue
            seen.add(key)
            chunks.append(await asyncio.to_thread(_tail_file, label, source, path, lines))

        if chunks:
            detail = f"read {len(chunks)} bounded log tail(s)"
        elif suppressed:
            detail = (
                "operational service logs are intentionally disabled to avoid "
                "unbounded transcript-bearing files; use status/health diagnostics"
            )
        else:
            detail = "no launchd-reported or configured log files were found"
        return LogTail(service, lines, tuple(chunks), detail)


_FIELD_PATTERNS = {
    "state": re.compile(r"^\s*state = (.+?)\s*$", re.MULTILINE),
    "pid": re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE),
    "runs": re.compile(r"^\s*runs = (\d+)\s*$", re.MULTILINE),
    "last_exit": re.compile(r"^\s*last exit code = (.+?)\s*$", re.MULTILINE),
    "stdout": re.compile(r"^\s*stdout path = (.+?)\s*$", re.MULTILINE),
    "stderr": re.compile(r"^\s*stderr path = (.+?)\s*$", re.MULTILINE),
}


def _parse_launchctl_print(job: LaunchdJobSpec, output: str) -> LaunchdJobStatus:
    state = _match(_FIELD_PATTERNS["state"], output)
    pid = _as_int(_match(_FIELD_PATTERNS["pid"], output))
    runs = _as_int(_match(_FIELD_PATTERNS["runs"], output))
    last_exit_detail = _match(_FIELD_PATTERNS["last_exit"], output)
    last_exit_code = _as_int(last_exit_detail)
    stdout = _match(_FIELD_PATTERNS["stdout"], output)
    stderr = _match(_FIELD_PATTERNS["stderr"], output)
    return LaunchdJobStatus(
        label=job.label,
        legacy=job.legacy,
        loaded=True,
        state=state,
        pid=pid,
        runs=runs,
        last_exit_code=last_exit_code,
        last_exit_detail=last_exit_detail,
        stdout_path=Path(stdout) if stdout else job.stdout_path,
        stderr_path=Path(stderr) if stderr else job.stderr_path,
    )


def _match(pattern: re.Pattern[str], text: str) -> str | None:
    matched = pattern.search(text)
    return matched.group(1).strip() if matched else None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _first_nonempty(*values: str) -> str | None:
    return next((value.strip() for value in values if value and value.strip()), None)


def _action_failure(
    service: str,
    action: Literal["start", "restart"],
    jobs: Sequence[LaunchdJobStatus],
    detail: str,
) -> ServiceActionResult:
    return ServiceActionResult(
        service=service,
        action=action,
        ok=False,
        changed=False,
        labels=tuple(job.label for job in jobs),
        commands=(),
        detail=detail,
    )


def _single_command_action(
    service: str,
    action: Literal["start", "restart"],
    label: str,
    command: CommandResult,
) -> ServiceActionResult:
    detail = (
        f"launchd {action} requested for {label}"
        if command.ok
        else command.error or _first_nonempty(command.stderr, command.stdout) or "launchctl failed"
    )
    return ServiceActionResult(
        service=service,
        action=action,
        ok=command.ok,
        changed=command.ok,
        labels=(label,),
        commands=(command,),
        detail=detail,
    )


def _tail_file(
    label: str,
    stream: Literal["stdout", "stderr"],
    path: Path,
    line_count: int,
) -> LogChunk:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = deque((line.rstrip("\r\n") for line in handle), maxlen=line_count)
        return LogChunk(label, stream, path, tuple(tail))
    except OSError as exc:
        return LogChunk(label, stream, path, (), error=f"{type(exc).__name__}: {exc}")


__all__ = [
    "CommandResult",
    "EnsureReadyResult",
    "HealthStatus",
    "KOKORO_SPEC",
    "LaunchdJobSpec",
    "LaunchdJobStatus",
    "LogChunk",
    "LogTail",
    "SERVICE_SPECS",
    "ServiceActionResult",
    "ServiceSpec",
    "ServiceStatus",
    "ServiceSupervisor",
    "WHISPER_SPEC",
    "default_service_specs",
]
