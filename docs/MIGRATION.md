# Migration and rollback

Migration is transactional. Vox does not delete the existing VoiceMode files,
models, or service definitions.

## Activation order

1. Build a dedicated Vox virtual environment from `uv.lock` with `--frozen`.
2. Run unit tests and a loopback canary against the existing Whisper/Kokoro.
3. Snapshot host MCP files, skills, plists, and exact loaded-job state.
4. Install the Vox app, skills, and fixed direct LaunchAgents.
5. Register `http://127.0.0.1:8766/mcp` as `vox` in Claude Code and Codex,
   remove the old `uvx --refresh` registration, and set Codex's dedicated
   600-second voice-tool timeout.
6. Unload the obsolete Connect/watchdog jobs and legacy backend jobs.
7. Start Whisper, Kokoro, then Vox; require all three loopback health canaries.
8. Seal the snapshot only after every canary passes. Any failure automatically
   restores the old host files and exact pre-migration launchd state.

Before each mutation the installer saves the original file and loaded-service
state under `~/.vox/rollback/<timestamp>/manifest.json`.

## Rollback

`vox rollback <snapshot> --yes` stops Vox, restores the prior launchd plists and host
MCP entries, and bootstraps only the jobs that were loaded before migration.
It never removes the Whisper/Kokoro repositories or models.

## Existing breakage cleaned by migration

- `com.voicemode.connect`: removed command in a 10-second launchd crash loop.
- `com.voicemode.whisper-keepalive`: nonexistent script in a 30-second loop.
- Kokoro: forced exit every 25 requests plus `uv pip install -e .` on restart.
- Whisper/Kokoro: unauthenticated `0.0.0.0` listeners.
- Claude Code: unpinned `uvx --refresh` MCP startup.
- Codex: missing VoiceMode registration and incompatible 60-second default
  tool timeout.
