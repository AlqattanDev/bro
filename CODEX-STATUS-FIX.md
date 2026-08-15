# Codex brief: partner bar stuck on "listening"

Do not patch one call site. The bar lies because the status loop dies at boot and is never restarted.

## What Ali sees

- Presses F4, talks, bar stays **listening** forever.
- Mode prefix (call / ping / quiet) also fails to update — same dead painter.
- He has asked for this fix more than once. Previous fixes touched one spot and the next boot broke it again.

## Proof from this session (2026-08-15)

| Check | Result |
|---|---|
| `~/.partner/status-word` | `listening` |
| Vox `state.json` | `state=idle`, `microphone_open=false` |
| `status-loop.pid` | `63159` — process **dead** |
| `watch/watch.pid` | `63158` — **alive** ~4h40m |
| `logs/status.log` | empty (died before useful output) |
| Work pane | `codex` already open — do not hijack it with `partner-run` |

## Root cause (three coupled bugs)

### 1. Status loop starts before the tmux session exists, then dies

`~/.partner/bin/partner` `create_session`:

```bash
start_watch_loop    # starts status-loop HERE
# then later:
new-session ...
```

`~/.partner/bin/partner-status-loop` has `set -euo pipefail` and this unguarded pipeline:

```bash
tmux -L "$SOCKET" list-clients -F '#{client_name}' 2>/dev/null | while read -r c; do
  tmux -L "$SOCKET" refresh-client -S -t "$c" 2>/dev/null || true
done
```

`tmux list-clients` exits **1** when there is no session yet, or no attached client. `pipefail` + `set -e` kills the whole loop on the first tick. That is why the pidfile is stale and the log is empty.

### 2. Dead status loop is never restarted

`start_status_loop` is only called from `start_watch_loop`, and only after starting a **new** watch process:

```bash
start_watch_loop() {
  if watch-pid is alive; then
    return 0          # NEVER reaches start_status_loop
  fi
  start watch
  start_status_loop
}
```

Watch stays up. Status dies. Every later `partner` attach is a no-op for the bar. F4 writes `listening` via `partner-talk` and nothing ever paints the next state.

### 3. Even a living loop cannot reach `ready`

Idle branch in `partner-status-loop`:

```bash
idle|"")
  if [[ "$cur" == "speaking" || "$cur" == "listening" ]]; then
    echo working >"$WORD"
  fi
  ;;
```

After the mic closes it would sit on **working** forever. There is no path to `ready` unless a human/`partner-status ready` does it. The backend boot prompt never requires that call. Fragile `grep` of the first `"state":"..."` in `state.json` is also not a JSON parse.

## Required fix (all of it)

1. **Supervise independently.** `start_status_loop` on every `partner` start/attach, regardless of watch liveness. If the pid is dead, start a new one. Optionally a tiny supervisor so a later crash comes back without re-attach.

2. **The loop must not be able to die from tmux.** Guard the `list-clients` pipeline with `|| true`. Tolerate missing session / zero clients. Keep painting `status-line` even when no client is attached.

3. **Single owner for the word.**
   - Vox `state.json` (parsed as JSON, not grepped): `speaking` / `listening` / `processing` → bar matches.
   - Vox idle + mic closed → `ready`, unless the backend has explicitly set `working`.
   - `partner-talk` may set `listening` only as a hint; the loop must overwrite it the moment Vox is idle and the mic is closed.
   - `starting` only during backend boot, then `ready`.

4. **Backend contract in `partner-boot-prompt.txt`:** call `partner-status working` while acting, `partner-status ready` when idle. Do not rely on the agent for F4 listen→ready — the loop owns that.

5. **Mode prefix** (`~/.partner/mode`) must keep updating from the same living painter (`partner-status-paint` already reads it).

## Do not do

- A timeout in `partner-talk` that forces `ready`.
- Only adding `|| true` on the pipeline and leaving the restart coupling.
- Only teaching the agent to call `partner-status`.
- Restarting the loop by hand and calling it fixed.

## Verify before done

- Fresh `partner` start: bar `starting` → `ready` without anyone pressing a key.
- Kill the status-loop process, run `partner` attach (or wait for supervisor): new loop, bar still correct.
- F4: bar is `listening` only while the mic is actually open; then `working` or `ready`, never stuck.
- After a spoken reply: `speaking` then `ready`.
- `bro quiet` / `bro call` / `bro ping`: prefix updates live.
- Start partner with no client attached yet; loop still alive after attach.

## Files to touch

- `~/.partner/bin/partner` — decouple start/restart of status loop from watch loop
- `~/.partner/bin/partner-status-loop` — no-die loop, JSON parse, idle → ready
- `~/.partner/bin/partner-talk` — hint only; must not be the owner of the word
- `~/.partner/bin/partner-status` / `partner-status-paint` — keep as the write/paint API
- `~/.partner/partner-boot-prompt.txt` — working/ready contract
- `~/.partner/HOW-TO.md` — only if the bar states change meaning
