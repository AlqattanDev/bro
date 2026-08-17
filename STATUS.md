# bro — status

Terminal-native assistant: tmux session (`bro`), Grok hidden in back, Vox for
voice, status word in the tmux bar, F1 board / F3 snapshot / F4 talk.

## What works

- Voice in/out through Vox (shared session; bro is one agent of several).
- Status bar words: starting / working / speaking / listening / ready, painted
  by `bin/bro-status-paint`, animated by `bin/bro-status-loop`.
- **Status truth fix (2026-08-17):** the backend's own state now lives in
  `status-backend-word`, written by `bin/bro-status`. A vox turn (speaking or
  listening) borrows the bar and the loop *restores* the backend word after,
  instead of forcing `ready` while the backend is still mid-task. Fresh
  `--hint` writes (bro-talk's early `listening`) get a 3-second grace window.

## Direction (agreed 2026-08-17)

Bro goes global in stages — see PLAN.md. Vox stays a separate layer (mouth and
ears, any agent can use it); bro remains one consumer of it. Brain stays where
it is; the eyes (terminal snapshot) and the face (tmux bar + nvim board) each
get a global replacement, one phase at a time, each useful on its own.

## Known limits

- Status is invisible unless a bro tmux client is on screen (Phase 1 fixes).
- Bro sees only the terminal snapshot, not the screen (Phase 2 fixes).
