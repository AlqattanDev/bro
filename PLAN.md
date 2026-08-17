# PLAN — bro goes global, in stages

Rule: one phase per session. Finish, verify, commit explicit paths, delete the
phase from this file, run /handoff. When no phases remain, replace this file's
body with exactly `DONE`.

## Phase 4 — decouple from tmux

- `bro` backend (Grok session + loops) runs headless under launchd
  (`com.bro.backend.plist`), terminal becomes an optional client that attaches.
- `bro <message>` and F4 talk work with zero terminals open.
- Accept: reboot → say nothing, `bro ask <thing>` from Spotlight-launched
  terminal works; killing every terminal does not kill bro.
