# Bro — how it works now

## What you see

- **Your work** — full screen terminal  
- **Commands run here** — when you ask to *do* something (e.g. Tailscale devices), bro types the command into **your** terminal  
- **A clean answer panel** — floats on top of whatever app you are in, never takes your keyboard. Only when you ask, or for a *plan you requested*. Not for “I ran this”. Not a chat log.  
- **You do not look at Grok.** Grok runs hidden in the back.

## Start

New terminal:

```bash
bro
```

## Always on (optional, one time)

Bro can run without any terminal at all — hidden backend, loops and menu bar
face owned by a launchd agent that comes back after a reboot:

```bash
bro daemon install     # writes ~/Library/LaunchAgents/com.bro.backend.plist
bro daemon status      # installed? loaded? running?
bro daemon restart
bro daemon uninstall
```

Installing a login item is a deliberate choice, so `bro` never does it for you.
Once installed, a terminal is just a client: `bro` attaches, and detaching
(Ctrl-a d, or closing the window) leaves bro running. Only `bro stop` takes the
whole thing down.

## Looking

Nothing watches you. There is no timer. Bro reads your pane at the moment it
acts on something — when you ask it a question, when you run `bro read` or
`bro snapshot`, or when you press Ctrl-a r. The screen (the whole display, not
the terminal) is only ever captured on F3 or an explicit ask, and
`~/.bro/show-policy` set to `no-screen` turns even that off.

## Keys

| Key | What |
|---|---|
| **F1** | Toggle the floating answer panel. It sits over any app. Click it (or Esc) to dismiss. |
| **F3** | Save a snapshot of your terminal for bro |
| **F4** | Talk — mic opens immediately. Talk now; I pick it up when ready. |

On Mac you may need **Fn+F1** / **Fn+F4**.

`bro board` opens the same answer in nvim inside the session, when you want to
scroll or edit it: **j/k** line, **q** close.

Bottom bar:

| Word | Meaning |
|---|---|
| **starting** | I am booting |
| **speaking** | I am talking. Mic is off. |
| **listening** | Mic is open. Talk. |
| **working** | I heard you. I am doing it. |
| **ready** | Waiting. Talk, F4, or type `bro <message>` |

## Voice

Talk with Vox to the bro agent (it boots when you run `bro`).  
You should not need to open Grok or type `/vox` yourself once the backend is up.

## How you talk

| Mode | What |
|---|---|
| **call** | Voice call. Keep going. |
| **ping** | One voice reply, then silent. |
| **quiet** | No voice. Answers on the F1 panel. |

One command, in or out of the session:

```bash
bro                              start / attach the interactive session
bro how do I undo the last commit
bro ask stop the deploy pipeline  # "ask" if your message starts with a
                                   # word like stop/read/backend/snapshot
bro quiet
bro call
bro ping
```

## Files

| Path | Role |
|---|---|
| `~/.bro/watch/latest.md` | What bro saw the last time it looked (written on demand, never on a timer) |
| `~/.bro/show/current.md` | What the panel shows you |
| `~/.bro/bin/bro-show` | How bro updates/opens the panel (and `--board` for nvim) |

## Stop

```bash
bro stop
```
