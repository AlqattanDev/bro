# Vox MCP

Vox is a local-only voice runtime for Claude Code, Codex, and any MCP client.
It keeps the audio engine in a persistent daemon and makes each MCP server a
small reconnectable adapter. Restarting or updating an agent host therefore
does not tear down the voice engine or corrupt its session state.

Vox uses the Whisper.cpp and Kokoro services already installed on this Mac.
It makes **no paid or cloud speech calls**. Speech endpoints must resolve to a
loopback address; Vox refuses to start if they do not.

## What is different

- Explicit `OFF → IDLE → LISTENING / SPEAKING → IDLE` lifecycle instead of a
  hidden state machine inside an MCP subprocess.
- The microphone opens only for one bounded `listen` turn or a
  response-waiting `converse`; manual end provides push-to-talk behavior.
- `pause`, `resume`, `stop`, replay, manual end-of-turn, and cancellation are
  daemon controls and remain available even when an MCP adapter reconnects.
- Native microphone sample-rate capture with a single high-quality resample;
  no hard-coded 24 kHz device assumption.
- Watchdog health probes and bounded restart/retry for local Whisper/Kokoro.
- A click-to-open macOS status panel with explicit start, pause/resume,
  cancel, stop, restart, and local activity controls. It states whether the
  microphone is actually open and explains an automatic idle stop.
- Frozen dependency lock and direct venv launcher. No `uvx --refresh`, no code
  download, and no version drift at MCP startup.
- Last-audio recovery is on by default; conversation archives and raw text
  logging are off by default.

## Status

This directory contains the implementation, installer, host skills, tests,
and the frozen VoiceMode compatibility layer. See `docs/EXPERIENCE.md` for the
listening contract and `docs/ARCHITECTURE.md` for the process model.

Build, inspect the dry-run, then activate transactionally:

```bash
uv sync --extra test --frozen
./scripts/build_macos_app.sh
uv run vox install
uv run vox install --activate --yes
```

Quick checks after installation:

```bash
.venv/bin/vox doctor
.venv/bin/vox session start
.venv/bin/vox status
```

The MCP tools are headed by `converse`, `speak`, `listen`, `voice_session`,
`voice_control`, `service`, `diagnostics`, `transcribe`, and `dj`.

Restart Claude Code and Codex once after activation so their MCP catalogs
reload. The Vox daemon persists across later host restarts and updates.

The `Vox` item in the macOS menu bar is a local control panel, not an
always-listening toggle. Click it to start/pause/stop a session or cancel the
current turn; starting or resuming only makes Vox ready. The microphone stays
closed until a host calls `listen` or response-waiting `converse`.
