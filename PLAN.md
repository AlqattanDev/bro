# PLAN — bro goes global, in stages

Rule: one phase per session. Finish, verify, commit explicit paths, delete the
phase from this file, run /handoff. When no phases remain, replace this file's
body with exactly `DONE`.

Phases 1–4 (menu bar status, screen snapshot, floating panel, launchd daemon)
are done and committed. What follows is Ali's direction from the voice session
on 2026-08-17.

## Phase 5 — look only when asked

Ali's call, verbatim in spirit: "I don't want him to watch every second. I want
him to watch when I want him to watch, when I want him to act."

- Delete the 3-second watch loop. Bro reads the pane at the moment it acts, not
  on a timer — `bin/bro-shell` already tells it not to trust the stale snapshot,
  so the loop is feeding a file nobody trusts.
- Keep every consumer working: check what still reads `watch/latest.md`,
  `watch/status.env`, and `watch/scrollback.txt` (at least `bin/bro-run` and the
  boot prompt) and give them an on-demand capture instead.
- `bin/bro-snapshot` stays, invoked on demand; `--screen` stays ask-only.
- Accept: no bro process wakes up on its own. `bro ask` about a terminal error
  still answers correctly, because it looks when asked.

## Phase 6 — global summon

Bro is reachable from anywhere, without a terminal, and works in the background.

- Global hotkey registered in BroBar via Carbon `RegisterEventHotKey` — the
  permission-free path (`~/vox-mcp/macos/VoxStatus.swift:361` explains why an
  NSEvent monitor is not). Voice summon opens the Vox mic and drops the
  transcript into the inbox, exactly as F4 does today, but from any app.
- Second hotkey: a text field in the floating panel for typed asks.
- Asks are asynchronous. Return immediately, menu bar shows `working`, the
  answer arrives in the panel and is spoken. Ali keeps working meanwhile.
- Sign BroBar with the existing `Vox Local Signing` identity instead of ad-hoc,
  so the code hash is stable and Accessibility trust survives a rebuild. This
  is what currently breaks Esc-to-dismiss on the panel after every build.
- Accept: with zero terminals open, the hotkey summons bro, a spoken question
  about what is on screen or in the IDE is answered in the panel, and bro can
  be given a longer job that reports back while Ali does something else.
