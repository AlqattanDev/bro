# Bro — how it works now

## What you see

- **Your work** — full screen terminal  
- **Commands run here** — when you ask to *do* something (e.g. Tailscale devices), bro types the command into **your** terminal  
- **A clean popup** — only when you ask, or for a *plan you requested*. Not for “I ran this”. Not a chat log.  
- **You do not look at Grok.** Grok runs hidden in the back.

## Start

New terminal:

```bash
bro
```

## Keys

| Key | What |
|---|---|
| **F1** | Toggle the board. It opens in nvim: **j/k** line, **q** close. |
| **F3** | Save a snapshot of your terminal for bro |
| **F4** | Talk — mic opens immediately. Talk now; I pick it up when ready. |

On Mac you may need **Fn+F1** / **Fn+F4**.

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
| **quiet** | No voice. Answers on the F1 board. |

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
| `~/.bro/watch/latest.md` | What bro sees of your terminal |
| `~/.bro/show/current.md` | What the popup shows you |
| `~/.bro/bin/bro-show` | How bro updates/opens the popup |

## Stop

```bash
bro stop
```
