# PLAN — bro goes global, in stages

Rule: one phase per session. Finish, verify, commit explicit paths, delete the
phase from this file, run /handoff. When no phases remain, replace this file's
body with exactly `DONE`.

## Phase 2 — global eyes: screen snapshot

- `bin/bro-snapshot --screen`: `screencapture -x` the main display to
  `~/.bro/watch/screen.png`, downscale to ≤1600px wide (sips), and reference it
  from `~/.bro/watch/latest.md`.
- Privacy rule stays manual-first: screen capture happens on F3 / explicit ask
  only, never on a timer, until Ali says otherwise. Honour `show-policy`.
- Teach the boot prompt (`bro-boot-prompt.txt`): when the user asks about
  something "on my screen", request the screen snapshot, not the pane capture.
- Accept: with a browser frontmost, "bro what's on my screen" answers from the
  screenshot, not from the terminal pane.

## Phase 3 — global face: floating answer panel

- Replace the nvim-board-only answer surface with a floating panel: a small
  always-on-top window (VoxHUD pattern from `~/vox-mcp/macos/VoxHUD.swift` —
  non-activating panel, orderFrontRegardless) rendering
  `~/.bro/show/current.md` as attributed text, toggled by F1 and by
  `bin/bro-show`.
- Board in nvim stays available (`bro board`) for editing/scrollback.
- Accept: answers appear over any app; panel never steals focus; Esc or click
  dismisses it.

## Phase 4 — decouple from tmux

- `bro` backend (Grok session + loops) runs headless under launchd
  (`com.bro.backend.plist`), terminal becomes an optional client that attaches.
- `bro <message>` and F4 talk work with zero terminals open.
- Accept: reboot → say nothing, `bro ask <thing>` from Spotlight-launched
  terminal works; killing every terminal does not kill bro.
