# The Vox listening contract

Vox treats microphone access as a short-lived capability, not as a side effect
of “voice mode.” A session can remain active for convenience while the
microphone is physically closed.

## When Vox listens

| Situation | Microphone |
|---|---|
| Vox runtime starts | Closed |
| A voice session starts | Closed; state becomes `IDLE` |
| `speak` or `converse(..., wait_for_response=false)` | Closed |
| `converse(..., wait_for_response=true)` | Opens only after playback has fully drained |
| `listen` | Opens immediately for one bounded turn |
| A `listen` turn is used as push-to-talk | Open until manual end, then closed |
| The user says a short standalone “wait” phrase | Closed during the wait, then reopened for a fresh bounded turn |
| No speech arrives within the onset timeout | Closed; session remains `IDLE` |
| Speech ends | Closed after adaptive trailing silence |
| Pause, mute, stop, Escape/cancel, sleep, screen lock, route loss, or request cancellation | Closed immediately |

There is no ambient listening by default. Starting the runtime, connecting an
MCP client, or leaving a voice session active does not open the microphone.

Default turn bounds are deliberately generous for this user’s speaking style:

- 300 ms pre-roll so first syllables survive detection.
- 15 seconds to begin speaking.
- 1.2 seconds of trailing silence to end a normal utterance.
- Up to 300 seconds for a long dictated turn.

All four are configurable. Unlike VoiceMode, the speech-onset timeout and
trailing-silence timeout are separate.

## Session and turn controls

| User intent | Effect |
|---|---|
| “Stop voice mode” / “switch to text” | Ends the session, stops audio, closes mic, releases ownership |
| “Pause voice mode” / “mute” | Keeps the session but blocks new listening and closes the mic |
| “Resume voice mode” | Returns a paused session to `IDLE`; it still does not listen until asked |
| Vox status-panel Start / resume | Makes Vox ready; it does not open the microphone |
| Vox status-panel Pause / Stop / Cancel | Pauses the session, ends it, or cancels only the active turn; each closes the microphone |
| “Repeat that” | Replays cached audio; Kokoro is not called again |
| “Wait” / “give me a second” | Closes the mic, waits, then listens again |
| Escape or `voice_control(cancel)` | Cancels only the current speak/listen turn; voice mode remains active |
| Manual end-of-turn | Closes the current recording immediately and transcribes what was captured |

Spoken controls are recognized only as short standalone utterances. A long
dictation containing the words “stop voice mode” is treated as content, not a
control command.

## Ownership and handoff

One runtime owns the hardware, so Claude Code and Codex cannot speak over each
other or race PortAudio. The first client to start/use a session receives a
lease. Another client gets a structured `busy` response immediately instead
of waiting until its MCP timeout. Identity comes from the stable MCP host name,
not a temporary HTTP session ID, so reconnects and host upgrades reclaim the
same lease. The owner can explicitly hand off; an idle lease expires after ten
minutes. Global `stop` is owner-independent and releases stale ownership.

The microphone closes when an active request is cancelled even while the
stable host lease is retained. The onset timeout and hard turn cap still apply
if a client disappears without transport shutdown. This is the privacy-safe
distinction between “the conversation can recover” and “the computer keeps
listening.”

## Failure behavior

- A Kokoro failure triggers one bounded local restart/retry, then falls back
  to macOS `say`. It does not end the voice session.
- A Whisper HTTP failure triggers one bounded local restart/retry, then uses
  the installed `whisper-cli` and local model.
- Cancellation signals a thread-safe stop event and waits for the recorder to
  confirm closure before releasing the audio lock.
- A host update can restart Claude Code or Codex without killing Vox because
  both connect to the persistent HTTP runtime.
- Vox never silently tries a cloud endpoint.
