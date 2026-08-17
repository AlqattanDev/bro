# bro

An always-on AI copilot for your Mac — a background service with a face in the
menu bar, a floating answer panel, voice, and two global hotkeys that reach it
from any app. It is not there to do your work. It is there to do what you want
and help you reach your goals.

The agent itself (Grok, Claude, or Codex) runs hidden. You never look at its
chat UI. You talk to bro; bro shows you clean answers.

```
you ──⌥§ / ⌃§ / F4 / `bro …`──► inbox queue ──► hidden backend agent
                                      │
                                      ├─► floating answer panel (never steals focus)
                                      ├─► voice reply (Vox: local Whisper + Kokoro)
                                      └─► commands typed into YOUR terminal (bro-run)
menu bar: one item, bro's real state — starting · working · listening · speaking · ready
```

## The philosophy (permanent)

- **Nothing watches you.** No timer captures your terminal or screen. Bro
  looks at the exact moment it acts on something you asked for — one ask, one
  look.
- **The screen is ask-only, triple-gated.** Callers never pass `--screen` by
  default; `BRO_NO_SCREEN` refuses capture in any automatic context;
  `~/.bro/state/show-policy` set to `no-screen` refuses it outright. All three
  stay when touching this code.
- **The panel is not a chat log.** Answers and plans you asked for. Nothing
  else opens it.
- **A terminal is just a client.** The backend is owned by a launchd daemon.
  Closing every window leaves bro running; only `bro stop` takes it down.

## Install

```bash
git clone <this repo> ~/.bro && cd ~/.bro
./install.sh          # builds BroBar, checks the machine, prints next steps
bro                   # start / attach the session
bro daemon install    # optional, explicit: come back at login (launchd)
```

Permissions bro will ask macOS for, when the feature first runs: Microphone
(voice), Screen Recording (`bro-snapshot --screen`), optionally Accessibility
(Esc-to-dismiss on the panel). The global hotkeys use Carbon and need **no**
grant.

## Keys

| Key | What |
|---|---|
| **⌥§** | summon by voice, from any app — mic opens, answer comes back async |
| **⌃§** | summon by typing, from any app — Enter sends, Esc cancels |
| **F1** | toggle the floating answer panel |
| **F3** | snapshot the screen for bro |
| **F4** | talk — mic opens now |

`§` is the key left of `1`. Rebind in `~/.bro/hotkeys`. Modes: `bro quiet`
(panel only), `bro ping` (one voice reply), `bro call` (keep talking).

## Layout

| Path | Role |
|---|---|
| `bin/` | every moving part, bash, each one testable |
| `macos/` | BroBar menu bar app (Swift): panel, summon field, hotkeys |
| `state/` | runtime words and pidfiles (migrated from the old flat layout) |
| `inbox/` | the durable ask queue: pending → claimed → done |
| `watch/` | what bro last saw, written only when asked |
| `show/` | what the panel shows |
| `tests/run` | the proof, one bash file — run it |

## Docs

- `HOW-TO.md` — daily use, all commands and keys
- `STATUS.md` — where the project stands right now
- `bro doctor` — machine health check
- `bro verify` — the keyboard checklist no headless test can reach

## Hacking

Everything is bash + one Swift app. Control files are plain text parsed in
shell precisely so `tests/run` can prove the rules the compiled app follows.
After changing anything: `bash tests/run`, then `bin/build-bro-bar` and
`bro stop && bro` to pick up Swift changes. Backends live in `bin/bro-shell`
— adding one is a `case` arm plus a line in `bro backend`.
