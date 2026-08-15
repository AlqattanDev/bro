Fix ~/.partner. This is a personal one-machine tool, not a product rewrite.

Do not review. Do not roast. Do not propose a broker, IPC, capability sandbox, or "fundamental redesign." Do not touch unrelated files. Do not type a verdict — change the code.

Four jobs only, in this order:

1) Status bar must tell the truth
   The painter dies at boot (set -e + tmux list-clients before the session exists) and is never restarted because start_status_loop is gated on the watch loop still being alive. F4 writes "listening" and the word sticks. Even a living loop never reaches "ready" (idle becomes "working" forever).
   Details: ~/.partner/CODEX-STATUS-FIX.md
   Required: supervise the status loop on every attach; loop cannot die from missing tmux/clients; parse Vox state.json as JSON; listening only while the mic is open; then ready. No timeout hack in partner-talk.

2) Inbox must be a queue
   bro and partner-talk both overwrite the same inbox.md. Two asks, or F4 during an ask, destroy the earlier note. Make an append-only queue with unique ids, atomic writes, and an explicit claimed/done state. Keep the existing bro / F4 / ask UX.

3) partner-run must not type into a non-shell
   It currently send-keys into whatever is focused (Vim, Codex, SSH, a half-typed line). Refuse unless the you-pane looks like a shell prompt. Never invent a confirmation UI. Just do not fire.

4) Wake the backend instead of hoping
   Watch/inbox updates are files. Nothing notifies the agent. Add a real wakeup the running backend can see (a fifo, a flag file the boot prompt already knows to poll, or an equivalent that does not require a new daemon language). Do not replace the LLM with a custom orchestrator.

Done means:
- Fresh `partner` start: bar goes starting → ready by itself
- Kill the status-loop process, attach again: it comes back
- F4: listening only while the mic is open, then ready
- Two `bro` notes in a row: both survive
- partner-run no-ops if Codex/vim is in the you pane
- No new review document. No scope beyond these four.
