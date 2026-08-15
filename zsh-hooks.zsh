# Optional: source from ~/.zshrc when inside the bro session
#   [[ -n $BRO_HOME ]] && source $BRO_HOME/zsh-hooks.zsh
#
# Writes a tiny status file so bro knows folder + last command.

[[ -z ${BRO_HOME:-} ]] && return 0

_BRO_STATUS="${BRO_HOME}/watch/status.env"
mkdir -p "${BRO_HOME}/watch"

_bro_write_status() {
  local ec=${1:-0}
  {
    echo "cwd=$(pwd)"
    echo "last_exit=$ec"
    echo "last_cmd=${_bro_last_cmd:-}"
    echo "time=$(date '+%Y-%m-%dT%H:%M:%S%z')"
  } >"$_BRO_STATUS" 2>/dev/null || true
}

_bro_preexec() {
  _bro_last_cmd="$1"
}

_bro_precmd() {
  local ec=$?
  _bro_write_status "$ec"
}

autoload -Uz add-zsh-hook 2>/dev/null || true
if typeset -f add-zsh-hook >/dev/null 2>&1; then
  add-zsh-hook preexec _bro_preexec
  add-zsh-hook precmd _bro_precmd
fi

_bro_write_status 0

# bro <tab> → quiet / call / ping / status
if (( $+functions[compdef] )); then
  _bro() {
    local -a cmds
    cmds=(
      'quiet:no voice — answers on F1'
      'call:voice, keep going'
      'ping:one voice reply, then silent'
      'status:show current mode'
      'snapshot:save your pane for bro'
      'read:print latest snapshot'
      'stop:end session'
      'backend:show/set backend'
      'help:show usage'
    )
    if (( CURRENT == 2 )); then
      _describe -t commands 'bro' cmds
    fi
  }
  compdef _bro bro
fi
