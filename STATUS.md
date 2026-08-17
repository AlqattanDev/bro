# STATUS — bro

Bro is global. It is no longer a tmux thing with a terminal attached; it is a
background service with a face in the menu bar, a panel that floats over any
app, and a hotkey that reaches it from anywhere.

## Where it stands (2026-08-17)

All six phases are implemented, tested (19 passing), and committed. The plan
file is `DONE`.

- Menu bar shows bro's real state from any app — `a1a8cb9`
- Screen snapshot, ask-only, three independent gates — `1b3d336`
- Floating answer panel that never steals focus — `2dd769d`
- launchd daemon; closing every terminal does not kill bro — `1f7c515`
- The 3-second watch loop is gone; bro looks when asked — `9eb6b62`
- Global summon: ⌥§ voice, ⌃§ typed, both asynchronous — `6ecf393`

## Waiting on Ali at the keyboard

Nothing here is known broken — it is the part no test can reach. There is now
a script for it: **`bro verify`** walks all five and records the outcome in
`~/.bro/verify.md`.

1. `bro daemon install` — deliberately not run. It writes a login item into
   `~/Library/LaunchAgents`; that is Ali's machine startup to change, not mine.
   Verified nothing was written there.
2. Restart BroBar (`bro stop && bro`), then press ⌥§ and ⌃§ from a browser or
   IDE. Confirm no permissions prompt. Carbon should not produce one.
3. Type into the ⌃§ field: keys reach it, Enter sends, Esc cancels, focus
   returns to the app you came from. This is the one interaction never
   exercised headlessly. If keys do not arrive, drop `.nonactivatingPanel`
   from `SummonPanel` only — never from `AnswerPanel`.
4. Optional: grant BroBar Accessibility once for Esc-to-dismiss on the answer
   panel. It now survives rebuilds, because signing is stable.
5. `bro summon "read this page for me"` with a webpage up — confirm it takes a
   screen snapshot, not the terminal pane.

## Settled since (2026-08-17, second pass)

- **State lives in `~/.bro/state/`** — words, pidfiles, mode, backend,
  show-policy. Any `bro` command migrates an old flat install once, never
  overwriting a live file. BroBar and tmux.conf read `state/` first with the
  root path as fallback.
- **The `~/.partner` era is gone** — CODEX work orders, `inbox.md`, and
  `show/codex-job.txt` deleted; `watch/stream.log` and its 1MB cap removed
  from `bro-snapshot`.
- **`README.md` exists** — philosophy, install, keys, layout.
- **23 tests** (was 19): bro-verify, state migration, legacy show-policy
  fallback.

## Things worth knowing

- **One menu bar item.** Bro claims `~/.vox/status-host.json`; Vox hides its
  own icon while that pid is alive. Shipped 2026-08-17: bro `290d33d`, Vox
  rebuilt and installed. Right-click bro's item to give Vox its icon back.
- **The screen is ask-only on purpose.** Three gates: the caller passes no
  `--screen`, `BRO_NO_SCREEN` refuses it in any automatic context, and
  `show-policy` can refuse outright. Keep all three when touching this.
- **Speaker ID is on**, with `ali` and `boss` enrolled.
