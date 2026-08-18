#!/usr/bin/env bash
# bro install — from clone to working copilot in one script.
#
# Expected shape: this repository cloned at ~/.bro (git clone <repo> ~/.bro).
# Safe to re-run; every step is idempotent, and nothing here touches login
# items — `bro daemon install` stays an explicit, separate choice.
set -euo pipefail

BRO_HOME="$(cd "$(dirname "$0")" && pwd)"

echo "bro install — home: $BRO_HOME"
echo

# --- prerequisites -----------------------------------------------------------
missing=0
for tool in tmux git swiftc uv; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "✓ $tool"
  else
    echo "✗ $tool missing — brew install $tool"
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  echo
  echo "Install the missing tools and re-run: $BRO_HOME/install.sh"
  exit 1
fi

# --- voice runtime venv ------------------------------------------------------
# Since the fuse, the voice runtime (vox) lives in-tree at vox/. Its Python
# daemon runs from vox/.venv; uv sync builds it deterministically from uv.lock.
echo
echo "setting up the voice runtime (vox/.venv)…"
( cd "$BRO_HOME/vox" && uv sync --frozen )

# --- build -------------------------------------------------------------------
echo
echo "building BroBar + Vox.app…"
"$BRO_HOME/bin/build"

# --- PATH --------------------------------------------------------------------
echo
if [[ ":$PATH:" == *":$BRO_HOME/bin:"* ]]; then
  echo "✓ $BRO_HOME/bin is on PATH"
else
  echo "! $BRO_HOME/bin is not on PATH. Add this to ~/.zshrc:"
  echo "    export PATH=\"$BRO_HOME/bin:\$PATH\""
fi

# --- health ------------------------------------------------------------------
echo
"$BRO_HOME/bin/bro-doctor" || true

# --- what only a human can grant ---------------------------------------------
cat <<EOF

— one-time macOS grants, when each feature first runs —
  Microphone        voice (Vox)
  Screen Recording  'read this page' / bro-snapshot --screen
                    (System Settings → Privacy & Security → Screen Recording)
  Accessibility     optional: Esc dismisses the answer panel
  (the global hotkeys ⌥§ / ⌃§ use Carbon and need NO grant)

— next steps —
  bro                 start / attach the session
  bro daemon install  optional: come back at login (launchd) — your choice
  bro verify          5-minute keyboard checklist, proves the human surfaces
  bro brief 8:00      optional: a morning brief, daily
EOF
