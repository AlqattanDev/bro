# Architecture

```text
Claude Code ── Streamable HTTP ─┐
                               │
Codex ──────── Streamable HTTP ─┼── 127.0.0.1:8766/mcp
                               │          Vox runtime (launchd)
CLI / menu bar ─ local control ┘             │
                                             ├── audio state machine
                                             ├── native-rate CoreAudio capture
                                             ├── bounded recovery/replay store
                                             ├── service watchdog
                                             └── one hardware owner/lease
                                                    │
                           ┌────────────────────────┴──────────────────────┐
                           │                                               │
                  Whisper.cpp :2022                              Kokoro :8880
                  127.0.0.1 only                                 127.0.0.1 only
                           │                                               │
                  whisper-cli fallback                           macOS say fallback
```

## Why the runtime is not a stdio child

The old MCP process is owned by the agent host. When Claude Code cancels,
updates, or tears down stdio, it can strand the underlying recording thread
after the MCP lock has already been released. It also cannot reconnect to a
dead stdio child.

Vox is a launchd-supervised Streamable HTTP server. Host processes are only
clients. Claude Code and Codex can reconnect independently; audio cancellation
and cleanup happen inside the process that owns the device.

## State and concurrency

The durable session state is explicit:

```text
OFF ──start──> IDLE ──speak──> SPEAKING ──done──> IDLE
                    └listen──> LISTENING ──audio──> PROCESSING ──done──> IDLE
                                  │
                         pause/cancel/stop
                                  │
                      PAUSED / IDLE / OFF

Any active state ──local backend failure──> ERROR/DEGRADED ──recovery──> IDLE
```

Only the runtime mutates this state. Each transition is validated, persisted
atomically, and logged without raw spoken text. A single operation lock protects
the audio device; a client lease protects multi-host ownership. Cancel and
manual-end events bypass that lock so they can interrupt an in-flight turn.

## Local-only boundary

- MCP, Whisper, and Kokoro bind to `127.0.0.1`.
- Speech endpoint configuration accepts only literal loopback hosts.
- HTTP clients ignore proxy environment variables and do not follow redirects.
- API-key environment variables are removed from compatibility subprocesses.
- Startup never installs packages, downloads models, resolves `latest`, or
  sources a shell environment file.
- The production launcher is an absolute path inside a frozen `.venv`.

“OpenAI-compatible” describes the JSON/multipart format spoken by local
Whisper and Kokoro. It does not mean OpenAI’s paid API is called.

## Retention

The default store contains exactly one latest STT recording, one latest TTS
recording, and eight replay clips. Work files expire after 24 hours. Full audio
archives, transcript archives, and transcript-bearing logs are off by default.
This replaces the current unbounded 2.5 GB audio directory and transcript-rich
service logs.

Setting `VOX_PERSIST_AUDIO=false` moves this bounded recovery store into an
ephemeral private temporary directory for the daemon lifetime.

## Frozen compatibility layer

The MIT-licensed VoiceMode 8.11.0 Python package is vendored for mature fringe
features: DJ/library operations, soundfonts, exchange tooling, voice clones,
model utilities, and shell completions. Vox launches it through fixed argv
arrays with cloud credentials removed and local endpoint variables forced.
The main conversation path does not import its implicit conversation state
machine.
